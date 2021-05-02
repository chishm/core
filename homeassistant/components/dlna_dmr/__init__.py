"""The dlna_dmr component."""
from __future__ import annotations

import asyncio
from ipaddress import IPv4Address, IPv6Address
from typing import cast, NamedTuple

import aiohttp
from async_upnp_client.aiohttp import AiohttpNotifyServer, AiohttpSessionRequester
from async_upnp_client.client import UpnpDevice, UpnpError, UpnpRequester
from async_upnp_client.client_factory import UpnpFactory
from async_upnp_client.device_updater import DeviceUpdater
from async_upnp_client.profiles.dlna import DmrDevice
from async_upnp_client.search import async_find_device

from homeassistant import config_entries
from homeassistant.components.media_player.const import DOMAIN as MEDIA_PLAYER_DOMAIN
from homeassistant.const import (
    CONF_DEVICE_ID,
    CONF_TYPE,
    CONF_UNIQUE_ID,
    CONF_URL,
)
from homeassistant.core import HomeAssistant, CALLBACK_TYPE
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_LISTEN_IP,
    CONF_LISTEN_PORT,
    CONF_CALLBACK_URL_OVERRIDE,
    DOMAIN,
    LOGGER,
)
from .media_player import DlnaDmrEntity

PLATFORMS = [MEDIA_PLAYER_DOMAIN]


class EventListenAddr(NamedTuple):
    """Unique identifier for an event listener"""

    ip: str | None
    port: int | None
    callback_url_override: str | None


class DomainData(NamedTuple):
    """Data stored by this integration under its Hass Domain"""

    lock: asyncio.Lock
    requester: UpnpRequester
    upnp_factory: UpnpFactory
    event_notifiers: dict[EventListenAddr, AiohttpNotifyServer]
    device_updaters: dict[IPv4Address | IPv6Address | None, DeviceUpdater]
    upnp_devices: dict[str, UpnpDevice]
    undo_update_listeners: dict[str, CALLBACK_TYPE]


async def _create_domain_data(hass: HomeAssistant) -> DomainData:
    """Create this integration's domain data if not already done"""
    if DOMAIN in hass.data:
        return hass.data[DOMAIN]

    session = aiohttp_client.async_get_clientsession(hass, verify_ssl=False)
    requester = AiohttpSessionRequester(session, with_sleep=False)
    upnp_factory = UpnpFactory(requester, non_strict=True)

    hass.data[DOMAIN] = DomainData(
        asyncio.Lock(), requester, upnp_factory, {}, {}, {}, {}
    )
    return hass.data[DOMAIN]


def get_domain_data(hass: HomeAssistant) -> DomainData:
    """Get existing domain data for this integration."""
    return cast(DomainData, hass.data[DOMAIN])


async def async_setup(hass: HomeAssistant, config: ConfigType):
    """Set up DLNA component."""
    LOGGER.debug("async_setup: config: %s", config)

    # Import data from configuration.yaml.
    if DOMAIN in config:
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_IMPORT}
            )
        )

    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: config_entries.ConfigEntry
) -> bool:
    """Set up a DLNA DMR device from a config entry"""
    LOGGER.debug("Setting up config entry: %s", entry.unique_id)

    domain_data = await _create_domain_data(hass)

    location = entry.data[CONF_URL]
    udn = entry.data[CONF_DEVICE_ID]
    listen_ip = entry.options.get(CONF_LISTEN_IP)

    try:
        # Create async_upnp_client device from last known location
        upnp_device = await domain_data.upnp_factory.async_create_device(location)
    except (asyncio.TimeoutError, aiohttp.ClientError, UpnpError):
        # Might have changed IP address, try to find it via discovery
        # TODO: This will delay startup by TIMEOUT seconds
        location = await async_find_device(udn, source_ip=listen_ip, loop=hass.loop)
        if not location:
            raise ConfigEntryNotReady
        try:
            upnp_device = await domain_data.upnp_factory.async_create_device(location)
        except (asyncio.TimeoutError, aiohttp.ClientError, UpnpError) as err:
            raise ConfigEntryNotReady from err
        # Update config data with new location
        updated_data = dict(entry.data)
        updated_data[CONF_URL] = location
        hass.config_entries.async_update_entry(entry, data=updated_data)

    # Store the UPnP device connection for the platform entity to use later
    domain_data.upnp_devices[entry.entry_id] = upnp_device

    undo_listener = entry.add_update_listener(_update_listener)
    domain_data.undo_update_listeners[entry.entry_id] = undo_listener

    # Forward setup to the appropriate platform
    hass.config_entries.async_setup_platforms(entry, PLATFORMS)

    return True


async def async_unload_entry(
    hass: HomeAssistant, config_entry: config_entries.ConfigEntry
) -> bool:
    """Unload a config entry."""
    domain_data = get_domain_data(hass)

    unload_ok = await hass.config_entries.async_unload_platforms(
        config_entry, PLATFORMS
    )

    undo_listener = domain_data.undo_update_listeners.pop(config_entry.entry_id)
    undo_listener()

    domain_data.upnp_devices.pop(config_entry.entry_id)

    return unload_ok


async def _update_listener(
    hass: HomeAssistant, config_entry: config_entries.ConfigEntry
) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(config_entry.entry_id)
