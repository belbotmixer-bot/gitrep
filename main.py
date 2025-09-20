import os
import time
import uuid
import logging
import threading
import requests
from flask import Flask, request, jsonify, send_from_directory

# 🔧 Конфиг
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")

DOWNLOAD_FOLDER = "downloads"
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)

# 📒 Логирование
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("main")


# 📤 Отправка в Telegram
def send_to_telegram(chat_id, file_url):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendAudio"
        payload = {
            "chat_id": chat_id,
            "audio": file_url
        }
        resp = requests.post(url, data=payload, timeout=20)
        logger.info(f"📤 Telegram response: {resp.text}")
    except Exception as e:
        logger.error(f"❌ Failed to send to Telegram: {e}")


# 🎵 Обработка аудио
def process_audio_task(voice_url, chat_id, name, host_url):
    try:
        logger.info(f"📥 Downloading from: {voice_url}")

        # скачать .oga
        file_id = str(uuid.uuid4())
        ogg_path = os.path.join(DOWNLOAD_FOLDER, f"voice_{file_id}.ogg")
        with requests.get(voice_url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(ogg_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)

        # эмуляция "микширования" -> переименуем в mp3
        mp3_filename = f"mixed_{file_id}.mp3"
        mp3_path = os.path.join(DOWNLOAD_FOLDER, mp3_filename)
        os.rename(ogg_path, mp3_path)

        # публичный URL
        download_url = f"{host_url}download/{mp3_filename}"
        logger.info(f"🔗 Download URL ready: {download_url}")

        # отправка в Telegram
        send_to_telegram(chat_id, download_url)

        # удалить локальный файл через задержку
        threading.Timer(30, lambda: os.remove(mp3_path)).start()
        logger.info(f"🗑️ Will delete later: {mp3_path}")

    except Exception as e:
        logger.error(f"❌ Error in process_audio_task: {e}")


@app.route("/process_audio", methods=["POST"])
def process_audio():
    try:
        data = request.json or {}
        logger.info(f"📥 Incoming request: {data}")

        voice_url = data.get("voice_url")
        chat_id = data.get("chat_id") or data.get("platform_id")  # <-- ключевое
        name = data.get("name")

        if not voice_url or not chat_id:
            return jsonify({"error": "voice_url and chat_id required"}), 400

        threading.Thread(
            target=process_audio_task,
            args=(voice_url, chat_id, name, request.host_url),
            daemon=True
        ).start()

        return jsonify({
            "chat_id": chat_id,
            "message": "🎤 Аудио принято в обработку",
            "status": "processing",
            "timestamp": time.time()
        }), 200

    except Exception as e:
        logger.error(f"❌ Error in /process_audio: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/download/<filename>")
def download(filename):
    return send_from_directory(DOWNLOAD_FOLDER, filename)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
