from flask import Flask, request, jsonify
import os
import uuid
import time
import requests
import logging
from audio_processor import mix_voice_with_music
import json  # важно для сериализации reply_markup

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)

# --- Конфигурация ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
GITHUB_MUSIC_URL = "https://raw.githubusercontent.com/belbotmixer-bot/gitrep/main/background_music.mp3"
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
TELEGRAM_BOT_USERNAME = os.environ.get("TELEGRAM_BOT_USERNAME", "PRISM_MAX_BOT")


def cleanup(filename, task_id=None):
    """Удаление временных файлов после обработки"""
    try:
        if filename and os.path.exists(filename):
            os.remove(filename)
            logger.info(f"[task_id={task_id}] 🗑️ Deleted: {filename}")
    except Exception as e:
        logger.error(f"[task_id={task_id}] ⚠️ Cleanup error for {filename}: {e}")


@app.route("/health")
def health_check():
    return jsonify({
        "status": "healthy",
        "service": "voice-mixer-api",
        "timestamp": time.time(),
        "version": "3.1"
    })


@app.route("/process_audio", methods=["POST"])
def process_audio():
    task_id = uuid.uuid4().hex[:8]
    logger.info(f"[task_id={task_id}] 🎯 /process_audio called")

    try:
        data = request.get_json() or request.form.to_dict()
        if not data:
            return jsonify({"error": "No data received", "task_id": task_id}), 400

        voice_url = data.get("voice_url")
        client_id = data.get("client_id")
        name = data.get("name", "")

        if not voice_url or not client_id:
            return jsonify({"error": "voice_url and client_id required", "task_id": task_id}), 400

        # --- Скачиваем голосовое ---
        voice_filename = f"voice_{task_id}.ogg"
        resp = requests.get(voice_url, timeout=300)
        resp.raise_for_status()
        with open(voice_filename, "wb") as f:
            f.write(resp.content)
        logger.info(f"[task_id={task_id}] 📥 Voice saved: {voice_filename}")

        # --- Миксуем с музыкой ---
        output_filename = f"mixed_{task_id}.mp3"
        mix_voice_with_music(voice_filename, output_filename, GITHUB_MUSIC_URL)
        logger.info(f"[task_id={task_id}] 🎵 Mixed audio created: {output_filename}")

        # --- Отправляем файл с inline-кнопкой ---
        send_url = f"{TELEGRAM_API_URL}/sendAudio"
        with open(output_filename, "rb") as audio_file:
            files = {"audio": (f"{task_id}.mp3", audio_file, "audio/mpeg")}
            # callback_data содержит task_id для Salebot
            reply_markup = {
                "inline_keyboard": [[
                    {"text": "💾 Сохранить ссылку на микс", "callback_data": f"save_mix:{task_id}"}
                ]]
            }
            payload = {
                "chat_id": client_id,
                "caption": f"🎶 Ваш микс готов! {name}" if name else "🎶 Ваш микс готов!",
                "reply_markup": json.dumps(reply_markup)
            }
            tg_resp = requests.post(send_url, data=payload, files=files, timeout=300)

        try:
            tg_json = tg_resp.json()
        except Exception:
            tg_json = {"raw_text": tg_resp.text}

        logger.info(f"[task_id={task_id}] 📦 Telegram response: {tg_json}")

        if tg_resp.status_code != 200 or not tg_json.get("ok"):
            logger.error(f"[task_id={task_id}] ❌ Telegram API error: {tg_json}")
            return jsonify({"error": "Failed to send audio", "task_id": task_id}), 500

        # --- Формируем ссылку для Salebot (callback) ---
        # Salebot в блоке колбэк проверяет tg_request.callback_query.data.startswith("save_mix:")
        mix_url = f"https://t.me/{TELEGRAM_BOT_USERNAME}?voice={tg_json['result']['audio']['file_id']}"

        cleanup(voice_filename, task_id)
        cleanup(output_filename, task_id)

        return jsonify({
            "status": "sent_to_telegram",
            "task_id": task_id,
            "client_id": client_id,
            "telegram_file_id": tg_json["result"]["audio"]["file_id"],
            "mix_url": mix_url
        })

    except Exception as e:
        logger.error(f"[task_id={task_id}] ❌ Error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e), "task_id": task_id}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"🌐 Starting Flask server on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=False)
