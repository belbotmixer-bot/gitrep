from flask import Flask, request, jsonify
import os
import uuid
import time
import requests
import logging
import json
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
        resp = requests.post(
            callback_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        resp.raise_for_status()
        logger.info(f"[client_id={client_id}] ✅ Salebot callback sent successfully: {resp.text}")
    except Exception as e:
        logger.error(f"[client_id={client_id}] ❌ Failed to send Salebot callback: {e}")

@app.route("/process_audio", methods=["POST"])
def process_audio():
    """Первый вебхук: Salebot → Render"""
    task_id = uuid.uuid4().hex[:8]
    logger.info(f"[task_id={task_id}] 🎯 /process_audio called")

    try:
        data = request.get_json(force=True, silent=True) or request.form.to_dict()
        logger.info(f"[task_id={task_id}] 🔍 Incoming data: {data}")

        voice_url = data.get("voice_url")
        client_id = data.get("client_id")
        name = data.get("name", "")

        if not voice_url or not client_id:
            return jsonify({"error": "voice_url and client_id required", "task_id": task_id}), 400

        # --- Скачиваем голос ---
        voice_filename = f"voice_{task_id}.ogg"
        resp = requests.get(voice_url, timeout=300)
        resp.raise_for_status()
        with open(voice_filename, "wb") as f:
            f.write(resp.content)
        logger.info(f"[task_id={task_id}] 📥 Voice saved as {voice_filename}")

        # --- Миксуем ---
        output_filename = f"mixed_{task_id}.mp3"
        mix_voice_with_music(voice_filename, output_filename, GITHUB_MUSIC_URL)
        logger.info(f"[task_id={task_id}] 🎵 Mixed audio created: {output_filename}")

        # --- Отправляем в Telegram с кнопкой ---
        send_url = f"{TELEGRAM_API_URL}/sendAudio"
        with open(output_filename, "rb") as audio_file:
            files = {"audio": (f"{task_id}.mp3", audio_file, "audio/mpeg")}

            # Сначала получаем direct_url
            payload = {
                "chat_id": client_id,
                "caption": f"🎶 Ваш микс готов! {name}" if name else "🎶 Ваш микс готов!"
            }
            tg_resp = requests.post(send_url, data=payload, files=files, timeout=300)
            tg_json = tg_resp.json()
            logger.info(f"[task_id={task_id}] 📨 Telegram resp: {tg_json}")

            if tg_resp.status_code != 200 or not tg_json.get("ok"):
                return jsonify({"error": "Failed to send audio to Telegram", "task_id": task_id}), 500

            file_id = tg_json["result"]["audio"]["file_id"]
            direct_url = get_direct_url(file_id)

            # --- Добавляем inline-кнопку с callback ---
            reply_markup = {
                "inline_keyboard": [[
                    {"text": "Сохранить микс", "url": f"{SALEBOT_CALLBACK_URL}?value_client_id={client_id}&value_message={direct_url}"}
                ]]
            }

            payload_update = {
                "chat_id": client_id,
                "reply_markup": json.dumps(reply_markup)
            }
            update_resp = requests.post(f"{TELEGRAM_API_URL}/editMessageReplyMarkup", data=payload_update, timeout=300)
            logger.info(f"[task_id={task_id}] 🔘 Button sent: {update_resp.json()}")

        # --- Сохраняем результат ---
        RESULTS[task_id] = {
            "status": "done",
            "file_id": file_id,
            "direct_url": direct_url,
            "client_id": client_id,
            "name": name,
            "created_at": time.time(),
        }

        # --- Отправляем callback в Salebot сразу ---
        send_salebot_callback(client_id, direct_url)

        cleanup(voice_filename, task_id)
        cleanup(output_filename, task_id)

        return jsonify({
            "task_id": task_id,
            "file_id": file_id,
            "direct_url": direct_url
        })

    except Exception as e:
        logger.error(f"[task_id={task_id}] ❌ Error in /process_audio: {e}")
        return jsonify({"error": str(e), "task_id": task_id}), 500

# --- Остальные маршруты ---
@app.route("/get_result/<task_id>", methods=["GET"])
def get_result(task_id):
    result = RESULTS.get(task_id)
    if not result:
        return jsonify({"error": "Task not found", "task_id": task_id}), 404
    if time.time() - result.get("created_at", 0) > RESULT_TTL:
        return jsonify({"error": "Result expired", "task_id": task_id}), 410
    return jsonify(result)

@app.route("/list_results", methods=["GET"])
def list_results():
    now = time.time()
    active_results = {tid: {"status": r.get("status", "unknown")} for tid, r in RESULTS.items() if now - r.get("created_at", now) <= RESULT_TTL}
    return jsonify(active_results)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
