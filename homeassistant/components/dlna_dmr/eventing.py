"""UPnP event handlers and device update listeners."""
from __future__ import annotations

from ipaddress import IPv4Address, IPv6Address

from async_upnp_client import UpnpEventHandler
from async_upnp_client.aiohttp import AiohttpNotifyServer
from async_upnp_client.device_updater import DeviceUpdater

from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant

from . import get_domain_data, EventListenAddr
from .const import LOGGER
from .exceptions import EventingError


async def async_get_or_create_event_notifier(
    hass: HomeAssistant,
    listen_ip: str | None = None,
    listen_port: int | None = None,
    callback_url_override: str | None = None,
) -> UpnpEventHandler:
    """Return existing event notifier on the given IP and port, or create one.

    Only one event notify server is kept for each local_ip/port/callback_url
    combination.
    """
    LOGGER.debug(
        "Getting event handler for %s:%s (%s)",
        listen_ip,
        listen_port,
        callback_url_override,
    )

    event_notifiers = get_domain_data(hass).event_notifiers
    data_lock = get_domain_data(hass).lock
    listen_addr = EventListenAddr(listen_ip, listen_port, callback_url_override)

    with data_lock:
        try:
            # Return an existing event handler if we can
            server = event_notifiers[listen_addr]
        except KeyError:
            # No existing event handler? It will be created below
            pass
        else:
            return server.event_handler

        # Start event handler
        server = AiohttpNotifyServer(
            requester=get_domain_data(hass).requester,
            listen_port=listen_port or 0,
            listen_host=listen_ip,
            callback_url=callback_url_override,
            loop=hass.loop,
        )
        await server.start_server()
        LOGGER.debug("Started event handler at %s", server.callback_url)

        # Store the server for other network devices connecting to the same interface
        event_notifiers[listen_addr] = server

    # Register for graceful shutdown
    async def async_stop_server(event):
        """Stop server."""
        del event  # unused
        LOGGER.debug("Stopping UPNP/DLNA event handler")
        with data_lock:
            try:
                del event_notifiers[listen_addr]
            except KeyError as err:
                LOGGER.debug("async_stop_server del event_notifier error: %s", err)
        await server.stop_server()

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, async_stop_server)

    return server.event_handler


async def async_get_or_create_device_updater(
    hass: HomeAssistant,
    listen_ip: IPv4Address | IPv6Address | None = None,
) -> DeviceUpdater:
    """Return existing device updater on the given IP, or create one.

    Only one existing device updater server is kept for each listen_host.
    """
    LOGGER.debug("Getting device updater for %s", listen_ip)

    device_updaters = get_domain_data(hass).device_updaters
    data_lock = get_domain_data(hass).lock

    with data_lock:
        # Return an existing updater if possible
        try:
            return device_updaters[listen_ip]
        except KeyError:
            pass

        # Create device updater
        updater = DeviceUpdater(
            device=None,
            factory=get_domain_data(hass).upnp_factory,
            source_ip=listen_ip,
        )
        await updater.async_start()

        # Store the updater for other devices connected on the same network interface
        device_updaters[listen_ip] = updater

    # Register for graceful shutdown
    async def async_stop_server(event):
        """Stop server."""
        del event  # unused
        LOGGER.debug("Stopping UPNP/DLNA device updater")
        with data_lock:
            try:
                del device_updaters[listen_ip]
            except KeyError as err:
                LOGGER.debug("async_stop_server del device_updater error: %s", err)
        await updater.async_stop()

    return updater
