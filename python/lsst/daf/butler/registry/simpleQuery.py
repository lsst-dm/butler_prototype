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

__all__ = ("Select", "SimpleQuery")

from typing import (
    Any,
    ClassVar,
    List,
    Optional,
    Union,
    Type,
    TypeVar,
)

import sqlalchemy


T = TypeVar("T")


class Select:
    """Tag class used to indicate that a field should be returned in
    a SELECT query.
    """

    Or: ClassVar


Select.Or = Union[T, Type[Select]]
"""A type annotation for arguments that can take the `Select` type or some
other value.
"""


class SimpleQuery:
    """A struct that combines SQLAlchemy objects representing SELECT, FROM,
    and WHERE clauses.
    """

    def __init__(self):
        self.columns = []
        self.where = []
        self._from = None

    def join(self, table: sqlalchemy.sql.FromClause, *,
             onclause: Optional[sqlalchemy.sql.ColumnElement] = None,
             isouter: bool = False,
             full: bool = False,
             **kwargs: Select.Or[Any]):
        """Add a table or subquery join to the query, possibly adding
        SELECT columns or WHERE expressions at the same time.

        Parameters
        ----------
        table : `sqlalchemy.sql.FromClause`
            Table or subquery to include.
        onclause : `sqlalchemy.sql.ColumnElement`, optional
            Expression used to join the new table or subquery to those already
            present.  Passed directly to `sqlalchemy.sql.FromClause.join`, but
            ignored if this is the first call to `SimpleQuery.join`.
        isouter : `bool`, optional
            If `True`, make this an LEFT OUTER JOIN.  Passed directly to
            `sqlalchemy.sql.FromClause.join`.
        full : `bool`, optional
            If `True`, make this a FULL OUTER JOIN.  Passed directly to
            `sqlalchemy.sql.FromClause.join`.
        **kwargs
            Additional keyword arguments correspond to columns in the joined
            table or subquery.  Values may be:

             - `Select` (a special tag type) to indicate that this column
               should be added to the SELECT clause as a query result;
             - `None` to do nothing (equivalent to no keyword argument);
             - Any other value to add an equality constraint to the WHERE
               clause that constrains this column to the given value.  Note
               that this cannot be used to add ``IS NULL`` constraints, because
               the previous condition for `None` is checked first.
        """
        if self._from is None:
            self._from = table
        else:
            self._from = self._from.join(table, onclause=onclause, isouter=isouter, full=full)
        for name, arg in kwargs.items():
            if arg is Select:
                self.columns.append(table.columns[name].label(name))
            elif arg is not None:
                self.where.append(table.columns[name] == arg)

    def combine(self) -> sqlalchemy.sql.Select:
        """Combine all terms into a single query object.

        Returns
        -------
        sql : `sqlalchemy.sql.Select`
            A SQLAlchemy object representing the full query.
        """
        result = sqlalchemy.sql.select(self.columns)
        if self._from is not None:
            result = result.select_from(self._from)
        if self.where:
            result = result.where(sqlalchemy.sql.and_(*self.where))
        return result

    @property
    def from_(self) -> sqlalchemy.sql.FromClause:
        """The FROM clause of the query (`sqlalchemy.sql.FromClause`).

        This property cannot be set.  To add tables to the FROM clause, call
        `join`.
        """
        return self._from

    columns: List[sqlalchemy.sql.ColumnElement]
    """The columns in the SELECT clause
    (`list` [ `sqlalchemy.sql.ColumnElement` ]).
    """

    where: List[sqlalchemy.sql.ColumnElement]
    """Boolean expressions that will be combined with AND to form the WHERE
    clause (`list` [ `sqlalchemy.sql.ColumnElement` ]).
    """
