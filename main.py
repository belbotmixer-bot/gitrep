from flask import Flask, request, jsonify
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

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def cleanup(filename):
    """Удаление временных файлов после обработки"""
    try:
        if filename and os.path.exists(filename):
            os.remove(filename)
            logger.info(f"🗑️ Deleted: {filename}")
    except Exception as e:
        logger.error(f"⚠️ Cleanup error for {filename}: {e}")


@app.route("/health")
def health_check():
    """Эндпоинт для проверки работоспособности"""
    return jsonify({
        "status": "healthy",
        "service": "voice-mixer-api",
        "timestamp": time.time(),
        "version": "2.1"
    })


@app.route("/process_audio", methods=["POST"])
def process_audio():
    """Основной эндпоинт: скачиваем голосовое → миксуем → отправляем в Telegram"""
    logger.info("🎯 /process_audio called")

    try:
        # Получаем данные
        data = None
        if request.is_json:
            data = request.get_json()
        else:
            data = request.get_json(force=True, silent=True) or request.form.to_dict()

        if not data:
            return jsonify({"error": "No data received"}), 400

        voice_url = data.get("voice_url")
        client_id = data.get("client_id")  # сюда из SaleBot прилетает #{platform_id}
        name = data.get("name", "")

        logger.info(f"🔍 voice_url={voice_url}, client_id={client_id}, name={name}")

        if not voice_url or not client_id:
            return jsonify({"error": "voice_url and client_id required"}), 400

        # --- Обработка chat_id ---
        chat_id = str(client_id).strip()
        if "@telegram" in chat_id:
            chat_id = chat_id.split("@")[0]

        logger.info(f"✅ Using chat_id={chat_id}")

        # 1. Скачиваем голосовое сообщение
        voice_filename = f"voice_{uuid.uuid4().hex}.ogg"
        resp = requests.get(voice_url, timeout=60)
        resp.raise_for_status()
        with open(voice_filename, "wb") as f:
            f.write(resp.content)
        logger.info(f"📥 Voice saved as {voice_filename}")

        # 2. Миксуем с музыкой
        output_filename = f"mixed_{uuid.uuid4().hex}.mp3"
        mix_voice_with_music(voice_filename, output_filename, GITHUB_MUSIC_URL)
        logger.info(f"🎵 Mixed audio created: {output_filename}")

        # 3. Отправляем файл в Telegram
        send_url = f"{TELEGRAM_API_URL}/sendAudio"
        with open(output_filename, "rb") as audio_file:
            files = {"audio": audio_file}
            payload = {
                "chat_id": chat_id,
                "caption": f"🎶 Ваш микс готов! {name}" if name else "🎶 Ваш микс готов!"
            }
            tg_resp = requests.post(send_url, data=payload, files=files, timeout=120)

        if tg_resp.status_code != 200:
            logger.error(f"❌ Telegram API error: {tg_resp.text}")
            return jsonify({"error": "Failed to send audio to Telegram"}), 500

        logger.info(f"✅ Sent to Telegram chat {chat_id}")

        # 4. Очистка
        cleanup(voice_filename)
        cleanup(output_filename)

        return jsonify({
            "status": "sent_to_telegram",
            "client_id": chat_id,
            "name": name,
            "processed_at": time.time()
        })

    except Exception as e:
        logger.error(f"❌ Error in /process_audio: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"🌐 Starting Flask server on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=False)
