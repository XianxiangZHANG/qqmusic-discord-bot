import unittest
import ast
from pathlib import Path
from types import SimpleNamespace

from lyrics import parse_lrc, current_line, lyric_context


class LyricsTests(unittest.TestCase):
    def test_three_line_window_tracks_current_line(self):
        lines = [(1, '第一句'), (3, '第二句'), (5, '第三句'), (7, '第四句')]
        self.assertEqual(lyric_context(lines, 3), ('第一句', '第二句', '第三句'))
        self.assertEqual(lyric_context(lines, 5), ('第二句', '第三句', '第四句'))

    def test_three_line_window_handles_intro_end_and_missing_lyrics(self):
        lines = [(1, '第一句'), (3, '第二句')]
        self.assertEqual(lyric_context(lines, 0), ('', '♪ 前奏 / 间奏', '第一句'))
        self.assertEqual(lyric_context(lines, 1), ('', '第一句', '第二句'))
        self.assertEqual(lyric_context(lines, 3), ('第一句', '第二句', ''))
        self.assertEqual(lyric_context([], 0), ('', '暂无同步歌词', ''))

    def test_paused_player_uses_audio_frames_for_lyric_position(self):
        tree = ast.parse(Path('bot.py').read_text(encoding='utf-8'))
        handler = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                       and node.name == 'player_state')
        source = SimpleNamespace(frames_read=100)
        voice = SimpleNamespace(source=source, is_paused=lambda: True)
        task = SimpleNamespace(done=lambda: True, cancelled=lambda: False,
                               result=lambda: [(1, '第一行'), (3, '第二行')])
        scope = dict(playback_channel=SimpleNamespace(guild=SimpleNamespace(voice_client=voice), mention='voice'),
                     playback_task=SimpleNamespace(done=lambda: False),
                     current_song=SimpleNamespace(interval=100), lyric_task=task,
                     lyric_context=lyric_context, track_label=lambda track: 'test', queue=[], playback_status=None)
        exec(compile(ast.Module(body=[handler], type_ignores=[]), 'bot.py', 'exec'), scope)
        self.assertEqual(scope['player_state']()['lyric'], '第一行')
        self.assertEqual(scope['player_state']()['lyric_lines'], ('', '第一行', '第二行'))
        self.assertEqual(scope['player_state']()['lyric'], '第一行')
        source.frames_read = 150
        self.assertEqual(scope['player_state']()['lyric'], '第二行')

    def test_multiple_timestamps_offset_and_sorting(self):
        lines = parse_lrc('[ar:artist]\n[00:02.50][00:04.500]第二行\n[00:01]第一行\n[offset:500]')
        self.assertEqual(lines, [(0.5, '第一行'), (2.0, '第二行'), (4.0, '第二行')])

    def test_line_changes_only_when_timestamp_reached(self):
        lines = [(1.0, '第一行'), (3.0, '第二行'), (5.0, '')]
        self.assertEqual(current_line(lines, 0), '♪ 前奏 / 间奏')
        self.assertEqual(current_line(lines, 2.99), '第一行')
        self.assertEqual(current_line(lines, 3), '第二行')
        self.assertEqual(current_line(lines, 5), '♪ 前奏 / 间奏')

    def test_plain_or_missing_lyrics_have_fallback(self):
        self.assertEqual(parse_lrc('无时间戳的歌词'), [])
        self.assertEqual(current_line([], 10), '暂无同步歌词')

    def test_html_entities_and_invalid_timestamps(self):
        self.assertEqual(parse_lrc('[00:60]错误\n[00:01.25]你 &amp; 我'), [(1.25, '你 & 我')])
