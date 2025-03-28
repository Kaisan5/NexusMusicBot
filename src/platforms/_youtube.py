#  Copyright (c) 2025 AshokShau.
#  TgMusicBot is an open-source Telegram music bot licensed under AGPL-3.0.
#  All rights reserved where applicable.
#
#

import re
from typing import Optional, Any

from py_yt import VideosSearch, Playlist

from src.logger import LOGGER
from ._dl_helper import YouTubeDownload
from ._httpx import HttpxClient
from .dataclass import PlatformTracks, TrackInfo, MusicTrack
from .downloader import MusicService


class YouTubeData(MusicService):
    YOUTUBE_VIDEO_PATTERN = re.compile(
        r"^(https?://)?(www\.)?(youtube\.com|music\.youtube\.com)/(watch\?v=|shorts/)[\w-]+",
        re.IGNORECASE,
    )
    YOUTUBE_PLAYLIST_PATTERN = re.compile(
        r"^(https?://)?(www\.)?(youtube\.com|music\.youtube\.com)/playlist\?list=[\w-]+",
        re.IGNORECASE,
    )

    def __init__(self, query: str = None) -> None:
        self.client = HttpxClient()
        self.query = None if not query else query.split("&")[0] if query and "&" in query else query

    def is_valid(self, url: str) -> bool:
        return (
            bool(
                self.YOUTUBE_VIDEO_PATTERN.match(url)
                or self.YOUTUBE_PLAYLIST_PATTERN.match(url)
            )
            if url
            else False
        )

    async def _fetch_data(self, url: str) -> Optional[dict[str, Any]]:
        if self.YOUTUBE_VIDEO_PATTERN.match(url):
            return await self._get_youtube_url(url)
        elif self.YOUTUBE_PLAYLIST_PATTERN.match(url):
            return await self._get_playlist(url)
        return await self.search()

    async def get_info(self) -> Optional[PlatformTracks]:
        if not self.is_valid(self.query):
            return None

        data = await self._fetch_data(self.query)
        return self._create_platform_tracks(data) if data else None

    async def search(self) -> Optional[PlatformTracks]:
        if not self.query:
            return None
        if self.is_valid(self.query):
            data = await self._fetch_data(self.query)
        else:
            try:
                search = VideosSearch(self.query, limit=5)
                results = await search.next()
                data = (
                    {
                        "results": [
                            self._format_track(video) for video in results["result"]
                        ]
                    }
                    if "result" in results
                    else None
                )
            except Exception as e:
                LOGGER.error(f"Error searching: {e}")
                data = None

        return self._create_platform_tracks(data) if data else None

    async def get_track(self) -> Optional[TrackInfo]:
        url = f"https://youtube.com/watch?v={self.query}"
        try:
            data = await self._get_youtube_url(url)
            if not data or "results" not in data:
                return None

            track_data = data["results"][0]
            return TrackInfo(
                cdnurl="None",
                key="None",
                name=track_data["name"],
                artist=track_data["artist"],
                tc=track_data["id"],
                album="YouTube",
                cover=track_data["cover"],
                lyrics="None",
                duration=track_data["duration"],
                year=0,
            )
        except Exception as e:
            LOGGER.error(f"Error fetching track: {e}")
            return None

    async def download_track(self, track: TrackInfo) -> Optional[str]:
        try:
            return await YouTubeDownload(track).process()
        except Exception as e:
            LOGGER.error(f"Error downloading track: {e}")
            return None

    async def _get_youtube_url(self, url: str) -> Optional[dict[str, Any]]:
        _url = f"https://www.youtube.com/oembed?url={url}&format=json"
        data = await self.client.make_request(_url)
        if not data:
            return None
        return {"results": [{
            "id": url.split("v=")[1],
            "name": data.get("title"),
            "duration": 0,
            "artist": data.get("author_name", ""),
            "cover": data.get("thumbnail_url", ""),
            "year": 0,
            "platform": "youtube",
        }]}

    @staticmethod
    async def _get_playlist(url: str) -> Optional[dict[str, Any]]:
        try:
            playlist = await Playlist.getVideos(url)
        except KeyError:
            return None
        except Exception as e:
            LOGGER.error(f"Error getting playlist: {e}")
            return None
        return (
            {
                "results": [
                    YouTubeData._format_track(track)
                    for track in playlist.get("videos", [])
                ]
            }
            if playlist
            else None
        )

    async def get_recommendations(self) -> Optional[PlatformTracks]:
        return None

    @staticmethod
    def _duration_to_seconds(duration: str) -> int:
        if not duration:
            return 0
        parts = duration.split(":")
        if len(parts) == 3:  # Format: H:MM:SS
            hours, minutes, seconds = map(int, parts)
            return hours * 3600 + minutes * 60 + seconds
        elif len(parts) == 2:  # Format: MM:SS
            minutes, seconds = map(int, parts)
            return minutes * 60 + seconds
        else:
            return 0

    @staticmethod
    def _create_platform_tracks(data: dict) -> Optional[PlatformTracks]:
        if data and "results" in data:
            return PlatformTracks(
                tracks=[MusicTrack(**track) for track in data["results"]]
            )
        return None

    @staticmethod
    def _format_track(track_data: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": track_data.get("id"),
            "name": track_data.get("title"),
            "duration": YouTubeData._duration_to_seconds(track_data.get("duration", "0:00")),
            "artist": track_data.get("channel", {}).get("name", "Unknown"),
            "cover": track_data.get("thumbnails", [{}])[-1].get("url", ""),
            "year": 0,
            "platform": "youtube",
        }
