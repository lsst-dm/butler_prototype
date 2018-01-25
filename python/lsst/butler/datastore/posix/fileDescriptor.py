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

from .location import Location


class FileDescriptor(object):
    """Describes a particular file.

    Attributes
    ----------
    location : `Location`
        Storage location.
    type : `cls`
        Type the object will have after reading in Python (typically `StorageClass.type`).
    parameters : `dict`
        Additional parameters that can be used for reading and writing.
    """

    __slots__ = ('location', 'type', 'parameters')

    def __init__(self, location, type=None, parameters=None):
        """Constructor

        Parameters
        ----------
        location : `Location`
            Storage location.
        type : `cls`
            Type the object will have after reading in Python (typically `StorageClass.type`).
        parameters : `dict`
            Additional parameters that can be used for reading and writing.
        """
        assert isinstance(location, Location)
        self.location = location
        self.type = type
        self.parameters = parameters
