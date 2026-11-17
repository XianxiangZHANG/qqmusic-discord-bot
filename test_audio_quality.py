import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import qq_provider as provider
from qqmusic_api.modules.song import SongFileType


class AudioQualityTests(unittest.IsolatedAsyncioTestCase):
    async def resolve(self, responses):
        client = SimpleNamespace()
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=client)
        context.__aexit__ = AsyncMock(return_value=False)
        request = AsyncMock(side_effect=responses)
        with patch.object(provider, 'Client', return_value=context), \
             patch.object(provider, 'playback_credential', return_value=object()), \
             patch.object(provider, 'request_track_quality', request, create=True):
            result = await provider.resolve_track(SimpleNamespace(mid='song', file=None))
        return result, [call.args[-1] for call in request.await_args_list]

    async def test_prefers_master_and_stops_after_success(self):
        result, qualities = await self.resolve(['https://cdn.qq.com/master.flac'])
        self.assertEqual(result, 'https://cdn.qq.com/master.flac')
        self.assertEqual(qualities, [SongFileType.MASTER])

    async def test_falls_back_to_flac_when_premium_formats_unavailable(self):
        result, qualities = await self.resolve([None, None, 'https://cdn.qq.com/song.flac'])
        self.assertEqual(result, 'https://cdn.qq.com/song.flac')
        self.assertEqual(qualities, [SongFileType.MASTER, SongFileType.ATMOS_2, SongFileType.FLAC])

    async def test_returns_none_when_all_qualities_unavailable(self):
        result, qualities = await self.resolve([None] * 20)
        self.assertIsNone(result)
        self.assertIn(SongFileType.MP3_128, qualities)
        self.assertEqual(len(qualities), len(set(qualities)))

    async def test_timed_out_quality_does_not_block_lower_quality(self):
        result, qualities = await self.resolve([TimeoutError(), 'https://cdn.qq.com/song.flac'])
        self.assertEqual(result, 'https://cdn.qq.com/song.flac')
        self.assertEqual(qualities[-1], SongFileType.ATMOS_2)


if __name__ == '__main__':
    unittest.main()
