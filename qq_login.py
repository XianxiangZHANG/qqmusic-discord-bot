import argparse
import asyncio
import logging
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory

from qqmusic_api import Client, Credential
from qqmusic_api.models.login import QRLoginType
from qqmusic_api.modules.login_utils import QRCodeLoginSession

DATA = Path("/qq-data")
CREDENTIAL_PATH = DATA / "credential.json"


def load_credential():
    return Credential.model_validate_json(CREDENTIAL_PATH.read_text(encoding="utf-8"))


def save_credential(credential):
    with NamedTemporaryFile(dir=DATA, delete=False) as output:
        temporary_path = Path(output.name)
    try:
        temporary_path.write_text(credential.model_dump_json(), encoding="utf-8")
        temporary_path.replace(CREDENTIAL_PATH)
    finally:
        temporary_path.unlink(missing_ok=True)


async def login(method):
    async with Client() as client:
        session = QRCodeLoginSession(
            client.login, QRLoginType[method.upper()], interval=1.5, timeout_seconds=180
        )
        with TemporaryDirectory(prefix="scan-", dir=DATA) as folder:
            qr = await session.get_qrcode()
            path = qr.save(folder)
            if path is None:
                raise RuntimeError("QR image unavailable")
            local_path = Path(path).relative_to(DATA)
            print(f"请用手机扫码并确认。Windows 图片路径：.\\qq-data\\{str(local_path).replace('/', chr(92))}")
            credential = await session.wait_qrcode_login()
        save_credential(credential)
        print("QQ 音乐扫码登录成功，凭据已保存到本机。")
        return credential


async def check(credential):
    async with Client(credential=credential) as client:
        if await client.login.check_expired():
            raise SystemExit("QQ 音乐凭据未通过服务端验证，请重新扫码。")
        print("QQ 音乐登录状态验证通过。")
        if not credential.encrypt_uin:
            raise SystemExit("这次登录未返回歌单接口所需的账号标识，歌单读取尚未验证。")
        liked = await client.user.get_fav_song(credential.encrypt_uin, num=10)
        print(f"「我喜欢」读取成功，第一页返回 {len(liked.songs)} 首。")
        playlists = await client.user.get_fav_songlist(credential.encrypt_uin, num=10)
        print(f"收藏歌单读取成功，第一页返回 {len(playlists.playlists)} 个。")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("login", "check"))
    parser.add_argument("--method", choices=("qq", "wx"), default="qq")
    args = parser.parse_args()
    if args.action == "login":
        credential = await login(args.method)
    else:
        if not CREDENTIAL_PATH.is_file():
            raise SystemExit("请先运行 login 完成扫码。")
        credential = load_credential()
    await check(credential)


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        raise SystemExit("已取消。") from None
    except Exception as error:
        raise SystemExit(f"QQ 音乐请求失败（{type(error).__name__}）。") from None
