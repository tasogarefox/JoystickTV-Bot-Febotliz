from .. import EventError

__all__ = [
    "JSTVEventError",
    "JSTVParseError",
    "JSTVValidationError",
]


# ==============================================================================
# Exceptions

class JSTVEventError(EventError): pass
class JSTVParseError(JSTVEventError): pass
class JSTVValidationError(JSTVParseError): pass
