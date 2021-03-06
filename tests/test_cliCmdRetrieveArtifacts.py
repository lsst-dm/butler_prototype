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

"""Unit tests for daf_butler CLI retrieve-artifacts command.
"""

import os
import unittest
from typing import List

from lsst.daf.butler.cli.butler import cli
from lsst.daf.butler.cli.utils import clickResultMsg, LogCliRunner
from lsst.daf.butler import StorageClassFactory, ButlerURI
from lsst.daf.butler.tests.utils import ButlerTestHelper, makeTestTempDir, MetricTestRepo, removeTestTempDir


TESTDIR = os.path.abspath(os.path.dirname(__file__))


class CliRetrieveArtifactsTest(unittest.TestCase, ButlerTestHelper):

    configFile = os.path.join(TESTDIR, "config/basic/butler.yaml")
    storageClassFactory = StorageClassFactory()

    def setUp(self):
        self.root = makeTestTempDir(TESTDIR)
        self.testRepo = MetricTestRepo(self.root,
                                       configFile=self.configFile)

    def tearDown(self):
        removeTestTempDir(self.root)

    @staticmethod
    def find_files(root: str) -> List[ButlerURI]:
        return list(ButlerURI.findFileResources([root]))

    def testRetrieveAll(self):
        runner = LogCliRunner()
        with runner.isolated_filesystem():

            # When preserving the path the run will be in the directory along
            # with a . in the component name.  When not preserving paths the
            # filename will have an underscore rather than dot.
            for counter, (preserve_path, prefix) in enumerate((("--preserve-path",
                                                               "ingest/run/test_metric_comp."),
                                                              ("--no-preserve-path",
                                                               "test_metric_comp_"))):
                destdir = f"tmp{counter}/"
                result = runner.invoke(cli, ["retrieve-artifacts", self.root, destdir, preserve_path])
                self.assertEqual(result.exit_code, 0, clickResultMsg(result))
                self.assertTrue(result.stdout.endswith(": 6\n"), f"Expected 6 got: {result.stdout}")

                artifacts = self.find_files(destdir)
                self.assertEqual(len(artifacts), 6, f"Expected 6 artifacts: {artifacts}")
                self.assertIn(f"{destdir}{prefix}", str(artifacts[1]))

    def testRetrieveSubset(self):
        runner = LogCliRunner()
        with runner.isolated_filesystem():
            destdir = "tmp1/"
            result = runner.invoke(cli, ["retrieve-artifacts", self.root, destdir,
                                         "--where", "instrument='DummyCamComp' AND visit=423"])
            self.assertEqual(result.exit_code, 0, clickResultMsg(result))
            self.assertTrue(result.stdout.endswith(": 3\n"), f"Expected 3 got: {result.stdout}")
            artifacts = self.find_files(destdir)
            self.assertEqual(len(artifacts), 3, f"Expected 3 artifacts: {artifacts}")

    def testClobber(self):
        runner = LogCliRunner()
        with runner.isolated_filesystem():
            destdir = "tmp2/"
            result = runner.invoke(cli, ["retrieve-artifacts", self.root, destdir])
            self.assertEqual(result.exit_code, 0, clickResultMsg(result))

            # Running again should fail
            result = runner.invoke(cli, ["retrieve-artifacts", self.root, destdir])
            self.assertNotEqual(result.exit_code, 0, clickResultMsg(result))

            # But with clobber should pass
            result = runner.invoke(cli, ["retrieve-artifacts", self.root, destdir, "--clobber"])
            self.assertEqual(result.exit_code, 0, clickResultMsg(result))


if __name__ == "__main__":
    unittest.main()
