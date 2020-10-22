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
    "NamedKeyDict",
    "NamedKeyMapping",
    "NameLookupMapping",
    "NamedValueAbstractSet",
    "NamedValueMutableSet",
    "NamedValueSet",
)

from abc import abstractmethod
from typing import (
    AbstractSet,
    Any,
    Dict,
    ItemsView,
    Iterable,
    Iterator,
    KeysView,
    Mapping,
    MutableMapping,
    MutableSet,
    TypeVar,
    Union,
    ValuesView,
)
from types import MappingProxyType
try:
    # If we're running mypy, we should have typing_extensions.
    # If we aren't running mypy, we shouldn't assume we do.
    # When we're safely on Python 3.8, we can import Protocol
    # from typing and avoid all of this.
    from typing_extensions import Protocol

    class Named(Protocol):
        @property
        def name(self) -> str:
            pass

except ImportError:
    Named = Any  # type: ignore


K = TypeVar("K", bound=Named)
K_co = TypeVar("K_co", bound=Named, covariant=True)
V = TypeVar("V")
V_co = TypeVar("V_co", covariant=True)


class NamedKeyMapping(Mapping[K_co, V_co]):
    """An abstract base class for custom mappings whose keys are objects with
    a `str` ``name`` attribute, for which lookups on the name as well as the
    object are permitted.

    Notes
    -----
    In addition to the new `names` property and `byName` method, this class
    simply redefines the type signature for `__getitem__` and `get` that would
    otherwise be inherited from `Mapping`. That is only relevant for static
    type checking; the actual Python runtime doesn't care about types at all.
    """

    __slots__ = ()

    @property
    @abstractmethod
    def names(self) -> AbstractSet[str]:
        """The set of names associated with the keys, in the same order
        (`AbstractSet` [ `str` ]).
        """
        raise NotImplementedError()

    def byName(self) -> Dict[str, V_co]:
        """Return a `Mapping` with names as keys and the same values as
        ``self``.

        Returns
        -------
        dictionary : `dict`
            A dictionary with the same values (and iteration order) as
            ``self``, with `str` names as keys.  This is always a new object,
            not a view.
        """
        return dict(zip(self.names, self.values()))

    @abstractmethod
    def __getitem__(self, key: Union[str, K_co]) -> V_co:
        raise NotImplementedError()

    def get(self, key: Union[str, K_co], default: Any = None) -> Any:
        # Delegating to super is not allowed by typing, because it doesn't
        # accept str, but we know it just delegates to __getitem__, which does.
        return super().get(key, default)  # type: ignore


NameLookupMapping = Union[NamedKeyMapping[K_co, V_co], Mapping[str, V_co]]
"""A type annotation alias for signatures that want to use ``mapping[s]``
(or ``mapping.get(s)``) where ``s`` is a `str`, and don't care whether
``mapping.keys()`` returns named objects or direct `str` instances.
"""


class NamedKeyMutableMapping(NamedKeyMapping[K, V], MutableMapping[K, V]):
    """An abstract base class that adds mutation to `NamedKeyMapping`.
    """

    __slots__ = ()

    @abstractmethod
    def __setitem__(self, key: Union[str, K], value: V) -> None:
        raise NotImplementedError()

    @abstractmethod
    def __delitem__(self, key: Union[str, K]) -> None:
        raise NotImplementedError()

    def pop(self, key: Union[str, K], default: Any = None) -> Any:
        # See comment in `NamedKeyMapping.get`; same logic applies here.
        return super().pop(key, default)  # type: ignore


class NamedKeyDict(NamedKeyMutableMapping[K, V]):
    """A dictionary wrapper that require keys to have a ``.name`` attribute,
    and permits lookups using either key objects or their names.

    Names can be used in place of keys when updating existing items, but not
    when adding new items.

    It is assumed (but asserted) that all name equality is equivalent to key
    equality, either because the key objects define equality this way, or
    because different objects with the same name are never included in the same
    dictionary.

    Parameters
    ----------
    args
        All positional constructor arguments are forwarded directly to `dict`.
        Keyword arguments are not accepted, because plain strings are not valid
        keys for `NamedKeyDict`.

    Raises
    ------
    AttributeError
        Raised when an attempt is made to add an object with no ``.name``
        attribute to the dictionary.
    AssertionError
        Raised when multiple keys have the same name.
    """

    __slots__ = ("_dict", "_names",)

    def __init__(self, *args: Any):
        self._dict: Dict[K, V] = dict(*args)
        self._names = {key.name: key for key in self._dict}
        assert len(self._names) == len(self._dict), "Duplicate names in keys."

    @property
    def names(self) -> KeysView[str]:
        """The set of names associated with the keys, in the same order
        (`~collections.abc.KeysView`).
        """
        return self._names.keys()

    def byName(self) -> Dict[str, V]:
        """Return a `dict` with names as keys and the same values as ``self``.
        """
        return dict(zip(self._names.keys(), self._dict.values()))

    def __len__(self) -> int:
        return len(self._dict)

    def __iter__(self) -> Iterator[K]:
        return iter(self._dict)

    def __str__(self) -> str:
        return "{{{}}}".format(", ".join(f"{str(k)}: {str(v)}" for k, v in self.items()))

    def __repr__(self) -> str:
        return "NamedKeyDict({{{}}})".format(", ".join(f"{repr(k)}: {repr(v)}" for k, v in self.items()))

    def __getitem__(self, key: Union[str, K]) -> V:
        if isinstance(key, str):
            return self._dict[self._names[key]]
        else:
            return self._dict[key]

    def __setitem__(self, key: Union[str, K], value: V) -> None:
        if isinstance(key, str):
            self._dict[self._names[key]] = value
        else:
            assert self._names.get(key.name, key) == key, "Name is already associated with a different key."
            self._dict[key] = value
            self._names[key.name] = key

    def __delitem__(self, key: Union[str, K]) -> None:
        if isinstance(key, str):
            del self._dict[self._names[key]]
            del self._names[key]
        else:
            del self._dict[key]
            del self._names[key.name]

    def keys(self) -> KeysView[K]:
        return self._dict.keys()

    def values(self) -> ValuesView[V]:
        return self._dict.values()

    def items(self) -> ItemsView[K, V]:
        return self._dict.items()

    def copy(self) -> NamedKeyDict[K, V]:
        """Return a new `NamedKeyDict` with the same elements.
        """
        result = NamedKeyDict.__new__(NamedKeyDict)
        result._dict = dict(self._dict)
        result._names = dict(self._names)
        return result

    def freeze(self) -> NamedKeyMapping[K, V]:
        """Disable all mutators, effectively transforming ``self`` into
        an immutable mapping.

        Returns
        -------
        self : `NamedKeyMapping`
            While ``self`` is modified in-place, it is also returned with a
            type anotation that reflects its new, frozen state; assigning it
            to a new variable (and considering any previous references
            invalidated) should allow for more accurate static type checking.
        """
        if not isinstance(self._dict, MappingProxyType):
            self._dict = MappingProxyType(self._dict)  # type: ignore
        return self


class NamedValueAbstractSet(AbstractSet[K_co]):
    """An abstract base class for custom sets whose elements are objects with
    a `str` ``name`` attribute, allowing some dict-like operations and
    views to be supported.
    """

    __slots__ = ()

    @property
    @abstractmethod
    def names(self) -> AbstractSet[str]:
        """The set of names associated with the keys, in the same order
        (`AbstractSet` [ `str` ]).
        """
        raise NotImplementedError()

    @abstractmethod
    def asMapping(self) -> Mapping[str, K_co]:
        """Return a mapping view with names as keys.

        Returns
        -------
        dict : `Mapping`
            A dictionary-like view with ``values() == self``.
        """
        raise NotImplementedError()

    @abstractmethod
    def __getitem__(self, key: Union[str, K_co]) -> K_co:
        raise NotImplementedError()

    def get(self, key: Union[str, K_co], default: Any = None) -> Any:
        """Return the element with the given name, or ``default`` if
        no such element is present.
        """
        try:
            return self[key]
        except KeyError:
            return default


class NamedValueMutableSet(NamedValueAbstractSet[K], MutableSet[K]):
    """An abstract base class that adds mutation interfaces to
    `NamedValueAbstractSet`.

    Methods that can add new elements to the set are unchanged from their
    `MutableSet` definitions, while those that only remove them can generally
    accept names or element instances.  `pop` can be used in either its
    `MutableSet` form (no arguments; an arbitrary element is returned) or its
    `MutableMapping` form (one or two arguments for the name and optional
    default value, respectively).  A `MutableMapping`-like `__delitem__`
    interface is also included, which takes only names (like
    `NamedValueAbstractSet.__getitem__`).
    """

    __slots__ = ()

    @abstractmethod
    def __delitem__(self, name: str) -> None:
        raise NotImplementedError()

    @abstractmethod
    def remove(self, element: Union[str, K]) -> Any:
        """Remove an element from the set.

        Parameters
        ----------
        element : `object` or `str`
            Element to remove or the string name thereof.  Assumed to be an
            element if it has a ``.name`` attribute.

        Raises
        ------
        KeyError
            Raised if an element with the given name does not exist.
        """
        raise NotImplementedError()

    @abstractmethod
    def discard(self, element: Union[str, K]) -> Any:
        """Remove an element from the set if it exists.

        Does nothing if no matching element is present.

        Parameters
        ----------
        element : `object` or `str`
            Element to remove or the string name thereof.  Assumed to be an
            element if it has a ``.name`` attribute.
        """
        raise NotImplementedError()

    @abstractmethod
    def pop(self, *args: str) -> K:
        """Remove and return an element from the set.

        Parameters
        ----------
        name : `str`, optional
            Name of the element to remove and return.  Must be passed
            positionally.  If not provided, an arbitrary element is
            removed and returned.

        Raises
        ------
        KeyError
            Raised if ``name`` is provided but ``default`` is not, and no
            matching element exists.
        """
        raise NotImplementedError()


class NamedValueSet(NamedValueMutableSet[K]):
    """A custom mutable set class that requires elements to have a ``.name``
    attribute, which can then be used as keys in `dict`-like lookup.

    Names and elements can both be used with the ``in`` and ``del``
    operators, `remove`, and `discard`.  Names (but not elements)
    can be used with ``[]``-based element retrieval (not assignment)
    and the `get` method.

    Parameters
    ----------
    elements : `iterable`
        Iterable over elements to include in the set.

    Raises
    ------
    AttributeError
        Raised if one or more elements do not have a ``.name`` attribute.

    Notes
    -----
    Iteration order is guaranteed to be the same as insertion order (with
    the same general behavior as `dict` ordering).
    Like `dicts`, sets with the same elements will compare as equal even if
    their iterator order is not the same.
    """

    __slots__ = ("_dict",)

    def __init__(self, elements: Iterable[K] = ()):
        self._dict = {element.name: element for element in elements}

    @property
    def names(self) -> KeysView[str]:
        # Docstring inherited.
        return self._dict.keys()

    def asMapping(self) -> Mapping[str, K]:
        # Docstring inherited.
        return self._dict

    def __contains__(self, key: Any) -> bool:
        return getattr(key, "name", key) in self._dict

    def __len__(self) -> int:
        return len(self._dict)

    def __iter__(self) -> Iterator[K]:
        return iter(self._dict.values())

    def __str__(self) -> str:
        return "{{{}}}".format(", ".join(str(element) for element in self))

    def __repr__(self) -> str:
        return "NamedValueSet({{{}}})".format(", ".join(repr(element) for element in self))

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, NamedValueSet):
            return self._dict.keys() == other._dict.keys()
        else:
            return NotImplemented

    def __hash__(self) -> int:
        return hash(frozenset(self._dict.keys()))

    # As per Set's docs, overriding just __le__ and __ge__ for performance will
    # cover the other comparisons, too.

    def __le__(self, other: AbstractSet[K]) -> bool:
        if isinstance(other, NamedValueSet):
            return self._dict.keys() <= other._dict.keys()
        else:
            return NotImplemented

    def __ge__(self, other: AbstractSet[K]) -> bool:
        if isinstance(other, NamedValueSet):
            return self._dict.keys() >= other._dict.keys()
        else:
            return NotImplemented

    def issubset(self, other: AbstractSet[K]) -> bool:
        return self <= other

    def issuperset(self, other: AbstractSet[K]) -> bool:
        return self >= other

    def __getitem__(self, key: Union[str, K]) -> K:
        if isinstance(key, str):
            return self._dict[key]
        else:
            return self._dict[key.name]

    def get(self, key: Union[str, K], default: Any = None) -> Any:
        # Docstring inherited
        if isinstance(key, str):
            return self._dict.get(key, default)
        else:
            return self._dict.get(key.name, default)

    def __delitem__(self, name: str) -> None:
        del self._dict[name]

    def add(self, element: K) -> None:
        """Add an element to the set.

        Raises
        ------
        AttributeError
            Raised if the element does not have a ``.name`` attribute.
        """
        self._dict[element.name] = element

    def remove(self, element: Union[str, K]) -> Any:
        # Docstring inherited.
        del self._dict[getattr(element, "name", element)]

    def discard(self, element: Union[str, K]) -> Any:
        # Docstring inherited.
        try:
            self.remove(element)
        except KeyError:
            pass

    def pop(self, *args: str) -> K:
        # Docstring inherited.
        if not args:
            return super().pop()
        else:
            return self._dict.pop(*args)

    def update(self, elements: Iterable[K]) -> None:
        """Add multple new elements to the set.

        Parameters
        ----------
        elements : `Iterable`
            Elements to add.
        """
        for element in elements:
            self.add(element)

    def copy(self) -> NamedValueSet[K]:
        """Return a new `NamedValueSet` with the same elements.
        """
        result = NamedValueSet.__new__(NamedValueSet)
        result._dict = dict(self._dict)
        return result

    def freeze(self) -> NamedValueAbstractSet[K]:
        """Disable all mutators, effectively transforming ``self`` into
        an immutable set.

        Returns
        -------
        self : `NamedValueAbstractSet`
            While ``self`` is modified in-place, it is also returned with a
            type anotation that reflects its new, frozen state; assigning it
            to a new variable (and considering any previous references
            invalidated) should allow for more accurate static type checking.
        """
        if not isinstance(self._dict, MappingProxyType):
            self._dict = MappingProxyType(self._dict)  # type: ignore
        return self
