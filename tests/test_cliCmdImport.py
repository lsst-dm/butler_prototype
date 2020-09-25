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

"""Unit tests for daf_butler CLI config-dump command.
"""

import os
import unittest
import unittest.mock

from lsst.daf.butler.tests import CliCmdTestBase
from lsst.daf.butler.cli.cmd import butler_import
from lsst.daf.butler.cli.utils import Mocker


class ImportTestCase(CliCmdTestBase, unittest.TestCase):

    @staticmethod
    def defaultExpected():
        return dict(repo=None,
                    transfer="auto",
                    directory=None,
                    skip_dimensions=(),
                    export_file=None)

    @staticmethod
    def command():
        return butler_import

    def test_minimal(self):
        """Test only the required parameters, and omit the optional parameters.
        """
        self.run_test(["import", "here", "foo"],
                      self.makeExpected(repo="here", directory="foo"))

    def test_almostAll(self):
        """Test all the parameters, except export_file which gets its own test
        case below.
        """
        self.run_test(["import", "here", "foo",
                       "--transfer", "symlink"],
                      self.makeExpected(repo="here", directory="foo",
                                        transfer="symlink"))

    def test_missingArgument(self):
        """Verify the command fails if either of the positional arguments,
        REPO or DIRECTORY, is missing."""
        self.run_missing(["import", "foo"],
                         r"Error: Missing argument ['\"]DIRECTORY['\"].")


class ExportFileCase(CliCmdTestBase, unittest.TestCase):

    didRead = None

    @staticmethod
    def defaultExpected():
        return dict(repo=None,
                    transfer="auto",
                    directory=None,
                    export_file=None)

    @staticmethod
    def command():
        return butler_import

    def setUp(self):
        # add a side effect to Mocker so that it will call our method when it
        # is called.
        Mocker.mock.side_effect = self.read_test
        super().setUp()

    def tearDown(self):
        # reset the Mocker's side effect on our way out!
        Mocker.mock.side_effect = None
        super().tearDown()

    @staticmethod
    def read_test(*args, **kwargs):
        """This gets called by the Mocker's side effect when the Mocker is
        called. Our export_file argument is a File so Click will open it before
        calling the Mocker, and thus before it gets here. A little bit is
        written into the file here and that is verified later.
        """
        print("in read_test")
        ExportFileCase.didRead = kwargs["export_file"].read()

    def test_exportFile(self):
        """Test all the parameters, except export_file.
        """
        # export_file is ANY in makeExpected because that variable is opened by
        # click and the open handle is passed to the command function as a
        # TestIOWrapper. It doesn't work to test it with
        # MagicMock.assert_called_with because if a TextIOWrapper is created
        # here it will be a different instance and not compare equal. We test
        # that variable via the mocker.side_effect used in self.read_test.
        with self.runner.isolated_filesystem():
            with open("output.yaml", "w") as f:
                f.write("foobarbaz")
            self.run_test(["import", "here", "foo",
                           "--skip-dimensions", "instrument", "-s", "detector",
                           "--export-file", os.path.abspath("output.yaml")],
                          self.makeExpected(repo="here", directory="foo",
                                            skip_dimensions=("instrument", "detector"),
                                            export_file=unittest.mock.ANY))
            self.assertEqual("foobarbaz", ExportFileCase.didRead)


if __name__ == "__main__":
    unittest.main()
