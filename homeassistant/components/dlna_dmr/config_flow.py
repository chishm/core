"""Config flow for DLNA DMR."""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import ipaddress
from pprint import pformat
from typing import Any, Optional
from urllib.parse import urlparse

from aiohttp import ClientError
from async_upnp_client.client import UpnpError
from async_upnp_client.profiles.dlna import DmrDevice
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import ssdp
from homeassistant.const import (
    CONF_DEVICE_ID,
    CONF_TYPE,
    CONF_UNIQUE_ID,
    CONF_URL,
)
from homeassistant.core import callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.data_entry_flow import FlowResult
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import DiscoveryInfoType

from . import get_domain_data
from .const import (
    CONF_CALLBACK_URL_OVERRIDE,
    CONF_LISTEN_IP,
    CONF_LISTEN_PORT,
    DOMAIN,
    LOGGER,
)


FlowInput = Optional[Mapping[str, Any]]


class DlnaDmrFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a DLNA DMR config flow."""

    VERSION = 1

    def __init__(self):
        """Initialize flow."""
        self._discoveries: Sequence[Mapping[str, Any]] = []
        self._listen_ip = None
        self._listen_port = None
        self._callback_url_override = None

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Define the config flow to handle options."""
        return DlnaDmrOptionsFlowHandler(config_entry)

    async def async_step_user(self, user_input: FlowInput = None) -> FlowResult:
        """Handle a flow initialized by the user.

        Scan for devices, then let the user choose.
        """
        LOGGER.debug("async_step_user: user_input: %s", user_input)

        errors = {}
        if user_input is not None:
            # Check if device description URL is set manually
            url = user_input.get(CONF_URL)
            if url:
                try:
                    discovery = await self._async_connect(url)
                except ConfigEntryNotReady as err:
                    errors["base"] = str(err)
                return await self._async_create_entry_from_discovery(discovery)
            else:
                # Discover devices if user didn't enter a host
                await self._async_discover()

                if len(self._discoveries) == 1:
                    # Exactly one device discovered, just use it
                    return await self._async_create_entry_from_discovery(
                        self._discoveries[0]
                    )

                if len(self._discoveries) > 1:
                    # Multiple devices found, show select form
                    return await self.async_step_select()

                # No devices discovered. Inform user and show manual entry form again.
                errors["base"] = "discovery_error"

        data_schema = vol.Schema({vol.Optional(CONF_URL): str})
        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )

    async def async_step_select(self, user_input: FlowInput = None) -> FlowResult:
        """Handle multiple discoveries found."""
        errors = {}
        if user_input is not None:
            # Get the discovery that matches the location URL
            for discovery in self._discoveries:
                if user_input[CONF_URL] == discovery[ssdp.ATTR_SSDP_LOCATION]:
                    return await self._async_create_entry_from_discovery(discovery)
            errors["base"] = "discovery_error"

        device_urls = [
            device[ssdp.ATTR_SSDP_LOCATION]
            for device in self._discoveries
            if ssdp.ATTR_SSDP_LOCATION in device
        ]
        data_schema = vol.Schema({vol.Required(CONF_URL): vol.In(device_urls)})
        return self.async_show_form(step_id="select", data_schema=data_schema)

    async def async_step_import(self, import_data: FlowInput = None) -> FlowResult:
        """Import a new DLNA DMR device from a config entry.

        This flow is triggered by `async_setup`. If no device has been
        configured before, find any device and create a config_entry for it.
        Otherwise, do nothing.
        """
        LOGGER.debug("async_step_import: import_data: %s", import_data)

        if self._async_current_entries():
            LOGGER.debug("Already configured, aborting")
            return self.async_abort(reason="already_configured")

        if not import_data:
            return self.async_abort(reason="incomplete_config")

        # Set options from the import_data
        self._listen_ip = import_data.get(CONF_LISTEN_IP)
        self._listen_port = import_data.get(CONF_LISTEN_PORT)
        self._callback_url_override = import_data.get(CONF_CALLBACK_URL_OVERRIDE)

        try:
            url = import_data[CONF_URL]
        except KeyError:
            return self.async_abort(reason="incomplete_config")

        try:
            discovery = await self._async_connect(url)
        except ConfigEntryNotReady as err:
            return self.async_abort(reason=str(err))

        return await self._async_create_entry_from_discovery(discovery)

    async def async_step_ssdp(self, discovery_info: DiscoveryInfoType) -> FlowResult:
        """Handle a flow initialized by SSDP discovery."""
        LOGGER.debug("async_step_ssdp: discovery_info %s", pformat(discovery_info))

        self._discoveries = [discovery_info]

        usn = discovery_info[ssdp.ATTR_SSDP_USN]
        location = discovery_info[ssdp.ATTR_SSDP_LOCATION]

        # Abort if already configured, but update the last-known location
        await self.async_set_unique_id(usn)
        self._abort_if_unique_id_configured(updates={CONF_URL: location})

        name = discovery_info.get(ssdp.ATTR_UPNP_FRIENDLY_NAME, location)
        self.context["title_placeholders"] = {"name": name}

        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: FlowInput = None) -> FlowResult:
        """Allow the user to confirm adding the device."""
        LOGGER.debug("async_step_confirm: %s", user_input)
        if user_input is not None:
            return await self._async_create_entry_from_discovery(self._discoveries[0])

        self._set_confirm_only()
        return self.async_show_form(step_id="confirm")

    async def async_step_unignore(self, user_input: Mapping[str, Any]) -> FlowResult:
        """Rediscover previously ignored devices."""
        unique_id = user_input["unique_id"]
        LOGGER.debug("async_step_unignore: user_input: %s", user_input)
        await self.async_set_unique_id(unique_id)

        await self._async_discover()

        # Filter discoveries for one matching the unignored unique_id
        self._discoveries = [
            device
            for device in self._discoveries
            if device[ssdp.ATTR_SSDP_USN] == unique_id
        ]

        if not self._discoveries:
            return self.async_abort(reason="discovery_error")

        if len(self._discoveries) > 1:
            # Multiple devices with the same unique_id should not happen
            return self.async_abort(reason="non_unique_id")

        # Supplement discovery to get a name for the device
        location = self._discoveries[0][ssdp.ATTR_SSDP_LOCATION]
        discovery = await self._async_connect(location)
        self._discoveries = [discovery]
        name = discovery.get(ssdp.ATTR_UPNP_FRIENDLY_NAME, location)
        self.context["title_placeholders"] = {"name": name}

        return await self.async_step_confirm()

    async def _async_create_entry_from_discovery(
        self, discovery: Mapping[str, Any]
    ) -> FlowResult:
        """Create an entry from discovery."""
        LOGGER.debug("_async_create_entry_from_discovery: discovery: %s", discovery)

        location = discovery[ssdp.ATTR_SSDP_LOCATION]
        usn = discovery[ssdp.ATTR_SSDP_USN]

        # Abort if already configured, but update the last-known location
        await self.async_set_unique_id(usn)
        self._abort_if_unique_id_configured(updates={CONF_URL: location})

        # If the discovery does not have the device description, connect and get it
        if (
            ssdp.ATTR_UPNP_FRIENDLY_NAME not in discovery
            or ssdp.ATTR_UPNP_UDN not in discovery
        ):
            discovery = await self._async_connect(location)

        parsed_url = urlparse(location)
        title = discovery.get(ssdp.ATTR_UPNP_FRIENDLY_NAME) or parsed_url.hostname

        data = {
            CONF_URL: discovery[ssdp.ATTR_SSDP_LOCATION],
            CONF_UNIQUE_ID: discovery[ssdp.ATTR_SSDP_USN],
            CONF_DEVICE_ID: discovery[ssdp.ATTR_UPNP_UDN],
            CONF_TYPE: discovery[ssdp.ATTR_SSDP_ST],
        }
        return self.async_create_entry(title=title, data=data)

    async def _async_discover(self) -> None:
        """Discover DLNA DMR devices via an SSDP search."""
        LOGGER.debug("_async_discover")

        found_devices = await DmrDevice.async_search()

        current_unique_ids = {
            entry.unique_id for entry in self._async_current_entries()
        }

        discoveries = []
        for device in found_devices:
            # Filter out devices already configured
            if device["usn"] in current_unique_ids:
                continue

            # Standardize discovery to match ssdp component's
            discovery = {
                ssdp.ATTR_SSDP_LOCATION: device["location"],
                ssdp.ATTR_SSDP_ST: device["st"],
                ssdp.ATTR_SSDP_USN: device["usn"],
                ssdp.ATTR_UPNP_UDN: device["_udn"],
            }
            LOGGER.debug("Discovered device: %s", discovery)
            discoveries.append(discovery)

        self._discoveries = discoveries

    async def _async_connect(self, location: str) -> dict[str, str]:
        """Connect to a device to confirm it works and get discovery information.

        Raises ConfigEntryNotReady if something goes wrong.
        """
        domain_data = get_domain_data(self.hass)
        try:
            device = await domain_data.upnp_factory.async_create_device(location)
        except (ClientError, UpnpError) as err:
            raise ConfigEntryNotReady("could_not_connect") from err

        if device.device_type not in DmrDevice.DEVICE_TYPES:
            raise ConfigEntryNotReady("not_dmr")

        discovery = {
            ssdp.ATTR_SSDP_LOCATION: location,
            ssdp.ATTR_SSDP_ST: device.device_type,
            ssdp.ATTR_SSDP_USN: f"{device.udn}::{device.device_type}",
            ssdp.ATTR_UPNP_UDN: device.udn,
            ssdp.ATTR_UPNP_FRIENDLY_NAME: device.name,
        }

        return discovery


class DlnaDmrOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle a DLNA DMR options flow.

    Configures the single instance and updates the existing config entry.
    """

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}
        options = self.config_entry.options

        if user_input is not None:
            listen_ip = user_input.get(CONF_LISTEN_IP) or None
            listen_port = user_input.get(CONF_LISTEN_PORT) or None
            callback_url_override = user_input.get(CONF_CALLBACK_URL_OVERRIDE) or None

            # Update existing options and save
            updated_options = dict(options)
            updated_options[CONF_LISTEN_IP] = listen_ip
            updated_options[CONF_LISTEN_PORT] = listen_port
            updated_options[CONF_CALLBACK_URL_OVERRIDE] = callback_url_override

            return self.async_create_entry(title="", data=updated_options)

        fields = {}

        def _add_with_suggestion(key: str, validator: Callable) -> None:
            """Add a field to with a suggested, not default, value."""
            suggested_value = options.get(key)
            if suggested_value is None:
                suggested_value = ""
            fields[
                vol.Optional(key, description={"suggested_value": suggested_value})
            ] = validator

        _add_with_suggestion(
            CONF_LISTEN_IP,
            vol.Any(
                vol.Coerce(ipaddress.IPv4Address),
                vol.Coerce(ipaddress.IPv6Address),
                vol.Equal(""),
            ),
        )
        #        _add_with_suggestion(CONF_LISTEN_PORT, vol.Any(cv.port, vol.Equal("")))
        _add_with_suggestion(CONF_LISTEN_PORT, cv.port)
        _add_with_suggestion(CONF_CALLBACK_URL_OVERRIDE, cv.url)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(fields),
            errors=errors,
        )
