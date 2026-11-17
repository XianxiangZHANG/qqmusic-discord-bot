# QQ Music Discord Bot

自托管的 QQ 音乐 Discord 机器人，支持搜索点歌、语音播放、交互式播放器和三行同步歌词。通过 Docker Compose 部署，QQ 音乐账号由部署者在本机扫码登录。

项目使用非官方 QQ 音乐接口，与 QQ 音乐及 Discord 官方无隶属关系。歌曲可用性取决于账号权限、歌曲版本、地区及上游服务状态。

## 功能

- **搜索点歌**：实时联想，或通过搜索结果下拉菜单选歌。
- **语音队列**：最多 25 首待播歌曲，播完自动退出语音频道。
- **Components V2 播放器**：歌曲、歌手、封面、进度、语音频道及队列数量；支持暂停／继续、下一首、停止和查看队列。
- **三行同步歌词**：上一句、当前句、下一句，当前句加粗；按音频进度更新，暂停时停留。
- **最高可用音质优先**：从高到低请求音源；播放开始前失败时，先切换同档 CDN，再降低音质。
- **个人收藏**：部署者可以查看登录账号的「我喜欢」及收藏歌单。
- **语音诊断**：五秒测试音，用来区分语音连接与 QQ 音源问题。

当前适合**一个 Discord 服务器、同一时间一个普通语音频道**。队列和卡片引用保存在内存中，不支持重启恢复。

## 使用权限

| 入口 | 可使用者 |
| --- | --- |
| `/search`、`/play`、`/queue` | 服务器成员；点歌需加入普通语音频道，播放期间须与机器人同频道 |
| 卡片上的暂停／继续、下一首、停止、队列按钮 | **能看到卡片的所有成员**，不检查管理员身份或是否在语音频道 |
| `/skip`、`/stop`、`/move` | 配置的部署者及服务器管理员 |
| `/liked`、`/playlists`、`/voice-test` | 配置的部署者 |

卡片按钮与斜杠命令的权限规则不同，请把卡片放在你愿意开放控制的文字频道中。

## 环境要求

- Docker Engine / Docker Desktop，以及 Docker Compose v2；Windows 使用 Linux 容器。
- 主机能访问 Discord、QQ 音乐接口及音频 CDN，并允许 Discord 语音所需的 UDP 通信。
- 一个 Discord 应用、Bot Token，以及有权安装机器人的服务器。
- 建议准备 QQ 音乐账号；登录不保证任意歌曲或音质都可播放。

镜像使用 Python 3.12、FFmpeg、`discord.py[voice]==2.7.1`、`davey==0.1.7` 和 `qqmusic-api-python==0.7.3`。Docker 部署无需在宿主机另外安装 Python 或 FFmpeg。

## 快速部署

以下命令以 **PowerShell** 为例，在项目目录执行。

### 1. 获取项目

```powershell
git clone https://github.com/XianxiangZHANG/qqmusic-discord-bot.git
cd qqmusic-discord-bot
docker compose version
```

本文使用默认 Compose 项目名。若已有实例使用 `-p 自定义名称` 启动，后续所有命令都应带上同一个 `-p`，避免重复启动同一个机器人。

### 2. 创建并邀请 Discord 机器人

在 [Discord Developer Portal](https://discord.com/developers/applications) 创建应用并获取 Bot Token，使用包含 `bot` 和 `applications.commands` 范围的服务器安装链接邀请机器人。

机器人在目标频道需要：

- **View Channels**、**Send Messages**、**Read Message History**。
- 语音频道的 **Connect** 和 **Speak**。

无需为了删除机器人自己发送的旧卡片而授予 **Manage Messages**，也无需授予 **Administrator**。代码使用默认 Intents，不要求启用 Message Content 特权 Intent。

在 Discord「用户设置 → 高级」中启用开发者模式，复制目标服务器 ID 和部署者用户 ID。

### 3. 创建本机配置

```powershell
if (!(Test-Path -LiteralPath '.env')) { Copy-Item '.env.example' '.env' }
New-Item -ItemType Directory -Path secrets -Force | Out-Null
notepad .env
```

填写自己的数字 ID：

```dotenv
DISCORD_GUILD_ID=你的服务器数字ID
DISCORD_OWNER_ID=你的用户数字ID
```

创建 Token 文件，将 Bot Token 单独放在第一行并保存：

```powershell
notepad .\secrets\discord_token.txt
```

确认 `discord_token.txt` 是普通文件，不是目录。

| 文件 | 用途 | 是否提交 Git |
| --- | --- | --- |
| `.env.example` | 空白配置模板 | 是 |
| `.env` | 本机服务器 ID、部署者 ID | 否 |
| `secrets/discord_token.txt` | Discord Bot Token | 否 |
| `qq-data/credential.json` | 扫码后生成的 QQ 音乐登录凭据 | 否 |

`.gitignore` 已忽略本机配置、凭据、缓存及测试依赖；`.dockerignore` 仅允许应用源码和 Dockerfile 进入构建上下文。Token 通过 Compose secret 挂载，QQ 登录数据通过目录挂载，不写入镜像。

### 4. 构建并启动

```powershell
docker compose up -d --build
docker compose ps
docker compose logs --tail 50 bot
```

看到 `Discord connected. Music commands are registered.` 后，部署者加入普通语音频道并执行 `/voice-test`，确认能听到约五秒的测试音。

命令仅注册到 `.env` 指定的服务器。不要同时用同一个 Bot Token 启动多个实例。

### 5. 扫码登录 QQ 音乐

```powershell
docker compose run --rm --no-deps bot python -u qq_login.py login
```

保持终端运行，打开提示路径下的二维码图片，用手机 QQ 扫码确认。二维码位于项目的 `qq-data` 临时子目录，登录流程结束后清理。

微信登录账号使用：

```powershell
docker compose run --rm --no-deps bot python -u qq_login.py login --method wx
```

凭据保存到 `qq-data/credential.json`。脚本随后检查登录状态并尝试读取收藏；收藏检查失败不一定代表凭据未保存。

检查已有登录：

```powershell
docker compose run --rm --no-deps bot python -u qq_login.py check
```

未登录时程序会尝试匿名请求，不保证音源可用。高品质或受限歌曲需要账号具有对应访问权限。

## 点歌与控制

1. 加入普通语音频道，在文字频道输入 `/play`。
2. 在 `keyword` 输入歌名及歌手，从实时联想中选择版本并发送。
3. 没有合适联想时，直接发送关键词并留空 `result`，等待下拉选歌菜单。
4. 选中歌曲后入队，机器人在聊天最新位置发送卡片，并删除上一次记录的卡片。

搜索或入队失败时不替换卡片；切歌和进度刷新继续编辑当前卡片。重启后机器人不再记得旧卡片，重启前遗留的卡片需手动删除。

| 命令 | 用途 |
| --- | --- |
| `/search keyword:歌名` | 查看前 5 条搜索结果 |
| `/play keyword:歌名 歌手` | 从实时联想或最多 10 项的下拉菜单点歌 |
| `/play keyword:歌名 result:1` | 将普通搜索第 1 条结果入队，序号范围 1–10 |
| `/queue` | 查看当前歌曲、前 10 首待播歌曲及播放提示 |
| `/skip` | 跳过当前播放的歌曲 |
| `/stop` | 停止、清空队列并退出语音频道 |
| `/move` | 移到执行者所在的普通语音频道 |
| `/liked page:1` | 查看部署者「我喜欢」，每页 10 首 |
| `/playlists page:1` | 查看部署者收藏歌单，每页 10 个 |
| `/voice-test` | 播放约五秒的测试音 |

收藏列表仅向部署者显示，当前不支持点击收藏直接点歌，可用歌名及歌手执行 `/play`。

### 音源与音质

搜索联想和实际音源使用不同接口：能搜到歌曲不代表对应版本或音质一定可播放。音频由 QQ 音乐接口返回地址，再从 QQ 音乐 CDN 读取。

音质优先顺序：

```text
臻品母带 → 臻品音质 → FLAC → OGG 640 → OGG 320 → MP3 320
→ AAC 192 → OGG 192 → MP3 128 → AAC 96 → OGG 96 → AAC 48
```

当前不直接解码 QQ 专用加密文件。Discord 输出仍转为 Opus，高品质输入不代表端到端无损播放。

开始播放前，FFmpeg 读取失败、返回 404 或无法解码时，先尝试同档其他 CDN，再请求下一档音质；全部失败才跳过。日志中的 `Trying QQ Music source quality` 记录当前候选的音质及 CDN 序号。

手动切歌不重试。已经播出音频后的故障不会通过换源从头重播；FFmpeg 按现有参数尝试网络重连，提前结束时记录已播时长和曲库标注时长。

### 歌词与进度

进度条上方显示上一句、当前句、下一句；当前句加粗，上下句以小字显示。歌词按 LRC 时间戳匹配音频输出帧，暂停时保持当前句。

每约 2 秒检查歌词，换行时刷新卡片；没有换行时约每 10 秒刷新进度。网络和 Discord 限流可能导致延迟。歌词获取失败或没有时间戳时显示「暂无同步歌词」，不影响播放。

进度条只作显示，不支持拖动定位。

## 更新、停止和迁移

```powershell
# 更新并重建；重启会中断播放及清空内存队列
git pull --ff-only
docker compose up -d --build

# 查看日志；Ctrl+C 仅退出日志查看
docker compose logs -f bot

# 停止，保留本机配置和登录文件
docker compose stop

# 再次启动
docker compose up -d
```

后台运行后可以关闭终端；主机关机、Docker 停止或容器停止时机器人离线。当前 Compose 配置未设置自动重启策略。

迁移前先停止旧实例，在新主机获取代码，配置 `.env`、Bot Token，再重新扫码或私下迁移 `qq-data/credential.json`。不要将凭据贴入 Issue、截图或公开日志。完成后分别验证测试音、搜索和歌曲播放。

## 常见问题

| 现象 | 检查方式 |
| --- | --- |
| 看不到命令 | 检查日志、`DISCORD_GUILD_ID` 及安装链接的 `applications.commands` 范围 |
| Token 路径被识别为目录 | 确保 `secrets/discord_token.txt` 是普通文件，修正后运行 `docker compose up -d --force-recreate` |
| 能进语音频道但没声音 | 先执行 `/voice-test`，检查 Connect/Speak 权限、静音、个人音量及 UDP 网络 |
| DAVE 超时 | 使用 Dockerfile 固定版本重新构建，并检查语音连接日志 |
| 联想为空或较慢 | 直接发送关键词并留空 `result`，使用发送后的选歌菜单 |
| 能搜索但音源 404 | 检查是否继续尝试其他 CDN 和较低音质；全部失败时可尝试其他歌曲版本 |
| 歌曲提前结束 | 查看 `/queue`，对比日志的 `audio_seconds`、`catalog_seconds`，检查上游断流及版本差异 |
| 没有卡片或旧卡片未清理 | 检查文字频道权限和日志；重启前的卡片需要手动删除 |
| 按钮没有响应 | 点击当前实例新生成的卡片，检查容器异常日志并更新代码 |
| 歌词不显示或滞后 | 检查歌词获取日志；部分歌曲没有同步歌词，显示受时间戳及网络影响 |
| 登录或收藏失效 | 执行 `qq_login.py check`，必要时重新扫码；设备数量限制需先在账号侧处理 |

## 开发与测试

测试使用 Python 标准库 `unittest`，不需要额外测试框架。通过镜像挂载源码执行：

```powershell
docker compose build
docker compose run --rm --no-deps --volume "${PWD}:/tests:ro" --workdir /tests bot python -m unittest discover -v
```

这些测试不连接 Discord 语音、不读取真实账号凭据、不真实点歌。覆盖音质选择、CDN 顺序、启动失败重试、手动跳过、歌词解析、三行显示及卡片按钮回调。

| 文件 | 职责 |
| --- | --- |
| `bot.py` | Discord 命令、队列、音频播放、卡片生命周期和刷新 |
| `music_panel.py` | Components V2 布局和按钮 |
| `lyrics.py` | LRC 解析、时间偏移及三行歌词匹配 |
| `qq_provider.py` | QQ 搜索、联想、歌词、音质与 CDN 候选 |
| `qq_login.py` | 扫码、凭据保存和登录检查 |
| `test_*.py` | 回归测试 |
| `Dockerfile`、`compose.yaml` | 镜像及运行配置 |

提交问题时，请提供复现步骤、歌曲名称／版本、错误时间及已脱敏日志；不要提供 Token、QQ 登录凭据或带签名的音源链接。请只播放你有权在频道播放的内容。

## 许可证

本项目采用 [MIT License](LICENSE)。第三方依赖仍遵循各自的许可证。
