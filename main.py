from flask import Flask, request, jsonify, send_file
import os
import uuid
import time
import requests
import logging
from audio_processor import mix_voice_with_music

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# --- Конфигурация ---
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')
GITHUB_MUSIC_URL = "https://raw.githubusercontent.com/belbotmixer-bot/gitrep/main/background_music.mp3"

# ==================== ЭНДПОИНТЫ ====================

@app.route("/health")
def health_check():
    """Эндпоинт для проверки работоспособности"""
    return jsonify({
        "status": "healthy",
        "service": "voice-mixer-api",
        "timestamp": time.time(),
        "version": "1.1"
    })


@app.route("/")
def index():
    """Главная страница"""
    return "🎵 Voice Mixer Bot API is running! Use /health for status check."


@app.route("/test", methods=["GET", "POST"])
def test_endpoint():
    """Тестовый эндпоинт для отладки"""
    logger.info("✅ Тестовый запрос получен!")
    logger.info(f"📋 Content-Type: {request.content_type}")
    logger.info(f"📋 Headers: {dict(request.headers)}")

    try:
        data = request.get_json()
        logger.info(f"📦 JSON data: {data}")
        logger.info(f"📦 Incoming data: {data}")
    except:
        logger.info("📦 No JSON data")

    return jsonify({"status": "test_ok", "message": "Request received"})


@app.route("/process_audio", methods=["POST"])
def process_audio():
    """Основной эндпоинт для обработки аудио"""
    logger.info("🎯 /process_audio endpoint called!")

    try:
        # Получаем данные
        data = request.get_json(silent=True) or request.form.to_dict()
        if not data:
            logger.error("❌ No data received")
            return jsonify({"error": "No data received"}), 400

        file_id = data.get("file_id")   # 🔑 теперь используем file_id
        client_id = data.get("client_id")
        name = data.get("name")

        logger.info(f"🔍 file_id: {file_id}")
        logger.info(f"🔍 client_id: {client_id}")
        logger.info(f"🔍 name: {name}")

        if not file_id:
            logger.error("❌ file_id is required")
            return jsonify({"error": "file_id is required"}), 400

        # 1. Получаем file_path у Telegram
        file_info_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getFile"
        resp = requests.get(file_info_url, params={"file_id": file_id}, timeout=30)
        resp.raise_for_status()
        file_info = resp.json()

        if not file_info.get("ok"):
            logger.error(f"❌ Telegram API error: {file_info}")
            return jsonify({"error": "Telegram API error", "details": file_info}), 400

        file_path = file_info["result"]["file_path"]
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
        logger.info(f"📥 Downloading from Telegram: {file_url}")

        # 2. Скачиваем голос
        voice_response = requests.get(file_url, timeout=30)
        voice_response.raise_for_status()

        voice_filename = f"voice_{uuid.uuid4().hex}.ogg"
        with open(voice_filename, "wb") as f:
            f.write(voice_response.content)
        logger.info(f"💾 Saved voice as: {voice_filename}")

        # 3. Обрабатываем аудио
        output_filename = f"mixed_{uuid.uuid4().hex}.mp3"
        output_path = os.path.join(os.getcwd(), output_filename)

        logger.info("🎵 Mixing audio with music...")
        try:
            mix_voice_with_music(voice_filename, output_path, GITHUB_MUSIC_URL)
            logger.info("✅ Audio mixed successfully")
        except Exception as e:
            logger.error(f"❌ Audio processing failed: {str(e)}")
            cleanup(voice_filename)
            return jsonify({"error": f"Audio processing failed: {str(e)}"}), 500

        # 4. Создаём download URL с cache-buster
        timestamp = int(time.time())
        download_url = f"{request.host_url}download/{output_filename}?v={timestamp}"
        logger.info(f"🔗 Download URL: {download_url}")

        # 5. Очистка временного файла голоса
        cleanup(voice_filename)

        # 6. Ответ
        response_data = {
            "status": "success",
            "message": "Audio processed successfully",
            "download_url": download_url,
            "file_name": output_filename,
            "client_id": client_id,
            "name": name,
            "processed_at": time.time(),
            "source_file_id": file_id  # для отладки, можно убрать
        }

        logger.info(f"✅ Success: {response_data}")
        return jsonify(response_data)

    except Exception as e:
        logger.error(f"❌ Error in /process_audio: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@app.route("/download/<filename>", methods=["GET"])
def download_file(filename):
    try:
        safe_filename = os.path.basename(filename)
        file_path = os.path.join(os.getcwd(), safe_filename)

        if not os.path.exists(file_path) or '..' in filename or '/' in filename:
            return jsonify({"status": "error", "message": "File not found"}), 404

        # Уникальное имя при скачивании
        timestamp = int(time.time())
        unique_name = f"voice_mix_{timestamp}_{safe_filename}"

        return send_file(
            file_path,
            as_attachment=True,
            download_name=unique_name
        )

    except Exception as e:
        logger.error(f"❌ Download error: {str(e)}")
        return jsonify({"error": str(e)}), 500


def cleanup(filename):
    """Удаление временных файлов после обработки"""
    try:
        if os.path.exists(filename):
            os.remove(filename)
            logger.info(f"🗑️ Deleted: {filename}")
    except Exception as e:
        logger.error(f"⚠️ Cleanup error for {filename}: {e}")


# ==================== ЗАПУСК СЕРВЕРА ====================
if __name__ == "__main__":
    logger.info("🌐 Starting Flask server...")
    port = int(os.environ.get("PORT", 5000))  # читаем порт из переменной окружения
    app.run(host="0.0.0.0", port=port, debug=False)
