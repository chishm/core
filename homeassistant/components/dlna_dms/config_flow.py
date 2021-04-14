"""Config flow for DLNA MediaServer."""
from __future__ import annotations

import asyncio
from pprint import pformat
from typing import Any
from urllib.parse import urlparse

import aiohttp
from async_upnp_client.const import NS as XML_NAMESPACES
from async_upnp_client.profiles.dlna import DmsDevice
from defusedxml import ElementTree
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import ssdp
from homeassistant.const import CONF_URL
from homeassistant.data_entry_flow import FlowResultDict

from .const import DOMAIN, LOGGER


class DlnaDmsFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a DLNA Digital Media Server config flow."""
    
    VERSION = 1
    
    def __init__(self):
        """Initialize the DMS config flow."""
        self.location = None # URL of the device root description
        self.usn = None # Unique Service Name, will be the unique_id
        self.dms_devices = []
    
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResultDict:
        """Handle a flow initialized by the user.
        
        Let user enter manual configuration, and provide option for discovery.
        """
        errors = {}
        if user_input is not None:
            # Check if device description URL is set manually
            url = user_input.get(CONF_URL)
            if url:
                self.location = url
                # USN will be figured out after connecting
                self.usn = None
                return await self.async_step_connect()
            
            # Discover devices if user didn't enter a host
            self.dms_devices = await async_discover()
            
            if len(self.dms_devices) == 1:
                # Exactly one device discovered, just use it
                self.location = self.dms_devices[0].get(ssdp.ATTR_SSDP_LOCATION)
                self.usn = self.dms_devices[0].get(ssdp.ATTR_SSDP_USN)
                return await self.async_step_connect()
            
            if len(self.dms_devices) > 1:
                # Multiple devices found, show select form
                return await self.async_step_select()
            
            # No devices discovered. Inform user and show manual entry form again.
            errors["base"] = "discovery_error"

        data_schema = vol.Schema({vol.Optional(CONF_URL): str})
        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )

    async def async_step_select(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResultDict:
        """Handle multiple Media Servers found."""
        if user_input is not None:
            self.location = user_input["select_url"]
            return await self.async_step_connect()

        device_urls = [
            device[ssdp.ATTR_SSDP_LOCATION]
            for device in self.dms_devices
            if ssdp.ATTR_SSDP_LOCATION in device
        ]
        data_schema = vol.Schema({vol.Required("select_url"): vol.In(device_urls)})
        return self.async_show_form(step_id="select", data_schema=data_schema)

    async def async_step_connect(self) -> FlowResultDict:
        """Connect to the Media Server to confirm it works and set USN if needed"""
        # Retrieve device description and convert it to something useful
        session = self.hass.helpers.aiohttp_client.async_get_clientsession()
        try:
            resp = await session.get(self.location, timeout=5)
            xml = await resp.text(errors="replace")
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            LOGGER.debug("Error fetching %s: %s", self.location, err)
            return self.async_abort(reason="cannot_connect")

        try:
            tree = ElementTree.fromstring(xml)
        except ElementTree.ParseError as err:
            LOGGER.debug("Error parsing %s: %s", self.location, err)
            return self.async_abort(reason="bad_description_xml")

        # Determine final USN from device description
        udn = tree.findtext(".//device:UDN", namespaces=XML_NAMESPACES)
        device_type = tree.findtext(".//device:deviceType", namespaces=XML_NAMESPACES)
        
        if not udn or not device_type:
            LOGGER.debug("Error extracting UDN or deviceType from %s", xml)
            return self.async_abort(reason="bad_description_xml")
            
        self.usn = construct_usn(udn, device_type)
        await self.async_set_unique_id(self.usn)
        self._abort_if_unique_id_configured()
 
        # Create the device entry
        parsed_url = urlparse(self.location)
        friendly_name = tree.findtext(".//device:friendlyName", namespaces=XML_NAMESPACES)
        title = friendly_name or parsed_url.hostname
 
        return self.async_create_entry(
            title=title,
            data={
                CONF_URL: self.location
            }
        )
        
    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResultDict:
        """Allow the user to confirm adding the device."""
        if user_input is not None:
            return await self.async_step_connect()

        self._set_confirm_only()
        return self.async_show_form(step_id="confirm")

    async def async_step_ssdp(self, discovery_info: dict[str, Any]) -> FlowResultDict:
        """Handle a DMS device discovered by SSDP."""
        LOGGER.debug("DLNA DMS SSDP discovery %s", pformat(discovery_info))
        
        self.location = discovery_info[ssdp.ATTR_SSDP_LOCATION]
        self.usn = discovery_info[ssdp.ATTR_SSDP_USN]

        await self.async_set_unique_id(self.usn)
        self._abort_if_unique_id_configured(updates={CONF_URL: self.location})

        name = discovery_info.get(ssdp.ATTR_UPNP_FRIENDLY_NAME, self.location)
        self.context["title_placeholders"] = {"name": name}
        
        return await self.async_step_confirm()
    
    async def async_step_unignore(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResultDict:
        unique_id = user_input["unique_id"]
        await self.async_set_unique_id(unique_id)
    
        self.dms_devices = await async_discover()
        
        for device in self.dms_devices:
            if device[ssdp.ATTR_SSDP_USN] == unique_id:
                self.location = device[ssdp.ATTR_SSDP_LOCATION]
                self.usn = device[ssdp.ATTR_SSDP_USN]
                break
        else:
            return self.async_abort(reason="no_devices_found")
    
        return await self.async_step_confirm()
    
def construct_usn(udn: str, device_type: str) -> str:
    """Construct a unique service name from a unique device name and device type."""
    return f"{udn}::{device_type}"

async def async_discover() -> list[dict[str, str]]:
    discoveries = await DmsDevice.async_search()
    
    # Convert field names to match Hass's ssdp discovery
    return [
        {
            ssdp.ATTR_SSDP_LOCATION: discovery["location"],
            ssdp.ATTR_SSDP_USN: discovery["usn"],
        }
        for discovery in discoveries
    ]
