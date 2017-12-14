#
# LSST Data Management System
#
# Copyright 2008-2017  AURA/LSST.
#
# This product includes software developed by the
# LSST Project (http://www.lsst.org/).
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
# You should have received a copy of the LSST License Statement and
# the GNU General Public License along with this program.  If not,
# see <https://www.lsstcorp.org/LegalNotices/>.
#

import yaml
from abc import ABCMeta, abstractmethod, abstractproperty
from ..config import Config

class DatastoreConfig(Config):
    pass

class Datastore(metaclass=ABCMeta):
    """Datastore interface.
    """
    @staticmethod
    def fromConfig(config):
        from lsst.daf.persistence import doImport
        cls = doImport(config['datastore.cls'])
        return cls(config=config)
    
    def __init__(self, config):
        """Constructor

        Parameters
        ----------
        config : `DatastoreConfig` or `str`
            Load configuration
        """
        self.config = DatastoreConfig(config)['datastore']

    @abstractmethod
    def get(self, uri, storageClass, parameters=None):
        """Load an `InMemoryDataset` from the store.

        Parameters
        ----------
        uri : `str`
            a Universal Resource Identifier that specifies the location of the stored `Dataset`.
        storageClass : `StorageClass`
            the `StorageClass` associated with the `DatasetType`.
        parameters : `dict`
            `StorageClass`-specific parameters that specify a slice of the `Dataset` to be loaded.

        Returns
        -------
        inMemoryDataset : `InMemoryDataset`
            Requested `Dataset` or slice thereof as an `InMemoryDataset`.
        """
        raise NotImplementedError("Must be implemented by subclass")

    @abstractmethod
    def put(self, inMemoryDataset, storageClass, path, typeName=None):
        """Write a `InMemoryDataset` with a given `StorageClass` to the store.

        Parameters
        ----------
        inMemoryDataset : `InMemoryDataset`
            The `Dataset` to store.
        storageClass : `StorageClass`
            The `StorageClass` associated with the `DatasetType`.
        path : `str`
            A `Path` that provides a hint that the `Datastore` may use as (part of) the URI.
        typeName : `str`
            The `DatasetType` name, which may be used by this `Datastore` to override the
            default serialization format for the `StorageClass`.

        Returns
        -------
        uri : `str` 
            The `URI` where the primary `Dataset` is stored.
        components : `dict`, optional
            A dictionary of URIs for the `Dataset`' components.
            The latter will be empty if the `Dataset` is not a composite.
        """
        raise NotImplementedError("Must be implemented by subclass")

    @abstractmethod
    def remove(self, uri):
        """Indicate to the Datastore that a `Dataset` can be removed.

        Parameters
        ----------
        uri : `str`
            a Universal Resource Identifier that specifies the location of the stored `Dataset`.

        .. note::
            Some Datastores may implement this method as a silent no-op to disable `Dataset` deletion through standard interfaces.
        
        Raises
        ------
        e : `FileNotFoundError`
            When `Dataset` does not exist.
        """
        raise NotImplementedError("Must be implemented by subclass")

    @abstractmethod
    def transfer(self, inputDatastore, inputUri, storageClass, path, typeName=None):
        """Retrieve a `Dataset` with a given `URI` from an input `Datastore`,
        and store the result in this `Datastore`.

        Parameters
        ----------
        inputDatastore : `Datastore`
            The external `Datastore` from which to retreive the `Dataset`.
        inputUri : `str`
            The `URI` of the `Dataset` in the input `Datastore`.
        storageClass : `StorageClass`
            The `StorageClass` associated with the `DatasetType`.
        path : `str`
            A `Path` that provides a hint that this `Datastore` may use as [part of] the `URI`.
        typeName : `str`
            The `DatasetType` name, which may be used by this `Datastore` to override the default serialization format for the `StorageClass`.

        Returns
        -------
        uri : `str` 
            The `URI` where the primary `Dataset` is stored.
        components : `dict`, optional
            A dictionary of URIs for the `Dataset`' components.
            The latter will be empty if the `Dataset` is not a composite.
        """
        raise NotImplementedError("Must be implemented by subclass")
