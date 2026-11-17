"""Parse timestamped LRC lyrics and select the line at audio playback time."""
import html
import re

STAMP = re.compile(r'\[(\d+):(\d{2})(?:\.(\d{1,3}))?\]')


def parse_lrc(text):
    text = html.unescape(text or '')
    offset = re.search(r'\[offset:([+-]?\d+)\]', text, re.IGNORECASE)
    offset = int(offset.group(1)) / 1000 if offset else 0
    lines = []
    for raw in text.splitlines():
        stamps = list(STAMP.finditer(raw))
        if not stamps:
            continue
        content = raw[stamps[-1].end():].strip()
        for stamp in stamps:
            minute, second, fraction = stamp.groups()
            if int(second) >= 60:
                continue
            timestamp = int(minute) * 60 + int(second) + float('0.' + (fraction or '0')) - offset
            lines.append((max(0, timestamp), content))
    return sorted(lines, key=lambda line: line[0])


def current_line(lines, elapsed):
    return lyric_context(lines, elapsed)[1]


def lyric_context(lines, elapsed):
    """Return previous, current and next lines, with empty boundary slots."""
    if not lines:
        return ('', '暂无同步歌词', '')
    index = -1
    for position, (timestamp, _) in enumerate(lines):
        if timestamp > elapsed:
            break
        index = position
    previous = lines[index - 1][1] if index > 0 else ''
    current = lines[index][1] if index >= 0 else ''
    following = lines[index + 1][1] if index + 1 < len(lines) else ''
    return previous, current or '♪ 前奏 / 间奏', following
