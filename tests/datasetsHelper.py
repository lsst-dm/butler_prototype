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

import os

import lsst.afw.table

testDir = os.path.dirname(__file__)


def makeExampleCatalog():
    import lsst.afw.table
    catalogPath = os.path.join(testDir, "data", "basic", "source_catalog.fits")
    return lsst.afw.table.SourceCatalog.readFits(catalogPath)


def assertCatalogEqual(self, inputCatalog, outputCatalog):
    self.assertIsInstance(outputCatalog, lsst.afw.table.SourceCatalog)
    inputTable = inputCatalog.getTable()
    inputRecord = inputCatalog[0]
    outputTable = outputCatalog.getTable()
    outputRecord = outputCatalog[0]
    self.assertEqual(inputTable.getPsfFluxDefinition(), outputTable.getPsfFluxDefinition())
    self.assertEqual(inputRecord.getPsfFlux(), outputRecord.getPsfFlux())
    self.assertEqual(inputRecord.getPsfFluxFlag(), outputRecord.getPsfFluxFlag())
    self.assertEqual(inputTable.getCentroidDefinition(), outputTable.getCentroidDefinition())        
    self.assertEqual(inputRecord.getCentroid(), outputRecord.getCentroid())
    self.assertFloatsAlmostEqual(
        inputRecord.getCentroidErr()[0, 0],
        outputRecord.getCentroidErr()[0, 0], rtol=1e-6)
    self.assertFloatsAlmostEqual(
        inputRecord.getCentroidErr()[1, 1],
        outputRecord.getCentroidErr()[1, 1], rtol=1e-6)
    self.assertEqual(inputTable.getShapeDefinition(), outputTable.getShapeDefinition())
    self.assertFloatsAlmostEqual(
        inputRecord.getShapeErr()[0, 0],
        outputRecord.getShapeErr()[0, 0], rtol=1e-6)
    self.assertFloatsAlmostEqual(
        inputRecord.getShapeErr()[1, 1],
        outputRecord.getShapeErr()[1, 1], rtol=1e-6)
    self.assertFloatsAlmostEqual(
        inputRecord.getShapeErr()[2, 2],
        outputRecord.getShapeErr()[2, 2], rtol=1e-6)
