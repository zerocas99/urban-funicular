import os
import base64
import json
import asyncio
import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.filters import Command

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import io

BOT_TOKEN = os.getenv("BOT_TOKEN")
GDRIVE_SA_B64 = os.getenv("GDRIVE_SA_B64")
GDRIVE_FOLDER_ID = os.getenv("GDRIVE_FOLDER_ID")

if not BOT_TOKEN or not GDRIVE_SA_B64 or not GDRIVE_FOLDER_ID:
    raise RuntimeError("Missing env vars")

# Google Drive client
sa_info = json.loads(base64.b64decode(GDRIVE_SA_B64).decode())
creds = service_account.Credentials.from_service_account_info(
    sa_info,
    scopes=["https://www.googleapis.com/auth/drive"]
)
drive = build("drive", "v3", credentials=creds, cache_discovery=False)

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def start(m: Message):
    await m.reply(
        "Пришли мне файл или прямую ссылку.\n"
        "Я загружу файл в Google Drive и пришлю ссылку."
    )

async def upload_to_drive(data: bytes, filename: str):
    media = MediaIoBaseUpload(io.BytesIO(data), resumable=True)
    meta = {"name": filename, "parents": [GDRIVE_FOLDER_ID]}
    f = drive.files().create(body=meta, media_body=media, fields="id").execute()
    drive.permissions().create(
        fileId=f["id"],
        body={"type": "anyone", "role": "reader"}
    ).execute()
    link = drive.files().get(fileId=f["id"], fields="webViewLink").execute()
    return link["webViewLink"]

@dp.message(F.document)
async def doc(m: Message):
    await m.reply("Скачиваю файл из Telegram…")
    f = await bot.get_file(m.document.file_id)
    url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{f.file_path}"

    async with aiohttp.ClientSession() as s:
        async with s.get(url) as r:
            data = await r.read()

    link = await upload_to_drive(data, m.document.file_name)
    await m.reply(f"Загружено в Drive:\n{link}")

@dp.message(F.text.startswith("http"))
async def url_handler(m: Message):
    await m.reply("Скачиваю по ссылке…")

    async with aiohttp.ClientSession() as s:
        async with s.get(m.text) as r:
            if r.status != 200:
                await m.reply("Ошибка скачивания")
                return
            data = await r.read()

    name = m.text.split("/")[-1].split("?")[0] or "file.bin"
    link = await upload_to_drive(data, name)
    await m.reply(f"Загружено в Drive:\n{link}")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())