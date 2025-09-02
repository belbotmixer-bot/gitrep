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
GITHUB_MUSIC_URL = "https://raw.githubusercontent.com/work24room-sketch/telegram-voice-mixer-bot/main/background_music.mp3"

# ==================== ЭНДПОИНТЫ ====================

@app.route("/health")
def health_check():
    """Эндпоинт для проверки работоспособности"""
    return jsonify({
        "status": "healthy",
        "service": "voice-mixer-api",
        "timestamp": time.time(),
        "version": "1.0"
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
    except:
        logger.info("📦 No JSON data")
    
    return jsonify({"status": "test_ok", "message": "Request received"})

@app.route("/process_audio", methods=["POST"])
def process_audio():
    """Основной эндпоинт для обработки аудио"""
    logger.info("🎯 /process_audio endpoint called!")
    
    # Детальное логирование запроса
    logger.info(f"📋 Content-Type: {request.content_type}")
    logger.info(f"📋 Headers: {dict(request.headers)}")
    
    try:
        # Пробуем разные способы получить данные
        data = None
        if request.is_json:
            data = request.get_json()
            logger.info(f"📦 JSON data: {data}")
        else:
            # Пробуем форсировать JSON парсинг
            data = request.get_json(force=True, silent=True)
            if data:
                logger.info(f"📦 Forced JSON data: {data}")
            else:
                # Пробуем form-data
                data = request.form.to_dict()
                logger.info(f"📦 Form data: {data}")

        if not data:
            logger.error("❌ No data received")
            return jsonify({"error": "No data received"}), 400

        # Извлекаем параметры из SaleBot переменных
        voice_url = data.get("voice_url")
        client_id = data.get("client_id")  # #{client_id}
        name = data.get("name")            # #{name}

        logger.info(f"🔍 voice_url: {voice_url}")
        logger.info(f"🔍 client_id: {client_id}")
        logger.info(f"🔍 name: {name}")

        if not voice_url:
            logger.error("❌ voice_url is required")
            return jsonify({"error": "voice_url is required"}), 400

        # 1. Скачиваем голосовое сообщение
        logger.info(f"📥 Downloading from: {voice_url}")
        try:
            voice_response = requests.get(voice_url, timeout=30)
            voice_response.raise_for_status()
        except Exception as e:
            logger.error(f"❌ Failed to download voice: {str(e)}")
            return jsonify({"error": f"Failed to download voice: {str(e)}"}), 400

        # 2. Сохраняем временный файл
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

        # 4. Создаем URL для скачивания
        download_url = f"{request.host_url}download/{output_filename}"
        logger.info(f"🔗 Download URL: {download_url}")

        # 5. Очистка временных файлов (голосового)
        cleanup(voice_filename)

        # 6. Возвращаем ответ для SaleBot
        response_data = {
            "status": "success",
            "message": "Audio processed successfully",
            "download_url": download_url,
            "file_name": output_filename,
            "client_id": client_id,
            "name": name,
            "processed_at": time.time()
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
        # Проверяем безопасность пути
        safe_filename = os.path.basename(filename)
        file_path = os.path.join(os.getcwd(), safe_filename)
        
        if not os.path.exists(file_path) or '..' in filename or '/' in filename:
            return jsonify({"status": "error", "message": "File not found"}), 404
        
        # ИСПРАВЛЕННЫЙ ВЫЗОВ - убрали as_attachment_filename
        return send_file(
            file_path,
            as_attachment=True,
            download_name=f"voice_mix_{safe_filename}"
        )
    
    except Exception as e:
        logging.error(f"❌ Download error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 404
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
    app.run(host="0.0.0.0", port=5000, debug=False)
