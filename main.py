import os
import requests
import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn
import aiofiles
from audio_processor import process_audio

# --- Логирование ---
logging.basicConfig(level=logging.INFO, format="INFO:main:%(message)s")
logger = logging.getLogger("main")

# --- Переменные окружения ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SALEBOT_API_KEY = os.getenv("SALEBOT_API_KEY")

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("❌ TELEGRAM_BOT_TOKEN не задан в переменных окружения")
if not SALEBOT_API_KEY:
    raise ValueError("❌ SALEBOT_API_KEY не задан в переменных окружения")

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

app = FastAPI()


@app.post("/process_audio")
async def process_audio_handler(request: Request):
    data = await request.json()
    voice_url = data.get("voice_url")
    client_id = data.get("client_id")
    name = data.get("name")

    logger.info(f"🎯 /process_audio called")
    logger.info(f"🔍 voice_url={voice_url}, client_id={client_id}, name={name}")

    if not voice_url or not client_id:
        return JSONResponse({"error": "voice_url and client_id are required"}, status_code=400)

    # --- Скачиваем голосовое ---
    voice_filename = f"voice_{os.urandom(16).hex()}.ogg"
    async with aiofiles.open(voice_filename, "wb") as f:
        resp = requests.get(voice_url, timeout=60)
        await f.write(resp.content)
    logger.info(f"📥 Voice saved as {voice_filename} ({len(resp.content)} bytes)")

    # --- Обработка аудио ---
    mixed_file = await process_audio(voice_filename)
    logger.info(f"🎵 Mixed audio created: {mixed_file}")

    # --- Отправляем в Telegram ---
    with open(mixed_file, "rb") as f:
        tg_resp = requests.post(
            f"{TELEGRAM_API}/sendAudio",
            data={"chat_id": client_id, "caption": f"🎶 Ваш микс готов! {name}"},
            files={"audio": f},
            timeout=120
        )

    tg_json = tg_resp.json()
    logger.info(f"📦 Telegram response: {tg_json}")

    # --- Получаем file_id и прямую ссылку ---
    file_id = tg_json["result"]["audio"]["file_id"]
    file_info = requests.get(f"{TELEGRAM_API}/getFile", params={"file_id": file_id}).json()
    file_path = file_info["result"]["file_path"]
    cdn_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
    logger.info(f"🌍 CDN URL: {cdn_url}")

    # --- Сохраняем переменную в Salebot ---
    sb_set_vars_url = "https://api.salebot.pro/v1/set_variables"
    vars_payload = {
        "token": SALEBOT_API_KEY,
        "client_id": str(client_id),
        "variables": {
            "last_mix_url": cdn_url
        }
    }
    sb_vars_resp = requests.post(sb_set_vars_url, json=vars_payload, timeout=30)
    logger.info(f"📨 Salebot set_variables response: {sb_vars_resp.status_code}, {sb_vars_resp.text}")

    # --- Отправляем сообщение в Salebot ---
    sb_send_msg_url = "https://api.salebot.pro/v1/send_message"
    msg_payload = {
        "token": SALEBOT_API_KEY,
        "client_id": str(client_id),
        "message": f"🔗 Ссылка на ваш микс: {cdn_url}"
    }
    sb_msg_resp = requests.post(sb_send_msg_url, json=msg_payload, timeout=30)
    logger.info(f"📨 Salebot send_message response: {sb_msg_resp.status_code}, {sb_msg_resp.text}")

    # --- Удаляем временные файлы ---
    try:
        os.remove(voice_filename)
        logger.info(f"🗑️ Deleted: {voice_filename}")
        os.remove(mixed_file)
        logger.info(f"🗑️ Deleted: {mixed_file}")
    except Exception as e:
        logger.error(f"⚠️ Cleanup error: {e}")

    return JSONResponse({"status": "ok", "cdn_url": cdn_url})


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
