from __future__ import annotations

__all__ = ["ByNameRegistryLayerOpaqueRecords", "ByNameRegistryLayerOpaqueStorage"]

from typing import (
    Any,
    Iterator,
    Optional,
)

import sqlalchemy

from ...core.schema import TableSpec, FieldSpec
from ..interfaces import Database, RegistryLayerOpaqueStorage, RegistryLayerOpaqueRecords


class ByNameRegistryLayerOpaqueRecords(RegistryLayerOpaqueRecords):

    def __init__(self, *, db: Database, name: str, table: sqlalchemy.schema.Table):
        super().__init__(name=name)
        self._db = db
        self._table = table

    def insert(self, *data: dict):
        self._db.connection.execute(self._table.insert(), *data)

    def fetch(self, **where: Any) -> Iterator[dict]:
        sql = self._table.select().where(
            sqlalchemy.sql.and_(*[self._table.columns[k] == v for k, v in where.items()])
        )
        yield from self._db.connection.execute(sql)

    def delete(self, **where: Any):
        sql = self._table.delete().where(
            sqlalchemy.sql.and_(*[self._table.columns[k] == v for k, v in where.items()])
        )
        self._db.connection.execute(sql)


class ByNameRegistryLayerOpaqueStorage(RegistryLayerOpaqueStorage):

    _META_TABLE_NAME = "opaque_meta"

    _META_TABLE_SPEC = TableSpec(
        fields=[
            FieldSpec("table_name", dtype=sqlalchemy.String, length=128, primaryKey=True),
        ],
    )

    def __init__(self, db: Database):
        self._db = db
        self._metaTable = db.ensureTableExists(self._META_TABLE_NAME, self._META_TABLE_SPEC)
        self._records = {}
        self.refresh()

    @classmethod
    def load(cls, db: Database) -> RegistryLayerOpaqueStorage:
        return cls(db=db)

    def refresh(self):
        records = {}
        for row in self._db.connection.execute(self._metaTable.select()).fetchall():
            name = row[self._metaTable.columns.table_name]
            table = self._db.getExistingTable(name)
            records[name] = ByNameRegistryLayerOpaqueRecords(name=name, table=table, db=self._db)
        self._records = records

    def get(self, name: str) -> Optional[RegistryLayerOpaqueRecords]:
        return self._records.get(name)

    def register(self, name: str, spec: TableSpec) -> RegistryLayerOpaqueRecords:
        result = self._records.get(name)
        if result is None:
            # Create the table itself.  If it already exists but wasn't in
            # the dict because it was added by another client since this one
            # was initialized, that's fine.
            table = self._db.ensureTableExists(name, spec)
            # Add a row to the meta table so we can find this table in the
            # future.  Also okay if that already exists, so we use sync.
            self._db.sync(self._metaTable, keys={"table_name": name})
            result = ByNameRegistryLayerOpaqueRecords(name=name, table=table, db=self._db)
            self._records[name] = result
        return result