from flask import Flask, request, jsonify, send_file
import os
import uuid
import time
import requests
import logging
import threading
from audio_processor import mix_voice_with_music

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# --- Конфигурация ---
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')
SALEBOT_API_KEY = os.environ.get("SALEBOT_API_KEY", "YOUR_SALEBOT_KEY")
SALEBOT_GROUP_ID = os.environ.get("SALEBOT_GROUP_ID", "YOUR_GROUP_ID")
GITHUB_MUSIC_URL = "https://raw.githubusercontent.com/belbotmixer-bot/gitrep/main/background_music.mp3"

# ==================== УТИЛИТЫ ====================

def cleanup(filename):
    try:
        if os.path.exists(filename):
            os.remove(filename)
            logger.info(f"🗑️ Deleted: {filename}")
    except Exception as e:
        logger.error(f"⚠️ Cleanup error for {filename}: {e}")

def notify_salebot(client_id, download_url):
    """Отправка результата в SaleBot"""
    url = "https://salebot.pro/api/message.send"
    payload = {
        "group_id": SALEBOT_GROUP_ID,
        "api_key": SALEBOT_API_KEY,
        "client_id": client_id,
        "text": f"🎵 Ваша аффирмация готова!\n{download_url}",
        "set_vars": {
            "download_url": download_url
        }
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        logger.info(f"📤 Notify SaleBot response: {r.text}")
    except Exception as e:
        logger.error(f"❌ Failed to notify SaleBot: {e}")

def process_audio_task(voice_url, client_id, name, base_url):
    """Фоновая задача обработки аудио"""
    try:
        # 1. Скачиваем голос
        logger.info(f"📥 Downloading from: {voice_url}")
        voice_response = requests.get(voice_url, timeout=30)
        voice_response.raise_for_status()

        voice_filename = f"voice_{uuid.uuid4().hex}.ogg"
        with open(voice_filename, "wb") as f:
            f.write(voice_response.content)

        # 2. Обрабатываем
        output_filename = f"mixed_{uuid.uuid4().hex}.mp3"
        output_path = os.path.join(os.getcwd(), output_filename)
        mix_voice_with_music(voice_filename, output_path, GITHUB_MUSIC_URL)

        # 3. Формируем ссылку
        download_url = f"{base_url}download/{output_filename}"
        logger.info(f"🔗 Download URL ready: {download_url}")

        # 4. Уведомляем SaleBot
        notify_salebot(client_id, download_url)

    except Exception as e:
        logger.error(f"❌ Error in process_audio_task: {e}")
    finally:
        cleanup(voice_filename if 'voice_filename' in locals() else None)

# ==================== ЭНДПОИНТЫ ====================

@app.route("/process_audio", methods=["POST"])
def process_audio():
    """Принимаем webhook, отвечаем быстро, а обработку запускаем фоном"""
    try:
        data = request.json or {}
        logger.info(f"📥 Incoming request: {data}")

        voice_url = data.get("voice_url")
        client_id = data.get("client_id")
        name = data.get("name")

        if not voice_url or not client_id:
            return jsonify({"error": "voice_url and client_id required"}), 400

        # Запускаем фоновую задачу
        threading.Thread(
            target=process_audio_task,
            args=(voice_url, client_id, name, request.host_url),
            daemon=True
        ).start()

        # Отвечаем сразу SaleBot (успеем за 1 сек)
        return jsonify({"status": "processing", "message": "Audio mixing started"}), 200

    except Exception as e:
        logger.error(f"❌ Error in /process_audio: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/download/<filename>", methods=["GET"])
def download_file(filename):
    try:
        safe_filename = os.path.basename(filename)
        file_path = os.path.join(os.getcwd(), safe_filename)

        if not os.path.exists(file_path):
            return jsonify({"status": "error", "message": "File not found"}), 404

        return send_file(
            file_path,
            as_attachment=True,
            download_name=f"voice_mix_{safe_filename}"
        )

    except Exception as e:
        logger.error(f"❌ Download error: {str(e)}")
        return jsonify({"error": str(e)}), 500

# ==================== ЗАПУСК ====================
if __name__ == "__main__":
    logger.info("🌐 Starting Flask server...")
    app.run(host="0.0.0.0", port=5000, debug=False)
