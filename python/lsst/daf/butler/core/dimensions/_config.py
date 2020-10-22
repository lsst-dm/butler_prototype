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

__all__ = ("DimensionConfig",)

from typing import Iterator, Iterable, Optional, Union

from ..config import Config, ConfigSubset
from .. import ddl
from .._butlerUri import ButlerURI
from .._topology import TopologicalSpace
from .construction import DimensionConstructionBuilder, DimensionConstructionVisitor
from ._packer import DimensionPackerConstructionVisitor
from ._skypix import SkyPixConstructionVisitor
from .standard import (
    StandardDimensionElementConstructionVisitor,
    StandardTopologicalFamilyConstructionVisitor,
)


class DimensionConfig(ConfigSubset):
    """Configuration that defines a `DimensionUniverse`.

    The configuration tree for dimensions is a (nested) dictionary
    with five top-level entries:

    - version: an integer version number, used as keys in a singleton registry
      of all `DimensionUniverse` instances;

    - skypix: a dictionary whose entries each define a `SkyPixSystem`,
      along with a special "common" key whose value is the name of a skypix
      dimension that is used to relate all other spatial dimensions in the
      `Registry` database;

    - elements: a nested dictionary whose entries each define
      `StandardDimension` or `StandardDimensionCombination`.

    - topology: a nested dictionary with ``spatial`` and ``temporal`` keys,
      with dictionary values that each define a `StandardTopologicalFamily`.

    - packers: a nested dictionary whose entries define factories for a
      `DimensionPacker` instance.

    See the documentation for the linked classes above for more information
    on the configuration syntax.

    Parameters
    ----------
    other : `Config` or `str` or `dict`, optional
        Argument specifying the configuration information as understood
        by `Config`. If `None` is passed then defaults are loaded from
        "dimensions.yaml", otherwise defaults are not loaded.
    validate : `bool`, optional
        If `True` required keys will be checked to ensure configuration
        consistency.
    searchPaths : `list` or `tuple`, optional
        Explicit additional paths to search for defaults. They should
        be supplied in priority order. These paths have higher priority
        than those read from the environment in
        `ConfigSubset.defaultSearchPaths()`.  Paths can be `str` referring to
        the local file system or URIs, `ButlerURI`.
    """

    requiredKeys = ("version", "elements", "skypix")
    defaultConfigFile = "dimensions.yaml"

    def __init__(self, other: Union[Config, ButlerURI, str, None] = None, validate: bool = True,
                 searchPaths: Optional[Iterable[Union[str, ButlerURI]]] = None):
        # if argument is not None then do not load/merge defaults
        mergeDefaults = other is None
        super().__init__(other=other, validate=validate, mergeDefaults=mergeDefaults,
                         searchPaths=searchPaths)

    def _updateWithConfigsFromPath(self, searchPaths: Iterable[Union[str, ButlerURI]],
                                   configFile: str) -> None:
        """Search the supplied paths reading config from first found.

        Raises
        ------
        FileNotFoundError
            Raised if config file is not found in any of given locations.

        Notes
        -----
        This method overrides base class method with different behavior.
        Instead of merging all found files into a single configuration it
        finds first matching file and reads it.
        """
        uri = ButlerURI(configFile)
        if uri.isabs() and uri.exists():
            # Assume this resource exists
            self._updateWithOtherConfigFile(configFile)
            self.filesRead.append(configFile)
        else:
            for pathDir in searchPaths:
                if isinstance(pathDir, (str, ButlerURI)):
                    pathDir = ButlerURI(pathDir, forceDirectory=True)
                    file = pathDir.join(configFile)
                    if file.exists():
                        self.filesRead.append(file)
                        self._updateWithOtherConfigFile(file)
                        break
                else:
                    raise TypeError(f"Unexpected search path type encountered: {pathDir!r}")
            else:
                raise FileNotFoundError(f"Could not find {configFile} in search path {searchPaths}")

    def _updateWithOtherConfigFile(self, file: Union[ButlerURI, str]) -> None:
        """Override for base class method.

        Parameters
        ----------
        file : `Config`, `str`, `ButlerURI`, or `dict`
            Entity that can be converted to a `ConfigSubset`.
        """
        # Use this class to read the defaults so that subsetting can happen
        # correctly.
        externalConfig = type(self)(file, validate=False)
        self.update(externalConfig)

    def _extractSkyPixVisitors(self) -> Iterator[DimensionConstructionVisitor]:
        """Process the 'skypix' section of the configuration, yielding a
        construction visitor for each `SkyPixSystem`.

        Yields
        ------
        visitor : `DimensionConstructionVisitor`
            Object that adds a skypix system and its dimensions to an
            under-construction `DimensionUniverse`.
        """
        config = self["skypix"]
        systemNames = set(config.keys())
        systemNames.remove("common")
        for systemName in sorted(systemNames):
            subconfig = config[systemName]
            pixelizationClassName = subconfig["class"]
            maxLevel = subconfig.get("max_level", 24)
            yield SkyPixConstructionVisitor(systemName, pixelizationClassName, maxLevel)

    def _extractElementVisitors(self) -> Iterator[DimensionConstructionVisitor]:
        """Process the 'elements' section of the configuration, yielding a
        construction visitor for each `StandardDimension` or
        `StandardDimensionCombination`.

        Yields
        ------
        visitor : `DimensionConstructionVisitor`
            Object that adds a `StandardDimension` or
            `StandardDimensionCombination` to an under-construction
            `DimensionUniverse`.
        """
        for name, subconfig in self["elements"].items():
            uniqueKeys = [ddl.FieldSpec.fromConfig(c, nullable=False) for c in subconfig.get("keys", ())]
            if uniqueKeys:
                uniqueKeys[0].primaryKey = True
            yield StandardDimensionElementConstructionVisitor(
                name=name,
                required=set(subconfig.get("requires", ())),
                implied=set(subconfig.get("implies", ())),
                metadata=[ddl.FieldSpec.fromConfig(c) for c in subconfig.get("metadata", ())],
                cached=subconfig.get("cached", False),
                viewOf=subconfig.get("view_of", None),
                alwaysJoin=subconfig.get("always_join", False),
                uniqueKeys=uniqueKeys,
            )

    def _extractTopologyVisitors(self) -> Iterator[DimensionConstructionVisitor]:
        """Process the 'topology' section of the configuration, yielding a
        construction visitor for each `StandardTopologicalFamily`.

        Yields
        ------
        visitor : `DimensionConstructionVisitor`
            Object that adds a `StandardTopologicalFamily` to an
            under-construction `DimensionUniverse` and updates its member
            `DimensionElement` instances.
        """
        for spaceName, subconfig in self.get("topology", {}).items():
            space = TopologicalSpace.__members__[spaceName.upper()]
            for name, members in subconfig.items():
                yield StandardTopologicalFamilyConstructionVisitor(
                    name=name,
                    space=space,
                    members=members,
                )

    def _extractPackerVisitors(self) -> Iterator[DimensionConstructionVisitor]:
        """Process the 'packers' section of the configuration, yielding
        construction visitors for each `DimensionPackerFactory`.

        Yields
        ------
        visitor : `DimensionConstructionVisitor`
            Object that adds a `DinmensionPackerFactory` to an
            under-construction `DimensionUniverse`.
        """
        for name, subconfig in self["packers"].items():
            yield DimensionPackerConstructionVisitor(
                name=name,
                clsName=subconfig["cls"],
                fixed=subconfig["fixed"],
                dimensions=subconfig["dimensions"],
            )

    def makeBuilder(self) -> DimensionConstructionBuilder:
        """Construct a `DinmensionConstructionBuilder` that reflects this
        configuration.

        Returns
        -------
        builder : `DimensionConstructionBuilder`
            A builder object populated with all visitors from this
            configuration.  The `~DimensionConstructionBuilder.finish` method
            will not have been called.
        """
        builder = DimensionConstructionBuilder(self["version"], self["skypix", "common"])
        builder.update(self._extractSkyPixVisitors())
        builder.update(self._extractElementVisitors())
        builder.update(self._extractTopologyVisitors())
        builder.update(self._extractPackerVisitors())
        return builder
