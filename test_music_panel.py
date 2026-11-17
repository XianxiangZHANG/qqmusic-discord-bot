import asyncio
import ast
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
import discord
from discord import app_commands

from music_panel import PlayerView


class PanelTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_request_replaces_and_deletes_previous_card(self):
        tree = ast.parse(Path('bot.py').read_text(encoding='utf-8'))
        handler = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
                       and node.name == 'ensure_panel')
        old = SimpleNamespace(delete=AsyncMock())
        new = SimpleNamespace()
        channel = SimpleNamespace(send=AsyncMock(return_value=new))
        scope = dict(discord=discord, asyncio=asyncio, panel_message=old,
                     panel_task=SimpleNamespace(done=lambda: False),
                     playback_task=SimpleNamespace(done=lambda: False), panel_lock=asyncio.Lock(),
                     PlayerView=lambda *args: None, player_state=lambda: {}, panel_action=None,
                     refresh_panel=AsyncMock())
        exec(compile(ast.Module(body=[handler], type_ignores=[]), 'bot.py', 'exec'), scope)
        await scope['ensure_panel'](channel)
        channel.send.assert_awaited_once()
        old.delete.assert_awaited_once()
        self.assertIs(scope['panel_message'], new)

    async def test_queue_button_responds_through_registered_command(self):
        # Load the real handlers without starting QQ/Discord clients or reading credentials.
        tree = ast.parse(Path('bot.py').read_text(encoding='utf-8'))
        handlers = [node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
                    and node.name in ('panel_action', 'show_queue')]
        client = discord.Client(intents=discord.Intents.none())
        scope = dict(discord=discord, commands=app_commands.CommandTree(client),
                     GUILD=discord.Object(id=1), queue=['待播歌曲'], current_song='当前歌曲',
                     playback_status=None, track_title=lambda song: song)
        exec(compile(ast.Module(body=handlers, type_ignores=[]), 'bot.py', 'exec'), scope)
        response = SimpleNamespace(send_message=AsyncMock())
        await scope['panel_action']('queue', SimpleNamespace(response=response))
        response.send_message.assert_awaited_once()
        args, kwargs = response.send_message.call_args
        self.assertIn('当前歌曲', args[0])
        self.assertIn('1. 待播歌曲', args[0])
        self.assertTrue(kwargs['ephemeral'])

    async def test_v2_card_and_public_pause_button(self):
        calls = []
        async def action(name, interaction):
            calls.append(name)
        view = PlayerView(dict(title='晴天', duration=269, elapsed=80,
                               active=True, paused=False, queue_size=3), action)
        self.assertTrue(view.has_components_v2())
        payload = str(view.to_components())
        self.assertIn('晴天', payload)
        self.assertIn('1:20', payload)
        button = next(item for item in view.walk_children()
                      if getattr(item, 'custom_id', None) == 'music:pause')
        self.assertTrue(await view.interaction_check(SimpleNamespace()))
        await button.callback(SimpleNamespace())
        self.assertEqual(calls, ['pause'])

    async def test_finished_card_disables_transport_but_keeps_queue(self):
        view = PlayerView(dict(active=False, title='播放结束'), None)
        buttons = {item.custom_id: item for item in view.walk_children()
                   if getattr(item, 'custom_id', None)}
        self.assertTrue(buttons['music:stop'].disabled)
        self.assertFalse(buttons['music:queue'].disabled)

    async def test_paused_card_with_cover_serializes_and_offers_resume(self):
        view = PlayerView(dict(active=True, paused=True, title='歌曲',
                               cover='https://example.com/cover.jpg', duration=0, elapsed=0), None)
        payload = str(view.to_components())
        self.assertIn('继续', payload)
        self.assertIn('https://example.com/cover.jpg', payload)
        self.assertIn('已暂停', payload)


if __name__ == '__main__':
    unittest.main()
