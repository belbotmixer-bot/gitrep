from flask import Flask, request, jsonify, send_file
import os
import uuid
import requests
import logging
import threading
import time   # ✅ добавлен импорт
from audio_processor import mix_voice_with_music

# --- Логирование ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# --- Конфигурация ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
SALEBOT_API_KEY = os.environ.get("SALEBOT_API_KEY", "YOUR_SALEBOT_KEY")
GITHUB_MUSIC_URL = "https://raw.githubusercontent.com/belbotmixer-bot/gitrep/main/background_music.mp3"

# ==================== УТИЛИТЫ ====================

def cleanup(filename):
    """Удаляем временные файлы"""
    try:
        if filename and os.path.exists(filename):
            os.remove(filename)
            logger.info(f"🗑️ Deleted: {filename}")
    except Exception as e:
        logger.error(f"⚠️ Cleanup error for {filename}: {e}")


def notify_salebot(client_id, download_url, name=""):
    """Обновляем custom_answer клиента в SaleBot"""
    url = f"https://chatter.salebot.pro/api/update_client/{SALEBOT_API_KEY}/{client_id}"
    payload = {
        "custom_answer": str({
            "download_url": download_url,
            "status": "success",
            "message": "🎵 Аудио готово!"
        })
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        logger.info(f"📤 Notify SaleBot response: {r.text}")
    except Exception as e:
        logger.error(f"❌ Failed to notify SaleBot: {e}")


def process_audio_task(voice_url, client_id, name, base_url):
    """Фоновая задача: качаем → миксуем → шлём ссылку в SaleBot"""
    voice_filename = None
    try:
        # 1. Скачиваем голос
        logger.info(f"📥 Downloading from: {voice_url}")
        resp = requests.get(voice_url, timeout=30)
        resp.raise_for_status()

        voice_filename = f"voice_{uuid.uuid4().hex}.ogg"
        with open(voice_filename, "wb") as f:
            f.write(resp.content)

        # 2. Обработка
        output_filename = f"mixed_{uuid.uuid4().hex}.mp3"
        output_path = os.path.join(os.getcwd(), output_filename)
        mix_voice_with_music(voice_filename, output_path, GITHUB_MUSIC_URL)

        # 3. Генерация ссылки
        download_url = f"{base_url}download/{output_filename}"
        logger.info(f"🔗 Download URL ready: {download_url}")

        # 4. Уведомляем SaleBot
        notify_salebot(client_id, download_url, name)

    except Exception as e:
        logger.error(f"❌ Error in process_audio_task: {e}")
    finally:
        cleanup(voice_filename)


# ==================== ЭНДПОИНТЫ ====================

@app.route("/process_audio", methods=["POST"])
def process_audio():
    """Принимаем webhook, отвечаем сразу, а работу делаем в фоне"""
    try:
        data = request.json or {}
        logger.info(f"📥 Incoming request: {data}")

        voice_url = data.get("voice_url")
        client_id = data.get("client_id")
        name = data.get("name")

        if not voice_url or not client_id:
            return jsonify({"error": "voice_url and client_id required"}), 400

        # Запускаем фоновую обработку
        threading.Thread(
            target=process_audio_task,
            args=(voice_url, client_id, name, request.host_url),
            daemon=True
        ).start()

        # Отвечаем быстро (чтобы SaleBot не отвалился по таймауту)
        return jsonify({
            "client_id": client_id,
            "message": "🎤 Аудио принято в обработку",
            "status": "processing",
            "timestamp": time.time()
        }), 200

    except Exception as e:
        logger.error(f"❌ Error in /process_audio: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/download/<filename>", methods=["GET"])
def download_file(filename):
    """Отдаём готовый файл клиенту"""
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
        logger.error(f"❌ Download error: {e}")
        return jsonify({"error": str(e)}), 500


# ==================== ЗАПУСК ====================
if __name__ == "__main__":
    logger.info("🌐 Starting Flask server...")
    app.run(host="0.0.0.0", port=5000, debug=False)
