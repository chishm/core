"""Support for DLNA DMR (Device Media Renderer)."""
from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import timedelta
import functools
from urllib.parse import urlparse

import aiohttp
from async_upnp_client.aiohttp import AiohttpNotifyServer, AiohttpSessionRequester
from async_upnp_client.client import UpnpDevice, UpnpService, UpnpStateVariable
from async_upnp_client.device_updater import DeviceUpdater
from async_upnp_client.profiles.dlna import DeviceState, DmrDevice
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.media_player import PLATFORM_SCHEMA, MediaPlayerEntity
from homeassistant.components.media_player.const import (
    SUPPORT_NEXT_TRACK,
    SUPPORT_PAUSE,
    SUPPORT_PLAY,
    SUPPORT_PLAY_MEDIA,
    SUPPORT_PREVIOUS_TRACK,
    SUPPORT_SEEK,
    SUPPORT_STOP,
    SUPPORT_VOLUME_MUTE,
    SUPPORT_VOLUME_SET,
)
from homeassistant.components import ssdp
from homeassistant.const import (
    CONF_NAME,
    CONF_URL,
    EVENT_HOMEASSISTANT_STOP,
    STATE_IDLE,
    STATE_OFF,
    STATE_ON,
    STATE_PAUSED,
    STATE_PLAYING,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import PlatformNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import get_local_ip
import homeassistant.util.dt as dt_util

from . import get_domain_data
from .const import (
    CONF_LISTEN_IP,
    CONF_LISTEN_PORT,
    CONF_CALLBACK_URL_OVERRIDE,
    CONNECT_TIMEOUT,
    DOMAIN,
    LOGGER as _LOGGER,
)
from .eventing import (
    async_get_or_create_device_updater,
    async_get_or_create_event_notifier,
)

DEFAULT_NAME = "DLNA Digital Media Renderer"

# Configuration via YAML is deprecated in favour of config flow
PLATFORM_SCHEMA = vol.All(
    cv.deprecated(CONF_URL),
    cv.deprecated(CONF_LISTEN_IP),
    cv.deprecated(CONF_LISTEN_PORT),
    cv.deprecated(CONF_NAME),
    cv.deprecated(CONF_CALLBACK_URL_OVERRIDE),
    PLATFORM_SCHEMA.extend(
        {
            vol.Required(CONF_URL): cv.string,
            vol.Optional(CONF_LISTEN_IP): cv.string,
            vol.Optional(CONF_LISTEN_PORT): cv.port,
            vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
            vol.Optional(CONF_CALLBACK_URL_OVERRIDE): cv.url,
        }
    ),
)


def catch_request_errors():
    """Catch asyncio.TimeoutError, aiohttp.ClientError errors."""

    def call_wrapper(func):
        """Call wrapper for decorator."""

        @functools.wraps(func)
        async def wrapper(self, *args, **kwargs):
            """Catch asyncio.TimeoutError, aiohttp.ClientError errors."""
            try:
                return await func(self, *args, **kwargs)
            except (asyncio.TimeoutError, aiohttp.ClientError):
                _LOGGER.error("Error during call %s", func.__name__)

        return wrapper

    return call_wrapper


async def async_setup_entry(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the DlnaDmrEntity from a config entry"""
    _LOGGER.debug("media_player.async_setup_entry %s (%s)", entry.entry_id, entry.title)
    domain_data = get_domain_data(hass)
    upnp_device = domain_data.upnp_devices[entry.entry_id]
    listen_ip = entry.options.get(CONF_LISTEN_IP)

    # Create/get event handler that is reachable by the device
    event_handler = await async_get_or_create_event_notifier(
        hass,
        listen_ip=listen_ip,
        listen_port=entry.options.get(CONF_LISTEN_PORT),
        callback_url_override=entry.options.get(CONF_CALLBACK_URL_OVERRIDE),
    )

    # Create/get device updater to listen for the device (dis)appearing on the network
    device_updater = await async_get_or_create_device_updater(hass, listen_ip)

    # Create profile wrapper
    dmr_device = DmrDevice(upnp_device, event_handler, device_updater)

    # Create our own device-wrapping entity
    entity = DlnaDmrEntity(dmr_device, entry.title)

    async_add_entities([entity])


class DlnaDmrEntity(MediaPlayerEntity):
    """Representation of a DLNA DMR device as a HA entity."""

    def __init__(self, dmr_device: DmrDevice, name: str = None):
        """Initialize DLNA DMR entity."""
        self._device = dmr_device
        self._device.on_event = self._on_event
        self._device.async_on_notify = self._async_on_notify

        self._name = name

        self._available = False
        self._subscription_renew_time = None

    async def async_added_to_hass(self):
        """Handle addition."""
        self._device_updater.add_device(self._device.device)
        await self._device.async_subscribe_services()

    async def async_will_remove_from_hass(self):
        """Handle removal."""
        await self._device.async_unsubscribe_services()
        self._device_updater.remove_device(self._device.device)

    @property
    def available(self):
        """Device is available."""
        return self._device.device.available

    @property
    def should_poll(self) -> bool:
        """The device needs polling if the device updater or event handler failed.

        Failure could be because the device can't connect to HA (e.g. NAT is in
        the way) or because the device doesn't properly support eventing.
        """
        # TODO: Implement logic as described above:
        # TODO: Check if we have a SID for eventing
        # TODO: Check if we have a notification listener
        # TODO: event / notify callbacks (below) can change this to False
        return True

    async def async_update(self):
        """Retrieve the latest data."""
        # TODO: Only do this if can't subscribe for events
        was_available = self._available

        try:
            await self._device.async_update()
            self._available = True
        except (asyncio.TimeoutError, aiohttp.ClientError):
            self._available = False
            _LOGGER.debug("Device unavailable")
            return

        # do we need to (re-)subscribe?
        now = dt_util.utcnow()
        should_renew = (
            self._subscription_renew_time and now >= self._subscription_renew_time
        )
        if should_renew or not was_available and self._available:
            try:
                timeout = await self._device.async_subscribe_services()
                self._subscription_renew_time = dt_util.utcnow() + timeout / 2
            except (asyncio.TimeoutError, aiohttp.ClientError):
                self._available = False
                _LOGGER.debug("Could not (re)subscribe")

    def _on_event(
        self, service: UpnpService, state_variables: Sequence[UpnpStateVariable]
    ) -> None:
        """State variable(s) changed, let home-assistant know."""
        del service, state_variables  # Unused
        self.schedule_update_ha_state()

    async def _async_on_notify(self, device: UpnpDevice, changed: bool) -> None:
        """Device availability or configuration changed, let Home Assistant know."""
        del device, changed  # Unused
        await self.async_update_ha_state()

    # TODO: device()

    @property
    def supported_features(self):
        """Flag media player features that are supported."""
        supported_features = 0

        if self._device.has_volume_level:
            supported_features |= SUPPORT_VOLUME_SET
        if self._device.has_volume_mute:
            supported_features |= SUPPORT_VOLUME_MUTE
        if self._device.has_play:
            supported_features |= SUPPORT_PLAY
        if self._device.has_pause:
            supported_features |= SUPPORT_PAUSE
        if self._device.has_stop:
            supported_features |= SUPPORT_STOP
        if self._device.has_previous:
            supported_features |= SUPPORT_PREVIOUS_TRACK
        if self._device.has_next:
            supported_features |= SUPPORT_NEXT_TRACK
        if self._device.has_play_media:
            supported_features |= SUPPORT_PLAY_MEDIA
        if self._device.has_seek_rel_time:
            supported_features |= SUPPORT_SEEK

        return supported_features

    @property
    def volume_level(self):
        """Volume level of the media player (0..1)."""
        if self._device.has_volume_level:
            return self._device.volume_level
        return 0

    @catch_request_errors()
    async def async_set_volume_level(self, volume):
        """Set volume level, range 0..1."""
        await self._device.async_set_volume_level(volume)

    @property
    def is_volume_muted(self):
        """Boolean if volume is currently muted."""
        return self._device.is_volume_muted

    @catch_request_errors()
    async def async_mute_volume(self, mute):
        """Mute the volume."""
        desired_mute = bool(mute)
        await self._device.async_mute_volume(desired_mute)

    @catch_request_errors()
    async def async_media_pause(self):
        """Send pause command."""
        if not self._device.can_pause:
            _LOGGER.debug("Cannot do Pause")
            return

        await self._device.async_pause()

    @catch_request_errors()
    async def async_media_play(self):
        """Send play command."""
        if not self._device.can_play:
            _LOGGER.debug("Cannot do Play")
            return

        await self._device.async_play()

    @catch_request_errors()
    async def async_media_stop(self):
        """Send stop command."""
        if not self._device.can_stop:
            _LOGGER.debug("Cannot do Stop")
            return

        await self._device.async_stop()

    @catch_request_errors()
    async def async_media_seek(self, position):
        """Send seek command."""
        if not self._device.can_seek_rel_time:
            _LOGGER.debug("Cannot do Seek/rel_time")
            return

        time = timedelta(seconds=position)
        await self._device.async_seek_rel_time(time)

    @catch_request_errors()
    async def async_play_media(self, media_type, media_id, **kwargs):
        """Play a piece of media."""
        _LOGGER.debug("Playing media: %s, %s, %s", media_type, media_id, kwargs)
        title = "Home Assistant"

        # Stop current playing media
        if self._device.can_stop:
            await self.async_media_stop()

        # Queue media
        await self._device.async_set_transport_uri(media_id, title)
        await self._device.async_wait_for_can_play()

        # If already playing, no need to call Play
        if self._device.state == DeviceState.PLAYING:
            return

        # Play it
        await self.async_media_play()

    @catch_request_errors()
    async def async_media_previous_track(self):
        """Send previous track command."""
        if not self._device.can_previous:
            _LOGGER.debug("Cannot do Previous")
            return

        await self._device.async_previous()

    @catch_request_errors()
    async def async_media_next_track(self):
        """Send next track command."""
        if not self._device.can_next:
            _LOGGER.debug("Cannot do Next")
            return

        await self._device.async_next()

    @property
    def media_title(self):
        """Title of current playing media."""
        return self._device.media_title

    @property
    def media_image_url(self):
        """Image url of current playing media."""
        return self._device.media_image_url

    # TODO: Implement all properties & methods of base class, and entity (e.g. picture/icon)
    # See also https://developers.home-assistant.io/docs/core/entity/media-player

    @property
    def state(self):
        """State of the player."""
        if not self._available:
            return STATE_OFF

        if self._device.state is None:
            return STATE_ON
        if self._device.state == DeviceState.PLAYING:
            return STATE_PLAYING
        if self._device.state == DeviceState.PAUSED:
            return STATE_PAUSED

        return STATE_IDLE

    @property
    def media_duration(self):
        """Duration of current playing media in seconds."""
        return self._device.media_duration

    @property
    def media_position(self):
        """Position of current playing media in seconds."""
        return self._device.media_position

    @property
    def media_position_updated_at(self):
        """When was the position of the current playing media valid.

        Returns value from homeassistant.util.dt.utcnow().
        """
        return self._device.media_position_updated_at

    @property
    def name(self) -> str:
        """Return the name of the device."""
        if self._name:
            return self._name
        return self._device.name

    @property
    def unique_id(self) -> str:
        """Return an unique ID."""
        return self._device.udn

    @property
    def udn(self) -> str:
        """Get the UDN."""
        return self._device.udn

    @property
    def device_type(self) -> str:
        """Get the device type."""
        return self._device.device_type

    @property
    def usn(self) -> str:
        """Get the USN."""
        return f"{self.udn}::{self.device_type}"
