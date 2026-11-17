"""Discord Components V2 music player presentation."""
import discord


def clock(seconds):
    seconds = max(0, int(seconds or 0))
    return f'{seconds // 60}:{seconds % 60:02d}'


class PlayerView(discord.ui.LayoutView):
    def __init__(self, state, action):
        super().__init__(timeout=None)
        active = state.get('active', False)
        paused = state.get('paused', False)
        heading = '⏸ 已暂停' if paused else ('♫ 正在播放' if active else '♫ 播放结束')
        title = discord.utils.escape_markdown(state.get('title') or '准备播放…')[:250]
        details = discord.ui.TextDisplay(f'### {title}\n-# QQ MUSIC · 音乐播放器')
        cover = state.get('cover')
        body = discord.ui.Section(details, accessory=discord.ui.Thumbnail(cover)) if cover else details
        duration = state.get('duration', 0) or 0
        elapsed = max(0, state.get('elapsed', 0) or 0)
        filled = min(16, int(elapsed / duration * 16)) if duration else 0
        progress = '━' * filled + '●' + '─' * (16 - filled)
        channel = state.get('channel') or '未连接'
        info = f'`{clock(elapsed)}` {progress} `{clock(duration)}`\n\n🔊 {channel}　 ·　待播 **{state.get("queue_size", 0)}** 首'
        row = discord.ui.ActionRow()
        for name, label, emoji, style in (
            ('pause', '继续' if paused else '暂停', '▶️' if paused else '⏸️', discord.ButtonStyle.primary),
            ('skip', '下一首', '⏭️', discord.ButtonStyle.secondary),
            ('stop', '停止', '⏹️', discord.ButtonStyle.danger),
            ('queue', '队列', '📋', discord.ButtonStyle.secondary),
        ):
            button = discord.ui.Button(label=label, emoji=emoji, style=style,
                                       custom_id=f'music:{name}', disabled=not active and name != 'queue')
            async def callback(interaction, command=name):
                await action(command, interaction)
            button.callback = callback
            row.add_item(button)
        children = [discord.ui.TextDisplay(f'## {heading}'), discord.ui.Separator(), body,
                    discord.ui.TextDisplay(info)]
        if state.get('status'):
            children.append(discord.ui.TextDisplay(discord.utils.escape_markdown(state['status'])[:500]))
        children.extend([discord.ui.Separator(), row, discord.ui.TextDisplay('-# 点歌请使用 /play · 所有成员均可操作')])
        self.add_item(discord.ui.Container(*children, accent_colour=0xA78BFA))
