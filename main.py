from flask import Flask, request, jsonify
import os
import uuid
import time
import requests
import logging
import shutil
from audio_processor import mix_voice_with_music

# --- Логирование ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# --- Конфигурация ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
GITHUB_MUSIC_URL = "https://raw.githubusercontent.com/belbotmixer-bot/gitrep/main/background_music.mp3"
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


@app.route("/health")
def health_check():
    return jsonify({
        "status": "healthy",
        "service": "voice-mixer-api",
        "timestamp": time.time(),
        "version": "debug-file-size"
    })


@app.route("/process_audio", methods=["POST"])
def process_audio():
    logger.info("🎯 /process_audio called")

    try:
        # --- Получение данных из вебхука ---
        data = None
        if request.is_json:
            data = request.get_json()
        else:
            data = request.get_json(force=True, silent=True) or request.form.to_dict()

        if not data:
            return jsonify({"error": "No data received"}), 400

        voice_url = data.get("voice_url")
        client_id = data.get("client_id")
        name = data.get("name", "")

        logger.info(f"🔍 voice_url={voice_url}, client_id={client_id}, name={name}")

        if not voice_url or not client_id:
            return jsonify({"error": "voice_url and client_id required"}), 400

        # --- Скачивание голосового ---
        voice_filename = f"voice_{uuid.uuid4().hex}.ogg"
        resp = requests.get(voice_url, timeout=60)
        resp.raise_for_status()
        with open(voice_filename, "wb") as f:
            f.write(resp.content)
        logger.info(f"📥 Voice saved as {voice_filename} ({os.path.getsize(voice_filename)} bytes)")

        # --- Миксинг с музыкой ---
        tmp_output = f"tmp_{uuid.uuid4().hex}.mp3"
        final_output = f"mixed_{uuid.uuid4().hex}.mp3"

        mix_voice_with_music(voice_filename, tmp_output, GITHUB_MUSIC_URL)

        # Перемещаем в финальный файл (чтобы не было недозаписанных)
        shutil.move(tmp_output, final_output)

        logger.info(f"🎵 Mixed audio created: {final_output} ({os.path.getsize(final_output)} bytes)")

        # --- Отправка в Telegram ---
        send_url = f"{TELEGRAM_API_URL}/sendDocument"
        with open(final_output, "rb") as audio_file:
            files = {"document": (f"{uuid.uuid4().hex}.mp3", audio_file, "audio/mpeg")}
            payload = {
                "chat_id": client_id,
                "caption": f"🎶 Ваш микс готов! {name}" if name else "🎶 Ваш микс готов!"
            }
            tg_resp = requests.post(send_url, data=payload, files=files, timeout=120)

        try:
            tg_json = tg_resp.json()
        except Exception:
            tg_json = {"raw_text": tg_resp.text}

        logger.info(f"📦 Telegram response: {tg_json}")

        if tg_resp.status_code != 200 or not tg_json.get("ok"):
            logger.error(f"❌ Telegram API error: {tg_json}")
            return jsonify({"error": "Failed to send audio to Telegram"}), 500

        # ⚠️ Cleanup временно отключен для отладки
        # os.remove(voice_filename)
        # os.remove(final_output)

        return jsonify({
            "status": "sent_to_telegram",
            "client_id": client_id,
            "name": name,
            "processed_at": time.time(),
            "telegram_result": tg_json.get("result", {})
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
