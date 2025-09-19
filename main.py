from flask import Flask, request, jsonify, send_file
import os
import uuid
import time
import requests
import logging
from threading import Thread
from audio_processor import mix_voice_with_music

# ==================== НАСТРОЙКИ ====================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Конфиг
GITHUB_MUSIC_URL = "https://raw.githubusercontent.com/belbotmixer-bot/gitrep/main/background_music.mp3"
SALEBOT_API_KEY = os.environ.get("SALEBOT_API_KEY", "YOUR_SALEBOT_API_KEY")
SALEBOT_BOT_ID = os.environ.get("SALEBOT_BOT_ID", "YOUR_BOT_ID")
SALEBOT_API_URL = f"https://chatter.salebot.pro/api/{SALEBOT_BOT_ID}/send_message"

# ==================== УТИЛИТЫ ====================

def cleanup(filename):
    """Удаление временных файлов после обработки"""
    try:
        if os.path.exists(filename):
            os.remove(filename)
            logger.info(f"🗑️ Deleted: {filename}")
    except Exception as e:
        logger.error(f"⚠️ Cleanup error for {filename}: {e}")


def notify_salebot(client_id, message, download_url=None):
    """Отправляем результат в Salebot"""
    payload = {
        "user_id": client_id,
        "message": message,
    }
    if download_url:
        payload["message"] += f"\n\n🎧 Ваша аффирмация: {download_url}"

    headers = {
        "Authorization": f"Token {SALEBOT_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(SALEBOT_API_URL, json=payload, headers=headers, timeout=30)
        if response.status_code == 200:
            logger.info("✅ Уведомление отправлено в SaleBot")
        else:
            logger.error(f"❌ Ошибка уведомления SaleBot: {response.status_code} {response.text}")
    except Exception as e:
        logger.error(f"❌ Ошибка отправки в SaleBot: {e}")


def process_audio_task(voice_url, client_id, name, host_url):
    """Фоновая задача обработки аудио"""
    try:
        logger.info(f"📥 Скачиваем голосовое: {voice_url}")
        voice_response = requests.get(voice_url, timeout=60)
        voice_response.raise_for_status()

        voice_filename = f"voice_{uuid.uuid4().hex}.ogg"
        with open(voice_filename, "wb") as f:
            f.write(voice_response.content)

        logger.info(f"💾 Голос сохранён: {voice_filename}")

        output_filename = f"mixed_{uuid.uuid4().hex}.mp3"
        output_path = os.path.join(os.getcwd(), output_filename)

        logger.info("🎵 Обработка и микширование...")
        mix_voice_with_music(voice_filename, output_path, GITHUB_MUSIC_URL)
        logger.info("✅ Аудио успешно обработано")

        cleanup(voice_filename)

        # Ссылка для скачивания
        download_url = f"{host_url}download/{output_filename}"
        logger.info(f"🔗 Ссылка на результат: {download_url}")

        # Отправляем пользователю
        notify_salebot(
            client_id,
            f"Привет, {name or 'друг'}! ✨ Ваша аффирмация готова!",
            download_url
        )

    except Exception as e:
        logger.error(f"❌ Ошибка в фоновой задаче: {e}")
        notify_salebot(client_id, f"⚠️ Ошибка при обработке аудио: {e}")

# ==================== ЭНДПОИНТЫ ====================

@app.route("/health")
def health_check():
    return jsonify({"status": "healthy", "timestamp": time.time()})


@app.route("/process_audio", methods=["POST"])
def process_audio():
    """Запускаем обработку в фоне и сразу отвечаем"""
    try:
        data = request.get_json(force=True, silent=True) or {}
        voice_url = data.get("voice_url")
        client_id = data.get("client_id")
        name = data.get("name")

        if not voice_url or not client_id:
            return jsonify({"error": "voice_url и client_id обязательны"}), 400

        logger.info(f"🎯 Получен запрос: voice_url={voice_url}, client_id={client_id}, name={name}")

        # Запускаем задачу в фоне
        Thread(
            target=process_audio_task,
            args=(voice_url, client_id, name, request.host_url),
            daemon=True
        ).start()

        return jsonify({"status": "processing", "message": "Обработка запущена"}), 202

    except Exception as e:
        logger.error(f"❌ Ошибка /process_audio: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/download/<filename>", methods=["GET"])
def download_file(filename):
    try:
        safe_filename = os.path.basename(filename)
        file_path = os.path.join(os.getcwd(), safe_filename)

        if not os.path.exists(file_path):
            return jsonify({"error": "Файл не найден"}), 404

        return send_file(file_path, as_attachment=True, download_name=f"voice_mix_{safe_filename}")

    except Exception as e:
        logger.error(f"❌ Ошибка скачивания: {e}")
        return jsonify({"error": str(e)}), 500

# ==================== ЗАПУСК ====================
if __name__ == "__main__":
    logger.info("🌐 Flask сервер запущен")
    app.run(host="0.0.0.0", port=5000, debug=False)
