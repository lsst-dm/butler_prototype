# This file is part of daf_butler.
#
# Developed for the LSST Data Management System.
# This product includes software developed by the LSST Project
# (http://www.lsst.org).
# See the COPYRIGHT file at the top-level directory of this distribution
# for details of code ownership.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from __future__ import annotations

__all__ = ["YamlRepoExportBackend", "YamlRepoImportBackend"]

import os
from datetime import datetime
from typing import (
    Any,
    Dict,
    IO,
    Iterable,
    List,
    Mapping,
    Optional,
    Set,
    Tuple,
    Type,
)
from collections import defaultdict

import yaml
import astropy.time

from lsst.utils import doImport
from ..core import (
    DatasetAssociation,
    DatasetRef,
    DatasetType,
    DataCoordinate,
    Datastore,
    DimensionElement,
    DimensionRecord,
    FileDataset,
    Timespan,
)
from ..core.utils import iterable
from ..core.named import NamedValueSet
from ..registry import CollectionType, Registry
from ..registry.wildcards import DatasetTypeRestriction
from ..registry.interfaces import ChainedCollectionRecord, CollectionRecord, RunRecord
from ._interfaces import RepoExportBackend, RepoImportBackend


class YamlRepoExportBackend(RepoExportBackend):
    """A repository export implementation that saves to a YAML file.

    Parameters
    ----------
    stream
        A writeable file-like object.
    """

    def __init__(self, stream: IO):
        self.stream = stream
        self.data: List[Dict[str, Any]] = []

    def saveDimensionData(self, element: DimensionElement, *data: DimensionRecord) -> None:
        # Docstring inherited from RepoExportBackend.saveDimensionData.
        data_dicts = [record.toDict(splitTimespan=True) for record in data]
        self.data.append({
            "type": "dimension",
            "element": element.name,
            "records": data_dicts,
        })

    def saveCollection(self, record: CollectionRecord) -> None:
        # Docstring inherited from RepoExportBackend.saveCollections.
        data: Dict[str, Any] = {
            "type": "collection",
            "collection_type": record.type.name,
            "name": record.name,
        }
        if isinstance(record, RunRecord):
            data["host"] = record.host
            data["timespan_begin"] = record.timespan.begin
            data["timespan_end"] = record.timespan.end
        elif isinstance(record, ChainedCollectionRecord):
            data["children"] = [
                [name, list(restriction.names) if restriction.names is not ... else None]  # type: ignore
                for name, restriction in record.children
            ]
        self.data.append(data)

    def saveDatasets(self, datasetType: DatasetType, run: str, *datasets: FileDataset) -> None:
        # Docstring inherited from RepoExportBackend.saveDatasets.
        self.data.append({
            "type": "dataset_type",
            "name": datasetType.name,
            "dimensions": [d.name for d in datasetType.dimensions],
            "storage_class": datasetType.storageClass.name,
            "is_calibration": datasetType.isCalibration(),
        })
        self.data.append({
            "type": "dataset",
            "dataset_type": datasetType.name,
            "run": run,
            "records": [
                {
                    "dataset_id": [ref.id for ref in dataset.refs],
                    "data_id": [ref.dataId.byName() for ref in dataset.refs],
                    "path": dataset.path,
                    "formatter": dataset.formatter,
                    # TODO: look up and save other collections
                }
                for dataset in datasets
            ]
        })

    def saveDatasetAssociations(self, collection: str, collectionType: CollectionType,
                                associations: Iterable[DatasetAssociation]) -> None:
        # Docstring inherited from RepoExportBackend.saveDatasetAssociations.
        if collectionType is CollectionType.TAGGED:
            self.data.append({
                "type": "associations",
                "collection": collection,
                "collection_type": collectionType.name,
                "dataset_ids": [assoc.ref.id for assoc in associations],
            })
        elif collectionType is CollectionType.CALIBRATION:
            idsByTimespan: Dict[Timespan, List[int]] = defaultdict(list)
            for association in associations:
                assert association.timespan is not None
                assert association.ref.id is not None
                idsByTimespan[association.timespan].append(association.ref.id)
            self.data.append({
                "type": "associations",
                "collection": collection,
                "collection_type": collectionType.name,
                "validity_ranges": [
                    {
                        "begin": timespan.begin,
                        "end": timespan.end,
                        "dataset_ids": dataset_ids,
                    }
                    for timespan, dataset_ids in idsByTimespan.items()
                ]
            })

    def finish(self) -> None:
        # Docstring inherited from RepoExportBackend.
        yaml.dump(
            {
                "description": "Butler Data Repository Export",
                "version": 0,
                "data": self.data,
            },
            stream=self.stream,
            sort_keys=False,
        )


class YamlRepoImportBackend(RepoImportBackend):
    """A repository import implementation that reads from a YAML file.

    Parameters
    ----------
    stream
        A readable file-like object.
    registry : `Registry`
        The registry datasets will be imported into.  Only used to retreive
        dataset types during construction; all write happen in `register`
        and `load`.
    """

    def __init__(self, stream: IO, registry: Registry):
        # We read the file fully and convert its contents to Python objects
        # instead of loading incrementally so we can spot some problems early;
        # because `register` can't be put inside a transaction, we'd rather not
        # run that at all if there's going to be problem later in `load`.
        wrapper = yaml.safe_load(stream)
        # TODO: When version numbers become meaningful, check here that we can
        # read the version in the file.
        self.runs: Dict[str, Tuple[Optional[str], Timespan]] = {}
        self.chains: Dict[str, List[Tuple[str, DatasetTypeRestriction]]] = {}
        self.collections: Dict[str, CollectionType] = {}
        self.datasetTypes: NamedValueSet[DatasetType] = NamedValueSet()
        self.dimensions: Mapping[DimensionElement, List[DimensionRecord]] = defaultdict(list)
        self.tagAssociations: Dict[str, List[int]] = defaultdict(list)
        self.calibAssociations: Dict[str, Dict[Timespan, List[int]]] = defaultdict(dict)
        self.refsByFileId: Dict[int, DatasetRef] = {}
        self.registry: Registry = registry
        datasetData = []
        for data in wrapper["data"]:
            if data["type"] == "dimension":
                # convert all datetime values to astropy
                for record in data["records"]:
                    for key in record:
                        # Some older YAML files were produced with native
                        # YAML support for datetime, we support reading that
                        # data back. Newer conversion uses _AstropyTimeToYAML
                        # class with special YAML tag.
                        if isinstance(record[key], datetime):
                            record[key] = astropy.time.Time(record[key], scale="utc")
                element = self.registry.dimensions[data["element"]]
                RecordClass: Type[DimensionRecord] = element.RecordClass
                self.dimensions[element].extend(
                    RecordClass(**r) for r in data["records"]
                )
            elif data["type"] == "collection":
                collectionType = CollectionType.__members__[data["collection_type"].upper()]
                if collectionType is CollectionType.RUN:
                    self.runs[data["name"]] = (
                        data["host"],
                        Timespan(begin=data["timespan_begin"], end=data["timespan_end"])
                    )
                elif collectionType is CollectionType.CHAINED:
                    children = []
                    for name, restriction_data in data["children"]:
                        if restriction_data is None:
                            restriction = DatasetTypeRestriction.any
                        else:
                            restriction = DatasetTypeRestriction.fromExpression(restriction_data)
                        children.append((name, restriction))
                    self.chains[data["name"]] = children
                else:
                    self.collections[data["name"]] = collectionType
            elif data["type"] == "run":
                # Also support old form of saving a run with no extra info.
                self.runs[data["name"]] = (None, Timespan(None, None))
            elif data["type"] == "dataset_type":
                self.datasetTypes.add(
                    DatasetType(data["name"], dimensions=data["dimensions"],
                                storageClass=data["storage_class"], universe=self.registry.dimensions,
                                isCalibration=data.get("is_calibration", False))
                )
            elif data["type"] == "dataset":
                # Save raw dataset data for a second loop, so we can ensure we
                # know about all dataset types first.
                datasetData.append(data)
            elif data["type"] == "associations":
                collectionType = CollectionType.__members__[data["collection_type"].upper()]
                if collectionType is CollectionType.TAGGED:
                    self.tagAssociations[data["collection"]].extend(data["dataset_ids"])
                elif collectionType is CollectionType.CALIBRATION:
                    assocsByTimespan = self.calibAssociations[data["collection"]]
                    for d in data["validity_ranges"]:
                        assocsByTimespan[Timespan(begin=d["begin"], end=d["end"])] = d["dataset_ids"]
                else:
                    raise ValueError(f"Unexpected calibration type for association: {collectionType.name}.")
            else:
                raise ValueError(f"Unexpected dictionary type: {data['type']}.")
        # key is (dataset type name, run)
        self.datasets: Mapping[Tuple[str, str], List[FileDataset]] = defaultdict(list)
        for data in datasetData:
            datasetType = self.datasetTypes.get(data["dataset_type"])
            if datasetType is None:
                datasetType = self.registry.getDatasetType(data["dataset_type"])
            self.datasets[data["dataset_type"], data["run"]].extend(
                FileDataset(
                    d.get("path"),
                    [DatasetRef(datasetType, dataId, run=data["run"], id=refid)
                     for dataId, refid in zip(iterable(d["data_id"]), iterable(d["dataset_id"]))],
                    formatter=doImport(d.get("formatter")) if "formatter" in d else None
                )
                for d in data["records"]
            )

    def register(self) -> None:
        # Docstring inherited from RepoImportBackend.register.
        for datasetType in self.datasetTypes:
            self.registry.registerDatasetType(datasetType)
        for run in self.runs:
            self.registry.registerRun(run)
            # No way to add extra run info to registry yet.
        for collection, collection_type in self.collections.items():
            self.registry.registerCollection(collection, collection_type)
        for chain, children in self.chains.items():
            self.registry.registerCollection(chain, CollectionType.CHAINED)
            self.registry.setCollectionChain(chain, children)

    def load(self, datastore: Optional[Datastore], *,
             directory: Optional[str] = None, transfer: Optional[str] = None,
             skip_dimensions: Optional[Set] = None) -> None:
        # Docstring inherited from RepoImportBackend.load.
        for element, dimensionRecords in self.dimensions.items():
            if skip_dimensions and element in skip_dimensions:
                continue
            self.registry.insertDimensionData(element, *dimensionRecords)
        # FileDatasets to ingest into the datastore (in bulk):
        fileDatasets = []
        for (datasetTypeName, run), records in self.datasets.items():
            datasetType = self.registry.getDatasetType(datasetTypeName)
            # Make a big flattened list of all data IDs and dataset_ids, while
            # remembering slices that associate them with the FileDataset
            # instances they came from.
            dataIds: List[DataCoordinate] = []
            dataset_ids: List[int] = []
            slices = []
            for fileDataset in records:
                start = len(dataIds)
                dataIds.extend(ref.dataId for ref in fileDataset.refs)
                dataset_ids.extend(ref.id for ref in fileDataset.refs)  # type: ignore
                stop = len(dataIds)
                slices.append(slice(start, stop))
            # Insert all of those DatasetRefs at once.
            # For now, we ignore the dataset_id we pulled from the file
            # and just insert without one to get a new autoincrement value.
            # Eventually (once we have origin in IDs) we'll preserve them.
            resolvedRefs = self.registry.insertDatasets(
                datasetType,
                dataIds=dataIds,
                run=run,
            )
            # Populate our dictionary that maps int dataset_id values from the
            # export file to the new DatasetRefs
            for fileId, ref in zip(dataset_ids, resolvedRefs):
                self.refsByFileId[fileId] = ref
            # Now iterate over the original records, and install the new
            # resolved DatasetRefs to replace the unresolved ones as we
            # reorganize the collection information.
            for sliceForFileDataset, fileDataset in zip(slices, records):
                fileDataset.refs = resolvedRefs[sliceForFileDataset]
                if directory is not None:
                    fileDataset.path = os.path.join(directory, fileDataset.path)
                fileDatasets.append(fileDataset)
        # Ingest everything into the datastore at once.
        if datastore is not None and fileDatasets:
            datastore.ingest(*fileDatasets, transfer=transfer)
        # Associate datasets with tagged collections.
        for collection, dataset_ids in self.tagAssociations.items():
            self.registry.associate(collection, [self.refsByFileId[i] for i in dataset_ids])
        # Associate datasets with calibration collections.
        for collection, idsByTimespan in self.calibAssociations.items():
            for timespan, dataset_ids in idsByTimespan.items():
                self.registry.certify(collection, [self.refsByFileId[i] for i in dataset_ids], timespan)
