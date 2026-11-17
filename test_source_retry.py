import ast
import asyncio
import logging
from collections import deque
from contextlib import aclosing
from pathlib import Path
from tempfile import TemporaryFile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock


class SourceRetryTests(unittest.IsolatedAsyncioTestCase):
    async def run_playback(self, skip=False, all_fail=False, mid_song_error=False):
        tree = ast.parse(Path('bot.py').read_text(encoding='utf-8'))
        handler = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'play_queue')
        attempts = []
        async def candidates(track):
            for url in ('cdn1-high', 'cdn2-high', 'cdn1-low'):
                yield url
        def audio(url, **kwargs):
            attempts.append(url)
            failed = all_fail or url != 'cdn1-low'
            if failed:
                kwargs['stderr'].write(b'HTTP error 404')
            return SimpleNamespace(frames_read=100 if mid_song_error else 0 if failed else 100,
                                   cleanup=lambda: None)
        def play(source, after):
            if skip:
                scope['skip_requested'] = True
            after(RuntimeError('interrupted') if mid_song_error else None)
        voice = SimpleNamespace(play=play, disconnect=AsyncMock())
        scope = dict(asyncio=asyncio, aclosing=aclosing, queue=deque([SimpleNamespace(interval=2)]),
                     current_song=None, playback_status=None, playback_channel=None, skip_requested=False,
                     lyric_task=None, fetch_lyrics=AsyncMock(return_value=[]),
                     wait_for_voice_encryption=AsyncMock(), iter_track_sources=candidates,
                     TemporaryFile=TemporaryFile, CountedAudio=audio, refresh_panel=AsyncMock(),
                     logger=logging.getLogger('retry-test'), describe_ffmpeg_failure=lambda text: 'HTTP 404')
        exec(compile(ast.Module(body=[handler], type_ignores=[]), 'bot.py', 'exec'), scope)
        await scope['play_queue'](SimpleNamespace(connect=AsyncMock(return_value=voice)))
        voice.disconnect.assert_awaited_once()
        return attempts, scope['playback_status']

    async def test_failed_cdn_then_lower_quality_are_tried_before_skipping(self):
        attempts, status = await self.run_playback()
        self.assertEqual(attempts, ['cdn1-high', 'cdn2-high', 'cdn1-low'])
        self.assertIsNone(status)

    async def test_manual_skip_does_not_retry_failed_source(self):
        attempts, _ = await self.run_playback(skip=True)
        self.assertEqual(attempts, ['cdn1-high'])

    async def test_all_failed_sources_report_failure(self):
        attempts, status = await self.run_playback(all_fail=True)
        self.assertEqual(len(attempts), 3)
        self.assertIn('404', status)

    async def test_mid_song_failure_does_not_restart_song(self):
        attempts, status = await self.run_playback(mid_song_error=True)
        self.assertEqual(attempts, ['cdn1-high'])
        self.assertIsNotNone(status)
