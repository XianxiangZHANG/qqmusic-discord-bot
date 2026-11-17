import asyncio
import logging
import os
import re
from collections import OrderedDict, deque
from contextlib import aclosing
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryFile

import aiohttp
import discord
from discord import app_commands
from qqmusic_api import Client

from qq_login import load_credential
from music_panel import PlayerView
from qq_provider import find_song_by_mid, iter_track_sources, search_songs, suggest_songs, fetch_lyrics
from lyrics import lyric_context

GUILD = discord.Object(id=int(os.environ["DISCORD_GUILD_ID"]))
OWNER_ID = int(os.environ["DISCORD_OWNER_ID"])
TOKEN_PATH = Path("/run/secrets/discord_token")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("voice-test")


class CountedAudio(discord.FFmpegOpusAudio):
    def __init__(self, source, **options):
        self.frames_read = 0
        super().__init__(source, **options)

    def read(self):
        frame = super().read()
        if frame:
            self.frames_read += 1
        return frame


class TestTone(discord.FFmpegPCMAudio):
    def __init__(self):
        super().__init__(
            "sine=frequency=440:sample_rate=48000:duration=5",
            before_options="-f lavfi",
            options="-af volume=2",
        )
        self.frames_read = 0

    def read(self):
        frame = super().read()
        self.frames_read += bool(frame)
        return frame


async def wait_for_voice_encryption(voice):
    # discord.py 2.7.1 can complete the voice handshake before DAVE is ready.
    connection = voice._connection
    try:
        async with asyncio.timeout(10):
            while not connection.can_encrypt:
                await asyncio.sleep(0.1)
    except TimeoutError:
        logger.warning("DAVE not ready (protocol=%s, davey=%s).",
                       connection.dave_protocol_version, version("davey"))
        raise
    logger.info("DAVE ready (protocol=%s, davey=%s).",
                connection.dave_protocol_version, version("davey"))


class VoiceTestClient(discord.Client):
    suggestion_http = None

    async def setup_hook(self):
        await commands.sync(guild=GUILD)
        self.suggestion_http = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=4),
            headers={"Referer": "https://y.qq.com/", "User-Agent": "Mozilla/5.0"},
        )

    async def close(self):
        try:
            if self.suggestion_http is not None:
                await self.suggestion_http.close()
        finally:
            await super().close()

    async def on_ready(self):
        logger.info("Discord connected. Music commands are registered.")


client = VoiceTestClient(intents=discord.Intents.default())
commands = app_commands.CommandTree(client)
test_lock = asyncio.Lock()
move_lock = asyncio.Lock()
queue = deque()
playback_task = None
playback_channel = None
current_song = None
playback_status = None
skip_requested = False
panel_message = None
panel_task = None
panel_lock = asyncio.Lock()
lyric_task = None


def player_state():
    voice = playback_channel.guild.voice_client if playback_channel else None
    active = playback_channel is not None and playback_task is not None and not playback_task.done()
    track = current_song
    album_mid = getattr(getattr(track, 'album', None), 'mid', None)
    source = voice.source if voice else None
    elapsed = getattr(source, 'frames_read', 0) * 0.02
    lyric = '歌词加载中…' if active else '♪ 播放已结束'
    lyric_lines = ('', lyric, '')
    if active and lyric_task is not None and lyric_task.done() and not lyric_task.cancelled():
        lyric_lines = lyric_context(lyric_task.result(), elapsed)
        lyric = lyric_lines[1]
    return dict(active=active, paused=bool(voice and voice.is_paused()),
                title=track_label(track) if track else '准备播放…' if active else '播放结束',
                cover=f'https://y.gtimg.cn/music/photo_new/T002R300x300M000{album_mid}.jpg' if album_mid else None,
                elapsed=elapsed, lyric=lyric, lyric_lines=lyric_lines,
                duration=getattr(track, 'interval', 0), queue_size=len(queue),
                channel=playback_channel.mention if playback_channel else None,
                status=playback_status)


async def refresh_panel():
    global panel_message
    async with panel_lock:
        if panel_message is None:
            return
        try:
            await panel_message.edit(view=PlayerView(player_state(), panel_action),
                                     allowed_mentions=discord.AllowedMentions.none())
        except discord.NotFound:
            panel_message = None
        except discord.HTTPException:
            logger.warning('Could not refresh player panel.')


async def panel_updates():
    last_lyric = None
    last_refresh = 0
    while playback_task is not None and not playback_task.done():
        state = player_state()
        now = asyncio.get_running_loop().time()
        if state['lyric_lines'] != last_lyric or now - last_refresh >= 10:
            await refresh_panel()
            last_lyric = state['lyric_lines']
            last_refresh = now
        await asyncio.sleep(2)
    await refresh_panel()


async def ensure_panel(channel):
    global panel_message, panel_task
    if channel is None or playback_task is None or playback_task.done():
        return
    async with panel_lock:
        previous = panel_message
        try:
            panel_message = await channel.send(view=PlayerView(player_state(), panel_action),
                                               allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            logger.warning('Could not send player panel; check channel permissions.')
            return
        if previous is not None:
            try:
                await previous.delete()
            except discord.NotFound:
                pass
            except discord.HTTPException:
                logger.warning('Could not delete previous player panel.')
    if panel_task is None or panel_task.done():
        panel_task = asyncio.create_task(panel_updates())
    await refresh_panel()


async def panel_action(action, interaction):
    global skip_requested
    if action == 'queue':
        await show_queue.callback(interaction)
        return
    await interaction.response.defer()
    voice = playback_channel.guild.voice_client if playback_channel else None
    if action == 'stop':
        task = playback_task
        async with move_lock:
            if task is not None and not task.done() and playback_task is task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
    elif voice is not None:
        if action == 'pause':
            if voice.is_paused():
                voice.resume()
            elif voice.is_playing():
                voice.pause()
        elif action == 'skip' and (voice.is_playing() or voice.is_paused()):
            skip_requested = True
            voice.stop()
    await refresh_panel()


def track_label(track):
    title = getattr(track, "title", None) or getattr(track, "name", None) or "未命名"
    artists = " / ".join(singer.name for singer in (getattr(track, "singer", None) or []))
    label = f"{title} — {artists}" if artists else title
    return " ".join(label.split())


def track_title(track):
    return discord.utils.escape_markdown(track_label(track)[:70])


def describe_ffmpeg_failure(output):
    output = output.lower()
    for code in (400, 401, 403, 404, 410, 429, 500, 502, 503):
        if f"http error {code}" in output or f"server returned {code}" in output:
            return f"音源服务器返回 HTTP {code}，已跳过。"
    if "timed out" in output:
        return "连接音源超时，已跳过。"
    if "failed to resolve hostname" in output or "temporary failure in name resolution" in output:
        return "容器无法解析音源域名，已跳过。"
    if "connection refused" in output or "network is unreachable" in output:
        return "容器无法连接音源服务器，已跳过。"
    if "certificate" in output or "tls" in output:
        return "音源的 TLS 连接失败，已跳过。"
    if "invalid data found" in output:
        return "音源返回了无法解码的数据，已跳过。"
    return "曲目播放失败，已跳过。"


async def play_queue(channel):
    global current_song, playback_status, playback_channel, skip_requested, lyric_task
    voice = None
    try:
        voice = await channel.connect(timeout=20, reconnect=False)
        await wait_for_voice_encryption(voice)
        while queue:
            current_song = queue.popleft()
            playback_status = None
            skip_requested = False
            lyric_task = asyncio.create_task(fetch_lyrics(current_song))
            source = None
            diagnostics = None
            try:
                loop = asyncio.get_running_loop()
                last_failure = None
                async with aclosing(iter_track_sources(current_song)) as candidates:
                    async for url in candidates:
                        if diagnostics is not None:
                            diagnostics.close()
                        diagnostics = TemporaryFile()
                        audio = None
                        try:
                            audio = source = CountedAudio(
                                url,
                                before_options=(
                                    "-rw_timeout 15000000 -user_agent Mozilla/5.0 "
                                    "-reconnect 1 -reconnect_on_network_error 1 -reconnect_delay_max 3"
                                ),
                                stderr=diagnostics,
                            )
                            finished = loop.create_future()

                            def after_playback(error, future=finished):
                                def complete():
                                    if not future.done():
                                        future.set_result(error)
                                loop.call_soon_threadsafe(complete)

                            voice.play(source, after=after_playback)
                            source = None
                            await refresh_panel()
                            error = await finished
                            if skip_requested:
                                break
                            if error is not None:
                                raise error
                            if audio.frames_read == 0:
                                raise RuntimeError('FFmpeg produced no audio frames')
                            break
                        except Exception:
                            # Retry only before audio has started. Replaying a
                            # source after a mid-song error would restart the song.
                            if audio is not None and audio.frames_read > 0:
                                raise
                            diagnostics.seek(0)
                            last_failure = describe_ffmpeg_failure(
                                diagnostics.read(16384).decode('utf-8', 'replace'))
                            logger.warning('Source failed before audio started; trying next CDN/quality: %s',
                                           last_failure)
                        finally:
                            if source is not None:
                                source.cleanup()
                                source = None
                    else:
                        playback_status = last_failure or '所有音质和 CDN 均无可用音源，已跳过。'
                        continue
                if not skip_requested:
                    expected = getattr(current_song, "interval", 0) or 0
                    played = round(audio.frames_read * 0.02)
                    logger.info("Track ended: audio_seconds=%d, catalog_seconds=%d.", played, expected)
                    if expected > played + 5:
                        diagnostics.seek(0)
                        output = diagnostics.read(16384).decode("utf-8", "replace").lower()
                        interrupted = any(marker in output for marker in (
                            "stream ends prematurely", "connection reset", "connection timed out",
                        ))
                        logger.warning("Track ended early: interrupted_transfer=%s.", interrupted)
                        playback_status = f"音频在约 {played} 秒结束，QQ 音乐标注时长为 {expected} 秒。"
                        if interrupted:
                            playback_status += "读取音源时连接中断。"
            except Exception as error:
                playback_status = "曲目播放失败，已跳过。"
                if diagnostics is not None:
                    diagnostics.seek(0)
                    playback_status = describe_ffmpeg_failure(diagnostics.read(16384).decode("utf-8", "replace"))
                logger.warning("Music playback failed (%s): %s", type(error).__name__, playback_status)
            finally:
                if lyric_task is not None and not lyric_task.done():
                    lyric_task.cancel()
                    try:
                        await lyric_task
                    except asyncio.CancelledError:
                        pass
                if source is not None:
                    source.cleanup()
                if diagnostics is not None:
                    diagnostics.close()
    except Exception as error:
        playback_status = "语音连接失败，队列已清空。"
        logger.warning("Music voice connection failed (%s).", type(error).__name__)
    finally:
        queue.clear()
        current_song = None
        lyric_task = None
        playback_channel = None
        if voice is not None:
            try:
                await voice.disconnect(force=True)
            except Exception as error:
                logger.warning("Music disconnect failed (%s).", type(error).__name__)
        await refresh_panel()


def can_manage_music(member):
    return member.id == OWNER_ID or member.guild_permissions.administrator


async def require_music_manager(interaction):
    member = interaction.user
    if isinstance(member, discord.Member) and can_manage_music(member):
        return True
    await interaction.response.send_message("此命令仅供部署者和服务器管理员使用。", ephemeral=True)
    return False


@commands.command(name="search", description="搜索 QQ 音乐歌曲", guild=GUILD)
async def search(interaction: discord.Interaction, keyword: str):
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        keyword = " ".join(keyword.split())
        tracks = await search_songs(keyword, limit=10)
        cache_autocomplete_choices(keyword, tracks)
    except Exception as error:
        logger.warning("QQ Music search failed (%s).", type(error).__name__)
        await interaction.followup.send("QQ 音乐搜索失败，请稍后重试。", ephemeral=True)
        return
    lines = [f"{index}. {track_title(track)}" for index, track in enumerate(tracks[:5], 1)]
    await interaction.followup.send("\n".join(lines) or "没有找到歌曲。", ephemeral=True,
                                    allowed_mentions=discord.AllowedMentions.none(), suppress_embeds=True)


def enqueue_track(member, track):
    global playback_task, playback_channel
    voice_state = member.voice
    active = playback_task is not None and not playback_task.done()
    if voice_state is None or not isinstance(voice_state.channel, discord.VoiceChannel):
        return "请先加入普通语音频道。"
    if move_lock.locked():
        return "机器人正在换频道，请稍后再点歌。"
    if test_lock.locked() or (active and playback_channel != voice_state.channel):
        return "机器人正在进行语音测试或在另一个频道播放。"
    if track is None:
        return "没有找到这个搜索结果。"
    if len(queue) >= 25:
        return "队列已满，请稍后再试。"

    queue.append(track)
    if not active:
        playback_channel = voice_state.channel
        playback_task = asyncio.create_task(play_queue(playback_channel))
    return f"已加入队列：{track_title(track)}"


class TrackPicker(discord.ui.View):
    def __init__(self, user_id, tracks):
        super().__init__(timeout=90)
        self.user_id = user_id
        self.tracks = tracks[:10]
        self.picker = discord.ui.Select(
            placeholder="选择要播放的歌曲",
            options=[
                discord.SelectOption(label=track_label(track)[:100], value=str(index))
                for index, track in enumerate(self.tracks)
            ],
        )
        self.picker.callback = self.pick_track
        self.add_item(self.picker)

    async def interaction_check(self, interaction):
        return interaction.user.id == self.user_id

    async def pick_track(self, interaction):
        if self.is_finished():
            await interaction.response.send_message("这次选歌已结束，请重新点歌。", ephemeral=True)
            return
        self.stop()
        message = enqueue_track(interaction.user, self.tracks[int(self.picker.values[0])])
        await interaction.response.edit_message(
            content=message, view=None, allowed_mentions=discord.AllowedMentions.none()
        )
        if message.startswith('已加入队列：'):
            await ensure_panel(interaction.channel)


@commands.command(name="play", description="搜索 QQ 音乐歌曲并加入播放队列", guild=GUILD)
async def play(interaction: discord.Interaction, keyword: str, result: app_commands.Range[int, 1, 10] = None):
    voice_state = interaction.user.voice
    if voice_state is None or not isinstance(voice_state.channel, discord.VoiceChannel):
        await interaction.response.send_message("请先加入普通语音频道。", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        selection = re.fullmatch(r"qqmid:([A-Za-z0-9]{1,64})", keyword)
        if selection:
            track = await find_song_by_mid(selection[1])
        else:
            keyword = " ".join(keyword.split())
            pending = autocomplete_pending.get(keyword)
            if pending is not None:
                await asyncio.shield(pending)
            cached = autocomplete_cache.get(keyword)
            if cached and cached[0] > asyncio.get_running_loop().time() and cached[2] is not None:
                tracks = cached[2]
            else:
                tracks = await search_songs(keyword, limit=10)
                cache_autocomplete_choices(keyword, tracks)
            if tracks and result is None:
                await interaction.followup.send(
                    "请选择要播放的歌曲。", view=TrackPicker(interaction.user.id, tracks), ephemeral=True
                )
                return
            track = tracks[result - 1] if result is not None and len(tracks) >= result else None
    except Exception as error:
        logger.warning("QQ Music search failed (%s).", type(error).__name__)
        await interaction.followup.send("QQ 音乐搜索失败，请稍后重试。", ephemeral=True)
        return

    message = enqueue_track(interaction.user, track)
    await interaction.followup.send(message, ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
                                    suppress_embeds=True)
    if message.startswith('已加入队列：'):
        await ensure_panel(interaction.channel)


autocomplete_cache = OrderedDict()
autocomplete_pending = {}
autocomplete_latest = {}
autocomplete_cooldown_until = 0.0


def cache_autocomplete_choices(keyword, tracks=None, *, suggestions=()):
    if tracks is not None:
        suggestions = ((track.mid, track_label(track)) for track in tracks)
    choices = {}
    for mid, label in suggestions:
        if label and re.fullmatch(r"[A-Za-z0-9]{1,64}", mid or ""):
            choices.setdefault(mid, app_commands.Choice(name=label[:100], value=f"qqmid:{mid}"))
    result = list(choices.values())[:10]
    autocomplete_cache[keyword] = (asyncio.get_running_loop().time() + 60, result, tracks)
    autocomplete_cache.move_to_end(keyword)
    if len(autocomplete_cache) > 128:
        autocomplete_cache.popitem(last=False)
    return result


async def load_autocomplete_choices(keyword):
    global autocomplete_cooldown_until

    async def fetch(expanded):
        global autocomplete_cooldown_until
        try:
            return expanded, await suggest_songs(client.suggestion_http, keyword, expanded=expanded)
        except aiohttp.ClientResponseError as error:
            if error.status == 429:
                autocomplete_cooldown_until = asyncio.get_running_loop().time() + 10
            logger.info("QQ Music suggestion endpoint returned HTTP %d (expanded=%s).", error.status, expanded)
        except Exception as error:
            logger.info("QQ Music suggestion request failed (%s, expanded=%s).", type(error).__name__, expanded)
        return expanded, []

    matches = {False: [], True: []}
    result = []
    try:
        for pending in asyncio.as_completed((fetch(False), fetch(True))):
            expanded, suggestions = await pending
            matches[expanded] = suggestions
            cached = autocomplete_cache.get(keyword)
            if cached and cached[0] > asyncio.get_running_loop().time() and cached[2] is not None:
                result = cached[1]
            else:
                result = cache_autocomplete_choices(keyword, suggestions=matches[False] + matches[True])
        return result
    finally:
        autocomplete_pending.pop(keyword, None)


@play.autocomplete("keyword")
async def play_autocomplete(interaction: discord.Interaction, current: str):
    user_id = interaction.user.id
    autocomplete_latest[user_id] = interaction.id
    try:
        keyword = " ".join(current.split())
        if not keyword or keyword.startswith("qqmid:"):
            return []

        loop = asyncio.get_running_loop()
        cached = autocomplete_cache.get(keyword)
        if cached and cached[0] > loop.time():
            autocomplete_cache.move_to_end(keyword)
            return cached[1]

        await asyncio.sleep(0.12)
        if autocomplete_latest.get(user_id) != interaction.id:
            return []
        age = max(0, (discord.utils.utcnow() - interaction.created_at).total_seconds())
        budget = 2.75 - age
        if budget <= 0 or loop.time() < autocomplete_cooldown_until:
            return []

        task = autocomplete_pending.get(keyword)
        if task is None:
            if autocomplete_pending:
                return []
            task = autocomplete_pending[keyword] = asyncio.create_task(load_autocomplete_choices(keyword))

        try:
            choices = await asyncio.wait_for(asyncio.shield(task), timeout=budget)
        except TimeoutError:
            cached = autocomplete_cache.get(keyword)
            choices = cached[1] if cached and cached[0] > loop.time() else []
            logger.info("Play autocomplete: returning %d suggestions at the response deadline.", len(choices))
            return choices
        logger.info("Play autocomplete: %d suggestions.", len(choices))
        return choices
    finally:
        if autocomplete_latest.get(user_id) == interaction.id:
            autocomplete_latest.pop(user_id, None)


@commands.command(name="queue", description="查看正在播放的歌曲和队列", guild=GUILD)
async def show_queue(interaction: discord.Interaction):
    lines = [f"当前曲目：{track_title(current_song)}"] if current_song else []
    lines.extend(f"{index}. {track_title(track)}" for index, track in enumerate(list(queue)[:10], 1))
    if len(queue) > 10:
        lines.append(f"另有 {len(queue) - 10} 首待播。")
    if playback_status:
        lines.append(playback_status)
    await interaction.response.send_message("\n".join(lines) or "队列为空。", ephemeral=True,
                                            allowed_mentions=discord.AllowedMentions.none(), suppress_embeds=True)


@commands.command(name="skip", description="跳过当前歌曲", guild=GUILD)
async def skip(interaction: discord.Interaction):
    global skip_requested
    if not await require_music_manager(interaction):
        return
    voice = interaction.guild.voice_client
    if current_song is not None and voice is not None and voice.is_playing():
        skip_requested = True
        voice.stop()
        message = "已跳过当前歌曲。"
    else:
        message = "目前没有正在播放的歌曲。"
    await interaction.response.send_message(message, ephemeral=True)


@commands.command(name="stop", description="停止音乐、清空队列并退出频道", guild=GUILD)
async def stop(interaction: discord.Interaction):
    if not await require_music_manager(interaction):
        return
    task = playback_task
    if task is None or task.done():
        await interaction.response.send_message("目前没有正在播放的队列。", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    async with move_lock:
        if playback_task is task and not task.done() and playback_channel is not None:
            task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    await interaction.followup.send("已停止播放并清空队列。", ephemeral=True)


@commands.command(name="move", description="将播放中的机器人移到你所在的语音频道", guild=GUILD)
async def move(interaction: discord.Interaction):
    global playback_channel
    if not await require_music_manager(interaction):
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    async with move_lock:
        state = interaction.user.voice
        voice = interaction.guild.voice_client
        if state is None or not isinstance(state.channel, discord.VoiceChannel):
            message = "请先加入目标语音频道。"
        elif playback_channel is None or voice is None or not voice.is_connected():
            message = "机器人当前没有连接播放频道。直接在目标频道点歌即可。"
        elif playback_channel == state.channel:
            message = "机器人已在你的频道。"
        else:
            task = playback_task
            target = state.channel
            try:
                await voice.move_to(target, timeout=15)
            except Exception as error:
                logger.warning("Music channel move failed (%s).", type(error).__name__)
                message = "换频道失败，请检查目标频道的连接和讲话权限。"
            else:
                message = "播放已经结束。"
                if playback_task is task and playback_channel is not None:
                    playback_channel = target
                    message = "已将机器人移到你的语音频道。"
    await interaction.followup.send(message, ephemeral=True)


async def show_qq_list(interaction, page, *, liked):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("此命令仅供部署者使用。", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        credential = load_credential()
        if not credential.encrypt_uin:
            await interaction.followup.send("当前 QQ 登录凭据缺少歌单查询所需的账号标识。", ephemeral=True)
            return
        async with Client(credential=credential) as qq:
            async with asyncio.timeout(25):
                if liked:
                    response = await qq.user.get_fav_song(credential.encrypt_uin, page=page, num=10)
                    items = response.songs
                    title = "我喜欢"
                else:
                    response = await qq.user.get_fav_songlist(credential.encrypt_uin, page=page, num=10)
                    items = response.playlists
                    title = "收藏歌单"
    except FileNotFoundError:
        await interaction.followup.send("请先在电脑上运行 QQ 音乐扫码登录。", ephemeral=True)
        return
    except Exception as error:
        logger.warning("QQ Music list request failed (%s).", type(error).__name__)
        await interaction.followup.send("读取失败。请在电脑上运行 QQ 登录检查命令。", ephemeral=True)
        return

    lines = []
    for index, item in enumerate(items, start=(page - 1) * 10 + 1):
        name = getattr(item, "title", None) or getattr(item, "name", None) or "未命名"
        name = discord.utils.escape_markdown(" ".join(name.split())[:65])
        lines.append(f"{index}. {name}")
    body = "\n".join(lines) or "这一页没有内容。"
    await interaction.followup.send(
        f"**{title} · 第 {page} 页**\n{body}",
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none(),
        suppress_embeds=True,
    )


@commands.command(name="liked", description="查看 QQ 音乐「我喜欢」", guild=GUILD)
async def liked(interaction: discord.Interaction, page: app_commands.Range[int, 1] = 1):
    await show_qq_list(interaction, page, liked=True)


@commands.command(name="playlists", description="查看 QQ 音乐收藏歌单", guild=GUILD)
async def playlists(interaction: discord.Interaction, page: app_commands.Range[int, 1] = 1):
    await show_qq_list(interaction, page, liked=False)


@commands.command(name="voice-test", description="Play a short test tone.", guild=GUILD)
async def voice_test(interaction: discord.Interaction):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("此命令仅供部署者使用。", ephemeral=True)
        return

    voice_state = interaction.user.voice
    if voice_state is None or not isinstance(voice_state.channel, discord.VoiceChannel):
        await interaction.response.send_message("请先加入普通语音频道。", ephemeral=True)
        return

    if test_lock.locked() or (playback_task is not None and not playback_task.done()):
        await interaction.response.send_message("已有语音测试正在运行。", ephemeral=True)
        return

    async with test_lock:
        await interaction.response.defer(ephemeral=True, thinking=True)
        voice = None
        source = None
        try:
            voice = await voice_state.channel.connect(timeout=20, reconnect=False)
            await wait_for_voice_encryption(voice)
            logger.info("Voice connection established. Starting test tone.")
            tone = source = TestTone()
            loop = asyncio.get_running_loop()
            finished = loop.create_future()

            def complete(error):
                if not finished.done():
                    finished.set_result(error)

            voice.play(source, after=lambda error: loop.call_soon_threadsafe(complete, error))
            source = None
            error = await asyncio.wait_for(finished, timeout=10)
            if error is not None:
                raise error
            logger.info("Test tone finished. PCM frames read: %d.", tone.frames_read)
            if tone.frames_read == 0:
                result = "FFmpeg 没有产出测试音，请查看容器日志。"
            else:
                result = "测试音播放流程已结束。请确认你听到了约五秒的测试音。"
        except Exception as error:
            logger.error("Voice test failed (%s).", type(error).__name__)
            result = "语音测试失败。请检查频道权限和容器日志。"
        finally:
            if source is not None:
                source.cleanup()
            if voice is not None:
                try:
                    await voice.disconnect(force=True)
                except Exception as error:
                    logger.error("Voice disconnect failed (%s).", type(error).__name__)

        await interaction.followup.send(result, ephemeral=True)


if __name__ == "__main__":
    token = TOKEN_PATH.read_text(encoding="utf-8-sig").strip()
    if not token:
        raise SystemExit("Discord token file is empty.")
    try:
        client.run(token, log_handler=None)
    except discord.LoginFailure:
        raise SystemExit("Discord rejected the bot token.") from None
