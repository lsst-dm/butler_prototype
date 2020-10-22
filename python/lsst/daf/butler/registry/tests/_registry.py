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

__all__ = ["RegistryTests"]

from abc import ABC, abstractmethod
import itertools
import os
import re
import unittest

import astropy.time
import sqlalchemy
from typing import Optional, Type, Union

try:
    import numpy as np
except ImportError:
    np = None

from ...core import (
    DataCoordinate,
    DataCoordinateSequence,
    DataCoordinateSet,
    DatasetAssociation,
    DatasetRef,
    DatasetType,
    DimensionGraph,
    NamedValueSet,
    StorageClass,
    ddl,
    Timespan,
)
from .._registry import (
    CollectionType,
    ConflictingDefinitionError,
    InconsistentDataIdError,
    Registry,
    RegistryConfig,
)
from ..wildcards import DatasetTypeRestriction
from ..interfaces import MissingCollectionError, ButlerAttributeExistsError


class RegistryTests(ABC):
    """Generic tests for the `Registry` class that can be subclassed to
    generate tests for different configurations.
    """

    collectionsManager: Optional[str] = None
    """Name of the collections manager class, if subclass provides value for
    this member then it overrides name specified in default configuration
    (`str`).
    """

    @classmethod
    @abstractmethod
    def getDataDir(cls) -> str:
        """Return the root directory containing test data YAML files.
        """
        raise NotImplementedError()

    def makeRegistryConfig(self) -> RegistryConfig:
        """Create RegistryConfig used to create a registry.

        This method should be called by a subclass from `makeRegistry`.
        Returned instance will be pre-configured based on the values of class
        members, and default-configured for all other parametrs. Subclasses
        that need default configuration should just instantiate
        `RegistryConfig` directly.
        """
        config = RegistryConfig()
        if self.collectionsManager:
            config["managers"]["collections"] = self.collectionsManager
        return config

    @abstractmethod
    def makeRegistry(self) -> Registry:
        """Return the Registry instance to be tested.
        """
        raise NotImplementedError()

    def loadData(self, registry: Registry, filename: str):
        """Load registry test data from ``getDataDir/<filename>``,
        which should be a YAML import/export file.
        """
        from ...transfers import YamlRepoImportBackend
        with open(os.path.join(self.getDataDir(), filename), 'r') as stream:
            backend = YamlRepoImportBackend(stream, registry)
        backend.register()
        backend.load(datastore=None)

    def assertRowCount(self, registry: Registry, table: str, count: int):
        """Check the number of rows in table.
        """
        # TODO: all tests that rely on this method should be rewritten, as it
        # needs to depend on Registry implementation details to have any chance
        # of working.
        sql = sqlalchemy.sql.select(
            [sqlalchemy.sql.func.count()]
        ).select_from(
            getattr(registry._tables, table)
        )
        self.assertEqual(registry._db.query(sql).scalar(), count)

    def testOpaque(self):
        """Tests for `Registry.registerOpaqueTable`,
        `Registry.insertOpaqueData`, `Registry.fetchOpaqueData`, and
        `Registry.deleteOpaqueData`.
        """
        registry = self.makeRegistry()
        table = "opaque_table_for_testing"
        registry.registerOpaqueTable(
            table,
            spec=ddl.TableSpec(
                fields=[
                    ddl.FieldSpec("id", dtype=sqlalchemy.BigInteger, primaryKey=True),
                    ddl.FieldSpec("name", dtype=sqlalchemy.String, length=16, nullable=False),
                    ddl.FieldSpec("count", dtype=sqlalchemy.SmallInteger, nullable=True),
                ],
            )
        )
        rows = [
            {"id": 1, "name": "one", "count": None},
            {"id": 2, "name": "two", "count": 5},
            {"id": 3, "name": "three", "count": 6},
        ]
        registry.insertOpaqueData(table, *rows)
        self.assertCountEqual(rows, list(registry.fetchOpaqueData(table)))
        self.assertEqual(rows[0:1], list(registry.fetchOpaqueData(table, id=1)))
        self.assertEqual(rows[1:2], list(registry.fetchOpaqueData(table, name="two")))
        self.assertEqual([], list(registry.fetchOpaqueData(table, id=1, name="two")))
        registry.deleteOpaqueData(table, id=3)
        self.assertCountEqual(rows[:2], list(registry.fetchOpaqueData(table)))
        registry.deleteOpaqueData(table)
        self.assertEqual([], list(registry.fetchOpaqueData(table)))

    def testDatasetType(self):
        """Tests for `Registry.registerDatasetType` and
        `Registry.getDatasetType`.
        """
        registry = self.makeRegistry()
        # Check valid insert
        datasetTypeName = "test"
        storageClass = StorageClass("testDatasetType")
        registry.storageClasses.registerStorageClass(storageClass)
        dimensions = registry.dimensions.extract(("instrument", "visit"))
        differentDimensions = registry.dimensions.extract(("instrument", "patch"))
        inDatasetType = DatasetType(datasetTypeName, dimensions, storageClass)
        # Inserting for the first time should return True
        self.assertTrue(registry.registerDatasetType(inDatasetType))
        outDatasetType1 = registry.getDatasetType(datasetTypeName)
        self.assertEqual(outDatasetType1, inDatasetType)

        # Re-inserting should work
        self.assertFalse(registry.registerDatasetType(inDatasetType))
        # Except when they are not identical
        with self.assertRaises(ConflictingDefinitionError):
            nonIdenticalDatasetType = DatasetType(datasetTypeName, differentDimensions, storageClass)
            registry.registerDatasetType(nonIdenticalDatasetType)

        # Template can be None
        datasetTypeName = "testNoneTemplate"
        storageClass = StorageClass("testDatasetType2")
        registry.storageClasses.registerStorageClass(storageClass)
        dimensions = registry.dimensions.extract(("instrument", "visit"))
        inDatasetType = DatasetType(datasetTypeName, dimensions, storageClass)
        registry.registerDatasetType(inDatasetType)
        outDatasetType2 = registry.getDatasetType(datasetTypeName)
        self.assertEqual(outDatasetType2, inDatasetType)

        allTypes = set(registry.queryDatasetTypes())
        self.assertEqual(allTypes, {outDatasetType1, outDatasetType2})

    def testDimensions(self):
        """Tests for `Registry.insertDimensionData`,
        `Registry.syncDimensionData`, and `Registry.expandDataId`.
        """
        registry = self.makeRegistry()
        dimensionName = "instrument"
        dimension = registry.dimensions[dimensionName]
        dimensionValue = {"name": "DummyCam", "visit_max": 10, "exposure_max": 10, "detector_max": 2,
                          "class_name": "lsst.obs.base.Instrument"}
        registry.insertDimensionData(dimensionName, dimensionValue)
        # Inserting the same value twice should fail
        with self.assertRaises(sqlalchemy.exc.IntegrityError):
            registry.insertDimensionData(dimensionName, dimensionValue)
        # expandDataId should retrieve the record we just inserted
        self.assertEqual(
            registry.expandDataId(
                instrument="DummyCam",
                graph=dimension.graph
            ).records[dimensionName].toDict(),
            dimensionValue
        )
        # expandDataId should raise if there is no record with the given ID.
        with self.assertRaises(LookupError):
            registry.expandDataId({"instrument": "Unknown"}, graph=dimension.graph)
        # band doesn't have a table; insert should fail.
        with self.assertRaises(TypeError):
            registry.insertDimensionData("band", {"band": "i"})
        dimensionName2 = "physical_filter"
        dimension2 = registry.dimensions[dimensionName2]
        dimensionValue2 = {"name": "DummyCam_i", "band": "i"}
        # Missing required dependency ("instrument") should fail
        with self.assertRaises(KeyError):
            registry.insertDimensionData(dimensionName2, dimensionValue2)
        # Adding required dependency should fix the failure
        dimensionValue2["instrument"] = "DummyCam"
        registry.insertDimensionData(dimensionName2, dimensionValue2)
        # expandDataId should retrieve the record we just inserted.
        self.assertEqual(
            registry.expandDataId(
                instrument="DummyCam", physical_filter="DummyCam_i",
                graph=dimension2.graph
            ).records[dimensionName2].toDict(),
            dimensionValue2
        )
        # Use syncDimensionData to insert a new record successfully.
        dimensionName3 = "detector"
        dimensionValue3 = {"instrument": "DummyCam", "id": 1, "full_name": "one",
                           "name_in_raft": "zero", "purpose": "SCIENCE"}
        self.assertTrue(registry.syncDimensionData(dimensionName3, dimensionValue3))
        # Sync that again.  Note that one field ("raft") is NULL, and that
        # should be okay.
        self.assertFalse(registry.syncDimensionData(dimensionName3, dimensionValue3))
        # Now try that sync with the same primary key but a different value.
        # This should fail.
        with self.assertRaises(ConflictingDefinitionError):
            registry.syncDimensionData(
                dimensionName3,
                {"instrument": "DummyCam", "id": 1, "full_name": "one",
                 "name_in_raft": "four", "purpose": "SCIENCE"}
            )

    @unittest.skipIf(np is None, "numpy not available.")
    def testNumpyDataId(self):
        """Test that we can use a numpy int in a dataId."""
        registry = self.makeRegistry()
        dimensionEntries = [
            ("instrument", {"instrument": "DummyCam"}),
            ("physical_filter", {"instrument": "DummyCam", "name": "d-r", "band": "R"}),
            # Using an np.int64 here fails unless Records.fromDict is also
            # patched to look for numbers.Integral
            ("visit", {"instrument": "DummyCam", "id": 42, "name": "fortytwo", "physical_filter": "d-r"}),
        ]
        for args in dimensionEntries:
            registry.insertDimensionData(*args)

        # Try a normal integer and something that looks like an int but
        # is not.
        for visit_id in (42, np.int64(42)):
            with self.subTest(visit_id=visit_id, id_type=type(visit_id).__name__):
                expanded = registry.expandDataId({"instrument": "DummyCam", "visit": visit_id})
                self.assertEqual(expanded["visit"], int(visit_id))
                self.assertIsInstance(expanded["visit"], int)

    def testDataIdRelationships(self):
        """Test that `Registry.expandDataId` raises an exception when the given
        keys are inconsistent.
        """
        registry = self.makeRegistry()
        self.loadData(registry, "base.yaml")
        # Insert a few more dimension records for the next test.
        registry.insertDimensionData(
            "exposure",
            {"instrument": "Cam1", "id": 1, "name": "one", "physical_filter": "Cam1-G"},
        )
        registry.insertDimensionData(
            "exposure",
            {"instrument": "Cam1", "id": 2, "name": "two", "physical_filter": "Cam1-G"},
        )
        registry.insertDimensionData(
            "visit_system",
            {"instrument": "Cam1", "id": 0, "name": "one-to-one"},
        )
        registry.insertDimensionData(
            "visit",
            {"instrument": "Cam1", "id": 1, "name": "one", "physical_filter": "Cam1-G", "visit_system": 0},
        )
        registry.insertDimensionData(
            "visit_definition",
            {"instrument": "Cam1", "visit": 1, "exposure": 1, "visit_system": 0},
        )
        with self.assertRaises(InconsistentDataIdError):
            registry.expandDataId(
                {"instrument": "Cam1", "visit": 1, "exposure": 2},
            )

    def testDataset(self):
        """Basic tests for `Registry.insertDatasets`, `Registry.getDataset`,
        and `Registry.removeDatasets`.
        """
        registry = self.makeRegistry()
        self.loadData(registry, "base.yaml")
        run = "test"
        registry.registerRun(run)
        datasetType = registry.getDatasetType("bias")
        dataId = {"instrument": "Cam1", "detector": 2}
        ref, = registry.insertDatasets(datasetType, dataIds=[dataId], run=run)
        outRef = registry.getDataset(ref.id)
        self.assertIsNotNone(ref.id)
        self.assertEqual(ref, outRef)
        with self.assertRaises(ConflictingDefinitionError):
            registry.insertDatasets(datasetType, dataIds=[dataId], run=run)
        registry.removeDatasets([ref])
        self.assertIsNone(registry.findDataset(datasetType, dataId, collections=[run]))

    def testFindDataset(self):
        """Tests for `Registry.findDataset`.
        """
        registry = self.makeRegistry()
        self.loadData(registry, "base.yaml")
        run = "test"
        datasetType = registry.getDatasetType("bias")
        dataId = {"instrument": "Cam1", "detector": 4}
        registry.registerRun(run)
        inputRef, = registry.insertDatasets(datasetType, dataIds=[dataId], run=run)
        outputRef = registry.findDataset(datasetType, dataId, collections=[run])
        self.assertEqual(outputRef, inputRef)
        # Check that retrieval with invalid dataId raises
        with self.assertRaises(LookupError):
            dataId = {"instrument": "Cam1"}  # no detector
            registry.findDataset(datasetType, dataId, collections=run)
        # Check that different dataIds match to different datasets
        dataId1 = {"instrument": "Cam1", "detector": 1}
        inputRef1, = registry.insertDatasets(datasetType, dataIds=[dataId1], run=run)
        dataId2 = {"instrument": "Cam1", "detector": 2}
        inputRef2, = registry.insertDatasets(datasetType, dataIds=[dataId2], run=run)
        self.assertEqual(registry.findDataset(datasetType, dataId1, collections=run), inputRef1)
        self.assertEqual(registry.findDataset(datasetType, dataId2, collections=run), inputRef2)
        self.assertNotEqual(registry.findDataset(datasetType, dataId1, collections=run), inputRef2)
        self.assertNotEqual(registry.findDataset(datasetType, dataId2, collections=run), inputRef1)
        # Check that requesting a non-existing dataId returns None
        nonExistingDataId = {"instrument": "Cam1", "detector": 3}
        self.assertIsNone(registry.findDataset(datasetType, nonExistingDataId, collections=run))

    def testDatasetTypeComponentQueries(self):
        """Test component options when querying for dataset types.
        """
        registry = self.makeRegistry()
        self.loadData(registry, "base.yaml")
        self.loadData(registry, "datasets.yaml")
        # Test querying for dataset types with different inputs.
        # First query for all dataset types; components should only be included
        # when components=True.
        self.assertEqual(
            {"bias", "flat"},
            NamedValueSet(registry.queryDatasetTypes()).names
        )
        self.assertEqual(
            {"bias", "flat"},
            NamedValueSet(registry.queryDatasetTypes(components=False)).names
        )
        self.assertLess(
            {"bias", "flat", "bias.wcs", "flat.photoCalib"},
            NamedValueSet(registry.queryDatasetTypes(components=True)).names
        )
        # Use a pattern that can match either parent or components.  Again,
        # components are only returned if components=True.
        self.assertEqual(
            {"bias"},
            NamedValueSet(registry.queryDatasetTypes(re.compile("^bias.*"))).names
        )
        self.assertEqual(
            {"bias"},
            NamedValueSet(registry.queryDatasetTypes(re.compile("^bias.*"), components=False)).names
        )
        self.assertLess(
            {"bias", "bias.wcs"},
            NamedValueSet(registry.queryDatasetTypes(re.compile("^bias.*"), components=True)).names
        )
        # This pattern matches only a component.  In this case we also return
        # that component dataset type if components=None.
        self.assertEqual(
            {"bias.wcs"},
            NamedValueSet(registry.queryDatasetTypes(re.compile(r"^bias\.wcs"))).names
        )
        self.assertEqual(
            set(),
            NamedValueSet(registry.queryDatasetTypes(re.compile(r"^bias\.wcs"), components=False)).names
        )
        self.assertEqual(
            {"bias.wcs"},
            NamedValueSet(registry.queryDatasetTypes(re.compile(r"^bias\.wcs"), components=True)).names
        )

    def testComponentLookups(self):
        """Test searching for component datasets via their parents.
        """
        registry = self.makeRegistry()
        self.loadData(registry, "base.yaml")
        self.loadData(registry, "datasets.yaml")
        # Test getting the child dataset type (which does still exist in the
        # Registry), and check for consistency with
        # DatasetRef.makeComponentRef.
        collection = "imported_g"
        parentType = registry.getDatasetType("bias")
        childType = registry.getDatasetType("bias.wcs")
        parentRefResolved = registry.findDataset(parentType, collections=collection,
                                                 instrument="Cam1", detector=1)
        self.assertIsInstance(parentRefResolved, DatasetRef)
        self.assertEqual(childType, parentRefResolved.makeComponentRef("wcs").datasetType)
        # Search for a single dataset with findDataset.
        childRef1 = registry.findDataset("bias.wcs", collections=collection,
                                         dataId=parentRefResolved.dataId)
        self.assertEqual(childRef1, parentRefResolved.makeComponentRef("wcs"))
        # Search for detector data IDs constrained by component dataset
        # existence with queryDataIds.
        dataIds = registry.queryDataIds(
            ["detector"],
            datasets=["bias.wcs"],
            collections=collection,
        ).toSet()
        self.assertEqual(
            dataIds,
            DataCoordinateSet(
                {
                    DataCoordinate.standardize(instrument="Cam1", detector=d, graph=parentType.dimensions)
                    for d in (1, 2, 3)
                },
                parentType.dimensions,
            )
        )
        # Search for multiple datasets of a single type with queryDatasets.
        childRefs2 = set(registry.queryDatasets(
            "bias.wcs",
            collections=collection,
        ))
        self.assertEqual(
            {ref.unresolved() for ref in childRefs2},
            {DatasetRef(childType, dataId) for dataId in dataIds}
        )

    def testCollections(self):
        """Tests for registry methods that manage collections.
        """
        registry = self.makeRegistry()
        self.loadData(registry, "base.yaml")
        self.loadData(registry, "datasets.yaml")
        run1 = "imported_g"
        run2 = "imported_r"
        datasetType = "bias"
        # Find some datasets via their run's collection.
        dataId1 = {"instrument": "Cam1", "detector": 1}
        ref1 = registry.findDataset(datasetType, dataId1, collections=run1)
        self.assertIsNotNone(ref1)
        dataId2 = {"instrument": "Cam1", "detector": 2}
        ref2 = registry.findDataset(datasetType, dataId2, collections=run1)
        self.assertIsNotNone(ref2)
        # Associate those into a new collection,then look for them there.
        tag1 = "tag1"
        registry.registerCollection(tag1, type=CollectionType.TAGGED)
        registry.associate(tag1, [ref1, ref2])
        self.assertEqual(registry.findDataset(datasetType, dataId1, collections=tag1), ref1)
        self.assertEqual(registry.findDataset(datasetType, dataId2, collections=tag1), ref2)
        # Disassociate one and verify that we can't it there anymore...
        registry.disassociate(tag1, [ref1])
        self.assertIsNone(registry.findDataset(datasetType, dataId1, collections=tag1))
        # ...but we can still find ref2 in tag1, and ref1 in the run.
        self.assertEqual(registry.findDataset(datasetType, dataId1, collections=run1), ref1)
        self.assertEqual(registry.findDataset(datasetType, dataId2, collections=tag1), ref2)
        collections = set(registry.queryCollections())
        self.assertEqual(collections, {run1, run2, tag1})
        # Associate both refs into tag1 again; ref2 is already there, but that
        # should be a harmless no-op.
        registry.associate(tag1, [ref1, ref2])
        self.assertEqual(registry.findDataset(datasetType, dataId1, collections=tag1), ref1)
        self.assertEqual(registry.findDataset(datasetType, dataId2, collections=tag1), ref2)
        # Get a different dataset (from a different run) that has the same
        # dataset type and data ID as ref2.
        ref2b = registry.findDataset(datasetType, dataId2, collections=run2)
        self.assertNotEqual(ref2, ref2b)
        # Attempting to associate that into tag1 should be an error.
        with self.assertRaises(ConflictingDefinitionError):
            registry.associate(tag1, [ref2b])
        # That error shouldn't have messed up what we had before.
        self.assertEqual(registry.findDataset(datasetType, dataId1, collections=tag1), ref1)
        self.assertEqual(registry.findDataset(datasetType, dataId2, collections=tag1), ref2)
        # Attempt to associate the conflicting dataset again, this time with
        # a dataset that isn't in the collection and won't cause a conflict.
        # Should also fail without modifying anything.
        dataId3 = {"instrument": "Cam1", "detector": 3}
        ref3 = registry.findDataset(datasetType, dataId3, collections=run1)
        with self.assertRaises(ConflictingDefinitionError):
            registry.associate(tag1, [ref3, ref2b])
        self.assertEqual(registry.findDataset(datasetType, dataId1, collections=tag1), ref1)
        self.assertEqual(registry.findDataset(datasetType, dataId2, collections=tag1), ref2)
        self.assertIsNone(registry.findDataset(datasetType, dataId3, collections=tag1))
        # Register a chained collection that searches:
        # 1. 'tag1'
        # 2. 'run1', but only for the flat dataset
        # 3. 'run2'
        chain1 = "chain1"
        registry.registerCollection(chain1, type=CollectionType.CHAINED)
        self.assertIs(registry.getCollectionType(chain1), CollectionType.CHAINED)
        # Chained collection exists, but has no collections in it.
        self.assertFalse(registry.getCollectionChain(chain1))
        # If we query for all collections, we should get the chained collection
        # only if we don't ask to flatten it (i.e. yield only its children).
        self.assertEqual(set(registry.queryCollections(flattenChains=False)), {tag1, run1, run2, chain1})
        self.assertEqual(set(registry.queryCollections(flattenChains=True)), {tag1, run1, run2})
        # Attempt to set its child collections to something circular; that
        # should fail.
        with self.assertRaises(ValueError):
            registry.setCollectionChain(chain1, [tag1, chain1])
        # Add the child collections.
        registry.setCollectionChain(chain1, [tag1, (run1, "flat"), run2])
        self.assertEqual(
            list(registry.getCollectionChain(chain1)),
            [(tag1, DatasetTypeRestriction.any),
             (run1, DatasetTypeRestriction.fromExpression("flat")),
             (run2, DatasetTypeRestriction.any)]
        )
        # Searching for dataId1 or dataId2 in the chain should return ref1 and
        # ref2, because both are in tag1.
        self.assertEqual(registry.findDataset(datasetType, dataId1, collections=chain1), ref1)
        self.assertEqual(registry.findDataset(datasetType, dataId2, collections=chain1), ref2)
        # Now disassociate ref2 from tag1.  The search (for bias) with
        # dataId2 in chain1 should then:
        # 1. not find it in tag1
        # 2. not look in tag2, because it's restricted to flat here
        # 3. find a different dataset in run2
        registry.disassociate(tag1, [ref2])
        ref2b = registry.findDataset(datasetType, dataId2, collections=chain1)
        self.assertNotEqual(ref2b, ref2)
        self.assertEqual(ref2b, registry.findDataset(datasetType, dataId2, collections=run2))
        # Look in the chain for a flat that is in run1; should get the
        # same ref as if we'd searched run1 directly.
        dataId3 = {"instrument": "Cam1", "detector": 2, "physical_filter": "Cam1-G"}
        self.assertEqual(registry.findDataset("flat", dataId3, collections=chain1),
                         registry.findDataset("flat", dataId3, collections=run1),)
        # Define a new chain so we can test recursive chains.
        chain2 = "chain2"
        registry.registerCollection(chain2, type=CollectionType.CHAINED)
        registry.setCollectionChain(chain2, [(run2, "bias"), chain1])
        # Query for collections matching a regex.
        self.assertCountEqual(
            list(registry.queryCollections(re.compile("imported_."), flattenChains=False)),
            ["imported_r", "imported_g"]
        )
        # Query for collections matching a regex or an explicit str.
        self.assertCountEqual(
            list(registry.queryCollections([re.compile("imported_."), "chain1"], flattenChains=False)),
            ["imported_r", "imported_g", "chain1"]
        )
        # Search for bias with dataId1 should find it via tag1 in chain2,
        # recursing, because is not in run1.
        self.assertIsNone(registry.findDataset(datasetType, dataId1, collections=run2))
        self.assertEqual(registry.findDataset(datasetType, dataId1, collections=chain2), ref1)
        # Search for bias with dataId2 should find it in run2 (ref2b).
        self.assertEqual(registry.findDataset(datasetType, dataId2, collections=chain2), ref2b)
        # Search for a flat that is in run2.  That should not be found
        # at the front of chain2, because of the restriction to bias
        # on run2 there, but it should be found in at the end of chain1.
        dataId4 = {"instrument": "Cam1", "detector": 3, "physical_filter": "Cam1-R2"}
        ref4 = registry.findDataset("flat", dataId4, collections=run2)
        self.assertIsNotNone(ref4)
        self.assertEqual(ref4, registry.findDataset("flat", dataId4, collections=chain2))
        # Deleting a collection that's part of a CHAINED collection is not
        # allowed, and is exception-safe.
        with self.assertRaises(Exception):
            registry.removeCollection(run2)
        self.assertEqual(registry.getCollectionType(run2), CollectionType.RUN)
        with self.assertRaises(Exception):
            registry.removeCollection(chain1)
        self.assertEqual(registry.getCollectionType(chain1), CollectionType.CHAINED)
        # Actually remove chain2, test that it's gone by asking for its type.
        registry.removeCollection(chain2)
        with self.assertRaises(MissingCollectionError):
            registry.getCollectionType(chain2)
        # Actually remove run2 and chain1, which should work now.
        registry.removeCollection(chain1)
        registry.removeCollection(run2)
        with self.assertRaises(MissingCollectionError):
            registry.getCollectionType(run2)
        with self.assertRaises(MissingCollectionError):
            registry.getCollectionType(chain1)
        # Remove tag1 as well, just to test that we can remove TAGGED
        # collections.
        registry.removeCollection(tag1)
        with self.assertRaises(MissingCollectionError):
            registry.getCollectionType(tag1)

    def testBasicTransaction(self):
        """Test that all operations within a single transaction block are
        rolled back if an exception propagates out of the block.
        """
        registry = self.makeRegistry()
        storageClass = StorageClass("testDatasetType")
        registry.storageClasses.registerStorageClass(storageClass)
        with registry.transaction():
            registry.insertDimensionData("instrument", {"name": "Cam1", "class_name": "A"})
        with self.assertRaises(ValueError):
            with registry.transaction():
                registry.insertDimensionData("instrument", {"name": "Cam2"})
                raise ValueError("Oops, something went wrong")
        # Cam1 should exist
        self.assertEqual(registry.expandDataId(instrument="Cam1").records["instrument"].class_name, "A")
        # But Cam2 and Cam3 should both not exist
        with self.assertRaises(LookupError):
            registry.expandDataId(instrument="Cam2")
        with self.assertRaises(LookupError):
            registry.expandDataId(instrument="Cam3")

    def testNestedTransaction(self):
        """Test that operations within a transaction block are not rolled back
        if an exception propagates out of an inner transaction block and is
        then caught.
        """
        registry = self.makeRegistry()
        dimension = registry.dimensions["instrument"]
        dataId1 = {"instrument": "DummyCam"}
        dataId2 = {"instrument": "DummyCam2"}
        checkpointReached = False
        with registry.transaction():
            # This should be added and (ultimately) committed.
            registry.insertDimensionData(dimension, dataId1)
            with self.assertRaises(sqlalchemy.exc.IntegrityError):
                with registry.transaction(savepoint=True):
                    # This does not conflict, and should succeed (but not
                    # be committed).
                    registry.insertDimensionData(dimension, dataId2)
                    checkpointReached = True
                    # This should conflict and raise, triggerring a rollback
                    # of the previous insertion within the same transaction
                    # context, but not the original insertion in the outer
                    # block.
                    registry.insertDimensionData(dimension, dataId1)
        self.assertTrue(checkpointReached)
        self.assertIsNotNone(registry.expandDataId(dataId1, graph=dimension.graph))
        with self.assertRaises(LookupError):
            registry.expandDataId(dataId2, graph=dimension.graph)

    def testInstrumentDimensions(self):
        """Test queries involving only instrument dimensions, with no joins to
        skymap."""
        registry = self.makeRegistry()

        # need a bunch of dimensions and datasets for test
        registry.insertDimensionData(
            "instrument",
            dict(name="DummyCam", visit_max=25, exposure_max=300, detector_max=6)
        )
        registry.insertDimensionData(
            "physical_filter",
            dict(instrument="DummyCam", name="dummy_r", band="r"),
            dict(instrument="DummyCam", name="dummy_i", band="i"),
        )
        registry.insertDimensionData(
            "detector",
            *[dict(instrument="DummyCam", id=i, full_name=str(i)) for i in range(1, 6)]
        )
        registry.insertDimensionData(
            "visit_system",
            dict(instrument="DummyCam", id=1, name="default"),
        )
        registry.insertDimensionData(
            "visit",
            dict(instrument="DummyCam", id=10, name="ten", physical_filter="dummy_i", visit_system=1),
            dict(instrument="DummyCam", id=11, name="eleven", physical_filter="dummy_r", visit_system=1),
            dict(instrument="DummyCam", id=20, name="twelve", physical_filter="dummy_r", visit_system=1),
        )
        registry.insertDimensionData(
            "exposure",
            dict(instrument="DummyCam", id=100, name="100", physical_filter="dummy_i"),
            dict(instrument="DummyCam", id=101, name="101", physical_filter="dummy_i"),
            dict(instrument="DummyCam", id=110, name="110", physical_filter="dummy_r"),
            dict(instrument="DummyCam", id=111, name="111", physical_filter="dummy_r"),
            dict(instrument="DummyCam", id=200, name="200", physical_filter="dummy_r"),
            dict(instrument="DummyCam", id=201, name="201", physical_filter="dummy_r"),
        )
        registry.insertDimensionData(
            "visit_definition",
            dict(instrument="DummyCam", exposure=100, visit_system=1, visit=10),
            dict(instrument="DummyCam", exposure=101, visit_system=1, visit=10),
            dict(instrument="DummyCam", exposure=110, visit_system=1, visit=11),
            dict(instrument="DummyCam", exposure=111, visit_system=1, visit=11),
            dict(instrument="DummyCam", exposure=200, visit_system=1, visit=20),
            dict(instrument="DummyCam", exposure=201, visit_system=1, visit=20),
        )
        # dataset types
        run1 = "test1_r"
        run2 = "test2_r"
        tagged2 = "test2_t"
        registry.registerRun(run1)
        registry.registerRun(run2)
        registry.registerCollection(tagged2)
        storageClass = StorageClass("testDataset")
        registry.storageClasses.registerStorageClass(storageClass)
        rawType = DatasetType(name="RAW",
                              dimensions=registry.dimensions.extract(("instrument", "exposure", "detector")),
                              storageClass=storageClass)
        registry.registerDatasetType(rawType)
        calexpType = DatasetType(name="CALEXP",
                                 dimensions=registry.dimensions.extract(("instrument", "visit", "detector")),
                                 storageClass=storageClass)
        registry.registerDatasetType(calexpType)

        # add pre-existing datasets
        for exposure in (100, 101, 110, 111):
            for detector in (1, 2, 3):
                # note that only 3 of 5 detectors have datasets
                dataId = dict(instrument="DummyCam", exposure=exposure, detector=detector)
                ref, = registry.insertDatasets(rawType, dataIds=[dataId], run=run1)
                # exposures 100 and 101 appear in both run1 and tagged2.
                # 100 has different datasets in the different collections
                # 101 has the same dataset in both collections.
                if exposure == 100:
                    ref, = registry.insertDatasets(rawType, dataIds=[dataId], run=run2)
                if exposure in (100, 101):
                    registry.associate(tagged2, [ref])
        # Add pre-existing datasets to tagged2.
        for exposure in (200, 201):
            for detector in (3, 4, 5):
                # note that only 3 of 5 detectors have datasets
                dataId = dict(instrument="DummyCam", exposure=exposure, detector=detector)
                ref, = registry.insertDatasets(rawType, dataIds=[dataId], run=run2)
                registry.associate(tagged2, [ref])

        dimensions = DimensionGraph(
            registry.dimensions,
            dimensions=(rawType.dimensions.required | calexpType.dimensions.required)
        )
        # Test that single dim string works as well as list of str
        rows = registry.queryDataIds("visit", datasets=rawType, collections=run1).expanded().toSet()
        rowsI = registry.queryDataIds(["visit"], datasets=rawType, collections=run1).expanded().toSet()
        self.assertEqual(rows, rowsI)
        # with empty expression
        rows = registry.queryDataIds(dimensions, datasets=rawType, collections=run1).expanded().toSet()
        self.assertEqual(len(rows), 4*3)   # 4 exposures times 3 detectors
        for dataId in rows:
            self.assertCountEqual(dataId.keys(), ("instrument", "detector", "exposure", "visit"))
            packer1 = registry.dimensions.makePacker("visit_detector", dataId)
            packer2 = registry.dimensions.makePacker("exposure_detector", dataId)
            self.assertEqual(packer1.unpack(packer1.pack(dataId)),
                             DataCoordinate.standardize(dataId, graph=packer1.dimensions))
            self.assertEqual(packer2.unpack(packer2.pack(dataId)),
                             DataCoordinate.standardize(dataId, graph=packer2.dimensions))
            self.assertNotEqual(packer1.pack(dataId), packer2.pack(dataId))
        self.assertCountEqual(set(dataId["exposure"] for dataId in rows),
                              (100, 101, 110, 111))
        self.assertCountEqual(set(dataId["visit"] for dataId in rows), (10, 11))
        self.assertCountEqual(set(dataId["detector"] for dataId in rows), (1, 2, 3))

        # second collection
        rows = registry.queryDataIds(dimensions, datasets=rawType, collections=tagged2).toSet()
        self.assertEqual(len(rows), 4*3)   # 4 exposures times 3 detectors
        for dataId in rows:
            self.assertCountEqual(dataId.keys(), ("instrument", "detector", "exposure", "visit"))
        self.assertCountEqual(set(dataId["exposure"] for dataId in rows),
                              (100, 101, 200, 201))
        self.assertCountEqual(set(dataId["visit"] for dataId in rows), (10, 20))
        self.assertCountEqual(set(dataId["detector"] for dataId in rows), (1, 2, 3, 4, 5))

        # with two input datasets
        rows = registry.queryDataIds(dimensions, datasets=rawType, collections=[run1, tagged2]).toSet()
        self.assertEqual(len(set(rows)), 6*3)   # 6 exposures times 3 detectors; set needed to de-dupe
        for dataId in rows:
            self.assertCountEqual(dataId.keys(), ("instrument", "detector", "exposure", "visit"))
        self.assertCountEqual(set(dataId["exposure"] for dataId in rows),
                              (100, 101, 110, 111, 200, 201))
        self.assertCountEqual(set(dataId["visit"] for dataId in rows), (10, 11, 20))
        self.assertCountEqual(set(dataId["detector"] for dataId in rows), (1, 2, 3, 4, 5))

        # limit to single visit
        rows = registry.queryDataIds(dimensions, datasets=rawType, collections=run1,
                                     where="visit = 10").toSet()
        self.assertEqual(len(rows), 2*3)   # 2 exposures times 3 detectors
        self.assertCountEqual(set(dataId["exposure"] for dataId in rows), (100, 101))
        self.assertCountEqual(set(dataId["visit"] for dataId in rows), (10,))
        self.assertCountEqual(set(dataId["detector"] for dataId in rows), (1, 2, 3))

        # more limiting expression, using link names instead of Table.column
        rows = registry.queryDataIds(dimensions, datasets=rawType, collections=run1,
                                     where="visit = 10 and detector > 1").toSet()
        self.assertEqual(len(rows), 2*2)   # 2 exposures times 2 detectors
        self.assertCountEqual(set(dataId["exposure"] for dataId in rows), (100, 101))
        self.assertCountEqual(set(dataId["visit"] for dataId in rows), (10,))
        self.assertCountEqual(set(dataId["detector"] for dataId in rows), (2, 3))

        # expression excludes everything
        rows = registry.queryDataIds(dimensions, datasets=rawType, collections=run1,
                                     where="visit > 1000").toSet()
        self.assertEqual(len(rows), 0)

        # Selecting by physical_filter, this is not in the dimensions, but it
        # is a part of the full expression so it should work too.
        rows = registry.queryDataIds(dimensions, datasets=rawType, collections=run1,
                                     where="physical_filter = 'dummy_r'").toSet()
        self.assertEqual(len(rows), 2*3)   # 2 exposures times 3 detectors
        self.assertCountEqual(set(dataId["exposure"] for dataId in rows), (110, 111))
        self.assertCountEqual(set(dataId["visit"] for dataId in rows), (11,))
        self.assertCountEqual(set(dataId["detector"] for dataId in rows), (1, 2, 3))

    def testSkyMapDimensions(self):
        """Tests involving only skymap dimensions, no joins to instrument."""
        registry = self.makeRegistry()

        # need a bunch of dimensions and datasets for test, we want
        # "band" in the test so also have to add physical_filter
        # dimensions
        registry.insertDimensionData(
            "instrument",
            dict(instrument="DummyCam")
        )
        registry.insertDimensionData(
            "physical_filter",
            dict(instrument="DummyCam", name="dummy_r", band="r"),
            dict(instrument="DummyCam", name="dummy_i", band="i"),
        )
        registry.insertDimensionData(
            "skymap",
            dict(name="DummyMap", hash="sha!".encode("utf8"))
        )
        for tract in range(10):
            registry.insertDimensionData("tract", dict(skymap="DummyMap", id=tract))
            registry.insertDimensionData(
                "patch",
                *[dict(skymap="DummyMap", tract=tract, id=patch, cell_x=0, cell_y=0)
                  for patch in range(10)]
            )

        # dataset types
        run = "test"
        registry.registerRun(run)
        storageClass = StorageClass("testDataset")
        registry.storageClasses.registerStorageClass(storageClass)
        calexpType = DatasetType(name="deepCoadd_calexp",
                                 dimensions=registry.dimensions.extract(("skymap", "tract", "patch",
                                                                         "band")),
                                 storageClass=storageClass)
        registry.registerDatasetType(calexpType)
        mergeType = DatasetType(name="deepCoadd_mergeDet",
                                dimensions=registry.dimensions.extract(("skymap", "tract", "patch")),
                                storageClass=storageClass)
        registry.registerDatasetType(mergeType)
        measType = DatasetType(name="deepCoadd_meas",
                               dimensions=registry.dimensions.extract(("skymap", "tract", "patch",
                                                                       "band")),
                               storageClass=storageClass)
        registry.registerDatasetType(measType)

        dimensions = DimensionGraph(
            registry.dimensions,
            dimensions=(calexpType.dimensions.required | mergeType.dimensions.required
                        | measType.dimensions.required)
        )

        # add pre-existing datasets
        for tract in (1, 3, 5):
            for patch in (2, 4, 6, 7):
                dataId = dict(skymap="DummyMap", tract=tract, patch=patch)
                registry.insertDatasets(mergeType, dataIds=[dataId], run=run)
                for aFilter in ("i", "r"):
                    dataId = dict(skymap="DummyMap", tract=tract, patch=patch, band=aFilter)
                    registry.insertDatasets(calexpType, dataIds=[dataId], run=run)

        # with empty expression
        rows = registry.queryDataIds(dimensions,
                                     datasets=[calexpType, mergeType], collections=run).toSet()
        self.assertEqual(len(rows), 3*4*2)   # 4 tracts x 4 patches x 2 filters
        for dataId in rows:
            self.assertCountEqual(dataId.keys(), ("skymap", "tract", "patch", "band"))
        self.assertCountEqual(set(dataId["tract"] for dataId in rows), (1, 3, 5))
        self.assertCountEqual(set(dataId["patch"] for dataId in rows), (2, 4, 6, 7))
        self.assertCountEqual(set(dataId["band"] for dataId in rows), ("i", "r"))

        # limit to 2 tracts and 2 patches
        rows = registry.queryDataIds(dimensions,
                                     datasets=[calexpType, mergeType], collections=run,
                                     where="tract IN (1, 5) AND patch IN (2, 7)").toSet()
        self.assertEqual(len(rows), 2*2*2)   # 2 tracts x 2 patches x 2 filters
        self.assertCountEqual(set(dataId["tract"] for dataId in rows), (1, 5))
        self.assertCountEqual(set(dataId["patch"] for dataId in rows), (2, 7))
        self.assertCountEqual(set(dataId["band"] for dataId in rows), ("i", "r"))

        # limit to single filter
        rows = registry.queryDataIds(dimensions,
                                     datasets=[calexpType, mergeType], collections=run,
                                     where="band = 'i'").toSet()
        self.assertEqual(len(rows), 3*4*1)   # 4 tracts x 4 patches x 2 filters
        self.assertCountEqual(set(dataId["tract"] for dataId in rows), (1, 3, 5))
        self.assertCountEqual(set(dataId["patch"] for dataId in rows), (2, 4, 6, 7))
        self.assertCountEqual(set(dataId["band"] for dataId in rows), ("i",))

        # expression excludes everything, specifying non-existing skymap is
        # not a fatal error, it's operator error
        rows = registry.queryDataIds(dimensions,
                                     datasets=[calexpType, mergeType], collections=run,
                                     where="skymap = 'Mars'").toSet()
        self.assertEqual(len(rows), 0)

    def testSpatialMatch(self):
        """Test involving spatial match using join tables.

        Note that realistic test needs a reasonably-defined skypix and regions
        in registry tables which is hard to implement in this simple test.
        So we do not actually fill registry with any data and all queries will
        return empty result, but this is still useful for coverage of the code
        that generates query.
        """
        registry = self.makeRegistry()

        # dataset types
        collection = "test"
        registry.registerRun(name=collection)
        storageClass = StorageClass("testDataset")
        registry.storageClasses.registerStorageClass(storageClass)

        calexpType = DatasetType(name="CALEXP",
                                 dimensions=registry.dimensions.extract(("instrument", "visit", "detector")),
                                 storageClass=storageClass)
        registry.registerDatasetType(calexpType)

        coaddType = DatasetType(name="deepCoadd_calexp",
                                dimensions=registry.dimensions.extract(("skymap", "tract", "patch",
                                                                        "band")),
                                storageClass=storageClass)
        registry.registerDatasetType(coaddType)

        dimensions = DimensionGraph(
            registry.dimensions,
            dimensions=(calexpType.dimensions.required | coaddType.dimensions.required)
        )

        # without data this should run OK but return empty set
        rows = registry.queryDataIds(dimensions, datasets=calexpType, collections=collection).toSet()
        self.assertEqual(len(rows), 0)

    def testAbstractQuery(self):
        """Test that we can run a query that just lists the known
        bands.  This is tricky because band is
        backed by a query against physical_filter.
        """
        registry = self.makeRegistry()
        registry.insertDimensionData("instrument", dict(name="DummyCam"))
        registry.insertDimensionData(
            "physical_filter",
            dict(instrument="DummyCam", name="dummy_i", band="i"),
            dict(instrument="DummyCam", name="dummy_i2", band="i"),
            dict(instrument="DummyCam", name="dummy_r", band="r"),
        )
        rows = registry.queryDataIds(["band"]).toSet()
        self.assertCountEqual(
            rows,
            [DataCoordinate.standardize(band="i", universe=registry.dimensions),
             DataCoordinate.standardize(band="r", universe=registry.dimensions)]
        )

    def testAttributeManager(self):
        """Test basic functionality of attribute manager.
        """
        # number of attributes with schema versions in a fresh database,
        # 6 managers with 3 records per manager, plus config for dimensions
        VERSION_COUNT = 6 * 3 + 1

        registry = self.makeRegistry()
        attributes = registry._attributes

        # check what get() returns for non-existing key
        self.assertIsNone(attributes.get("attr"))
        self.assertEqual(attributes.get("attr", ""), "")
        self.assertEqual(attributes.get("attr", "Value"), "Value")
        self.assertEqual(len(list(attributes.items())), VERSION_COUNT)

        # cannot store empty key or value
        with self.assertRaises(ValueError):
            attributes.set("", "value")
        with self.assertRaises(ValueError):
            attributes.set("attr", "")

        # set value of non-existing key
        attributes.set("attr", "value")
        self.assertEqual(len(list(attributes.items())), VERSION_COUNT + 1)
        self.assertEqual(attributes.get("attr"), "value")

        # update value of existing key
        with self.assertRaises(ButlerAttributeExistsError):
            attributes.set("attr", "value2")

        attributes.set("attr", "value2", force=True)
        self.assertEqual(len(list(attributes.items())), VERSION_COUNT + 1)
        self.assertEqual(attributes.get("attr"), "value2")

        # delete existing key
        self.assertTrue(attributes.delete("attr"))
        self.assertEqual(len(list(attributes.items())), VERSION_COUNT)

        # delete non-existing key
        self.assertFalse(attributes.delete("non-attr"))

        # store bunch of keys and get the list back
        data = [
            ("version.core", "1.2.3"),
            ("version.dimensions", "3.2.1"),
            ("config.managers.opaque", "ByNameOpaqueTableStorageManager"),
        ]
        for key, value in data:
            attributes.set(key, value)
        items = dict(attributes.items())
        for key, value in data:
            self.assertEqual(items[key], value)

    def testQueryDatasetsDeduplication(self):
        """Test that the findFirst option to queryDatasets selects datasets
        from collections in the order given".
        """
        registry = self.makeRegistry()
        self.loadData(registry, "base.yaml")
        self.loadData(registry, "datasets.yaml")
        self.assertCountEqual(
            list(registry.queryDatasets("bias", collections=["imported_g", "imported_r"])),
            [
                registry.findDataset("bias", instrument="Cam1", detector=1, collections="imported_g"),
                registry.findDataset("bias", instrument="Cam1", detector=2, collections="imported_g"),
                registry.findDataset("bias", instrument="Cam1", detector=3, collections="imported_g"),
                registry.findDataset("bias", instrument="Cam1", detector=2, collections="imported_r"),
                registry.findDataset("bias", instrument="Cam1", detector=3, collections="imported_r"),
                registry.findDataset("bias", instrument="Cam1", detector=4, collections="imported_r"),
            ]
        )
        self.assertCountEqual(
            list(registry.queryDatasets("bias", collections=["imported_g", "imported_r"],
                                        findFirst=True)),
            [
                registry.findDataset("bias", instrument="Cam1", detector=1, collections="imported_g"),
                registry.findDataset("bias", instrument="Cam1", detector=2, collections="imported_g"),
                registry.findDataset("bias", instrument="Cam1", detector=3, collections="imported_g"),
                registry.findDataset("bias", instrument="Cam1", detector=4, collections="imported_r"),
            ]
        )
        self.assertCountEqual(
            list(registry.queryDatasets("bias", collections=["imported_r", "imported_g"],
                                        findFirst=True)),
            [
                registry.findDataset("bias", instrument="Cam1", detector=1, collections="imported_g"),
                registry.findDataset("bias", instrument="Cam1", detector=2, collections="imported_r"),
                registry.findDataset("bias", instrument="Cam1", detector=3, collections="imported_r"),
                registry.findDataset("bias", instrument="Cam1", detector=4, collections="imported_r"),
            ]
        )

    def testQueryResults(self):
        """Test querying for data IDs and then manipulating the QueryResults
        object returned to perform other queries.
        """
        registry = self.makeRegistry()
        self.loadData(registry, "base.yaml")
        self.loadData(registry, "datasets.yaml")
        bias = registry.getDatasetType("bias")
        flat = registry.getDatasetType("flat")
        # Obtain expected results from methods other than those we're testing
        # here.  That includes:
        # - the dimensions of the data IDs we want to query:
        expectedGraph = DimensionGraph(registry.dimensions, names=["detector", "physical_filter"])
        # - the dimensions of some other data IDs we'll extract from that:
        expectedSubsetGraph = DimensionGraph(registry.dimensions, names=["detector"])
        # - the data IDs we expect to obtain from the first queries:
        expectedDataIds = DataCoordinateSet(
            {
                DataCoordinate.standardize(instrument="Cam1", detector=d, physical_filter=p,
                                           universe=registry.dimensions)
                for d, p in itertools.product({1, 2, 3}, {"Cam1-G", "Cam1-R1", "Cam1-R2"})
            },
            graph=expectedGraph,
            hasFull=False,
            hasRecords=False,
        )
        # - the flat datasets we expect to find from those data IDs, in just
        #   one collection (so deduplication is irrelevant):
        expectedFlats = [
            registry.findDataset(flat, instrument="Cam1", detector=1, physical_filter="Cam1-R1",
                                 collections="imported_r"),
            registry.findDataset(flat, instrument="Cam1", detector=2, physical_filter="Cam1-R1",
                                 collections="imported_r"),
            registry.findDataset(flat, instrument="Cam1", detector=3, physical_filter="Cam1-R2",
                                 collections="imported_r"),
        ]
        # - the data IDs we expect to extract from that:
        expectedSubsetDataIds = expectedDataIds.subset(expectedSubsetGraph)
        # - the bias datasets we expect to find from those data IDs, after we
        #   subset-out the physical_filter dimension, both with duplicates:
        expectedAllBiases = [
            registry.findDataset(bias, instrument="Cam1", detector=1, collections="imported_g"),
            registry.findDataset(bias, instrument="Cam1", detector=2, collections="imported_g"),
            registry.findDataset(bias, instrument="Cam1", detector=3, collections="imported_g"),
            registry.findDataset(bias, instrument="Cam1", detector=2, collections="imported_r"),
            registry.findDataset(bias, instrument="Cam1", detector=3, collections="imported_r"),
        ]
        # - ...and without duplicates:
        expectedDeduplicatedBiases = [
            registry.findDataset(bias, instrument="Cam1", detector=1, collections="imported_g"),
            registry.findDataset(bias, instrument="Cam1", detector=2, collections="imported_r"),
            registry.findDataset(bias, instrument="Cam1", detector=3, collections="imported_r"),
        ]
        # Test against those expected results, using a "lazy" query for the
        # data IDs (which re-executes that query each time we use it to do
        # something new).
        dataIds = registry.queryDataIds(
            ["detector", "physical_filter"],
            where="detector.purpose = 'SCIENCE'",  # this rejects detector=4
        )
        self.assertEqual(dataIds.graph, expectedGraph)
        self.assertEqual(dataIds.toSet(), expectedDataIds)
        self.assertCountEqual(
            list(
                dataIds.findDatasets(
                    flat,
                    collections=["imported_r"],
                )
            ),
            expectedFlats,
        )
        subsetDataIds = dataIds.subset(expectedSubsetGraph, unique=True)
        self.assertEqual(subsetDataIds.graph, expectedSubsetGraph)
        self.assertEqual(subsetDataIds.toSet(), expectedSubsetDataIds)
        self.assertCountEqual(
            list(
                subsetDataIds.findDatasets(
                    bias,
                    collections=["imported_r", "imported_g"],
                    findFirst=False
                )
            ),
            expectedAllBiases
        )
        self.assertCountEqual(
            list(
                subsetDataIds.findDatasets(
                    bias,
                    collections=["imported_r", "imported_g"],
                    findFirst=True
                )
            ), expectedDeduplicatedBiases
        )
        # Materialize the bias dataset queries (only) by putting the results
        # into temporary tables, then repeat those tests.
        with subsetDataIds.findDatasets(bias, collections=["imported_r", "imported_g"],
                                        findFirst=False).materialize() as biases:
            self.assertCountEqual(list(biases), expectedAllBiases)
        with subsetDataIds.findDatasets(bias, collections=["imported_r", "imported_g"],
                                        findFirst=True).materialize() as biases:
            self.assertCountEqual(list(biases), expectedDeduplicatedBiases)
        # Materialize the data ID subset query, but not the dataset queries.
        with subsetDataIds.materialize() as subsetDataIds:
            self.assertEqual(subsetDataIds.graph, expectedSubsetGraph)
            self.assertEqual(subsetDataIds.toSet(), expectedSubsetDataIds)
            self.assertCountEqual(
                list(
                    subsetDataIds.findDatasets(
                        bias,
                        collections=["imported_r", "imported_g"],
                        findFirst=False
                    )
                ),
                expectedAllBiases
            )
            self.assertCountEqual(
                list(
                    subsetDataIds.findDatasets(
                        bias,
                        collections=["imported_r", "imported_g"],
                        findFirst=True
                    )
                ), expectedDeduplicatedBiases
            )
            # Materialize the dataset queries, too.
            with subsetDataIds.findDatasets(bias, collections=["imported_r", "imported_g"],
                                            findFirst=False).materialize() as biases:
                self.assertCountEqual(list(biases), expectedAllBiases)
            with subsetDataIds.findDatasets(bias, collections=["imported_r", "imported_g"],
                                            findFirst=True).materialize() as biases:
                self.assertCountEqual(list(biases), expectedDeduplicatedBiases)
        # Materialize the original query, but none of the follow-up queries.
        with dataIds.materialize() as dataIds:
            self.assertEqual(dataIds.graph, expectedGraph)
            self.assertEqual(dataIds.toSet(), expectedDataIds)
            self.assertCountEqual(
                list(
                    dataIds.findDatasets(
                        flat,
                        collections=["imported_r"],
                    )
                ),
                expectedFlats,
            )
            subsetDataIds = dataIds.subset(expectedSubsetGraph, unique=True)
            self.assertEqual(subsetDataIds.graph, expectedSubsetGraph)
            self.assertEqual(subsetDataIds.toSet(), expectedSubsetDataIds)
            self.assertCountEqual(
                list(
                    subsetDataIds.findDatasets(
                        bias,
                        collections=["imported_r", "imported_g"],
                        findFirst=False
                    )
                ),
                expectedAllBiases
            )
            self.assertCountEqual(
                list(
                    subsetDataIds.findDatasets(
                        bias,
                        collections=["imported_r", "imported_g"],
                        findFirst=True
                    )
                ), expectedDeduplicatedBiases
            )
            # Materialize just the bias dataset queries.
            with subsetDataIds.findDatasets(bias, collections=["imported_r", "imported_g"],
                                            findFirst=False).materialize() as biases:
                self.assertCountEqual(list(biases), expectedAllBiases)
            with subsetDataIds.findDatasets(bias, collections=["imported_r", "imported_g"],
                                            findFirst=True).materialize() as biases:
                self.assertCountEqual(list(biases), expectedDeduplicatedBiases)
            # Materialize the subset data ID query, but not the dataset
            # queries.
            with subsetDataIds.materialize() as subsetDataIds:
                self.assertEqual(subsetDataIds.graph, expectedSubsetGraph)
                self.assertEqual(subsetDataIds.toSet(), expectedSubsetDataIds)
                self.assertCountEqual(
                    list(
                        subsetDataIds.findDatasets(
                            bias,
                            collections=["imported_r", "imported_g"],
                            findFirst=False
                        )
                    ),
                    expectedAllBiases
                )
                self.assertCountEqual(
                    list(
                        subsetDataIds.findDatasets(
                            bias,
                            collections=["imported_r", "imported_g"],
                            findFirst=True
                        )
                    ), expectedDeduplicatedBiases
                )
                # Materialize the bias dataset queries, too, so now we're
                # materializing every single step.
                with subsetDataIds.findDatasets(bias, collections=["imported_r", "imported_g"],
                                                findFirst=False).materialize() as biases:
                    self.assertCountEqual(list(biases), expectedAllBiases)
                with subsetDataIds.findDatasets(bias, collections=["imported_r", "imported_g"],
                                                findFirst=True).materialize() as biases:
                    self.assertCountEqual(list(biases), expectedDeduplicatedBiases)

    def testEmptyDimensionsQueries(self):
        """Test Query and QueryResults objects in the case where there are no
        dimensions.
        """
        # Set up test data: one dataset type, two runs, one dataset in each.
        registry = self.makeRegistry()
        self.loadData(registry, "base.yaml")
        schema = DatasetType("schema", dimensions=registry.dimensions.empty, storageClass="Catalog")
        registry.registerDatasetType(schema)
        dataId = DataCoordinate.makeEmpty(registry.dimensions)
        run1 = "run1"
        run2 = "run2"
        registry.registerRun(run1)
        registry.registerRun(run2)
        (dataset1,) = registry.insertDatasets(schema, dataIds=[dataId], run=run1)
        (dataset2,) = registry.insertDatasets(schema, dataIds=[dataId], run=run2)
        # Query directly for both of the datasets, and each one, one at a time.
        self.assertCountEqual(
            list(registry.queryDatasets(schema, collections=[run1, run2], findFirst=False)),
            [dataset1, dataset2]
        )
        self.assertEqual(
            list(registry.queryDatasets(schema, collections=[run1, run2], findFirst=True)),
            [dataset1],
        )
        self.assertEqual(
            list(registry.queryDatasets(schema, collections=[run2, run1], findFirst=True)),
            [dataset2],
        )
        # Query for data IDs with no dimensions.
        dataIds = registry.queryDataIds([])
        self.assertEqual(
            dataIds.toSequence(),
            DataCoordinateSequence([dataId], registry.dimensions.empty)
        )
        # Use queried data IDs to find the datasets.
        self.assertCountEqual(
            list(dataIds.findDatasets(schema, collections=[run1, run2], findFirst=False)),
            [dataset1, dataset2],
        )
        self.assertEqual(
            list(dataIds.findDatasets(schema, collections=[run1, run2], findFirst=True)),
            [dataset1],
        )
        self.assertEqual(
            list(dataIds.findDatasets(schema, collections=[run2, run1], findFirst=True)),
            [dataset2],
        )
        # Now materialize the data ID query results and repeat those tests.
        with dataIds.materialize() as dataIds:
            self.assertEqual(
                dataIds.toSequence(),
                DataCoordinateSequence([dataId], registry.dimensions.empty)
            )
            self.assertCountEqual(
                list(dataIds.findDatasets(schema, collections=[run1, run2], findFirst=False)),
                [dataset1, dataset2],
            )
            self.assertEqual(
                list(dataIds.findDatasets(schema, collections=[run1, run2], findFirst=True)),
                [dataset1],
            )
            self.assertEqual(
                list(dataIds.findDatasets(schema, collections=[run2, run1], findFirst=True)),
                [dataset2],
            )
        # Query for non-empty data IDs, then subset that to get the empty one.
        # Repeat the above tests starting from that.
        dataIds = registry.queryDataIds(["instrument"]).subset(registry.dimensions.empty, unique=True)
        self.assertEqual(
            dataIds.toSequence(),
            DataCoordinateSequence([dataId], registry.dimensions.empty)
        )
        self.assertCountEqual(
            list(dataIds.findDatasets(schema, collections=[run1, run2], findFirst=False)),
            [dataset1, dataset2],
        )
        self.assertEqual(
            list(dataIds.findDatasets(schema, collections=[run1, run2], findFirst=True)),
            [dataset1],
        )
        self.assertEqual(
            list(dataIds.findDatasets(schema, collections=[run2, run1], findFirst=True)),
            [dataset2],
        )
        with dataIds.materialize() as dataIds:
            self.assertEqual(
                dataIds.toSequence(),
                DataCoordinateSequence([dataId], registry.dimensions.empty)
            )
            self.assertCountEqual(
                list(dataIds.findDatasets(schema, collections=[run1, run2], findFirst=False)),
                [dataset1, dataset2],
            )
            self.assertEqual(
                list(dataIds.findDatasets(schema, collections=[run1, run2], findFirst=True)),
                [dataset1],
            )
            self.assertEqual(
                list(dataIds.findDatasets(schema, collections=[run2, run1], findFirst=True)),
                [dataset2],
            )
        # Query for non-empty data IDs, then materialize, then subset to get
        # the empty one.  Repeat again.
        with registry.queryDataIds(["instrument"]).materialize() as nonEmptyDataIds:
            dataIds = nonEmptyDataIds.subset(registry.dimensions.empty, unique=True)
            self.assertEqual(
                dataIds.toSequence(),
                DataCoordinateSequence([dataId], registry.dimensions.empty)
            )
            self.assertCountEqual(
                list(dataIds.findDatasets(schema, collections=[run1, run2], findFirst=False)),
                [dataset1, dataset2],
            )
            self.assertEqual(
                list(dataIds.findDatasets(schema, collections=[run1, run2], findFirst=True)),
                [dataset1],
            )
            self.assertEqual(
                list(dataIds.findDatasets(schema, collections=[run2, run1], findFirst=True)),
                [dataset2],
            )
            with dataIds.materialize() as dataIds:
                self.assertEqual(
                    dataIds.toSequence(),
                    DataCoordinateSequence([dataId], registry.dimensions.empty)
                )
                self.assertCountEqual(
                    list(dataIds.findDatasets(schema, collections=[run1, run2], findFirst=False)),
                    [dataset1, dataset2],
                )
                self.assertEqual(
                    list(dataIds.findDatasets(schema, collections=[run1, run2], findFirst=True)),
                    [dataset1],
                )
                self.assertEqual(
                    list(dataIds.findDatasets(schema, collections=[run2, run1], findFirst=True)),
                    [dataset2],
                )

    def testCalibrationCollections(self):
        """Test operations on `~CollectionType.CALIBRATION` collections,
        including `Registry.certify`, `Registry.decertify`, and
        `Registry.findDataset`.
        """
        # Setup - make a Registry, fill it with some datasets in
        # non-calibration collections.
        registry = self.makeRegistry()
        self.loadData(registry, "base.yaml")
        self.loadData(registry, "datasets.yaml")
        # Set up some timestamps.
        t1 = astropy.time.Time('2020-01-01T01:00:00', format="isot", scale="tai")
        t2 = astropy.time.Time('2020-01-01T02:00:00', format="isot", scale="tai")
        t3 = astropy.time.Time('2020-01-01T03:00:00', format="isot", scale="tai")
        t4 = astropy.time.Time('2020-01-01T04:00:00', format="isot", scale="tai")
        t5 = astropy.time.Time('2020-01-01T05:00:00', format="isot", scale="tai")
        allTimespans = [
            Timespan(a, b) for a, b in itertools.combinations([None, t1, t2, t3, t4, t5, None], r=2)
        ]
        # Get references to some datasets.
        bias2a = registry.findDataset("bias", instrument="Cam1", detector=2, collections="imported_g")
        bias3a = registry.findDataset("bias", instrument="Cam1", detector=3, collections="imported_g")
        bias2b = registry.findDataset("bias", instrument="Cam1", detector=2, collections="imported_r")
        bias3b = registry.findDataset("bias", instrument="Cam1", detector=3, collections="imported_r")
        # Register the main calibration collection we'll be working with.
        collection = "Cam1/calibs/default"
        registry.registerCollection(collection, type=CollectionType.CALIBRATION)
        # Cannot associate into a calibration collection (no timespan).
        with self.assertRaises(TypeError):
            registry.associate(collection, [bias2a])
        # Certify 2a dataset with [t2, t4) validity.
        registry.certify(collection, [bias2a], Timespan(begin=t2, end=t4))
        # We should not be able to certify 2b with anything overlapping that
        # window.
        with self.assertRaises(ConflictingDefinitionError):
            registry.certify(collection, [bias2b], Timespan(begin=None, end=t3))
        with self.assertRaises(ConflictingDefinitionError):
            registry.certify(collection, [bias2b], Timespan(begin=None, end=t5))
        with self.assertRaises(ConflictingDefinitionError):
            registry.certify(collection, [bias2b], Timespan(begin=t1, end=t3))
        with self.assertRaises(ConflictingDefinitionError):
            registry.certify(collection, [bias2b], Timespan(begin=t1, end=t5))
        with self.assertRaises(ConflictingDefinitionError):
            registry.certify(collection, [bias2b], Timespan(begin=t1, end=None))
        with self.assertRaises(ConflictingDefinitionError):
            registry.certify(collection, [bias2b], Timespan(begin=t2, end=t3))
        with self.assertRaises(ConflictingDefinitionError):
            registry.certify(collection, [bias2b], Timespan(begin=t2, end=t5))
        with self.assertRaises(ConflictingDefinitionError):
            registry.certify(collection, [bias2b], Timespan(begin=t2, end=None))
        # We should be able to certify 3a with a range overlapping that window,
        # because it's for a different detector.
        # We'll certify 3a over [t1, t3).
        registry.certify(collection, [bias3a], Timespan(begin=t1, end=t3))
        # Now we'll certify 2b and 3b together over [t4, ∞).
        registry.certify(collection, [bias2b, bias3b], Timespan(begin=t4, end=None))

        # Fetch all associations and check that they are what we expect.
        self.assertCountEqual(
            list(
                registry.queryDatasetAssociations(
                    "bias",
                    collections=[collection, "imported_g", "imported_r"],
                )
            ),
            [
                DatasetAssociation(
                    ref=registry.findDataset("bias", instrument="Cam1", detector=1, collections="imported_g"),
                    collection="imported_g",
                    timespan=None,
                ),
                DatasetAssociation(
                    ref=registry.findDataset("bias", instrument="Cam1", detector=4, collections="imported_r"),
                    collection="imported_r",
                    timespan=None,
                ),
                DatasetAssociation(ref=bias2a, collection="imported_g", timespan=None),
                DatasetAssociation(ref=bias3a, collection="imported_g", timespan=None),
                DatasetAssociation(ref=bias2b, collection="imported_r", timespan=None),
                DatasetAssociation(ref=bias3b, collection="imported_r", timespan=None),
                DatasetAssociation(ref=bias2a, collection=collection, timespan=Timespan(begin=t2, end=t4)),
                DatasetAssociation(ref=bias3a, collection=collection, timespan=Timespan(begin=t1, end=t3)),
                DatasetAssociation(ref=bias2b, collection=collection, timespan=Timespan(begin=t4, end=None)),
                DatasetAssociation(ref=bias3b, collection=collection, timespan=Timespan(begin=t4, end=None)),
            ]
        )

        class Ambiguous:
            """Tag class to denote lookups that are expected to be ambiguous.
            """
            pass

        def assertLookup(detector: int, timespan: Timespan,
                         expected: Optional[Union[DatasetRef, Type[Ambiguous]]]) -> None:
            """Local function that asserts that a bias lookup returns the given
            expected result.
            """
            if expected is Ambiguous:
                with self.assertRaises(RuntimeError):
                    registry.findDataset("bias", collections=collection, instrument="Cam1",
                                         detector=detector, timespan=timespan)
            else:
                self.assertEqual(
                    expected,
                    registry.findDataset("bias", collections=collection, instrument="Cam1",
                                         detector=detector, timespan=timespan)
                )

        # Systematically test lookups against expected results.
        assertLookup(detector=2, timespan=Timespan(None, t1), expected=None)
        assertLookup(detector=2, timespan=Timespan(None, t2), expected=None)
        assertLookup(detector=2, timespan=Timespan(None, t3), expected=bias2a)
        assertLookup(detector=2, timespan=Timespan(None, t4), expected=bias2a)
        assertLookup(detector=2, timespan=Timespan(None, t5), expected=Ambiguous)
        assertLookup(detector=2, timespan=Timespan(None, None), expected=Ambiguous)
        assertLookup(detector=2, timespan=Timespan(t1, t2), expected=None)
        assertLookup(detector=2, timespan=Timespan(t1, t3), expected=bias2a)
        assertLookup(detector=2, timespan=Timespan(t1, t4), expected=bias2a)
        assertLookup(detector=2, timespan=Timespan(t1, t5), expected=Ambiguous)
        assertLookup(detector=2, timespan=Timespan(t1, None), expected=Ambiguous)
        assertLookup(detector=2, timespan=Timespan(t2, t3), expected=bias2a)
        assertLookup(detector=2, timespan=Timespan(t2, t4), expected=bias2a)
        assertLookup(detector=2, timespan=Timespan(t2, t5), expected=Ambiguous)
        assertLookup(detector=2, timespan=Timespan(t2, None), expected=Ambiguous)
        assertLookup(detector=2, timespan=Timespan(t3, t4), expected=bias2a)
        assertLookup(detector=2, timespan=Timespan(t3, t5), expected=Ambiguous)
        assertLookup(detector=2, timespan=Timespan(t3, None), expected=Ambiguous)
        assertLookup(detector=2, timespan=Timespan(t4, t5), expected=bias2b)
        assertLookup(detector=2, timespan=Timespan(t4, None), expected=bias2b)
        assertLookup(detector=2, timespan=Timespan(t5, None), expected=bias2b)
        assertLookup(detector=3, timespan=Timespan(None, t1), expected=None)
        assertLookup(detector=3, timespan=Timespan(None, t2), expected=bias3a)
        assertLookup(detector=3, timespan=Timespan(None, t3), expected=bias3a)
        assertLookup(detector=3, timespan=Timespan(None, t4), expected=bias3a)
        assertLookup(detector=3, timespan=Timespan(None, t5), expected=Ambiguous)
        assertLookup(detector=3, timespan=Timespan(None, None), expected=Ambiguous)
        assertLookup(detector=3, timespan=Timespan(t1, t2), expected=bias3a)
        assertLookup(detector=3, timespan=Timespan(t1, t3), expected=bias3a)
        assertLookup(detector=3, timespan=Timespan(t1, t4), expected=bias3a)
        assertLookup(detector=3, timespan=Timespan(t1, t5), expected=Ambiguous)
        assertLookup(detector=3, timespan=Timespan(t1, None), expected=Ambiguous)
        assertLookup(detector=3, timespan=Timespan(t2, t3), expected=bias3a)
        assertLookup(detector=3, timespan=Timespan(t2, t4), expected=bias3a)
        assertLookup(detector=3, timespan=Timespan(t2, t5), expected=Ambiguous)
        assertLookup(detector=3, timespan=Timespan(t2, None), expected=Ambiguous)
        assertLookup(detector=3, timespan=Timespan(t3, t4), expected=None)
        assertLookup(detector=3, timespan=Timespan(t3, t5), expected=bias3b)
        assertLookup(detector=3, timespan=Timespan(t3, None), expected=bias3b)
        assertLookup(detector=3, timespan=Timespan(t4, t5), expected=bias3b)
        assertLookup(detector=3, timespan=Timespan(t4, None), expected=bias3b)
        assertLookup(detector=3, timespan=Timespan(t5, None), expected=bias3b)

        # Decertify [t3, t5) for all data IDs, and do test lookups again.
        # This should truncate bias2a to [t2, t3), leave bias3a unchanged at
        # [t1, t3), and truncate bias2b and bias3b to [t5, ∞).
        registry.decertify(collection=collection, datasetType="bias", timespan=Timespan(t3, t5))
        assertLookup(detector=2, timespan=Timespan(None, t1), expected=None)
        assertLookup(detector=2, timespan=Timespan(None, t2), expected=None)
        assertLookup(detector=2, timespan=Timespan(None, t3), expected=bias2a)
        assertLookup(detector=2, timespan=Timespan(None, t4), expected=bias2a)
        assertLookup(detector=2, timespan=Timespan(None, t5), expected=bias2a)
        assertLookup(detector=2, timespan=Timespan(None, None), expected=Ambiguous)
        assertLookup(detector=2, timespan=Timespan(t1, t2), expected=None)
        assertLookup(detector=2, timespan=Timespan(t1, t3), expected=bias2a)
        assertLookup(detector=2, timespan=Timespan(t1, t4), expected=bias2a)
        assertLookup(detector=2, timespan=Timespan(t1, t5), expected=bias2a)
        assertLookup(detector=2, timespan=Timespan(t1, None), expected=Ambiguous)
        assertLookup(detector=2, timespan=Timespan(t2, t3), expected=bias2a)
        assertLookup(detector=2, timespan=Timespan(t2, t4), expected=bias2a)
        assertLookup(detector=2, timespan=Timespan(t2, t5), expected=bias2a)
        assertLookup(detector=2, timespan=Timespan(t2, None), expected=Ambiguous)
        assertLookup(detector=2, timespan=Timespan(t3, t4), expected=None)
        assertLookup(detector=2, timespan=Timespan(t3, t5), expected=None)
        assertLookup(detector=2, timespan=Timespan(t3, None), expected=bias2b)
        assertLookup(detector=2, timespan=Timespan(t4, t5), expected=None)
        assertLookup(detector=2, timespan=Timespan(t4, None), expected=bias2b)
        assertLookup(detector=2, timespan=Timespan(t5, None), expected=bias2b)
        assertLookup(detector=3, timespan=Timespan(None, t1), expected=None)
        assertLookup(detector=3, timespan=Timespan(None, t2), expected=bias3a)
        assertLookup(detector=3, timespan=Timespan(None, t3), expected=bias3a)
        assertLookup(detector=3, timespan=Timespan(None, t4), expected=bias3a)
        assertLookup(detector=3, timespan=Timespan(None, t5), expected=bias3a)
        assertLookup(detector=3, timespan=Timespan(None, None), expected=Ambiguous)
        assertLookup(detector=3, timespan=Timespan(t1, t2), expected=bias3a)
        assertLookup(detector=3, timespan=Timespan(t1, t3), expected=bias3a)
        assertLookup(detector=3, timespan=Timespan(t1, t4), expected=bias3a)
        assertLookup(detector=3, timespan=Timespan(t1, t5), expected=bias3a)
        assertLookup(detector=3, timespan=Timespan(t1, None), expected=Ambiguous)
        assertLookup(detector=3, timespan=Timespan(t2, t3), expected=bias3a)
        assertLookup(detector=3, timespan=Timespan(t2, t4), expected=bias3a)
        assertLookup(detector=3, timespan=Timespan(t2, t5), expected=bias3a)
        assertLookup(detector=3, timespan=Timespan(t2, None), expected=Ambiguous)
        assertLookup(detector=3, timespan=Timespan(t3, t4), expected=None)
        assertLookup(detector=3, timespan=Timespan(t3, t5), expected=None)
        assertLookup(detector=3, timespan=Timespan(t3, None), expected=bias3b)
        assertLookup(detector=3, timespan=Timespan(t4, t5), expected=None)
        assertLookup(detector=3, timespan=Timespan(t4, None), expected=bias3b)
        assertLookup(detector=3, timespan=Timespan(t5, None), expected=bias3b)

        # Decertify everything, this time with explicit data IDs, then check
        # that no lookups succeed.
        registry.decertify(
            collection, "bias", Timespan(None, None),
            dataIds=[
                dict(instrument="Cam1", detector=2),
                dict(instrument="Cam1", detector=3),
            ]
        )
        for detector in (2, 3):
            for timespan in allTimespans:
                assertLookup(detector=detector, timespan=timespan, expected=None)
        # Certify bias2a and bias3a over (-∞, ∞), check that all lookups return
        # those.
        registry.certify(collection, [bias2a, bias3a], Timespan(None, None),)
        for timespan in allTimespans:
            assertLookup(detector=2, timespan=timespan, expected=bias2a)
            assertLookup(detector=3, timespan=timespan, expected=bias3a)
        # Decertify just bias2 over [t2, t4).
        # This should split a single certification row into two (and leave the
        # other existing row, for bias3a, alone).
        registry.decertify(collection, "bias", Timespan(t2, t4),
                           dataIds=[dict(instrument="Cam1", detector=2)])
        for timespan in allTimespans:
            assertLookup(detector=3, timespan=timespan, expected=bias3a)
            overlapsBefore = timespan.overlaps(Timespan(None, t2))
            overlapsAfter = timespan.overlaps(Timespan(t4, None))
            if overlapsBefore and overlapsAfter:
                expected = Ambiguous
            elif overlapsBefore or overlapsAfter:
                expected = bias2a
            else:
                expected = None
            assertLookup(detector=2, timespan=timespan, expected=expected)
