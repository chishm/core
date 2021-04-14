"""Constants for the DLNA MediaServer integration."""
import logging

from didl_lite import didl_lite
from homeassistant.components.media_player import const as _mp_const

LOGGER = logging.getLogger(__package__)

DOMAIN = "dlna_dms"
BY_NAME = "by_name"
ROOT_OBJECT_ID = "0"
ACTION_OBJECT = "object"
ACTION_PATH = "path"
ACTION_SEARCH = "search"
PATH_SEP = "/"
# Only request the metadata needed to build a browse/resolve response
DLNA_BROWSE_FILTER = [
    "id", "upnp:class", "dc:title", "res", "@childCount", "upnp:albumArtURI"
]
DLNA_RESOLVE_FILTER = ["id", "upnp:class", "res"]
# Metadata needed to resolve a path
DLNA_PATH_FILTER = ["id", "upnp:class", "dc:title"]

# Map DIDL-Lite type to media_player class
# TODO: Use upnp class as below, delete MEDIA_TYPE_MAP
MEDIA_CLASS_MAP = {
    didl_lite.DidlObject: _mp_const.MEDIA_CLASS_URL,
    didl_lite.Item: _mp_const.MEDIA_CLASS_URL,
    didl_lite.ImageItem: _mp_const.MEDIA_CLASS_IMAGE,
    didl_lite.Photo: _mp_const.MEDIA_CLASS_IMAGE,
    didl_lite.AudioItem: _mp_const.MEDIA_CLASS_MUSIC,
    didl_lite.MusicTrack: _mp_const.MEDIA_CLASS_MUSIC,
    didl_lite.AudioBroadcast: _mp_const.MEDIA_CLASS_MUSIC,
    didl_lite.AudioBook: _mp_const.MEDIA_CLASS_PODCAST,
    didl_lite.VideoItem: _mp_const.MEDIA_CLASS_VIDEO,
    didl_lite.Movie: _mp_const.MEDIA_CLASS_MOVIE,
    didl_lite.VideoBroadcast: _mp_const.MEDIA_CLASS_TV_SHOW,
    didl_lite.MusicVideoClip: _mp_const.MEDIA_CLASS_VIDEO,
    didl_lite.PlaylistItem: _mp_const.MEDIA_CLASS_TRACK,
    didl_lite.TextItem: _mp_const.MEDIA_CLASS_URL,
    didl_lite.BookmarkItem: _mp_const.MEDIA_CLASS_URL,
    didl_lite.EpgItem: _mp_const.MEDIA_CLASS_EPISODE,
    didl_lite.AudioProgram: _mp_const.MEDIA_CLASS_MUSIC,
    didl_lite.VideoProgram: _mp_const.MEDIA_CLASS_VIDEO,
    didl_lite.Container: _mp_const.MEDIA_CLASS_DIRECTORY,
    didl_lite.Person: _mp_const.MEDIA_CLASS_ARTIST,
    didl_lite.MusicArtist: _mp_const.MEDIA_CLASS_ARTIST,
    didl_lite.PlaylistContainer: _mp_const.MEDIA_CLASS_PLAYLIST,
    didl_lite.Album: _mp_const.MEDIA_CLASS_ALBUM,
    didl_lite.MusicAlbum: _mp_const.MEDIA_CLASS_ALBUM,
    didl_lite.PhotoAlbum: _mp_const.MEDIA_CLASS_ALBUM,
    didl_lite.Genre: _mp_const.MEDIA_CLASS_GENRE,
    didl_lite.MusicGenre: _mp_const.MEDIA_CLASS_GENRE,
    didl_lite.MovieGenre: _mp_const.MEDIA_CLASS_GENRE,
    didl_lite.ChannelGroup: _mp_const.MEDIA_CLASS_CHANNEL,
    didl_lite.AudioChannelGroup: _mp_const.MEDIA_TYPE_CHANNELS,
    didl_lite.VideoChannelGroup: _mp_const.MEDIA_TYPE_CHANNELS,
    didl_lite.EpgContainer: _mp_const.MEDIA_CLASS_DIRECTORY,
    didl_lite.StorageSystem: _mp_const.MEDIA_CLASS_DIRECTORY,
    didl_lite.StorageVolume: _mp_const.MEDIA_CLASS_DIRECTORY,
    didl_lite.StorageFolder: _mp_const.MEDIA_CLASS_DIRECTORY,
    didl_lite.BookmarkFolder: _mp_const.MEDIA_CLASS_DIRECTORY,
}

# Map UPnP class to media_player media_content_type
MEDIA_TYPE_MAP = {
    "object": _mp_const.MEDIA_TYPE_URL,
    "object.item": _mp_const.MEDIA_TYPE_URL,
    "object.item.imageItem": _mp_const.MEDIA_TYPE_IMAGE,
    "object.item.imageItem.photo": _mp_const.MEDIA_TYPE_IMAGE,
    "object.item.audioItem": _mp_const.MEDIA_TYPE_MUSIC,
    "object.item.audioItem.musicTrack": _mp_const.MEDIA_TYPE_MUSIC,
    "object.item.audioItem.audioBroadcast": _mp_const.MEDIA_TYPE_MUSIC,
    "object.item.audioItem.audioBook": _mp_const.MEDIA_TYPE_PODCAST,
    "object.item.videoItem": _mp_const.MEDIA_TYPE_VIDEO,
    "object.item.videoItem.movie": _mp_const.MEDIA_TYPE_MOVIE,
    "object.item.videoItem.videoBroadcast": _mp_const.MEDIA_TYPE_VIDEO,
    "object.item.videoItem.musicVideoClip": _mp_const.MEDIA_TYPE_VIDEO,
    "object.item.playlistItem": _mp_const.MEDIA_TYPE_PLAYLIST,
    "object.item.textItem": _mp_const.MEDIA_TYPE_URL,
    "object.item.bookmarkItem": _mp_const.MEDIA_TYPE_URL,
    "object.item.epgItem": _mp_const.MEDIA_TYPE_EPISODE,
    "object.item.epgItem.audioProgram": _mp_const.MEDIA_TYPE_EPISODE,
    "object.item.epgItem.videoProgram": _mp_const.MEDIA_TYPE_EPISODE,
    "object.container": _mp_const.MEDIA_TYPE_PLAYLIST,
    "object.container.person": _mp_const.MEDIA_TYPE_ARTIST,
    "object.container.person.musicArtist": _mp_const.MEDIA_TYPE_ARTIST,
    "object.container.playlistContainer": _mp_const.MEDIA_TYPE_PLAYLIST,
    "object.container.album": _mp_const.MEDIA_TYPE_ALBUM,
    "object.container.album.musicAlbum": _mp_const.MEDIA_TYPE_ALBUM,
    "object.container.album.photoAlbum": _mp_const.MEDIA_TYPE_ALBUM,
    "object.container.genre": _mp_const.MEDIA_TYPE_GENRE,
    "object.container.genre.musicGenre": _mp_const.MEDIA_TYPE_GENRE,
    "object.container.genre.movieGenre": _mp_const.MEDIA_TYPE_GENRE,
    "object.container.channelGroup": _mp_const.MEDIA_TYPE_CHANNELS,
    "object.container.channelGroup.audioChannelGroup": _mp_const.MEDIA_TYPE_CHANNELS,
    "object.container.channelGroup.videoChannelGroup": _mp_const.MEDIA_TYPE_CHANNELS,
    "object.container.epgContainer": _mp_const.MEDIA_TYPE_TVSHOW,
    "object.container.storageSystem": _mp_const.MEDIA_TYPE_PLAYLIST,
    "object.container.storageVolume": _mp_const.MEDIA_TYPE_PLAYLIST,
    "object.container.storageFolder": _mp_const.MEDIA_TYPE_PLAYLIST,
    "object.container.bookmarkFolder": _mp_const.MEDIA_TYPE_PLAYLIST,
}
