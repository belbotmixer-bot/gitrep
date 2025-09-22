from flask import Flask, request, jsonify
import os
import uuid
import time
import requests
import logging
from audio_processor import mix_voice_with_music

# --- Логирование ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)

# --- Конфигурация ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
GITHUB_MUSIC_URL = "https://raw.githubusercontent.com/belbotmixer-bot/gitrep/main/background_music.mp3"
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
TELEGRAM_FILE_API_URL = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}"

# --- Salebot callback ---
SALEBOT_API_KEY = os.environ.get("SALEBOT_API_KEY", "YOUR_SALEBOT_API_KEY_HERE")
SALEBOT_CALLBACK_URL = f"https://chatter.salebot.pro/api/{SALEBOT_API_KEY}/callback"

# --- Хранилище результатов ---
RESULTS = {}
RESULT_TTL = 3600  # хранение 1 час

def cleanup(filename, task_id=None):
    try:
        if filename and os.path.exists(filename):
            os.remove(filename)
            logger.info(f"[task_id={task_id}] 🗑️ Deleted: {filename}")
    except Exception as e:
        logger.error(f"[task_id={task_id}] ⚠️ Cleanup error for {filename}: {e}")

def get_direct_url(file_id):
    try:
        resp = requests.get(f"{TELEGRAM_API_URL}/getFile", params={"file_id": file_id}, timeout=30)
        resp.raise_for_status()
        file_path = resp.json()["result"]["file_path"]
        return f"{TELEGRAM_FILE_API_URL}/{file_path}"
    except Exception as e:
        logger.error(f"⚠️ Failed to get direct_url for file_id={file_id}: {e}")
        return None

def send_salebot_callback(client_id, direct_url):
    try:
        callback_url = f"{SALEBOT_CALLBACK_URL}?value_client_id=my_client&value_message=my_message"
        payload = {
            "my_client": client_id,
            "my_message": direct_url
        }
        resp = requests.post(callback_url, json=payload, headers={"Content-Type": "application/json"}, timeout=30)
        resp.raise_for_status()
        logger.info(f"[client_id={client_id}] ✅ Salebot callback sent successfully: {resp.text}")
    except Exception as e:
        logger.error(f"[client_id={client_id}] ❌ Failed to send Salebot callback: {e}")

@app.route("/process_audio", methods=["POST"])
def process_audio():
    task_id = uuid.uuid4().hex[:8]
    logger.info(f"[task_id={task_id}] 🎯 /process_audio called")

    try:
        data = request.get_json(force=True, silent=True) or request.form.to_dict()
        logger.info(f"[task_id={task_id}] 🔍 Incoming data: {data}")

        if not data:
            return jsonify({"error": "No data received", "task_id": task_id}), 400

        voice_url = data.get("voice_url")
        client_id = data.get("client_id")
        name = data.get("name", "")

        if not voice_url or not client_id:
            return jsonify({"error": "voice_url and client_id required", "task_id": task_id}), 400

        voice_filename = f"voice_{task_id}.ogg"
        resp = requests.get(voice_url, timeout=300)
        resp.raise_for_status()
        with open(voice_filename, "wb") as f:
            f.write(resp.content)
        logger.info(f"[task_id={task_id}] 📥 Voice saved as {voice_filename}")

        output_filename = f"mixed_{task_id}.mp3"
        mix_voice_with_music(voice_filename, output_filename, GITHUB_MUSIC_URL)
        logger.info(f"[task_id={task_id}] 🎵 Mixed audio created: {output_filename}")

        # --- Отправляем аудио с кнопкой ---
        direct_url = None
        with open(output_filename, "rb") as audio_file:
            files = {"audio": (f"{task_id}.mp3", audio_file, "audio/mpeg")}
            payload = {
                "chat_id": client_id,
                "caption": f"🎶 Ваш микс готов! {name}" if name else "🎶 Ваш микс готов!",
                "reply_markup": {
                    "inline_keyboard": [[
                        {"text": "Сохранить микс", "url": f"https://chatter.salebot.pro/api/{SALEBOT_API_KEY}/callback?value_client_id={client_id}&value_message=MIX_URL_PLACEHOLDER"}
                    ]]
                }
            }
            tg_resp = requests.post(f"{TELEGRAM_API_URL}/sendAudio", data=payload, files=files, timeout=300)

        tg_json = tg_resp.json()
        logger.info(f"[task_id={task_id}] 📨 Telegram resp: {tg_json}")

        if tg_resp.status_code != 200 or not tg_json.get("ok"):
            return jsonify({"error": "Failed to send audio", "task_id": task_id}), 500

        file_id = tg_json["result"]["audio"]["file_id"]
        direct_url = get_direct_url(file_id)

        # --- Обновляем кнопку ссылкой на реальный direct_url ---
        payload = {
            "chat_id": client_id,
            "message_id": tg_json["result"]["message_id"],
            "reply_markup": {
                "inline_keyboard": [[
                    {"text": "Сохранить микс", "url": f"{SALEBOT_CALLBACK_URL}?value_client_id={client_id}&value_message={direct_url}"}
                ]]
            }
        }
        requests.post(f"{TELEGRAM_API_URL}/editMessageReplyMarkup", json=payload, timeout=30)

        RESULTS[task_id] = {
            "status": "done",
            "file_id": file_id,
            "direct_url": direct_url,
            "client_id": client_id,
            "name": name,
            "created_at": time.time(),
        }

        cleanup(voice_filename, task_id)
        cleanup(output_filename, task_id)

        return jsonify({"task_id": task_id, "file_id": file_id, "direct_url": direct_url})

    except Exception as e:
        logger.error(f"[task_id={task_id}] ❌ Error: {e}")
        return jsonify({"error": str(e), "task_id": task_id}), 500

# --- Остальные маршруты get_result, list_results, health_check остаются без изменений ---
