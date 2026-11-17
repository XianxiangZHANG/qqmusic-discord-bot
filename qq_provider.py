import asyncio
import logging
from dataclasses import replace
from urllib.parse import urljoin, urlsplit

from qqmusic_api import Client, Credential
from qqmusic_api.core.versioning import Platform
from qqmusic_api.modules.song import SongFileInfo, SongQueryInfo, SongFileType

from qq_login import load_credential

logger = logging.getLogger(__name__)

# Prefer high-resolution stereo sources; proprietary encrypted files require a
# separate decoder and cannot be passed directly to the current FFmpeg player.
PLAYBACK_QUALITIES = (
    SongFileType.MASTER, SongFileType.ATMOS_2, SongFileType.FLAC,
    SongFileType.OGG_640, SongFileType.OGG_320, SongFileType.MP3_320,
    SongFileType.ACC_192, SongFileType.OGG_192, SongFileType.MP3_128,
    SongFileType.ACC_96, SongFileType.OGG_96, SongFileType.ACC_48,
)


def playback_credential():
    try:
        return load_credential()
    except FileNotFoundError:
        return Credential()


async def search_songs(keyword, *, limit=5):
    async with asyncio.timeout(20):
        async with Client(credential=playback_credential()) as qq:
            response = await qq.search.search_by_type(keyword=keyword, num=limit)
            return response.song or []


async def suggest_songs(http, keyword, *, expanded=False):
    if expanded:
        url = "https://c.y.qq.com/soso/fcgi-bin/client_search_cp"
        params = {"w": keyword, "p": 1, "n": 10, "t": 0, "aggr": 1}
    else:
        url = "https://c.y.qq.com/splcloud/fcgi-bin/smartbox_new.fcg"
        params = {"key": keyword}
    params.update(format="json", inCharset="utf-8", outCharset="utf-8")

    async with http.get(url, params=params, allow_redirects=False) as response:
        response.raise_for_status()
        payload = await response.json(content_type=None)
    if payload.get("code") != 0:
        return []
    songs = (payload.get("data") or {}).get("song") or {}
    suggestions = []
    for item in (songs.get("list" if expanded else "itemlist") or [])[:10]:
        mid = item.get("songmid" if expanded else "mid")
        title = item.get("songname" if expanded else "name")
        artist = item.get("singer")
        if expanded:
            artist = " / ".join(singer["name"] for singer in (artist or []) if singer.get("name"))
        if isinstance(mid, str) and isinstance(title, str) and title.strip():
            label = f"{title} — {artist}" if artist else title
            suggestions.append((mid, " ".join(label.split())))
    return suggestions


async def find_song_by_mid(mid):
    async with asyncio.timeout(20):
        async with Client(credential=playback_credential()) as qq:
            response = await qq.song.query_song([SongQueryInfo(mid=mid)])
            return next((track for track in response.tracks if track.mid == mid), None)


async def resolve_track(track):
    credential = playback_credential()
    async with Client(credential=credential) as qq:
        for quality in PLAYBACK_QUALITIES:
            try:
                async with asyncio.timeout(5):
                    url = await request_track_quality(qq, credential, track, quality)
            except Exception as error:
                # A format may be unavailable for this song/account, or its
                # endpoint may fail. Never log signed URLs or credentials.
                logger.warning('Audio quality %s failed (%s); trying next.',
                               quality.name, type(error).__name__)
                continue
            if url:
                logger.info('Selected QQ Music source quality: %s.', quality.name)
                return url
    logger.warning('No available QQ Music source at any supported quality.')
    return None


async def request_track_quality(qq, credential, track, quality):
    # Keep the signed path paired with the CDN from this quality's response.
    media_mid = getattr(getattr(track, 'file', None), 'media_mid', None)
    request = qq.song.get_song_urls([
        SongFileInfo(mid=track.mid, media_mid=media_mid, file_type=quality)
    ])
    stream_request = replace(
        request,
        module='music.vkey.GetEVkey',
        method='CgiGetEVkey',
        platform=Platform.WEB,
        param={**request.param, 'platform': '20', 'loginflag': 1, 'xcdn': 1},
        comm={
            **(request.comm or {}), 'ct': 24, 'cv': 0, 'format': 'json',
            'uin': credential.str_musicid, 'authst': credential.musickey,
            'tmeLoginType': credential.login_type,
        },
        credential=credential,
        response_model=None,
    )
    response = await stream_request

    url = select_stream_url(response, track.mid)
    entries = response.get("midurlinfo") or []
    codes = [entry["result"] for entry in entries if type(entry.get("result")) is int]
    logger.info(
        "QQ Music quality=%s: result_codes=%s, CDN_count=%d, usable_https=%s.",
        quality.name, codes, len(response.get("sip") or []), bool(url),
    )
    return url


def select_stream_url(response, song_mid):
    for entry in response.get("midurlinfo") or []:
        path = entry.get("purl")
        if entry.get("songmid") != song_mid or entry.get("result", 0) != 0 or not path:
            continue
        absolute = urlsplit(path)
        if absolute.scheme or absolute.netloc:
            return qq_https_url(path)
        for base in response.get("sip") or []:
            https_base = qq_https_url(base)
            if https_base:
                url = urljoin(https_base, path)
                if urlsplit(url).netloc == urlsplit(https_base).netloc:
                    return url
    return None


def qq_https_url(value):
    parts = urlsplit(value)
    if (
        parts.scheme not in ("", "http", "https")
        or not (parts.hostname or "").endswith(".qq.com")
        or parts.username is not None
        or parts.port not in (None, 443)
    ):
        return None
    return parts._replace(scheme="https").geturl()
