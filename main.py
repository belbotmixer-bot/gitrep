import os
import uuid
import time
import requests
import logging
from flask import Flask, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
from audio_processor import mix_voice_with_music  # твой модуль микса

# --- Логирование ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# --- Flask ---
app = Flask(__name__)

# --- Конфигурация ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
GITHUB_MUSIC_URL = "https://raw.githubusercontent.com/belbotmixer-bot/gitrep/main/background_music.mp3"
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# 🔹 Render URL приложения (текущий домен)
APP_URL = "https://gitrep-9iwv.onrender.com"


# --- Keep-alive функции ---
def self_ping():
    """Регулярный self-ping"""
    try:
        requests.get(f"{APP_URL}/health", timeout=30)
        logger.info("🔄 self_ping triggered")
    except Exception as e:
        logger.warning(f"⚠️ self_ping error: {e}")


def emergency_ping():
    """Аварийный ping при старте приложения"""
    try:
        requests.get(f"{APP_URL}/health", timeout=60)
        logger.info("🚀 emergency_ping done")
    except requests.exceptions.Timeout:
        logger.info("⚠️ Приложение просыпается...")
    except Exception as e:
        logger.warning(f"❌ Ошибка emergency ping: {e}")


# --- Запуск keep-alive сразу при импорте (для Gunicorn) ---
emergency_ping()
scheduler = BackgroundScheduler()
scheduler.add_job(self_ping, 'interval', minutes=8)
scheduler.start()
logger.info("⏰ APScheduler started — keep-alive активен")


# --- Вспомогательные функции ---
def cleanup(filename, task_id=None):
    try:
        if filename and os.path.exists(filename):
            os.remove(filename)
            logger.info(f"[task_id={task_id}] 🗑️ Deleted: {filename}")
    except Exception as e:
        logger.error(f"[task_id={task_id}] ⚠️ Cleanup error for {filename}: {e}")


# --- Маршруты ---
@app.route('/')
def index():
    return "✅ Server is running and protected from sleep!"


@app.route('/health')
def health_check():
    return jsonify({
        "status": "healthy",
        "service": "voice-mixer-api",
        "timestamp": time.time(),
        "version": "4.3-keepalive"
    })


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

        # --- Отправляем в Telegram ---
        send_url = f"{TELEGRAM_API_URL}/sendAudio"
        with open(output_filename, "rb") as audio_file:
            files = {"audio": (f"{task_id}.mp3", audio_file, "audio/mpeg")}
            caption_text = f"{name}, аффирмация готова" if name else "Аффирмация готова"
            payload = {"chat_id": client_id, "caption": caption_text}
            tg_resp = requests.post(send_url, data=payload, files=files, timeout=300)

        tg_json = tg_resp.json()
        logger.info(f"[task_id={task_id}] 📦 Telegram response: {tg_json}")

        if tg_resp.status_code != 200 or not tg_json.get("ok"):
            logger.error(f"[task_id={task_id}] ❌ Telegram API error")
            return jsonify({"error": "Failed to send audio to Telegram", "task_id": task_id}), 500

        cleanup(voice_filename, task_id)
        cleanup(output_filename, task_id)

        response = {
            "task_id": task_id,
            "status": "done",
            "telegram_result": tg_json
        }
        logger.info(f"[task_id={task_id}] ✅ Done: {response}")
        return jsonify(response)

    except Exception as e:
        logger.error(f"[task_id={task_id}] ❌ Error in /process_audio: {e}")
        return jsonify({"error": str(e), "task_id": task_id}), 500


# --- Запуск только для локального теста ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"🌐 Starting Flask server on port {port} (local test)")
    app.run(host="0.0.0.0", port=port, debug=False)
