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
SALEBOT_API_KEY = os.environ.get("SALEBOT_API_KEY", "your_salebot_api_key_here")
GITHUB_MUSIC_URL = "https://raw.githubusercontent.com/belbotmixer-bot/gitrep/main/background_music.mp3"

# ==================== УТИЛИТЫ ====================

def cleanup(filename):
    try:
        if os.path.exists(filename):
            os.remove(filename)
            logger.info(f"🗑️ Deleted: {filename}")
    except Exception as e:
        logger.error(f"⚠️ Cleanup error for {filename}: {e}")

def set_salebot_variable(client_id, variable_name, variable_value):
    """Установка переменной в Salebot через официальный API"""
    url = "https://api.salebot.pro/api/v1/clients/set_variables"
    
    payload = {
        "client_id": client_id,
        "variables": {
            variable_name: variable_value
        }
    }
    
    headers = {
        "Authorization": f"Bearer {SALEBOT_API_KEY}",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        if response.status_code == 200:
            logger.info(f"✅ Variable '{variable_name}' set to '{variable_value}' for client {client_id}")
            return True
        else:
            logger.error(f"❌ Failed to set variable: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.error(f"🚫 Error setting variable: {e}")
        return False

def send_salebot_message(client_id, message_text):
    """Отправка сообщения клиенту через Salebot API"""
    url = "https://api.salebot.pro/api/v1/message/send"
    
    payload = {
        "client_id": client_id,
        "message": {
            "type": "text",
            "text": message_text
        }
    }
    
    headers = {
        "Authorization": f"Bearer {SALEBOT_API_KEY}",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        if response.status_code == 200:
            logger.info(f"✅ Message sent to client {client_id}")
            return True
        else:
            logger.warning(f"⚠️ Failed to send message: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.error(f"🚫 Error sending message: {e}")
        return False

def process_audio_task(voice_url, client_id, name, base_url):
    """Фоновая задача обработки аудио с обновлением в Salebot"""
    voice_filename = None
    output_filename = None
    
    try:
        # 1. Немедленно обновляем статус в Salebot - начали обработку
        set_salebot_variable(client_id, "audio_status", "processing")
        set_salebot_variable(client_id, "download_url", "")
        
        # 2. Скачиваем голос
        logger.info(f"📥 Downloading from: {voice_url}")
        voice_response = requests.get(voice_url, timeout=30)
        voice_response.raise_for_status()

        voice_filename = f"voice_{uuid.uuid4().hex}.ogg"
        with open(voice_filename, "wb") as f:
            f.write(voice_response.content)

        # 3. Обрабатываем аудио
        output_filename = f"mixed_{uuid.uuid4().hex}.mp3"
        output_path = os.path.join(os.getcwd(), output_filename)
        
        logger.info(f"🔧 Starting audio mixing for client {client_id}")
        mix_voice_with_music(voice_filename, output_path, GITHUB_MUSIC_URL)
        logger.info(f"✅ Audio mixing completed for client {client_id}")

        # 4. Формируем ссылку
        download_url = f"{base_url}download/{output_filename}"
        logger.info(f"🔗 Download URL ready: {download_url}")

        # 5. ОБНОВЛЯЕМ ПЕРЕМЕННЫЕ В SALEBOT ЧЕРЕЗ API
        set_salebot_variable(client_id, "audio_status", "completed")
        set_salebot_variable(client_id, "download_url", download_url)
        
        # 6. ОТПРАВЛЯЕМ СООБЩЕНИЕ ЧЕРЕЗ SALEBOT API
        send_salebot_message(
            client_id, 
            f"🎵 Ваша аффирмация готова, {name}!\n\nСкачать: {download_url}"
        )

    except Exception as e:
        logger.error(f"❌ Error in process_audio_task for client {client_id}: {e}")
        
        # ОБНОВЛЯЕМ СТАТУС ОШИБКИ В SALEBOT
        set_salebot_variable(client_id, "audio_status", "error")
        set_salebot_variable(client_id, "download_url", "")
        
        # ОТПРАВЛЯЕМ СООБЩЕНИЕ ОБ ОШИБКЕ
        send_salebot_message(
            client_id, 
            "❌ Произошла ошибка при обработке аудио. Попробуйте отправить голосовое сообщение еще раз."
        )
        
    finally:
        # Очистка временных файлов
        if voice_filename and os.path.exists(voice_filename):
            cleanup(voice_filename)

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

        # Немедленно отвечаем Salebot (в течение 13 секунд)
        response_data = {
            "status": "processing",
            "message": "Аудио принято в обработку",
            "client_id": client_id,
            "timestamp": time.time()
        }
        
        # Запускаем фоновую задачу
        threading.Thread(
            target=process_audio_task,
            args=(voice_url, client_id, name, request.host_url),
            daemon=True
        ).start()

        logger.info(f"🚀 Started background processing for client {client_id}")
        
        return jsonify(response_data), 200

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
            download_name=f"affirmation_{safe_filename}"
        )

    except Exception as e:
        logger.error(f"❌ Download error: {str(e)}")
        return jsonify({"error": str(e)}), 500

# ==================== ЗАПУСК ====================
if __name__ == "__main__":
    logger.info("🌐 Starting Flask server with Salebot API integration...")
    app.run(host="0.0.0.0", port=5000, debug=False)
