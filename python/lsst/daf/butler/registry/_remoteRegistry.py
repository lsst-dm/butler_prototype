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

__all__ = (
    "RemoteRegistry",
)

from typing import (
    Any,
    Dict,
    Iterable,
    Iterator,
    List,
    Mapping,
    Optional,
    TYPE_CHECKING,
    Union,
)

import re
import contextlib
import httpx

from ..core import (
    ButlerURI,
    Config,
    DataCoordinate,
    DataId,
    DatasetAssociation,
    DatasetId,
    DatasetRef,
    DatasetType,
    Dimension,
    DimensionConfig,
    DimensionElement,
    DimensionGraph,
    DimensionRecord,
    DimensionUniverse,
    NameLookupMapping,
    SerializedDatasetType,
    StorageClassFactory,
    Timespan,
)
from ..core.utils import iterable

from . import queries
from ._registry import Registry
from ._config import RegistryConfig
from ._defaults import RegistryDefaults
from .interfaces import DatasetIdGenEnum
from ._collectionType import CollectionType
from .wildcards import CollectionSearch
from .summaries import CollectionSummary

if TYPE_CHECKING:
    from .._butlerConfig import ButlerConfig
    from .interfaces import (
        CollectionRecord,
        DatastoreRegistryBridgeManager,
    )


class RemoteRegistry(Registry):
    """Registry that can talk to a remote Butler server.

    Parameters
    ----------
    server_uri : `ButlerURI`
        URL of the remote Butler server.
    defaults : `RegistryDefaults`
        Default collection search path and/or output `~CollectionType.RUN`
        collection.
    """

    @classmethod
    def createFromConfig(cls, config: Optional[Union[RegistryConfig, str]] = None,
                         dimensionConfig: Optional[Union[DimensionConfig, str]] = None,
                         butlerRoot: Optional[str] = None) -> Registry:
        """Create registry database and return `Registry` instance.

        A remote registry can not create a registry database. Calling this
        method will raise an exception.
        """
        raise NotImplementedError("A remote registry can not create a registry.")

    @classmethod
    def fromConfig(cls, config: Union[ButlerConfig, RegistryConfig, Config, str],
                   butlerRoot: Optional[Union[str, ButlerURI]] = None, writeable: bool = True,
                   defaults: Optional[RegistryDefaults] = None) -> Registry:
        # Docstring inherited from lsst.daf.butler.registry.Registry
        config = cls.forceRegistryConfig(config)
        config.replaceRoot(butlerRoot)

        if defaults is None:
            defaults = RegistryDefaults()

        server_uri = ButlerURI(config["db"])
        return cls(server_uri, defaults, writeable)

    def __init__(self, server_uri: ButlerURI, defaults: RegistryDefaults, writeable: bool):
        self._db = server_uri
        self._defaults = defaults

        # All PUT calls should be short-circuited if not writeable.
        self._writeable = writeable

        self._dimensions: Optional[DimensionUniverse] = None

        # Does each API need to be sent the defaults so that the server
        # can use specific defaults each time?

        # Storage class information should be pulled from server.
        # Dimensions should be pulled from server.

    def __str__(self) -> str:
        return str(self._db)

    def __repr__(self) -> str:
        return f"RemoteRegistry({self._db!r}, {self.dimensions!r})"

    def isWriteable(self) -> bool:
        # Docstring inherited from lsst.daf.butler.registry.Registry
        # Can be used to prevent any PUTs to server
        return self._writeable

    def copy(self, defaults: Optional[RegistryDefaults] = None) -> Registry:
        # Docstring inherited from lsst.daf.butler.registry.Registry
        if defaults is None:
            # No need to copy, because `RegistryDefaults` is immutable; we
            # effectively copy on write.
            defaults = self.defaults
        return type(self)(self._db, defaults, self.isWriteable())

    @property
    def dimensions(self) -> DimensionUniverse:
        # Docstring inherited from lsst.daf.butler.registry.Registry
        if self._dimensions is not None:
            return self._dimensions

        # Access /dimensions.json on server and cache it locally.
        try:
            response = httpx.get(str(self._db.join("universe")))
            response.raise_for_status()
        except httpx.RequestError as e:
            print(f"An error occurred while requesting {e.request.url!r}.")
            raise e
        except httpx.HTTPStatusError as e:
            print(f"Error response {e.response.status_code} while requesting {e.request.url!r}.")
            raise e

        config = DimensionConfig.fromString(response.text, format="json")
        self._dimensions = DimensionUniverse(config)
        return self._dimensions

    def refresh(self) -> None:
        # Docstring inherited from lsst.daf.butler.registry.Registry

        # Need to determine what to refresh.
        # Might need a server method to return all the DatasetTypes up front.
        pass

    # def transaction():
    #    What does a transaction mean for the client? The server is running
    #    in a transaction but if the client wants one transaction that
    #    involves two server methods how does that work? The server will have
    #    already closed the transaction.
    @contextlib.contextmanager
    def transaction(self, *, savepoint: bool = False) -> Iterator[None]:
        # No-op for now
        try:
            yield
        except BaseException:
            raise

    # insertOpaqueData + fetchOpaqueData + deleteOpaqueData
    #    There are no managers for opaque data in client. This implies
    #    that the server would have to have specific implementations for
    #    use by Datastore. DatastoreBridgeManager also is not needed.

    # Should makeQueryBuilder be a public method? Nothing uses it outside
    # of Registry.

    def registerCollection(self, name: str, type: CollectionType = CollectionType.TAGGED,
                           doc: Optional[str] = None) -> None:
        # Docstring inherited from lsst.daf.butler.registry.Registry
        raise NotImplementedError()

    def getCollectionType(self, name: str) -> CollectionType:
        # Docstring inherited from lsst.daf.butler.registry.Registry
        raise NotImplementedError()

    def _get_collection_record(self, name: str) -> CollectionRecord:
        # Docstring inherited from lsst.daf.butler.registry.Registry
        raise NotImplementedError

    def registerRun(self, name: str, doc: Optional[str] = None) -> None:
        # Docstring inherited from lsst.daf.butler.registry.Registry
        raise NotImplementedError()

    def removeCollection(self, name: str) -> None:
        # Docstring inherited from lsst.daf.butler.registry.Registry
        raise NotImplementedError()

    def getCollectionChain(self, parent: str) -> CollectionSearch:
        # Docstring inherited from lsst.daf.butler.registry.Registry
        raise NotImplementedError()

    def setCollectionChain(self, parent: str, children: Any, *, flatten: bool = False) -> None:
        # Docstring inherited from lsst.daf.butler.registry.Registry
        raise NotImplementedError()

    def getCollectionDocumentation(self, collection: str) -> Optional[str]:
        # Docstring inherited from lsst.daf.butler.registry.Registry
        raise NotImplementedError()

    def setCollectionDocumentation(self, collection: str, doc: Optional[str]) -> None:
        # Docstring inherited from lsst.daf.butler.registry.Registry
        raise NotImplementedError()

    def getCollectionSummary(self, collection: str) -> CollectionSummary:
        # Docstring inherited from lsst.daf.butler.registry.Registry
        raise NotImplementedError()

    def registerDatasetType(self, datasetType: DatasetType) -> bool:
        # Docstring inherited from lsst.daf.butler.registry.Registry
        raise NotImplementedError()

    def removeDatasetType(self, name: str) -> None:
        # Docstring inherited from lsst.daf.butler.registry.Registry
        raise NotImplementedError()

    def getDatasetType(self, name: str) -> DatasetType:
        # Docstring inherited from lsst.daf.butler.registry.Registry
        raise NotImplementedError()

    def findDataset(self, datasetType: Union[DatasetType, str], dataId: Optional[DataId] = None, *,
                    collections: Any = None, timespan: Optional[Timespan] = None,
                    **kwargs: Any) -> Optional[DatasetRef]:
        # Docstring inherited from lsst.daf.butler.registry.Registry
        raise NotImplementedError()

    def insertDatasets(self, datasetType: Union[DatasetType, str], dataIds: Iterable[DataId],
                       run: Optional[str] = None, expand: bool = True,
                       idGenerationMode: DatasetIdGenEnum = DatasetIdGenEnum.UNIQUE) -> List[DatasetRef]:
        # Docstring inherited from lsst.daf.butler.registry.Registry
        raise NotImplementedError()

    def _importDatasets(self, datasets: Iterable[DatasetRef], expand: bool = True,
                        idGenerationMode: DatasetIdGenEnum = DatasetIdGenEnum.UNIQUE,
                        reuseIds: bool = False) -> List[DatasetRef]:
        # Docstring inherited from lsst.daf.butler.registry.Registry
        raise NotImplementedError()

    def getDataset(self, id: DatasetId) -> Optional[DatasetRef]:
        # Docstring inherited from lsst.daf.butler.registry.Registry
        raise NotImplementedError()

    def removeDatasets(self, refs: Iterable[DatasetRef]) -> None:
        # Docstring inherited from lsst.daf.butler.registry.Registry
        raise NotImplementedError()

    def associate(self, collection: str, refs: Iterable[DatasetRef]) -> None:
        # Docstring inherited from lsst.daf.butler.registry.Registry
        raise NotImplementedError()

    def disassociate(self, collection: str, refs: Iterable[DatasetRef]) -> None:
        # Docstring inherited from lsst.daf.butler.registry.Registry
        raise NotImplementedError()

    def certify(self, collection: str, refs: Iterable[DatasetRef], timespan: Timespan) -> None:
        # Docstring inherited from lsst.daf.butler.registry.Registry
        raise NotImplementedError()

    def decertify(self, collection: str, datasetType: Union[str, DatasetType], timespan: Timespan, *,
                  dataIds: Optional[Iterable[DataId]] = None) -> None:
        # Docstring inherited from lsst.daf.butler.registry.Registry
        raise NotImplementedError()

    def getDatastoreBridgeManager(self) -> DatastoreRegistryBridgeManager:
        """Return an object that allows a new `Datastore` instance to
        communicate with this `Registry`.

        Returns
        -------
        manager : `DatastoreRegistryBridgeManager`
            Object that mediates communication between this `Registry` and its
            associated datastores.
        """
        from ..tests._dummyRegistry import DummyDatastoreRegistryBridgeManager, DummyOpaqueTableStorageManager
        return DummyDatastoreRegistryBridgeManager(DummyOpaqueTableStorageManager(),
                                                   self.dimensions, int)

    def getDatasetLocations(self, ref: DatasetRef) -> Iterable[str]:
        # Docstring inherited from lsst.daf.butler.registry.Registry
        raise NotImplementedError()

    def expandDataId(self, dataId: Optional[DataId] = None, *, graph: Optional[DimensionGraph] = None,
                     records: Optional[NameLookupMapping[DimensionElement, Optional[DimensionRecord]]] = None,
                     withDefaults: bool = True,
                     **kwargs: Any) -> DataCoordinate:
        # Docstring inherited from lsst.daf.butler.registry.Registry
        raise NotImplementedError()

    def insertDimensionData(self, element: Union[DimensionElement, str],
                            *data: Union[Mapping[str, Any], DimensionRecord],
                            conform: bool = True) -> None:
        # Docstring inherited from lsst.daf.butler.registry.Registry
        raise NotImplementedError()

    def syncDimensionData(self, element: Union[DimensionElement, str],
                          row: Union[Mapping[str, Any], DimensionRecord],
                          conform: bool = True) -> bool:
        # Docstring inherited from lsst.daf.butler.registry.Registry
        raise NotImplementedError()

    def queryDatasetTypes(self, expression: Any = ..., *, components: Optional[bool] = None
                          ) -> Iterator[DatasetType]:
        # Docstring inherited from lsst.daf.butler.registry.Registry
        params: Dict[str, Any] = {}

        if expression is ...:
            path = "registry/datasetTypes"
        else:
            path = "registry/datasetTypes/re"
            expressions = iterable(expression)

            for expression in expressions:
                if isinstance(expression, re.Pattern):
                    if (k := "regex") not in params:
                        params[k] = []
                    params["regex"].append(expression.pattern)
                else:
                    if (k := "glob") not in params:
                        params[k] = []
                    params["glob"].append(expression)

        if components is not None:
            params = {"components": components}
        try:
            response = httpx.get(str(self._db.join(path)), params=params)
            response.raise_for_status()
        except httpx.RequestError as e:
            raise e
        except httpx.HTTPStatusError as e:
            raise e

        # Really could do with a ListSerializedDatasetType model but for
        # now do it explicitly.
        datasetTypes = response.json()
        return (DatasetType.from_simple(SerializedDatasetType(**d), universe=self.dimensions)
                for d in datasetTypes)

    def queryCollections(self, expression: Any = ...,
                         datasetType: Optional[DatasetType] = None,
                         collectionTypes: Iterable[CollectionType] = CollectionType.all(),
                         flattenChains: bool = False,
                         includeChains: Optional[bool] = None) -> Iterator[str]:
        # Docstring inherited from lsst.daf.butler.registry.Registry
        raise NotImplementedError()

    def queryDatasets(self, datasetType: Any, *,
                      collections: Any = None,
                      dimensions: Optional[Iterable[Union[Dimension, str]]] = None,
                      dataId: Optional[DataId] = None,
                      where: Optional[str] = None,
                      findFirst: bool = False,
                      components: Optional[bool] = None,
                      bind: Optional[Mapping[str, Any]] = None,
                      check: bool = True,
                      **kwargs: Any) -> queries.DatasetQueryResults:
        # Docstring inherited from lsst.daf.butler.registry.Registry
        raise NotImplementedError()

    def queryDataIds(self, dimensions: Union[Iterable[Union[Dimension, str]], Dimension, str], *,
                     dataId: Optional[DataId] = None,
                     datasets: Any = None,
                     collections: Any = None,
                     where: Optional[str] = None,
                     components: Optional[bool] = None,
                     bind: Optional[Mapping[str, Any]] = None,
                     check: bool = True,
                     **kwargs: Any) -> queries.DataCoordinateQueryResults:
        # Docstring inherited from lsst.daf.butler.registry.Registry
        raise NotImplementedError()

    def queryDimensionRecords(self, element: Union[DimensionElement, str], *,
                              dataId: Optional[DataId] = None,
                              datasets: Any = None,
                              collections: Any = None,
                              where: Optional[str] = None,
                              components: Optional[bool] = None,
                              bind: Optional[Mapping[str, Any]] = None,
                              check: bool = True,
                              **kwargs: Any) -> Iterator[DimensionRecord]:
        # Docstring inherited from lsst.daf.butler.registry.Registry
        raise NotImplementedError()

    def queryDatasetAssociations(
        self,
        datasetType: Union[str, DatasetType],
        collections: Any = ...,
        *,
        collectionTypes: Iterable[CollectionType] = CollectionType.all(),
        flattenChains: bool = False,
    ) -> Iterator[DatasetAssociation]:
        # Docstring inherited from lsst.daf.butler.registry.Registry
        raise NotImplementedError()

    storageClasses: StorageClassFactory
    """All storage classes known to the registry (`StorageClassFactory`).
    """