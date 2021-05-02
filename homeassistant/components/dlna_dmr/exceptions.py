"""DLNA platform exceptions"""

from homeassistant.exceptions import IntegrationError


class EventingError(IntegrationError):
    """Error when creating or using event or device notifiers."""
