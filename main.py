from flask import Flask, request, jsonify, send_file
import os
import uuid
import time
import requests
import logging
from threading import Thread
from audio_processor import mix_voice_with_music

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# --- Конфигурация ---
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')
GITHUB_MUSIC_URL = "https://raw.githubusercontent.com/belbotmixer-bot/gitrep/main/background_music.mp3"
SALEBOT_BOT_ID = os.environ.get("SALEBOT_BOT_ID")
SALEBOT_API_KEY = os.environ.get("SALEBOT_API_KEY")

# ==================== Уведомление SaleBot ====================

def notify_salebot(client_id, download_url, name):
    """Отправка push-сообщения в SaleBot"""
    if not SALEBOT_BOT_ID or not SALEBOT_API_KEY:
        logger.error("❌ SALEBOT_BOT_ID или SALEBOT_API_KEY не заданы в переменных окружения")
        return

    url = f"https://chatter.salebot.pro/api/{SALEBOT_BOT_ID}/push"
    headers = {"Authorization": f"Bearer {SALEBOT_API_KEY}"}
    payload = {
        "client_id": client_id,
        "message": f"🎶 {name}, ваша аффирмация готова!",
        "attachments": [
            {
                "type": "audio",
                "url": download_url
            }
        ]
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=15)
        if resp.status_code == 200:
            logger.info("✅ SaleBot уведомлён успешно")
        else:
            logger.error(f"❌ Ошибка уведомления SaleBot: {resp.status_code} {resp.text}")
    except Exception as e:
        logger.error(f"⚠️ Ошибка при отправке в SaleBot: {e}")

# ==================== ЭНДПОИНТЫ ====================

@app.route("/health")
def health_check():
    return jsonify({
        "status": "healthy",
        "service": "voice-mixer-api",
        "timestamp": time.time(),
        "version": "1.1"
    })

@app.route("/")
def index():
    return "🎵 Voice Mixer Bot API is running! Use /health for status check."

@app.route("/process_audio", methods=["POST"])
def process_audio():
    logger.info("🎯 /process_audio endpoint called!")

    try:
        data = request.get_json(force=True, silent=True) or request.form.to_dict()
        if not data:
            return jsonify({"error": "No data received"}), 400

        voice_url = data.get("voice_url")
        client_id = data.get("client_id")
        name = data.get("name")

        logger.info(f"🔍 voice_url: {voice_url}")
        logger.info(f"🔍 client_id: {client_id}")
        logger.info(f"🔍 name: {name}")

        if not voice_url:
            return jsonify({"error": "voice_url is required"}), 400

        # Скачиваем голосовое сообщение
        logger.info(f"📥 Скачиваем голосовое: {voice_url}")
        voice_response = requests.get(voice_url, timeout=30)
        voice_response.raise_for_status()

        voice_filename = f"voice_{uuid.uuid4().hex}.ogg"
        with open(voice_filename, "wb") as f:
            f.write(voice_response.content)
        logger.info(f"💾 Голос сохранён: {voice_filename}")

        # Обрабатываем аудио
        output_filename = f"mixed_{uuid.uuid4().hex}.mp3"
        output_path = os.path.join(os.getcwd(), output_filename)

        logger.info("🎵 Обработка и микширование...")
        mix_voice_with_music(voice_filename, output_path, GITHUB_MUSIC_URL)
        logger.info("✅ Аудио успешно обработано")

        cleanup(voice_filename)

        # Генерируем ссылку для скачивания
        download_url = f"{request.host_url}download/{output_filename}"
        logger.info(f"🔗 Ссылка на результат: {download_url}")

        # Уведомляем SaleBot в отдельном потоке (чтобы не блокировать ответ)
        Thread(target=notify_salebot, args=(client_id, download_url, name)).start()

        # Отвечаем 202 Accepted, чтобы бот знал — задача взята
        return jsonify({
            "status": "processing",
            "message": "Аудио обрабатывается",
            "client_id": client_id,
            "name": name,
            "submitted_at": time.time()
        }), 202

    except Exception as e:
        logger.error(f"❌ Ошибка в /process_audio: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/download/<filename>", methods=["GET"])
def download_file(filename):
    try:
        safe_filename = os.path.basename(filename)
        file_path = os.path.join(os.getcwd(), safe_filename)

        if not os.path.exists(file_path):
            return jsonify({"status": "error", "message": "File not found"}), 404

        return send_file(file_path, as_attachment=True, download_name=f"voice_mix_{safe_filename}")
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки файла: {e}")
        return jsonify({"error": str(e)}), 500

def cleanup(filename):
    try:
        if os.path.exists(filename):
            os.remove(filename)
            logger.info(f"🗑️ Deleted: {filename}")
    except Exception as e:
        logger.error(f"⚠️ Ошибка при очистке {filename}: {e}")

# ==================== ЗАПУСК СЕРВЕРА ====================
if __name__ == "__main__":
    logger.info("🌐 Starting Flask server...")
    app.run(host="0.0.0.0", port=5000, debug=False)
