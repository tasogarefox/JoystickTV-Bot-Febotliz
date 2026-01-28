class JSTVError(Exception):
    """Base exception for all JSTV-related errors."""

class JSTVAuthError(JSTVError):
    """Authentication or token-related failure."""

class JSTVTokenNotFound(JSTVAuthError):
    """No access token exists for the requested channel."""

class JSTVTokenRefreshError(JSTVAuthError):
    """Failed to refresh an access token."""

class JSTVOAuthInitError(JSTVAuthError):
    """OAuth initialization failed."""

class JSTVWebError(JSTVError):
    """JSTV API request failed."""
