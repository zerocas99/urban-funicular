import os
import json
import base64
import asyncio
import tempfile
import subprocess
import aiohttp

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.filters import Command

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


BOT_TOKEN = os.getenv("BOT_TOKEN")
GDRIVE_FOLDER_ID = os.getenv("GDRIVE_FOLDER_ID")

# Render удобнее хранить как JSON целиком
GDRIVE_SA_JSON = os.getenv("GDRIVE_SA_JSON")
GDRIVE_SA_B64 = os.getenv("GDRIVE_SA_B64")

MAX_DOWNLOAD_MB = int(os.getenv("MAX_DOWNLOAD_MB", "1500"))
MAX_DOWNLOAD_BYTES = MAX_DOWNLOAD_MB * 1024 * 1024

HLS_MAX_DURATION_SEC = int(os.getenv("HLS_MAX_DURATION_SEC", "0"))  # 0 = без проверки длительности

if not BOT_TOKEN or not GDRIVE_FOLDER_ID:
    raise RuntimeError("Missing BOT_TOKEN or GDRIVE_FOLDER_ID")

if not (GDRIVE_SA_JSON or GDRIVE_SA_B64):
    raise RuntimeError("Missing GDRIVE_SA_JSON or GDRIVE_SA_B64")


def get_sa_info() -> dict:
    if GDRIVE_SA_JSON:
        return json.loads(GDRIVE_SA_JSON)
    return json.loads(base64.b64decode(GDRIVE_SA_B64).decode("utf-8"))


sa_info = get_sa_info()
creds = service_account.Credentials.from_service_account_info(
    sa_info, scopes=["https://www.googleapis.com/auth/drive"]
)
drive = build("drive", "v3", credentials=creds, cache_discovery=False)

bot = Bot(BOT_TOKEN)
dp = Dispatcher()


def safe_filename(name: str) -> str:
    name = (name or "file.bin").strip()
    name = name.replace("/", "_").replace("\\", "_")
    return name[:180] if name else "file.bin"


async def download_to_temp(url: str, suggested_name: str) -> tuple[str, str]:
    filename = safe_filename(suggested_name)

    fd, path = tempfile.mkstemp(prefix="dl_", suffix="_" + filename)
    os.close(fd)

    total = 0
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=300)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, allow_redirects=True) as r:
            if r.status != 200:
                raise RuntimeError(f"Download failed: HTTP {r.status}")

            cl = r.headers.get("Content-Length")
            if cl and int(cl) > MAX_DOWNLOAD_BYTES:
                raise RuntimeError(f"File too large ({int(cl)//(1024*1024)} MB)")

            with open(path, "wb") as f:
                async for chunk in r.content.iter_chunked(1024 * 256):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > MAX_DOWNLOAD_BYTES:
                        raise RuntimeError(f"Exceeded limit {MAX_DOWNLOAD_MB} MB")
                    f.write(chunk)

    return path, filename


def ffmpeg_hls_to_mp4(m3u8_url: str, out_path: str) -> None:
    """
    Скачивает HLS и собирает MP4 через ffmpeg.
    Важно: работает только если m3u8 и сегменты доступны без обхода защит (без 403/DRM).
    """
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-y",
        "-i", m3u8_url,
        "-c", "copy",
        "-bsf:a", "aac_adtstoasc",
        out_path
    ]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        err = (p.stderr or "").strip()
        raise RuntimeError(f"ffmpeg failed: {err[:800]}")


def upload_file_to_drive(local_path: str, filename: str) -> str:
    media = MediaFileUpload(local_path, resumable=True)
    meta = {"name": filename, "parents": [GDRIVE_FOLDER_ID]}
    created = drive.files().create(body=meta, media_body=media, fields="id").execute()

    # Публичная ссылка (если не нужно — скажи, уберу)
    drive.permissions().create(
        fileId=created["id"],
        body={"type": "anyone", "role": "reader"},
    ).execute()

    link = drive.files().get(fileId=created["id"], fields="webViewLink").execute()
    return link["webViewLink"]


@dp.message(Command("start"))
async def start(m: Message):
    await m.reply(
        "Пришли:\n"
        "1) прямую ссылку (http/https) на файл\n"
        "2) или ссылку на .m3u8 (HLS)\n\n"
        "Я скачаю и загружу в Google Drive.\n"
        "⚠️ Если HLS защищён (403/DRM/нужны куки) — не получится."
    )


@dp.message(F.document)
async def on_document(m: Message):
    await m.reply("Ок, скачиваю файл из Telegram…")

    tg_file = await bot.get_file(m.document.file_id)
    url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{tg_file.file_path}"

    path = None
    try:
        path, filename = await download_to_temp(url, m.document.file_name or "telegram_file.bin")
        await m.reply("Загрузил, отправляю в Google Drive…")
        link = upload_file_to_drive(path, filename)
        await m.reply(f"Готово ✅\n{link}")
    except Exception as e:
        await m.reply(f"Ошибка: {e}")
    finally:
        if path and os.path.exists(path):
            try: os.remove(path)
            except: pass


@dp.message(F.text.startswith("http"))
async def on_url(m: Message):
    url = m.text.strip()
    lower = url.lower()

    path = None
    try:
        # HLS
        if ".m3u8" in lower:
            await m.reply("Это HLS (.m3u8). Собираю MP4 через ffmpeg…")

            filename = safe_filename((url.split("/")[-1].split("?")[0] or "video") + ".mp4")
            fd, out_path = tempfile.mkstemp(prefix="hls_", suffix="_" + filename)
            os.close(fd)

            path = out_path
            ffmpeg_hls_to_mp4(url, out_path)

            await m.reply("Готово. Загружаю в Google Drive…")
            link = upload_file_to_drive(out_path, filename)
            await m.reply(f"Готово ✅\n{link}")
            return

        # обычный файл
        name_guess = url.split("/")[-1].split("?")[0] or "file.bin"
        await m.reply("Ок, скачиваю по ссылке…")
        path, filename = await download_to_temp(url, name_guess)

        await m.reply("Скачал. Загружаю в Google Drive…")
        link = upload_file_to_drive(path, filename)
        await m.reply(f"Готово ✅\n{link}")

    except Exception as e:
        await m.reply(f"Ошибка: {e}")
    finally:
        if path and os.path.exists(path):
            try: os.remove(path)
            except: pass


async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
