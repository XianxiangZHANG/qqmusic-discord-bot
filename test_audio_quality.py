import unittest
from contextlib import aclosing
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import qq_provider as provider
from qqmusic_api.modules.song import SongFileType


class AudioQualityTests(unittest.IsolatedAsyncioTestCase):
    async def test_candidate_iterator_exhausts_cdns_before_next_quality(self):
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=object())
        context.__aexit__ = AsyncMock(return_value=False)
        request = AsyncMock(side_effect=[['https://a.qq.com/high', 'https://b.qq.com/high'],
                                         ['https://a.qq.com/lower']])
        urls = []
        with patch.object(provider, 'Client', return_value=context), \
             patch.object(provider, 'playback_credential', return_value=object()), \
             patch.object(provider, 'request_track_urls', request):
            async with aclosing(provider.iter_track_sources(SimpleNamespace(mid='song'))) as candidates:
                async for url in candidates:
                    urls.append(url)
                    if len(urls) == 2:
                        self.assertEqual(request.await_count, 1)
                    if len(urls) == 3:
                        break
        self.assertEqual(urls, ['https://a.qq.com/high', 'https://b.qq.com/high', 'https://a.qq.com/lower'])
        self.assertEqual([call.args[-1] for call in request.await_args_list],
                         [SongFileType.MASTER, SongFileType.ATMOS_2])
        context.__aexit__.assert_awaited_once()

    async def resolve(self, responses):
        client = SimpleNamespace()
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=client)
        context.__aexit__ = AsyncMock(return_value=False)
        request = AsyncMock(side_effect=responses)
        with patch.object(provider, 'Client', return_value=context), \
             patch.object(provider, 'playback_credential', return_value=object()), \
             patch.object(provider, 'request_track_urls', request, create=True):
            result = await provider.resolve_track(SimpleNamespace(mid='song', file=None))
        return result, [call.args[-1] for call in request.await_args_list]

    async def test_prefers_master_and_stops_after_success(self):
        result, qualities = await self.resolve([['https://cdn.qq.com/master.flac']])
        self.assertEqual(result, 'https://cdn.qq.com/master.flac')
        self.assertEqual(qualities, [SongFileType.MASTER])

    async def test_falls_back_to_flac_when_premium_formats_unavailable(self):
        result, qualities = await self.resolve([[], [], ['https://cdn.qq.com/song.flac']])
        self.assertEqual(result, 'https://cdn.qq.com/song.flac')
        self.assertEqual(qualities, [SongFileType.MASTER, SongFileType.ATMOS_2, SongFileType.FLAC])

    async def test_returns_none_when_all_qualities_unavailable(self):
        result, qualities = await self.resolve([[]] * 20)
        self.assertIsNone(result)
        self.assertIn(SongFileType.MP3_128, qualities)
        self.assertEqual(len(qualities), len(set(qualities)))

    async def test_timed_out_quality_does_not_block_lower_quality(self):
        result, qualities = await self.resolve([TimeoutError(), ['https://cdn.qq.com/song.flac']])
        self.assertEqual(result, 'https://cdn.qq.com/song.flac')
        self.assertEqual(qualities[-1], SongFileType.ATMOS_2)

    def test_all_cdns_are_retained_in_order_without_duplicates(self):
        response = dict(midurlinfo=[dict(songmid='song', result=0, purl='track.ogg')],
                        sip=['http://first.qq.com/', 'https://second.qq.com/', 'http://first.qq.com/'])
        self.assertEqual(provider.stream_urls(response, 'song'),
                         ['https://first.qq.com/track.ogg', 'https://second.qq.com/track.ogg'])

    def test_rejects_failed_entries_and_non_qq_urls(self):
        response = dict(midurlinfo=[dict(songmid='song', result=1, purl='bad.ogg'),
                                   dict(songmid='other', result=0, purl='other.ogg'),
                                   dict(songmid='song', result=0, purl='https://example.com/bad')],
                        sip=['https://first.qq.com/'])
        self.assertEqual(provider.stream_urls(response, 'song'), [])


if __name__ == '__main__':
    unittest.main()
