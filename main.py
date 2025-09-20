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
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
GITHUB_MUSIC_URL = "https://raw.githubusercontent.com/belbotmixer-bot/gitrep/main/background_music.mp3"
SALEBOT_GROUP_ID = os.environ.get("SALEBOT_GROUP_ID")
SALEBOT_API_KEY = os.environ.get("SALEBOT_API_KEY")

# ==================== УВЕДОМЛЕНИЕ SALEBOT ====================

def notify_salebot(client_id: str, name: str, download_url: str):
    """Уведомление SaleBot о готовности файла (только текст)."""
    try:
        if not SALEBOT_GROUP_ID or not SALEBOT_API_KEY:
            logger.error("❌ SALEBOT_GROUP_ID или SALEBOT_API_KEY не заданы")
            return

        # Формируем текст сообщения
        text = f"🎵 {name}, ваша аффирмация готова!\n{download_url}"

        payload = {
            "client_id": client_id,
            "text": text
        }

        # ✅ Правильный endpoint Salebot (групповой + токен в URL)
        url = f"https://salebot.pro/api/{SALEBOT_GROUP_ID}/send_message?token={SALEBOT_API_KEY}"

        resp = requests.post(url, json=payload, timeout=15)

        if resp.status_code == 200:
            logger.info(f"✅ Уведомление SaleBot успешно отправлено: {resp.json()}")
        else:
            logger.error(f"❌ Ошибка уведомления SaleBot: {resp.status_code} {resp.text}")

    except Exception as e:
        logger.error(f"⚠️ Ошибка в notify_salebot: {e}")

# ==================== ВСПОМОГАТЕЛЬНЫЕ ====================

def get_telegram_file_url(file_id: str) -> str:
    """Получаем прямую ссылку на файл в Telegram по file_id"""
    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getFile?file_id={file_id}"
    resp = requests.get(api_url, timeout=10)
    resp.raise_for_status()
    file_path = resp.json()["result"]["file_path"]
    return f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"

def cleanup(filename):
    try:
        if os.path.exists(filename):
            os.remove(filename)
            logger.info(f"🗑️ Deleted: {filename}")
    except Exception as e:
        logger.error(f"⚠️ Ошибка при очистке {filename}: {e}")

# ==================== ЭНДПОИНТЫ ====================

@app.route("/health")
def health_check():
    return jsonify({
        "status": "healthy",
        "service": "voice-mixer-api",
        "timestamp": time.time(),
        "version": "1.2"
    })

@app.route("/")
def index():
    return "🎵 Voice Mixer Bot API is running! Use /health for status check."

@app.route("/process_audio", methods=["POST"])
def process_audio():
    try:
        data = request.json
        file_id = data.get("file_id")       # новый вариант
        voice_url = data.get("voice_url")   # старый вариант
        client_id = data.get("client_id")
        name = data.get("name", "Пользователь")

        if not (file_id or voice_url):
            return jsonify({"error": "Нужно передать либо file_id, либо voice_url"}), 400
        if not client_id:
            return jsonify({"error": "client_id обязателен"}), 400

        # 1. Определяем источник файла
        if file_id:
            logger.info(f"🎤 Получен file_id: {file_id}")
            voice_url = get_telegram_file_url(file_id)
            logger.info(f"📥 Telegram file URL: {voice_url}")
        else:
            logger.info(f"📥 Скачиваем голосовое по URL: {voice_url}")

        # 2. Скачиваем голосовое сообщение
        voice_response = requests.get(voice_url, timeout=30)
        voice_response.raise_for_status()

        voice_filename = f"voice_{uuid.uuid4().hex}.ogg"
        with open(voice_filename, "wb") as f:
            f.write(voice_response.content)
        logger.info(f"💾 Голос сохранён: {voice_filename}")

        # 3. Обрабатываем аудио
        output_filename = f"mixed_{uuid.uuid4().hex}.mp3"
        output_path = os.path.join(os.getcwd(), output_filename)

        logger.info("🎵 Обработка и микширование...")
        mix_voice_with_music(voice_filename, output_path, GITHUB_MUSIC_URL)
        logger.info("✅ Аудио успешно обработано")

        # 4. Чистим временный файл
        cleanup(voice_filename)

        # 5. Генерируем ссылку для скачивания
        download_url = f"{request.host_url}download/{output_filename}"
        logger.info(f"🔗 Ссылка на результат: {download_url}")

        # 6. Уведомляем SaleBot в отдельном потоке (push-схема)
        Thread(target=notify_salebot, args=(client_id, name, download_url)).start()

        # 7. Возвращаем ответ для SaleBot
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

# ==================== ЗАПУСК СЕРВЕРА ====================
if __name__ == "__main__":
    logger.info("🌐 Starting Flask server...")
    app.run(host="0.0.0.0", port=5000, debug=False)
