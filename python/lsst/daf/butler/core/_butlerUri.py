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

__all__ = ("ButlerURI",)

import os
import os.path
import urllib
import posixpath
from pathlib import Path, PurePath, PurePosixPath
import copy

from typing import (
    Any,
    Optional,
    Tuple,
    Type,
    Union,
)

# Determine if the path separator for the OS looks like POSIX
IS_POSIX = os.sep == posixpath.sep

# Root path for this operating system
OS_ROOT_PATH = Path().resolve().root


def os2posix(ospath: str) -> str:
    """Convert a local path description to a POSIX path description.

    Parameters
    ----------
    path : `str`
        Path using the local path separator.

    Returns
    -------
    posix : `str`
        Path using POSIX path separator
    """
    if IS_POSIX:
        return ospath

    posix = PurePath(ospath).as_posix()

    # PurePath strips trailing "/" from paths such that you can no
    # longer tell if a path is meant to be referring to a directory
    # Try to fix this.
    if ospath.endswith(os.sep) and not posix.endswith(posixpath.sep):
        posix += posixpath.sep

    return posix


def posix2os(posix: Union[PurePath, str]) -> str:
    """Convert a POSIX path description to a local path description.

    Parameters
    ----------
    posix : `str`
        Path using the POSIX path separator.

    Returns
    -------
    ospath : `str`
        Path using OS path separator
    """
    if IS_POSIX:
        return str(posix)

    posixPath = PurePosixPath(posix)
    paths = list(posixPath.parts)

    # Have to convert the root directory after splitting
    if paths[0] == posixPath.root:
        paths[0] = OS_ROOT_PATH

    # Trailing "/" is stripped so we need to add back an empty path
    # for consistency
    if str(posix).endswith(posixpath.sep):
        paths.append("")

    return os.path.join(*paths)


class ButlerURI:
    """Convenience wrapper around URI parsers.

    Provides access to URI components and can convert file
    paths into absolute path URIs. Scheme-less URIs are treated as if
    they are local file system paths and are converted to absolute URIs.

    A specialist subclass is created for each supported URI scheme.

    Parameters
    ----------
    uri : `str` or `urllib.parse.ParseResult`
        URI in string form.  Can be scheme-less if referring to a local
        filesystem path.
    root : `str`, optional
        When fixing up a relative path in a ``file`` scheme or if scheme-less,
        use this as the root. Must be absolute.  If `None` the current
        working directory will be used.
    forceAbsolute : `bool`, optional
        If `True`, scheme-less relative URI will be converted to an absolute
        path using a ``file`` scheme. If `False` scheme-less URI will remain
        scheme-less and will not be updated to ``file`` or absolute path.
    forceDirectory: `bool`, optional
        If `True` forces the URI to end with a separator, otherwise given URI
        is interpreted as is.
    """

    _pathLib: Type[PurePath] = PurePosixPath
    """Path library to use for this scheme."""

    _pathModule = posixpath
    """Path module to use for this scheme."""

    # mypy is confused without this
    _uri: urllib.parse.ParseResult

    def __new__(cls, uri: Union[str, urllib.parse.ParseResult, ButlerURI],
                root: Optional[str] = None, forceAbsolute: bool = True,
                forceDirectory: bool = False) -> ButlerURI:
        parsed: urllib.parse.ParseResult
        dirLike: bool
        subclass: Optional[Type] = None

        # Record if we need to post process the URI components
        # or if the instance is already fully configured
        if isinstance(uri, str):
            parsed = urllib.parse.urlparse(uri)
        elif isinstance(uri, urllib.parse.ParseResult):
            parsed = copy.copy(uri)
        elif isinstance(uri, ButlerURI):
            parsed = copy.copy(uri._uri)
            dirLike = uri.dirLike
            # No further parsing required and we know the subclass
            subclass = type(uri)
        else:
            raise ValueError(f"Supplied URI must be string, ButlerURI, or ParseResult but got '{uri!r}'")

        if subclass is None:
            parsed, dirLike = cls._fixupPathUri(parsed, root=root,
                                                forceAbsolute=forceAbsolute,
                                                forceDirectory=forceDirectory)

            # Work out the subclass from the URI scheme
            if not parsed.scheme:
                subclass = ButlerSchemelessURI
            elif parsed.scheme == "file":
                subclass = ButlerFileURI
            elif parsed.scheme == "s3":
                subclass = ButlerS3URI
            else:
                subclass = ButlerGenericURI

        # Now create an instance of the correct subclass and set the
        # attributes directly
        self = object.__new__(subclass)  # , parsed, dirLike)
        self._uri = parsed
        self.dirLike = dirLike
        return self

    @property
    def scheme(self) -> str:
        """The URI scheme (``://`` is not part of the scheme)."""
        return self._uri.scheme

    @property
    def netloc(self) -> str:
        """The URI network location."""
        return self._uri.netloc

    @property
    def path(self) -> str:
        """The path component of the URI."""
        return self._uri.path

    @property
    def ospath(self) -> str:
        """Path component of the URI localized to current OS."""
        raise AttributeError(f"Non-file URI ({self}) has no local OS path.")

    @property
    def relativeToPathRoot(self) -> str:
        """Returns path relative to network location.

        Effectively, this is the path property with posix separator stripped
        from the left hand side of the path.
        """
        p = self._pathLib(self.path)
        relToRoot = str(p.relative_to(p.root))
        if self.dirLike and not relToRoot.endswith("/"):
            relToRoot += "/"
        return relToRoot

    @property
    def fragment(self) -> str:
        """The fragment component of the URI."""
        return self._uri.fragment

    @property
    def params(self) -> str:
        """Any parameters included in the URI."""
        return self._uri.params

    @property
    def query(self) -> str:
        """Any query strings included in the URI."""
        return self._uri.query

    def geturl(self) -> str:
        """Return the URI in string form.

        Returns
        -------
        url : `str`
            String form of URI.
        """
        return self._uri.geturl()

    def split(self) -> Tuple[ButlerURI, str]:
        """Splits URI into head and tail. Equivalent to os.path.split where
        head preserves the URI components.

        Returns
        -------
        head: `ButlerURI`
            Everything leading up to tail, expanded and normalized as per
            ButlerURI rules.
        tail : `str`
            Last `self.path` component. Tail will be empty if path ends on a
            separator. Tail will never contain separators.
        """
        head, tail = self._pathModule.split(self.path)
        headuri = self._uri._replace(path=head)
        return self.__class__(headuri, forceDirectory=True), tail

    def basename(self) -> str:
        """Returns the base name, last element of path, of the URI. If URI ends
        on a slash returns an empty string. This is the second element returned
        by split().

        Equivalent of os.path.basename().

        Returns
        -------
        tail : `str`
            Last part of the path attribute. Trail will be empty if path ends
            on a separator.
        """
        return self.split()[1]

    def dirname(self) -> ButlerURI:
        """Returns a ButlerURI containing all the directories of the path
        attribute.

        Equivalent of os.path.dirname()

        Returns
        -------
        head : `ButlerURI`
            Everything except the tail of path attribute, expanded and
            normalized as per ButlerURI rules.
        """
        return self.split()[0]

    def replace(self, **kwargs: Any) -> ButlerURI:
        """Replace components in a URI with new values and return a new
        instance.

        Returns
        -------
        new : `ButlerURI`
            New `ButlerURI` object with updated values.
        """
        return self.__class__(self._uri._replace(**kwargs))

    def updateFile(self, newfile: str) -> None:
        """Update in place the final component of the path with the supplied
        file name.

        Parameters
        ----------
        newfile : `str`
            File name with no path component.

        Notes
        -----
        Updates the URI in place.
        Updates the ButlerURI.dirLike attribute.
        """
        dir, _ = self._pathModule.split(self.path)
        newpath = self._pathModule.join(dir, newfile)

        self.dirLike = False
        self._uri = self._uri._replace(path=newpath)

    def getExtension(self) -> str:
        """Return the file extension(s) associated with this URI path.

        Returns
        -------
        ext : `str`
            The file extension (including the ``.``). Can be empty string
            if there is no file extension. Will return all file extensions
            as a single extension such that ``file.fits.gz`` will return
            a value of ``.fits.gz``.
        """
        extensions = self._pathLib(self.path).suffixes
        return "".join(extensions)

    def __str__(self) -> str:
        return self.geturl()

    def __repr__(self) -> str:
        return f'ButlerURI("{self.geturl()}")'

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, ButlerURI):
            return False
        return self.geturl() == other.geturl()

    def __copy__(self) -> ButlerURI:
        # Implement here because the __new__ method confuses things
        return type(self)(str(self))

    def __deepcopy__(self, memo: Any) -> ButlerURI:
        # Implement here because the __new__ method confuses things
        return self.__copy__()

    def __getnewargs__(self) -> Tuple:
        return (str(self),)

    @staticmethod
    def _fixupPathUri(parsed: urllib.parse.ParseResult, root: Optional[str] = None,
                      forceAbsolute: bool = False,
                      forceDirectory: bool = False) -> Tuple[urllib.parse.ParseResult, bool]:
        """Fix up relative paths in URI instances.

        Parameters
        ----------
        parsed : `~urllib.parse.ParseResult`
            The result from parsing a URI using `urllib.parse`.
        root : `str`, optional
            Path to use as root when converting relative to absolute.
            If `None`, it will be the current working directory. This
            is a local file system path, not a URI.
        forceAbsolute : `bool`, optional
            If `True`, scheme-less relative URI will be converted to an
            absolute path using a ``file`` scheme. If `False` scheme-less URI
            will remain scheme-less and will not be updated to ``file`` or
            absolute path. URIs with a defined scheme will not be affected
            by this parameter.
        forceDirectory : `bool`, optional
            If `True` forces the URI to end with a separator, otherwise given
            URI is interpreted as is.

        Returns
        -------
        modified : `~urllib.parse.ParseResult`
            Update result if a URI is being handled.
        dirLike : `bool`
            `True` if given parsed URI has a trailing separator or
            forceDirectory is True. Otherwise `False`.

        Notes
        -----
        Relative paths are explicitly not supported by RFC8089 but `urllib`
        does accept URIs of the form ``file:relative/path.ext``. They need
        to be turned into absolute paths before they can be used.  This is
        always done regardless of the ``forceAbsolute`` parameter.

        AWS S3 differentiates between keys with trailing POSIX separators (i.e
        `/dir` and `/dir/`) whereas POSIX does not neccessarily.

        Scheme-less paths are normalized.
        """
        # assume we are not dealing with a directory like URI
        dirLike = False
        if not parsed.scheme or parsed.scheme == "file":

            # Replacement values for the URI
            replacements = {}

            if root is None:
                root = os.path.abspath(os.path.curdir)

            if not parsed.scheme:
                # if there was no scheme this is a local OS file path
                # which can support tilde expansion.
                expandedPath = os.path.expanduser(parsed.path)

                # Ensure that this is a file URI if it is already absolute
                if os.path.isabs(expandedPath):
                    replacements["scheme"] = "file"
                    replacements["path"] = os2posix(os.path.normpath(expandedPath))
                elif forceAbsolute:
                    # This can stay in OS path form, do not change to file
                    # scheme.
                    replacements["path"] = os.path.normpath(os.path.join(root, expandedPath))
                else:
                    # No change needed for relative local path staying relative
                    # except normalization
                    replacements["path"] = os.path.normpath(expandedPath)
                    # normalization of empty path returns "." so we are dirLike
                    if expandedPath == "":
                        dirLike = True

                # normpath strips trailing "/" which makes it hard to keep
                # track of directory vs file when calling replaceFile
                # find the appropriate separator
                if "scheme" in replacements:
                    sep = posixpath.sep
                else:
                    sep = os.sep

                # add the trailing separator only if explicitly required or
                # if it was stripped by normpath. Acknowledge that trailing
                # separator exists.
                endsOnSep = expandedPath.endswith(os.sep) and not replacements["path"].endswith(sep)
                if (forceDirectory or endsOnSep or dirLike):
                    dirLike = True
                    replacements["path"] += sep

            elif parsed.scheme == "file":
                # file URI implies POSIX path separators so split as POSIX,
                # then join as os, and convert to abspath. Do not handle
                # home directories since "file" scheme is explicitly documented
                # to not do tilde expansion.
                sep = posixpath.sep
                if posixpath.isabs(parsed.path):
                    if forceDirectory:
                        parsed = parsed._replace(path=parsed.path+sep)
                        dirLike = True
                    return copy.copy(parsed), dirLike

                replacements["path"] = posixpath.normpath(posixpath.join(os2posix(root), parsed.path))

                # normpath strips trailing "/" so put it back if necessary
                # Acknowledge that trailing separator exists.
                if forceDirectory or (parsed.path.endswith(sep) and not replacements["path"].endswith(sep)):
                    replacements["path"] += sep
                    dirLike = True
            else:
                raise RuntimeError("Unexpectedly got confused by URI scheme")

            # ParseResult is a NamedTuple so _replace is standard API
            parsed = parsed._replace(**replacements)

        # URI is dir-like if explicitly stated or if it ends on a separator
        endsOnSep = parsed.path.endswith(posixpath.sep)
        if forceDirectory or endsOnSep:
            dirLike = True
            # only add the separator if it's not already there
            if not endsOnSep:
                parsed = parsed._replace(path=parsed.path+posixpath.sep)

        if dirLike is None:
            raise RuntimeError("ButlerURI.dirLike attribute not set successfully.")

        return parsed, dirLike


class ButlerFileURI(ButlerURI):
    """URI for explicit ``file`` scheme."""

    @property
    def ospath(self) -> str:
        """Path component of the URI localized to current OS."""
        return posix2os(self._uri.path)


class ButlerS3URI(ButlerURI):
    """S3 URI"""
    pass


class ButlerGenericURI(ButlerURI):
    """Generic URI with a defined scheme"""
    pass


class ButlerSchemelessURI(ButlerURI):
    """Scheme-less URI referring to the local file system"""

    _pathLib = PurePath
    _pathModule = os.path

    @property
    def ospath(self) -> str:
        """Path component of the URI localized to current OS."""
        return self.path
