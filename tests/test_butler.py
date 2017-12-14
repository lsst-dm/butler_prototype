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

import unittest
import datetime

import lsst.utils.tests
from lsst.butler.butler import ButlerConfig, Butler
from lsst.butler.registry import Registry
from lsst.butler.datastore import PosixDatastore

from lsst.butler.datasets import DatasetType, DatasetLabel
from lsst.butler.units import Camera, AbstractFilter, PhysicalFilter, PhysicalSensor, Visit, ObservedSensor
from lsst.butler.storageClass import SourceCatalog

import datasetsHelper


class ButlerTestCase(lsst.utils.tests.TestCase):

    def setUp(self):
        pass

    def _populateMinimalRegistry(self, registry, cameraName='dummycam', filters=('g', 'r', 'i', 'z', 'y'), visitNumbers=range(2)):
        """Make a minimal Registry, populated with ObservedSensor (and all dependent DataUnits)
        for the specified *cameraName*, *filters* and *visitNumbers*.
        """
        visitDuration = 30.  # seconds

        camera = Camera(cameraName)
        registry.addDataUnit(camera)

        for n, f in enumerate(filters):
            abstractFilter = AbstractFilter(f)
            physicalFilter = PhysicalFilter(abstractFilter, camera, "{0}_{1}".format(cameraName, f))
            physicalSensor = PhysicalSensor(camera, n, name=str(n), group="", purpose="")

            for unit in (abstractFilter, physicalFilter, physicalSensor):
                registry.addDataUnit(unit)

            obsBegin = datetime.datetime(2017, 1, 1)
            for n in visitNumbers:
                visit = Visit(camera, n, physicalFilter, obsBegin, exposureTime=visitDuration, region=None)
                observedSensor = ObservedSensor(camera, visit, physicalSensor, region=None)
                for unit in (visit, observedSensor):
                    registry.addDataUnit(unit)
                obsBegin += datetime.timedelta(seconds=visitDuration)

        run = registry.makeRun("testing")
        datasetType = DatasetType("testdst", template=None, units=(
            ObservedSensor, ), storageClass=SourceCatalog)
        registry.registerDatasetType(datasetType)

        return run, datasetType

    def testBasicPutAndGet(self):
        registry = Registry()
        datastore = PosixDatastore(root="./butler_test_repository", create=True)
        collectionTag = "mycollection"
        cameraName = "dummycam"
        visitNumber = 0
        run, datasetType = self._populateMinimalRegistry(
            registry, cameraName=cameraName, visitNumbers=(visitNumber, ))
        butlerConfig = ButlerConfig(run=run)
        butler = Butler(butlerConfig, datastore, registry)
        datasetLabel = DatasetLabel(datasetType.name, Camera=cameraName, AbstractFilter='i',
                                    PhysicalFilter='dummycam_i', PhysicalSensor=0, Visit=visitNumber)
        catalog = datasetsHelper.makeExampleCatalog()

        # Put
        butler.put(datasetLabel, catalog)
        # Get
        catalogOut = butler.get(datasetLabel)
        datasetsHelper.assertCatalogEqual(self, catalog, catalogOut)
        # Unlink
        butler.unlink(datasetLabel)
        self.assertIsNone(butler.get(datasetLabel))


class MemoryTester(lsst.utils.tests.MemoryTestCase):
    pass


def setup_module(module):
    lsst.utils.tests.init()


if __name__ == "__main__":
    lsst.utils.tests.init()
    unittest.main()
