"""The DLNA MediaServer integration."""
from __future__ import annotations

import asyncio
from urllib.parse import urlparse

import aiohttp
from async_upnp_client import UpnpFactory
from async_upnp_client.aiohttp import AiohttpNotifyServer, AiohttpSessionRequester
from async_upnp_client.profiles.dlna import DeviceState
from async_upnp_client.profiles.dlna import DmsDevice

from homeassistant.components.media_source.const import DOMAIN as MEDIA_SOURCE_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import BY_NAME, DOMAIN, LOGGER


# TODO: "quality_scale": "silver" in manifest.json
# SEE https://developers.home-assistant.io/docs/integration_fetching_data/
# TODO: Subscribe in async_added_to_hass in the hass entity
# TODO: self.async_write_ha_state after first connect

# TODO: Use UPnP (in SSDP?) advertisements for device alive. Use BOOTID.UPNP.ORG
# to check if device rebooted and event subscriptions cancelled

async def async_construct_device(hass: HomeAssistant, location: str) -> DmsDevice:
    """Construct a DmsDevice from a description XML URL."""
    # Build UPnP requester
    session = hass.helpers.aiohttp_client.async_get_clientsession()
    requester = AiohttpSessionRequester(session)

    # TODO: Use last known location, but if that fails then try SSDP search for
    # the USN and try agian. Make sure this doesn't collide with config-flow
    # discoveries.

    # Create UPnP device
    factory = UpnpFactory(requester, disable_state_variable_validation=True)
    try:
        upnp_device = await factory.async_create_device(location)
    except (asyncio.TimeoutError, aiohttp.ClientError) as err:
        raise ConfigEntryNotReady from err

    # Wrap with DmsDevice
    dms_device = DmsDevice(upnp_device, None)

    # Update the device properties, for search and sort capabilities
    await dms_device.async_update()

    return dms_device


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up DLNA MediaServer from a config entry."""
    hass.data.setdefault(DOMAIN, {BY_NAME: {}})

    LOGGER.debug("Setting up config entry: %s", entry.unique_id)

    dms_device = await async_construct_device(hass, entry.data[CONF_URL])
    hass.data[DOMAIN][entry.unique_id] = dms_device
    hass.data[DOMAIN][BY_NAME][device_name(dms_device)] = dms_device

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    dms_device = hass.data[DOMAIN].pop(entry.unique_id)
    del hass.data[DOMAIN][BY_NAME][device_name(dms_device)]

    return True

def device_name(device: DmsDevice) -> str:
    """Return a name for the device, either friendly name or host name"""
    parsed_url = urlparse(device.device.device_url)
    return device.name or parsed_url.hostname
