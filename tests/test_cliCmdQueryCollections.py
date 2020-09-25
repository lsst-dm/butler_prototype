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

"""Unit tests for daf_butler CLI query-collections command.
"""

import unittest
import yaml

from lsst.daf.butler import Butler, CollectionType
from lsst.daf.butler.cli.butler import cli
from lsst.daf.butler.cli.cmd import query_collections
from lsst.daf.butler.cli.utils import LogCliRunner
from lsst.daf.butler.tests import CliCmdTestBase


class QueryCollectionsCmdTest(CliCmdTestBase, unittest.TestCase):

    @staticmethod
    def defaultExpected():
        return dict(repo=None,
                    collection_type=tuple(CollectionType.__members__.values()),
                    flatten_chains=False,
                    glob=(),
                    include_chains=None)

    @staticmethod
    def command():
        return query_collections

    def test_minimal(self):
        """Test only the required parameters, and omit the optional parameters.
        """
        self.run_test(["query-collections", "here"],
                      self.makeExpected(repo="here"))

    def test_all(self):
        """Test all parameters"""
        self.run_test(["query-collections", "here", "foo*",
                       "--collection-type", "TAGGED",
                       "--collection-type", "RUN",
                       "--flatten-chains",
                       "--include-chains"],
                      self.makeExpected(repo="here",
                                        glob=("foo*",),
                                        collection_type=(CollectionType.TAGGED, CollectionType.RUN),
                                        flatten_chains=True,
                                        include_chains=True))


class QueryCollectionsScriptTest(unittest.TestCase):

    def testGetCollections(self):
        run = "ingest/run"
        tag = "tag"
        runner = LogCliRunner()
        with runner.isolated_filesystem():
            butlerCfg = Butler.makeRepo("here")
            # the purpose of this call is to create some collections
            _ = Butler(butlerCfg, run=run, tags=[tag], collections=[tag])

            # Verify collections that were created are found by
            # query-collections.
            result = runner.invoke(cli, ["query-collections", "here"])
            self.assertEqual({"collections": [run, tag]}, yaml.safe_load(result.output))

            # Verify that with a glob argument, that only collections whose
            # name matches with the specified pattern are returned.
            result = runner.invoke(cli, ["query-collections", "here", "t*"])
            self.assertEqual({"collections": [tag]}, yaml.safe_load(result.output))

            # Verify that with a collection type argument, only collections of
            # that type are returned.
            result = runner.invoke(cli, ["query-collections", "here", "--collection-type", "RUN"])
            self.assertEqual({"collections": [run]}, yaml.safe_load(result.output))


if __name__ == "__main__":
    unittest.main()
