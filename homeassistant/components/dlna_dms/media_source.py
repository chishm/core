from __future__ import annotations

from collections.abc import Iterable, Mapping

from async_upnp_client.client import UpnpError
from async_upnp_client.profiles.dlna import DmsDevice
from didl_lite import didl_lite

from homeassistant.components.media_player.const import MEDIA_CLASS_DIRECTORY
from homeassistant.components.media_player.errors import BrowseError
from homeassistant.components.media_source.const import MEDIA_MIME_TYPES
from homeassistant.components.media_source.error import Unresolvable
from homeassistant.components.media_source.models import (
    BrowseMediaSource,
    MediaSource,
    MediaSourceItem,
    PlayMedia,
)
from homeassistant.core import HomeAssistant, callback

from .const import (
    ACTION_OBJECT,
    ACTION_PATH,
    ACTION_SEARCH,
    BY_NAME,
    DLNA_BROWSE_FILTER,
    DLNA_PATH_FILTER,
    DLNA_RESOLVE_FILTER,
    DOMAIN,
    LOGGER,
    MEDIA_CLASS_MAP,
    MEDIA_TYPE_MAP,
    PATH_SEP,
    ROOT_OBJECT_ID
)


async def async_get_media_source(hass: HomeAssistant):
    """Set up DLNA DMS media source."""
    LOGGER.debug("Setting up DLNA media sources")
    sources = hass.data[DOMAIN][BY_NAME]
    return DlnaDmsSource(sources)


# TODO: Use this, but with more things too
DLNA_SORT_CRITERIA = ["+upnp:class", "+upnp:originalTrackNumber", "+dc:title"]


class DlnaDmsSource(MediaSource):
    """Provide contents of all known DLNA DMS devices as media sources.

    Media identifiers are formatted as:
    `media-source://dlna_dms/<server_id>/<action>/<parameters>`
    `server_id` is the entity_id of the server to browse/play. It may be left
    blank to specify all servers for `search`, or the (arbitrarily) first
    server for "path" or "object" actions.
    `action` can be one of `object`, `path`, or `search`:
        `object`: Browse/resolve an object from its server-assigned ObjectID.
        `path`: Treat `parameters` like a directory path.
        `search`: Search with `parameters` as the criteria string. See
        [DLNA ContentDirectory SearchCriteria](http://www.upnp.org/specs/av/UPnP-av-ContentDirectory-v1-Service.pdf#%5B%7B%22num%22%3A271%2C%22gen%22%3A0%7D%2C%7B%22name%22%3A%22XYZ%22%7D%2C0%2C431%2Cnull%5D)
        for the syntax.
    """

    name: str = "DLNA Server"
    sources: Mapping[str, DmsDevice]

    def __init__(self, sources: Mapping[str, DmsDevice]) -> None:
        """Initialize DLNA DMS Source

        :param sources: Map of server name to device.
        """
        super().__init__(DOMAIN)
        self.sources = sources

    async def async_resolve_media(self, item: MediaSourceItem) -> PlayMedia:
        """Resolve a media item to a playable item."""
        LOGGER.debug("resolve identifier=%s", item.identifier)
        if not self.sources:
            raise Unresolvable("No servers available")

        server_id, action, parameters = async_parse_identifier(item)

        if not server_id:
            # No server specified, default to the first registered
            server_id = next(iter(self.sources))

        try:
            device = self.sources[server_id]
        except KeyError as err:
            raise Unresolvable("Unknown server") from err

        if action == ACTION_SEARCH:
            return await self._async_resolve_search(device, parameters)

        if action == ACTION_OBJECT:
            return await self._async_resolve_object(device, parameters)

        if action == ACTION_PATH:
            object_id = await self._async_resolve_path(device, parameters)
            return await self._async_resolve_object(device, object_id)

        raise Unresolvable(f"Invalid identifier {item.identifier}")

    async def async_browse_media(
        self, item: MediaSourceItem, media_types: tuple[str] = MEDIA_MIME_TYPES
    ) -> BrowseMediaSource:
        """Browse media."""
        LOGGER.debug("browse identifier=%s media_types=%r", item.identifier, media_types)
        if not self.sources:
            raise BrowseError("No servers available")

        server_id, action, parameters = async_parse_identifier(item)

        if not server_id and not action and len(self.sources) > 1:
            # Browsing the root of dlna_dms with more than one server, return
            # all known servers.
            base = BrowseMediaSource(
                domain=DOMAIN,
                identifier="",
                media_class=MEDIA_CLASS_DIRECTORY,
                media_content_type=None,
                title=self.name,
                can_play=False,
                can_expand=True,
                children_media_class=MEDIA_CLASS_DIRECTORY,
            )

            base.children = [
                BrowseMediaSource(
                    domain=DOMAIN,
                    identifier=f"{server_id}/object/{ROOT_OBJECT_ID}",
                    media_class=MEDIA_CLASS_DIRECTORY,
                    media_content_type=None,
                    title=device.name,
                    can_play=False,
                    can_expand=True,
                    children_media_class=MEDIA_CLASS_DIRECTORY,
                    thumbnail=device.icon,
                )
                for server_id, device in self.sources
            ]

        if action == ACTION_SEARCH:
            return await self._async_browse_search(server_id, parameters)

        if not server_id:
            # No server specified, default to the first registered
            server_id = next(iter(self.sources))

        if server_id not in self.sources:
            raise BrowseError("Unknown server")

        if not action:
            # Browsing the root of the server
            media_source = await self._async_browse_object(server_id, ROOT_OBJECT_ID)
            # Change title to the server_id, instead of "root"
            media_source.title = server_id
            return media_source

        if action == ACTION_OBJECT:
            return await self._async_browse_object(server_id, parameters)

        if action == ACTION_PATH:
            object_id = await self._async_resolve_path(
                self.sources[server_id], parameters
            )
            return await self._async_browse_object(server_id, object_id)

        raise BrowseError(f"Invalid identifier {item.identifier}")

    async def _async_resolve_object(self, device: DmsDevice, object_id: str) -> PlayMedia:
        """Return a URL to a DLNA object specified by ObjectID"""
        LOGGER.debug("Resolve object %s on device %s", object_id, device.name)
        try:
            item = await device.async_browse_metadata(
                object_id, metadata_filter=DLNA_RESOLVE_FILTER
            )
        except UpnpError as err:
            LOGGER.debug(f"Invalid object or server: %s", err)
            raise Unresolvable(f"Invalid object or server: {err}") from err

        # Use the first available resource
        try:
            resource = item.res[0]
        except IndexError as err:
            LOGGER.debug(f"Object has no resources")
            raise Unresolvable("Object has no resources") from err

        mime_type = _resource_mime_type(resource)

        if not resource.uri or not mime_type:
            LOGGER.debug(f"Object resource has no URI or MIME type")
            raise Unresolvable("Object resource has no URI or MIME type")

        url = device.get_absolute_url(resource.uri)

        LOGGER.debug(f"Resolved to url %s MIME %s", url, mime_type)

        return PlayMedia(url, mime_type)

    async def _async_resolve_path(self, device: DmsDevice, path: str) -> str:
        """Return an Object ID resolved from a path string"""
        # Iterate through the path, searching for a matching title within the
        # DLNA object hierarchy.
        object_id = ROOT_OBJECT_ID
        for node in path.split(PATH_SEP):
            criteria = f"@parentID=\"{object_id}\" and dc:title=\"{node}\""
            try:
                items = await device.async_search_directory(
                    object_id,
                    search_criteria=criteria,
                    metadata_filter=DLNA_BROWSE_FILTER
                )
            except UpnpError as err:
                raise Unresolvable(f"Path search failed: {err}") from err
            if not items:
                raise Unresolvable(f"Nothing found for {node} in {path}")
            if len(items) > 1:
                raise Unresolvable(f"Too many items found for {node} in {path}")
            object_id = items[0].id
        return object_id

    async def _async_browse_object(self, server_id: str, object_id: str) -> BrowseMediaSource:
        """Return the contents of a DLNA container by ObjectID"""
        device = self.sources[server_id]

        try:
            base_object = await device.async_browse_metadata(
                object_id,
                metadata_filter=DLNA_BROWSE_FILTER
            )
            child_objects = await device.async_browse_direct_children(
                object_id,
                metadata_filter=DLNA_BROWSE_FILTER,
                sort_criteria=DLNA_SORT_CRITERIA
            )
        except UpnpError as err:
            raise BrowseError(f"Invalid object or server: {err}") from err

        return self._didl_to_media_source(server_id, base_object, child_objects)

    def _didl_to_media_source(
            self,
            server_id: str,
            item: didl_lite.DidlObject,
            children: Iterable[didl_lite.DidlObject] | None = None
        ) -> BrowseMediaSource:
        """Convert a DIDL-Lite object to a browse media source."""
        if children:
            children = [
                self._didl_to_media_source(server_id, child)
                for child in children
            ]
        else:
            # Explicit None in case async_browse_direct_children returned an empty list
            children = None

        # Can expand if it has children, even if we don't have them yet
        try:
            child_count = int(item.child_count)
        except (AttributeError, ValueError):
            child_count = 0
        can_expand = bool(children) or child_count > 0

        media_source = BrowseMediaSource(
            domain=DOMAIN,
            identifier=f"{server_id}/object/{item.id}",
            media_class=MEDIA_CLASS_MAP[type(item)],
            # TODO: Use resource mime type. This should be mime_type or ""
            media_content_type=MEDIA_TYPE_MAP[item.upnp_class],
            title=item.title,
            # Can play if it has any resources
            can_play=bool(item.res),
            can_expand=can_expand,
            children=children,
            thumbnail=self._didl_image_url(server_id, item),
        )

        media_source.calculate_children_class()

        # TODO: Remove most LOGGER messages
        LOGGER.debug("didl result: %r", media_source.as_dict())

        return media_source

    def _didl_image_url(
            self, server_id: str, item: didl_lite.DidlObject
        ) -> str | None:
        """Image URL for a DIDL-Lite object"""
        # Based on DmrDevice.media_image_url from async_upnp_client.

        device = self.sources[server_id]

        # Some objects have the thumbnail in albumArtURI, others in a resource
        if hasattr(item, "album_art_uri"):
            return device.get_absolute_url(item.album_art_uri)

        for resource in item.res:
            if resource.protocol_info.startswith("http-get:*:image/"):
                return device.get_absolute_url(resource.uri)

        return None

@callback
def async_parse_identifier(item: MediaSourceItem) -> tuple[str, str, str]:
    """Parse a media identifer according to the scheme described above."""
    if not item.identifier:
        # Empty server, action, and parameters
        return "", "", ""

    parts = item.identifier.split("/", 2)
    if len(parts) == 1:
        # Server specified, nothing else
        return parts[0], "", ""
    if len(parts) == 2:
        # Action specified but not parameters
        raise BrowseError("Invalid parameters")

    server_id, action, parameters = parts
    if action not in (ACTION_OBJECT, ACTION_PATH, ACTION_SEARCH):
        raise BrowseError("Invalid action")

    return server_id, action, parameters

def _resource_mime_type(resource: didl_lite.Resource) -> str | None:
    try:
        return resource.protocol_info.split(":")[2]
    except (AttributeError, IndexError):
        return None
