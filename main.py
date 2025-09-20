from flask import Flask, request, jsonify
import os
import uuid
import time
import requests
import logging
from audio_processor import mix_voice_with_music

# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# --- Конфигурация ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
GITHUB_MUSIC_URL = "https://raw.githubusercontent.com/belbotmixer-bot/gitrep/main/background_music.mp3"

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
TELEGRAM_FILE_URL = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}"


# ==================== УТИЛИТЫ ====================

def download_file_from_tg(file_id: str, save_as: str):
    """Скачиваем файл из Telegram по file_id"""
    file_info = requests.get(f"{TELEGRAM_API_URL}/getFile", params={"file_id": file_id}).json()
    logger.info(f"📂 Ответ getFile: {file_info}")

    file_path = file_info["result"]["file_path"]
    file_url = f"{TELEGRAM_FILE_URL}/{file_path}"

    resp = requests.get(file_url)
    resp.raise_for_status()

    with open(save_as, "wb") as f:
        f.write(resp.content)

    logger.info(f"✅ Файл скачан: {save_as}")
    return save_as


def send_audio_to_tg(chat_id: str, audio_path: str, caption: str = "🎵 Ваш микс готов!"):
    """Отправляем mp3 в Telegram"""
    with open(audio_path, "rb") as f:
        resp = requests.post(
            f"{TELEGRAM_API_URL}/sendAudio",
            data={"chat_id": chat_id, "caption": caption},
            files={"audio": f},
        )
    resp_json = resp.json()
    logger.info(f"📤 Ответ sendAudio: {resp_json}")
    return resp_json


# ==================== ЭНДПОИНТ ====================

@app.route("/process_audio", methods=["POST"])
def process_audio():
    try:
        data = request.json
        logger.info(f"📥 Пришёл tg_request: {data}")

        message = data.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        voice = message.get("voice", {})
        file_id = voice.get("file_id")

        if not chat_id or not file_id:
            return jsonify({"error": "Нет chat_id или file_id"}), 400

        # 1. Скачиваем голосовое сообщение
        voice_filename = f"voice_{uuid.uuid4().hex}.ogg"
        download_file_from_tg(file_id, voice_filename)

        # 2. Обрабатываем аудио
        output_filename = f"mixed_{uuid.uuid4().hex}.mp3"
        mix_voice_with_music(voice_filename, output_filename, GITHUB_MUSIC_URL)

        # 3. Отправляем результат в Telegram
        resp_json = send_audio_to_tg(chat_id, output_filename)
        audio_file_id = resp_json.get("result", {}).get("audio", {}).get("file_id")

        # 4. Чистим временные файлы
        cleanup(voice_filename)
        cleanup(output_filename)

        # 5. Возвращаем file_id микса в SaleBot
        return jsonify({
            "status": "success",
            "audio_file_id": audio_file_id,
            "chat_id": chat_id,
            "processed_at": time.time()
        })

    except Exception as e:
        logger.error(f"❌ Ошибка в /process_audio: {e}")
        return jsonify({"error": str(e)}), 500


def cleanup(filename):
    try:
        if os.path.exists(filename):
            os.remove(filename)
            logger.info(f"🗑️ Deleted: {filename}")
    except Exception as e:
        logger.error(f"⚠️ Ошибка при очистке {filename}: {e}")


# ==================== ЗАПУСК ====================
if __name__ == "__main__":
    logger.info("🌐 Starting Flask server...")
    app.run(host="0.0.0.0", port=5000, debug=False)
