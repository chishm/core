"""DLNA Media Server entity"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from async_upnp_client.profiles.dlna import DmsDevice

from homeassistant.const import (
    ATTR_ASSUMED_STATE,
    ATTR_DEVICE_CLASS,
    ATTR_ENTITY_PICTURE,
    ATTR_FRIENDLY_NAME,
    ATTR_ICON,
    ATTR_SUPPORTED_FEATURES,
    ATTR_UNIT_OF_MEASUREMENT,
    DEVICE_DEFAULT_NAME,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    TEMP_CELSIUS,
    TEMP_FAHRENHEIT,
)
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.typing import StateType

class DlnaDmsEntity(Entity):
    """DLNA Digital Media Server entity"""

    def __init__(self, usn: str, dms_device: DmsDevice | None) -> None:
        """Initialize with a connected DMS device, or None as a placeholder"""
        # TODO 
        self.usn = usn
        self.dms_device = dms_device
        
    @property
    def should_poll(self) -> bool:
        """Updates will come via UPnP events to the event server"""
        return False
    
    @property
    def unique_id(self) -> str | None:
        """Return a unique ID."""
        return self.usn

    @property
    def name(self) -> str | None:
        """Return the name of the entity."""
        return None

    @property
    def state(self) -> StateType:
        """Return the state of the entity."""
        if not self.dms_device:
            return STATE_UNAVAILABLE
        # TODO: Return off when device off, on when on

    @property
    def capability_attributes(self) -> Mapping[str, Any] | None:
        """Return the capability attributes.

        Attributes that explain the capabilities of an entity.

        Implemented by component base class. Convention for attribute names
        is lowercase snake_case.
        """
        return None

    @property
    def state_attributes(self) -> dict[str, Any] | None:
        """Return the state attributes.

        Implemented by component base class, should not be extended by integrations.
        Convention for attribute names is lowercase snake_case.
        """
        return None

    @property
    def device_info(self) -> Mapping[str, Any] | None:
        """Return device specific attributes.

        Implemented by platform classes.
        """
        return None

    @property
    def icon(self) -> str | None:
        """Return the icon to use in the frontend, if any."""
        return "mdi:server-network"

    @property
    def entity_picture(self) -> str | None:
        """Return the entity picture to use in the frontend, if any."""
        # TODO: Use device icon
        return None

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        # TODO: figure out and implement
        return True

    @property
    def assumed_state(self) -> bool:
        """Return True if unable to access real state of the entity."""
        return self.dms_device is None

    @property
    def force_update(self) -> bool:
        """Return True if state updates should be forced.

        If True, a state change will be triggered anytime the state property is
        updated, not just when the value changes.
        """
        return False

    @property
    def supported_features(self) -> int | None:
        """Flag supported features."""
        return None

