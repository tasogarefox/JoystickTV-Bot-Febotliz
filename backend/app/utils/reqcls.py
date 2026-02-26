"""
ReqCls - Required-Class Utility

This module provides a lightweight superclass for defining
classes with required class attributes and class methods,
without the need for instantiation.

Key features:
- `required_field()` marks a class attribute as required in subclasses.
- `required_method` decorates a class method that must be implemented
  in subclasses.
- `ReqCls` enforces that all required attributes and methods are
  implemented unless the current subclass explicitly sets
  `__reqcheck__ = False`.

Example:
    class Foo(ReqCls):
        __reqcheck__ = False
        foo_attr: ClassVar[str] = required_field()

        @classmethod
        @required_method
        async def foo_method(cls) -> None:
            ...

    class Bar(Foo):
        '''Implements required items, will not raise.'''
        foo_attr = "baz"

        @classmethod
        async def foo_method(cls) -> None:
            pass

    class Baz(Foo):
        '''Does NOT implement required items, will raise.'''
"""

from typing import NamedTuple, ClassVar, Any

__all__ = (
    "ReqCls",
    "required_field",
    "required_method",

    "get_reqdata",
    "is_required",
    "is_missing",
    "is_implemented",
)


# ==============================================================================
# Public Interface

def get_reqdata(cls: type["ReqCls"]) -> "ReqData":
    return ReqData.init(cls)

def is_implemented(cls: type["ReqCls"]) -> bool:
    return get_reqdata(cls).is_implemented

def is_required(cls: type["ReqCls"], attr: str) -> bool:
    reqdata = get_reqdata(cls)
    return attr in reqdata.required_attrs or attr in reqdata.required_methods

def is_missing(cls: type["ReqCls"], attr: str) -> bool:
    reqdata = get_reqdata(cls)
    return attr in reqdata.missing_attrs or attr in reqdata.missing_methods


# ==============================================================================
# Required Method

def required_method(f):
    f.__isabstractmethod__ = True
    return f


# ==============================================================================
# Required Field

class RequiredField:
    __slots__ = ()

def required_field() -> Any:
    return RequiredField()


# ==============================================================================
# Required Class

class ReqCls:
    __slots__ = ()

    __reqcheck__: ClassVar[bool] = True
    __reqdata__: ClassVar["ReqData | None"] = None

    def __init_subclass__(cls):
        super().__init_subclass__()
        ReqData.init(cls)


# ==============================================================================
# Required Data

class ReqData(NamedTuple):
    required_attrs: frozenset[str]
    required_methods: frozenset[str]

    missing_attrs: frozenset[str]
    missing_methods: frozenset[str]

    @property
    def is_implemented(self) -> bool:
        return not self.missing_attrs and not self.missing_methods

    @classmethod
    def init(cls, rqcls: type[ReqCls]) -> "ReqData":
        rqdata = rqcls.__dict__.get("__reqdata__")
        if rqdata is not None:
            return rqdata

        # Gather inherited ReqData instances
        rqdatbases: list[ReqData] = []
        for base in rqcls.__bases__:
            if base is not ReqCls and issubclass(base, ReqCls):
                rqbase = base.__reqdata__
                if rqbase is None:
                    raise TypeError(
                        f"{base.__name__}.__reqdata__ has not been initialized"
                    )

                rqdatbases.append(rqbase)

        # Determine required class attributes and methods
        required_attrs = set()
        required_methods = set()
        for key, value in rqcls.__dict__.items():
            if isinstance(value, RequiredField):
                required_attrs.add(key)

            elif getattr(value, "__isabstractmethod__", False):
                required_methods.add(key)

        # Remove RequiredField instances
        for key in required_attrs:
            delattr(rqcls, key)

        # Add inherited required class attributes and methods
        required_attrs.update(*(x.required_attrs for x in rqdatbases))
        required_methods.update(*(x.required_methods for x in rqdatbases))

        # Determine missing class attributes
        missing_attrs = set()
        for iname in required_attrs:
            if not hasattr(rqcls, iname):
                missing_attrs.add(iname)

        # Determine missing class methods
        missing_methods = set()
        for iname in required_methods:
            method = getattr(rqcls, iname, None)
            if method is None or getattr(method, "__isabstractmethod__", False):
                missing_methods.add(iname)

        # Instantiate and store ReqData
        rqdata = rqcls.__reqdata__ = cls(
            required_attrs=frozenset(required_attrs),
            required_methods=frozenset(required_methods),
            missing_attrs=frozenset(missing_attrs),
            missing_methods=frozenset(missing_methods),
        )

        # Enforce implementation
        if rqcls.__dict__.get("__reqcheck__", True):
            if missing_attrs or missing_methods:
                missing_str = ", ".join(sorted(missing_attrs | missing_methods))
                raise TypeError(
                    f"{rqcls.__name__} missing"
                    f" {len(missing_attrs)} required class attributes"
                    f" and {len(missing_methods)} required class methods"
                    f": {missing_str}"
                )

        return rqdata
