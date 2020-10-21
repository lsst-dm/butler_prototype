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

__all__ = ["PostgresqlDatabase"]

from contextlib import contextmanager, closing
from typing import Any, Dict, Iterable, Iterator, Mapping, Optional, Tuple, Type, Union

import psycopg2
import sqlalchemy.dialects.postgresql

from ..interfaces import Database
from ..nameShrinker import NameShrinker
from ...core import TimespanDatabaseRepresentation, ddl, Timespan, time_utils


class PostgresqlDatabase(Database):
    """An implementation of the `Database` interface for PostgreSQL.

    Parameters
    ----------
    connection : `sqlalchemy.engine.Connection`
        An existing connection created by a previous call to `connect`.
    origin : `int`
        An integer ID that should be used as the default for any datasets,
        quanta, or other entities that use a (autoincrement, origin) compound
        primary key.
    namespace : `str`, optional
        The namespace (schema) this database is associated with.  If `None`,
        the default schema for the connection is used (which may be `None`).
    writeable : `bool`, optional
        If `True`, allow write operations on the database, including
        ``CREATE TABLE``.

    Notes
    -----
    This currently requires the psycopg2 driver to be used as the backend for
    SQLAlchemy.  Running the tests for this class requires the
    ``testing.postgresql`` be installed, which we assume indicates that a
    PostgreSQL server is installed and can be run locally in userspace.

    Some functionality provided by this class (and used by `Registry`) requires
    the ``btree_gist`` PostgreSQL server extension to be installed an enabled
    on the database being connected to; this is checked at connection time.
    """

    def __init__(self, *, connection: sqlalchemy.engine.Connection, origin: int,
                 namespace: Optional[str] = None, writeable: bool = True):
        super().__init__(origin=origin, connection=connection, namespace=namespace)
        dbapi = connection.connection
        try:
            dsn = dbapi.get_dsn_parameters()
        except (AttributeError, KeyError) as err:
            raise RuntimeError("Only the psycopg2 driver for PostgreSQL is supported.") from err
        if namespace is None:
            namespace = connection.execute("SELECT current_schema();").scalar()
        if not connection.execute("SELECT COUNT(*) FROM pg_extension WHERE extname='btree_gist';").scalar():
            raise RuntimeError(
                "The Butler PostgreSQL backend requires the btree_gist extension. "
                "As extensions are enabled per-database, this may require an administrator to run "
                "`CREATE EXTENSION btree_gist;` in a database before a butler client for it is initialized."
            )
        self.namespace = namespace
        self.dbname = dsn.get("dbname")
        self._writeable = writeable
        self._shrinker = NameShrinker(connection.engine.dialect.max_identifier_length)

    @classmethod
    def connect(cls, uri: str, *, writeable: bool = True) -> sqlalchemy.engine.Connection:
        return sqlalchemy.engine.create_engine(uri, poolclass=sqlalchemy.pool.NullPool).connect()

    @classmethod
    def fromConnection(cls, connection: sqlalchemy.engine.Connection, *, origin: int,
                       namespace: Optional[str] = None, writeable: bool = True) -> Database:
        return cls(connection=connection, origin=origin, namespace=namespace, writeable=writeable)

    @contextmanager
    def transaction(self, *, interrupting: bool = False, savepoint: bool = False,
                    lock: Iterable[sqlalchemy.schema.Table] = ()) -> Iterator[None]:
        with super().transaction(interrupting=interrupting, savepoint=savepoint, lock=lock):
            if not self.isWriteable():
                with closing(self._connection.connection.cursor()) as cursor:
                    cursor.execute("SET TRANSACTION READ ONLY")
            yield

    def _lockTables(self, tables: Iterable[sqlalchemy.schema.Table] = ()) -> None:
        # Docstring inherited.
        for table in tables:
            self._connection.execute(f"LOCK TABLE {table.key} IN EXCLUSIVE MODE")

    def isWriteable(self) -> bool:
        return self._writeable

    def __str__(self) -> str:
        return f"PostgreSQL@{self.dbname}:{self.namespace}"

    def shrinkDatabaseEntityName(self, original: str) -> str:
        return self._shrinker.shrink(original)

    def expandDatabaseEntityName(self, shrunk: str) -> str:
        return self._shrinker.expand(shrunk)

    def _convertExclusionConstraintSpec(self, table: str,
                                        spec: Tuple[Union[str, Type[TimespanDatabaseRepresentation]], ...],
                                        metadata: sqlalchemy.MetaData) -> sqlalchemy.schema.Constraint:
        # Docstring inherited.
        args = []
        names = ["excl"]
        for item in spec:
            if isinstance(item, str):
                args.append((sqlalchemy.schema.Column(item), "="))
                names.append(item)
            elif issubclass(item, TimespanDatabaseRepresentation):
                assert item is self.getTimespanRepresentation()
                args.append((sqlalchemy.schema.Column(TimespanDatabaseRepresentation.NAME), "&&"))
                names.append(TimespanDatabaseRepresentation.NAME)
        return sqlalchemy.dialects.postgresql.ExcludeConstraint(
            *args,
            name=self.shrinkDatabaseEntityName("_".join(names)),
        )

    @classmethod
    def getTimespanRepresentation(cls) -> Type[TimespanDatabaseRepresentation]:
        # Docstring inherited.
        return _RangeTimespanRepresentation

    def replace(self, table: sqlalchemy.schema.Table, *rows: dict) -> None:
        self.assertTableWriteable(table, f"Cannot replace into read-only table {table}.")
        if not rows:
            return
        # This uses special support for UPSERT in PostgreSQL backend:
        # https://docs.sqlalchemy.org/en/13/dialects/postgresql.html#insert-on-conflict-upsert
        query = sqlalchemy.dialects.postgresql.dml.insert(table)
        # In the SET clause assign all columns using special `excluded`
        # pseudo-table.  If some column in the table does not appear in the
        # INSERT list this will set it to NULL.
        excluded = query.excluded
        data = {column.name: getattr(excluded, column.name)
                for column in table.columns
                if column.name not in table.primary_key}
        query = query.on_conflict_do_update(constraint=table.primary_key, set_=data)
        self._connection.execute(query, *rows)

    def ensure(self, table: sqlalchemy.schema.Table, *rows: dict) -> int:
        # Docstring inherited.
        self.assertTableWriteable(table, f"Cannot ensure into read-only table {table}.")
        if not rows:
            return 0
        # Like `replace`, this uses UPSERT, but it's a bit simpler because
        # we don't care which constraint is violated or specify which columns
        # to update.
        query = sqlalchemy.dialects.postgresql.dml.insert(table).on_conflict_do_nothing()
        return self._connection.execute(query, *rows).rowcount


class _RangeTimespanType(sqlalchemy.TypeDecorator):
    """A single-column `Timespan` representation usable only with
    PostgreSQL.

    This type should be able to take advantage of PostgreSQL's built-in
    range operators, and the indexing and EXCLUSION table constraints built
    off of them.
    """

    impl = sqlalchemy.dialects.postgresql.INT8RANGE

    def process_bind_param(self, value: Optional[Timespan],
                           dialect: sqlalchemy.engine.Dialect
                           ) -> Optional[psycopg2.extras.NumericRange]:
        if value is None:
            return None
        if not isinstance(value, Timespan):
            raise TypeError(f"Unsupported type: {type(value)}, expected Timespan.")
        lower = None if value.begin is None else time_utils.astropy_to_nsec(value.begin)
        upper = None if value.end is None else time_utils.astropy_to_nsec(value.end)
        return psycopg2.extras.NumericRange(lower=lower, upper=upper)

    def process_result_value(self, value: Optional[psycopg2.extras.NumericRange],
                             dialect: sqlalchemy.engine.Dialect
                             ) -> Optional[Timespan]:
        if value is None or value.isempty:
            return None
        begin = None if value.lower is None else time_utils.nsec_to_astropy(value.lower)
        end = None if value.upper is None else time_utils.nsec_to_astropy(value.upper)
        return Timespan(begin=begin, end=end)

    class comparator_factory(sqlalchemy.types.Concatenable.Comparator):  # noqa: N801
        """Comparison operators for TimespanColumnRanges.

        Notes
        -----
        The existence of this nested class is a workaround for a bug
        submitted upstream as
        https://github.com/sqlalchemy/sqlalchemy/issues/5476.  The code is
        a limited copy of the operators in
        ``sqlalchemy.dialects.postgresql.ranges.RangeOperators``, but with
        ``is_comparison=True`` added to all calls.
        """

        def __ne__(self, other: Any) -> Any:
            "Boolean expression. Returns true if two ranges are not equal"
            if other is None:
                return super().__ne__(other)
            else:
                return self.expr.op("<>", is_comparison=True)(other)

        def contains(self, other: Any, **kw: Any) -> Any:
            """Boolean expression. Returns true if the right hand operand,
            which can be an element or a range, is contained within the
            column.
            """
            return self.expr.op("@>", is_comparison=True)(other)

        def contained_by(self, other: Any) -> Any:
            """Boolean expression. Returns true if the column is contained
            within the right hand operand.
            """
            return self.expr.op("<@", is_comparison=True)(other)

        def overlaps(self, other: Any) -> Any:
            """Boolean expression. Returns true if the column overlaps
            (has points in common with) the right hand operand.
            """
            return self.expr.op("&&", is_comparison=True)(other)


class _RangeTimespanRepresentation(TimespanDatabaseRepresentation):
    """An implementation of `TimespanDatabaseRepresentation` that uses
    `_RangeTimespanType` to store a timespan in a single
    PostgreSQL-specific field.

    Parameters
    ----------
    column : `sqlalchemy.sql.ColumnElement`
        SQLAlchemy object representing the column.
    """
    def __init__(self, column: sqlalchemy.sql.ColumnElement):
        self.column = column

    __slots__ = ("column",)

    @classmethod
    def makeFieldSpecs(cls, nullable: bool, **kwargs: Any) -> Tuple[ddl.FieldSpec, ...]:
        # Docstring inherited.
        return (
            ddl.FieldSpec(
                cls.NAME, dtype=_RangeTimespanType, nullable=nullable,
                default=(None if nullable else sqlalchemy.sql.text("'(,)'::int8range")),
                **kwargs
            ),
        )

    @classmethod
    def getFieldNames(cls) -> Tuple[str, ...]:
        # Docstring inherited.
        return (cls.NAME,)

    @classmethod
    def update(cls, timespan: Optional[Timespan], *,
               result: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        # Docstring inherited.
        if result is None:
            result = {}
        result[cls.NAME] = timespan
        return result

    @classmethod
    def extract(cls, mapping: Mapping[str, Any]) -> Optional[Timespan]:
        # Docstring inherited.
        return mapping[cls.NAME]

    @classmethod
    def hasExclusionConstraint(cls) -> bool:
        # Docstring inherited.
        return True

    @classmethod
    def fromSelectable(cls, selectable: sqlalchemy.sql.FromClause) -> _RangeTimespanRepresentation:
        # Docstring inherited.
        return cls(selectable.columns[cls.NAME])

    def isNull(self) -> sqlalchemy.sql.ColumnElement:
        # Docstring inherited.
        return self.column.is_(None)

    def overlaps(self, other: Union[Timespan, _RangeTimespanRepresentation]) -> sqlalchemy.sql.ColumnElement:
        # Docstring inherited.
        if isinstance(other, Timespan):
            return self.column.overlaps(other)
        else:
            return self.column.overlaps(other.column)
