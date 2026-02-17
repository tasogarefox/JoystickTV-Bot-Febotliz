"""
ReqCls — Required-Class Utility

This module provides a lightweight metaclass `ReqClsMeta` for defining
classes with required class attributes and classmethods, without
forcing instantiation.

Key features:

- `required_field()` marks a class attribute as required in subclasses.
- `required_method` decorates a classmethod that must be implemented
  in subclasses.
- `ReqClsMeta` enforces that all required attributes and methods are
  implemented when `reqcls_check=True`.
- `ReqCls` is a convenient base class using this metaclass.

Example:
    class Foo(ReqCls, reqcls_check=False):
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

from typing import Any

__all__ = (
    "ReqCls",
    "ReqClsMeta",
    "required_field",
    "required_method",
    "is_implemented",
    "is_required",
)


# ==============================================================================
# Helpers

def is_implemented(cls: type) -> bool:
    try:
        return cls.__reqcls_implemented__
    except AttributeError as e:
        raise TypeError(f"{cls.__name__} is not like ReqCls") from e

def is_required(cls: type, attr: str) -> bool:
    try:
        return attr in cls.__reqcls_attributes__ or attr in cls.__reqcls_methods__
    except AttributeError as e:
        raise TypeError(f"{cls.__name__} is not like ReqCls") from e


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
# Metaclass

class ReqClsMeta(type):
    __slots__ = ()

    def __new__(
        mcls,
        name: str,
        bases: tuple[type, ...],
        namespace: dict[str, Any],
        *,
        reqcls_check: bool = True,
    ):
        # Determine required class attributes and methods
        req_attrs = set()
        req_methods = set()
        for key, value in namespace.items():
            if isinstance(value, RequiredField):
                req_attrs.add(key)

            elif getattr(value, "__isabstractmethod__", False):
                req_methods.add(key)

        # Remove RequiredField instances from namespace
        for key in req_attrs:
            del namespace[key]

        # Add inherited required class attributes and methods
        req_attrs.update(*(
            getattr(b, "__reqcls_attributes__", set())
            for b in bases
        ))
        req_methods.update(*(
            getattr(b, "__reqcls_methods__", set())
            for b in bases
        ))

        # Store class attributes
        namespace["__reqcls_attributes__"] = frozenset(req_attrs)
        namespace["__reqcls_methods__"] = frozenset(req_methods)
        namespace["__reqcls_implemented__"] = False

        # Create class
        cls: Any | ReqCls = super().__new__(mcls, name, bases, namespace)

        if reqcls_check:
            # Check required class attributes and methods
            missing_attrs = set()
            for iname in req_attrs:
                if not hasattr(cls, iname):
                    missing_attrs.add(iname)

            missing_methods = set()
            for iname in req_methods:
                method = getattr(cls, iname, None)
                if method is None or getattr(method, "__isabstractmethod__", False):
                    missing_methods.add(iname)

            if missing_attrs or missing_methods:
                missing_str = ", ".join(sorted(missing_attrs | missing_methods))
                raise TypeError(
                    f"{name} missing"
                    f" {len(missing_attrs)} required class attributes"
                    f" and {len(missing_methods)} required class methods"
                    f": {missing_str}"
                )

            # Mark class as implemented
            cls.__reqcls_implemented__ = True

        return cls


# ==============================================================================
# Required Class

class ReqCls(metaclass=ReqClsMeta):
    __slots__ = ()

    __reqcls_attributes__: frozenset[str]
    __reqcls_methods__: frozenset[str]
    __reqcls_implemented__: bool
