from typing import Any
from datetime import datetime, timezone
import enum

from sqlalchemy import TypeDecorator, Integer, DateTime, Enum as SAEnum


# ==============================================================================
# Types

class Enum(SAEnum):
    """
    SQLAlchemy Enum with safe defaults:
    stores values as strings and validates assignments.
    """
    def __init__(self, *enums: type[enum.Enum], **kwargs: Any):
        kwargs.setdefault("native_enum", False)
        kwargs.setdefault("validate_strings", True)
        super().__init__(*enums, **kwargs)

class IntEnum(TypeDecorator):
    """
    Stores a Python IntEnum in the database as its .value (integer).

    If strict=True, only actual enum members can be bound (not raw ints).
    """
    impl = Integer
    cache_ok = True

    _enumtype: type[enum.IntEnum]
    _strict: bool

    def __init__(self, enumtype: type[enum.IntEnum], strict: bool = True, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._enumtype: type[enum.IntEnum] = enumtype
        self._strict: bool = strict

    def process_bind_param(self, value: enum.IntEnum | int | None, dialect) -> int | None:
        if value is None:
            return None
        if isinstance(value, self._enumtype):
            return value.value
        if not self._strict and isinstance(value, int):
            return value
        raise ValueError(f"Expected {self._enumtype.__name__}, got {type(value).__name__}: {value}")

    def process_result_value(self, value: int | None, dialect) -> enum.IntEnum | None:
        if value is None:
            return None
        try:
            return self._enumtype(value)
        except ValueError:
            raise ValueError(f"Invalid value {value} for enum {self._enumtype.__name__}")

class AwareDateTime(TypeDecorator):
    """
    Stores a datetime in the database as a naive UTC datetime.
    """
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is not None:
            if value.tzinfo is None:
                raise ValueError(f"Naive datetime passed to {type(self).__name__}: {value}")
            return value.astimezone(timezone.utc).replace(tzinfo=None)  # store as naive UTC
        return value

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is not None:
            return value.replace(tzinfo=timezone.utc)
        return value
