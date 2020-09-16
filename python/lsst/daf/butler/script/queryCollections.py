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

from .. import Butler
from ..core.utils import globToRegex


def queryCollections(repo, glob, collection_type, flatten_chains, include_chains):
    """Get the collections whose names match an expression.

    Parameters
    ----------
    repo : `str`
        URI to the location of the repo or URI to a config file describing the
        repo and its location.
    glob : iterable [`str`]
        A list of glob-style search string that fully or partially identify
        the dataset type names to search for.
    collection_type : `Iterable` [ `CollectionType` ], optional
        If provided, only return collections of these types.
    flatten_chains : `bool`
        If `True` (`False` is default), recursively yield the child collections
        of matching `~CollectionType.CHAINED` collections.
    include_chains : `bool` or `None`
        If `True`, yield records for matching `~CollectionType.CHAINED`
        collections.  Default is the opposite of ``flattenChains``: include
        either CHAINED collections or their children, but not both.

    Returns
    -------
    collections : `dict` [`str`, [`str`]]
        A dict whose key is "collections" and whose value is a list of
        collection names.
    """
    butler = Butler(repo)
    expression = globToRegex(glob)
    # Only pass expression to queryCollections if there is an expression to
    # apply; otherwise let queryCollections use its default value.
    kwargs = {}
    if expression:
        kwargs["expression"] = expression
    collections = butler.registry.queryCollections(collectionTypes=frozenset(collection_type),
                                                   flattenChains=flatten_chains,
                                                   includeChains=include_chains,
                                                   **kwargs)
    return {"collections": list(collections)}
