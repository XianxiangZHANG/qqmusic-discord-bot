# QQ Music Discord Bot

自托管的 Discord 音乐机器人。服务器成员可以搜索 QQ 音乐、选择歌曲并在语音频道一起听。部署者可扫码登录自己的 QQ 音乐账号，查看「我喜欢」和收藏歌单。

## 功能和权限

| 功能 | 谁可以使用 |
| --- | --- |
| 搜索、点歌和查看队列 | 当前服务器的所有成员 |
| 切歌、停止和移动机器人 | 部署者及服务器管理员 |
| 查看个人收藏和播放测试音 | 部署者 |

一套配置对应一个 Discord 服务器，同一时间在一个语音频道播放。机器人空闲时加入点歌人所在的普通语音频道。播放期间，同频道成员可以继续加歌。队列播完后自动离开。

## 首次部署

### 1. 准备 Docker 和项目

Windows 启动 Docker Desktop，使用 Linux 容器。Linux 主机可使用 Docker Engine 和 Docker Compose。主机需要能连接 QQ 音乐和 Discord，并支持 Discord 语音使用的 UDP 通信。

```powershell
docker compose version
docker run --rm hello-world
```

已有项目时，直接进入项目目录。本机部署路径为 `C:\study\QQmusicBot`。从 GitHub 获取代码时，先登录有权访问仓库的账号：

```powershell
git clone https://github.com/XianxiangZHANG/qqmusic-discord-bot.git
Set-Location qqmusic-discord-bot
```

### 2. 创建并邀请 Discord 机器人

1. 在 [Discord Developer Portal](https://discord.com/developers/applications) 创建应用。打开 **Bot** 页面，获取 **Bot Token**。
2. 打开 **Installation**，启用 **Guild Install**，选择 **Discord Provided Link**。
3. 在 **Default Install Settings → Guild Install** 添加 `bot` 和 `applications.commands`，为机器人勾选 **View Channels**、**Send Messages**、**Connect** 和 **Speak**。
4. 保存后打开安装链接，选 **Add to Server**，选择你有「管理服务器」权限的服务器。
5. 在 Discord 的 **用户设置 → 高级** 启用开发者模式。右键服务器图标复制**服务器 ID**，右键自己的头像复制**用户 ID**。

### 3. 配置本机文件

以下命令在项目目录执行：

```powershell
if (!(Test-Path -LiteralPath '.env')) { Copy-Item '.env.example' '.env' }
New-Item -ItemType Directory -Path 'secrets' -Force | Out-Null
notepad .env
```

在 `.env` 填入两个数字 ID：

```dotenv
DISCORD_GUILD_ID=你的服务器数字ID
DISCORD_OWNER_ID=你的用户数字ID
```

启动前运行 `notepad .\secrets\discord_token.txt`，将 **Bot Token** 单独粘贴到第一行并保存。确认 `discord_token.txt` 是普通文件。

### 4. 启动并验证

```powershell
docker compose -p discord-voice-test up --build -d
docker compose -p discord-voice-test ps
docker compose -p discord-voice-test logs --tail 50 bot
```

看到 `Discord connected. Music commands are registered.` 后，部署者可加入普通语音频道，在服务器文字频道执行 `/voice-test`，确认能听到约五秒的测试音。后续操作沿用同一个 Compose 项目名。

### 5. 扫码连接 QQ 音乐

```powershell
docker compose -p discord-voice-test run --rm --no-deps bot python -u qq_login.py login
```

保持终端运行，在文件资源管理器打开提示的二维码图片，再用手机 QQ 扫码确认。如果 QQ 音乐账号使用微信登录，在命令末尾加 `--method wx` 并用微信扫码。登录凭据保存在 `qq-data/credential.json`，脚本还会尝试读取「我喜欢」和收藏歌单。

检查已有登录是否有效：

```powershell
docker compose -p discord-voice-test run --rm --no-deps bot python -u qq_login.py check
```

## 在 Discord 里点歌

1. 加入普通语音频道，在同一服务器的文字频道选择 **QQ Music Bot** 的 `/play`。
2. 在 `keyword` 输入歌名，可以加歌手，例如 `周杰伦 枫`。
3. 输入时下拉最多显示 10 条建议。选中要听的版本，再发送命令。
4. 下拉为空或没有想要的版本时，直接发送关键词并留空 `result`。机器人会返回最多 10 首的选歌菜单，选中后加入队列。
5. 已知搜索序号时，填 `result:1` 至 `result:10` 可直接点歌。

| 命令 | 用途 |
| --- | --- |
| `/search keyword:枫` | 查看前 5 条搜索结果。 |
| `/play keyword:周杰伦 枫` | 从实时下拉或发送后的菜单选择歌曲。 |
| `/play keyword:枫 result:1` | 把普通搜索的第一条加入队列。 |
| `/queue` | 查看当前曲目、待播歌曲和最近的播放提示。 |
| `/skip` | 跳过当前歌曲。 |
| `/stop` | 停止播放、清空队列并退出语音频道。 |
| `/move` | 将播放中的机器人移到你所在的语音频道。先加入目标频道再执行。 |
| `/liked page:1` | 查看「我喜欢」，每页 10 首。 |
| `/playlists page:1` | 查看收藏歌单，每页 10 个。 |
| `/voice-test` | 播放约五秒的测试音。 |

收藏结果只对部署者显示。想播放收藏中的某首歌，可以用歌名和歌手执行 `/play`。QQ 音源是否可播取决于账号、曲目、地区及接口状态。请只播放你获准在频道播放的内容。

## 日常运行和迁移

```powershell
docker compose -p discord-voice-test up -d
docker compose -p discord-voice-test logs -f bot
docker compose -p discord-voice-test stop
```

三条命令分别用于启动、跟踪日志和停止。跟踪日志时按 `Ctrl+C` 可以退出日志查看。更新代码后用 `docker compose -p discord-voice-test up --build -d` 重建。使用后台模式启动后，关掉 PowerShell 不影响运行。完全退出 Docker Desktop 或关机后，机器人会离线。

迁移到云主机时，在新主机部署相同项目，配置 `.env` 和 Token，然后重新扫码或私下迁移已有登录凭据。先停止旧实例，再用同一个 Discord Bot Token 启动新实例，无需重新邀请。分别测试 `/voice-test` 和 QQ 歌曲播放，确认新主机的语音和音源都可用。

**凭据文件**包括 `secrets/discord_token.txt` 和 `qq-data/credential.json`。这两处以及本机 `.env` 都已被 Git 忽略。备份和迁移时请私下传输，避免贴到聊天、提交到仓库或写进镜像。

## 常见问题

| 现象 | 检查方法 |
| --- | --- |
| 机器人上线前看不到命令 | 检查容器日志、服务器 ID 和安装时的 `applications.commands` 范围。 |
| 容器提示 Token 路径是目录 | 确认 `secrets/discord_token.txt` 是文件，然后执行 `docker compose -p discord-voice-test up -d --force-recreate`。 |
| 能进语音频道但没声音 | 先跑 `/voice-test`，检查频道讲话权限、服务器静音和个人音量。如果日志显示 DAVE 超时，确认镜像使用 Dockerfile 固定的 `discord.py 2.7.1` 和 `davey 0.1.7`。 |
| 实时联想为空或条数较少 | QQ 音乐接口可能返回较少结果或没赶上 Discord 的响应时限。直接发送关键词并留空 `result`，等待选歌菜单。 |
| 某首歌播不了或提前结束 | 执行 `/queue` 查看提示，再检查容器日志。若 `audio_seconds` 比 `catalog_seconds` 短很多，对照同一版本在 QQ 音乐客户端的时长。 |
| 收藏列表读不出来 | 运行 `qq_login.py check` 的检查命令。凭据失效时重新扫码。 |

## 项目文件

- `bot.py` 处理 Discord 命令、实时联想、选歌菜单、队列和语音控制。
- `qq_provider.py` 连接 QQ 音乐搜索、联想和音源接口。
- `qq_login.py` 处理本机扫码、凭据保存和登录检查。
- `Dockerfile` 和 `compose.yaml` 定义运行环境与本机文件挂载。

项目使用 Python、discord.py、FFmpeg 和非官方 QQMusicApi。QQ 音乐接口变更可能影响登录、搜索或播放。
# 聊天播放器

使用 `/play` 点歌并选中歌曲后，机器人会在文字频道发送 Components V2 播放器卡片。
卡片显示歌曲、专辑封面（有专辑信息时）、音频进度、语音频道和待播数量，每 10 秒刷新。
所有成员均可点击暂停／继续、下一首、停止及查看队列；现有斜杠命令的管理权限保持原样。
机器人需要在文字频道拥有查看频道、发送消息和读取消息历史的权限。
每次成功点歌后，会在最新消息位置发送新卡片并删除上一张卡片；进度刷新仍编辑当前卡片。点歌失败不会替换卡片。
播放结束后控制按钮会禁用。重启后旧卡片不再响应，重新点歌会创建新卡片（重启前的卡片需手动删除）。

音源自动优先请求账号及歌曲可用的最高立体声音质：臻品母带 → 臻品音质 → FLAC → 高码率 OGG/MP3 → 标准及流畅音质。
单档请求失败或超时后会尝试下一档，日志中的 `Selected QQ Music source quality` 显示最终选用的档位。
当前不支持直接播放 QQ 专用加密格式；Discord 语音输出仍会转为 Opus。
