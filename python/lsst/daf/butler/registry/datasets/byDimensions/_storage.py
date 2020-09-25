from __future__ import annotations

__all__ = ("ByDimensionsDatasetRecordStorage",)

from typing import (
    Any,
    Dict,
    Iterable,
    Iterator,
    Optional,
    TYPE_CHECKING,
)

import sqlalchemy

from lsst.daf.butler import (
    CollectionType,
    DataCoordinate,
    DatasetRef,
    DatasetType,
    SimpleQuery,
)
from lsst.daf.butler.registry.interfaces import DatasetRecordStorage

if TYPE_CHECKING:
    from ...interfaces import CollectionManager, CollectionRecord, Database, RunRecord
    from .tables import StaticDatasetTablesTuple


class ByDimensionsDatasetRecordStorage(DatasetRecordStorage):
    """Dataset record storage implementation paired with
    `ByDimensionsDatasetRecordStorageManager`; see that class for more
    information.

    Instances of this class should never be constructed directly; use
    `DatasetRecordStorageManager.register` instead.
    """
    def __init__(self, *, datasetType: DatasetType,
                 db: Database,
                 dataset_type_id: int,
                 collections: CollectionManager,
                 static: StaticDatasetTablesTuple,
                 tags: sqlalchemy.sql.Table):
        super().__init__(datasetType=datasetType)
        self._dataset_type_id = dataset_type_id
        self._db = db
        self._collections = collections
        self._static = static
        self._tags = tags
        self._runKeyColumn = collections.getRunForeignKeyName()

    def insert(self, run: RunRecord, dataIds: Iterable[DataCoordinate]) -> Iterator[DatasetRef]:
        # Docstring inherited from DatasetRecordStorage.
        staticRow = {
            "dataset_type_id": self._dataset_type_id,
            self._runKeyColumn: run.key,
        }
        dataIds = list(dataIds)
        # Insert into the static dataset table, generating autoincrement
        # dataset_id values.
        with self._db.transaction():
            datasetIds = self._db.insert(self._static.dataset, *([staticRow]*len(dataIds)),
                                         returnIds=True)
            assert datasetIds is not None
            # Combine the generated dataset_id values and data ID fields to
            # form rows to be inserted into the tags table.
            protoTagsRow = {
                "dataset_type_id": self._dataset_type_id,
                self._collections.getCollectionForeignKeyName(): run.key,
            }
            tagsRows = [
                dict(protoTagsRow, dataset_id=dataset_id, **dataId.byName())
                for dataId, dataset_id in zip(dataIds, datasetIds)
            ]
            # Insert those rows into the tags table.  This is where we'll
            # get any unique constraint violations.
            self._db.insert(self._tags, *tagsRows)
        for dataId, datasetId in zip(dataIds, datasetIds):
            yield DatasetRef(
                datasetType=self.datasetType,
                dataId=dataId,
                id=datasetId,
                run=run.name,
            )

    def find(self, collection: CollectionRecord, dataId: DataCoordinate) -> Optional[DatasetRef]:
        # Docstring inherited from DatasetRecordStorage.
        assert dataId.graph == self.datasetType.dimensions
        sql = self.select(collection=collection, dataId=dataId, id=SimpleQuery.Select,
                          run=SimpleQuery.Select).combine()
        row = self._db.query(sql).fetchone()
        if row is None:
            return None
        return DatasetRef(
            datasetType=self.datasetType,
            dataId=dataId,
            id=row["id"],
            run=self._collections[row[self._runKeyColumn]].name
        )

    def delete(self, datasets: Iterable[DatasetRef]) -> None:
        # Docstring inherited from DatasetRecordStorage.
        # Only delete from common dataset table; ON DELETE foreign key clauses
        # will handle the rest.
        self._db.delete(
            self._static.dataset,
            ["id"],
            *[{"id": dataset.getCheckedId()} for dataset in datasets],
        )

    def associate(self, collection: CollectionRecord, datasets: Iterable[DatasetRef]) -> None:
        # Docstring inherited from DatasetRecordStorage.
        if collection.type is not CollectionType.TAGGED:
            raise TypeError(f"Cannot associate into collection '{collection}' "
                            f"of type {collection.type.name}; must be TAGGED.")
        protoRow = {
            self._collections.getCollectionForeignKeyName(): collection.key,
            "dataset_type_id": self._dataset_type_id,
        }
        rows = []
        for dataset in datasets:
            row = dict(protoRow, dataset_id=dataset.getCheckedId())
            for dimension, value in dataset.dataId.items():
                row[dimension.name] = value
            rows.append(row)
        self._db.replace(self._tags, *rows)

    def disassociate(self, collection: CollectionRecord, datasets: Iterable[DatasetRef]) -> None:
        # Docstring inherited from DatasetRecordStorage.
        if collection.type is not CollectionType.TAGGED:
            raise TypeError(f"Cannot disassociate from collection '{collection}' "
                            f"of type {collection.type.name}; must be TAGGED.")
        rows = [
            {
                "dataset_id": dataset.getCheckedId(),
                self._collections.getCollectionForeignKeyName(): collection.key
            }
            for dataset in datasets
        ]
        self._db.delete(self._tags, ["dataset_id", self._collections.getCollectionForeignKeyName()],
                        *rows)

    def select(self, collection: CollectionRecord,
               dataId: SimpleQuery.Select.Or[DataCoordinate] = SimpleQuery.Select,
               id: SimpleQuery.Select.Or[Optional[int]] = SimpleQuery.Select,
               run: SimpleQuery.Select.Or[None] = SimpleQuery.Select,
               ) -> SimpleQuery:
        # Docstring inherited from DatasetRecordStorage.
        assert collection.type is not CollectionType.CHAINED
        query = SimpleQuery()
        # We always include the _static.dataset table, and we can always get
        # the id and run fields from that; passing them as kwargs here tells
        # SimpleQuery to handle them whether they're constraints or results.
        # We always constraint the dataset_type_id here as well.
        query.join(
            self._static.dataset,
            id=id,
            dataset_type_id=self._dataset_type_id,
            **{self._runKeyColumn: run}
        )
        # If and only if the collection is a RUN, we constrain it in the static
        # table (and also the tags table below)
        if collection.type is CollectionType.RUN:
            query.where.append(self._static.dataset.columns[self._runKeyColumn]
                               == collection.key)
        # We get or constrain the data ID from the tags table, but that's
        # multiple columns, not one, so we need to transform the one Select.Or
        # argument into a dictionary of them.
        kwargs: Dict[str, Any]
        if dataId is SimpleQuery.Select:
            kwargs = {dim.name: SimpleQuery.Select for dim in self.datasetType.dimensions.required}
        else:
            kwargs = dict(dataId.byName())
        # We always constrain (never retrieve) the collection from the tags
        # table.
        kwargs[self._collections.getCollectionForeignKeyName()] = collection.key
        # And now we finally join in the tags table.
        query.join(
            self._tags,
            onclause=(self._static.dataset.columns.id == self._tags.columns.dataset_id),
            **kwargs
        )
        return query

    def getDataId(self, id: int) -> DataCoordinate:
        # Docstring inherited from DatasetRecordStorage.
        # This query could return multiple rows (one for each tagged collection
        # the dataset is in, plus one for its run collection), and we don't
        # care which of those we get.
        sql = self._tags.select().where(
            sqlalchemy.sql.and_(
                self._tags.columns.dataset_id == id,
                self._tags.columns.dataset_type_id == self._dataset_type_id
            )
        ).limit(1)
        row = self._db.query(sql).fetchone()
        assert row is not None, "Should be guaranteed by caller and foreign key constraints."
        return DataCoordinate.standardize(
            {dimension.name: row[dimension.name] for dimension in self.datasetType.dimensions.required},
            graph=self.datasetType.dimensions
        )
