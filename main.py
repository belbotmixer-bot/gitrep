from flask import Flask, request, jsonify
import os
import uuid
import time
import requests
import logging
from audio_processor import mix_voice_with_music

# --- Логирование ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# --- Конфигурация ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
SALEBOT_API_KEY = os.environ.get("SALEBOT_API_KEY", "YOUR_SALEBOT_KEY")
GITHUB_MUSIC_URL = "https://raw.githubusercontent.com/belbotmixer-bot/gitrep/main/background_music.mp3"
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def cleanup(filename):
    """Удаление временных файлов"""
    try:
        if filename and os.path.exists(filename):
            os.remove(filename)
            logger.info(f"🗑️ Deleted: {filename}")
    except Exception as e:
        logger.error(f"⚠️ Cleanup error for {filename}: {e}")


@app.route("/health")
def health_check():
    return jsonify({
        "status": "healthy",
        "service": "voice-mixer-api",
        "timestamp": time.time(),
        "version": "4.0"
    })


@app.route("/process_audio", methods=["POST"])
def process_audio():
    logger.info("🎯 /process_audio called")

    try:
        # --- Получаем данные ---
        if request.is_json:
            data = request.get_json()
        else:
            data = request.get_json(force=True, silent=True) or request.form.to_dict()

        if not data:
            return jsonify({"error": "No data received"}), 400

        voice_url = data.get("voice_url")
        client_id = data.get("client_id")  # chat_id в Telegram
        name = data.get("name", "")

        logger.info(f"🔍 voice_url={voice_url}, client_id={client_id}, name={name}")

        if not voice_url or not client_id:
            return jsonify({"error": "voice_url and client_id required"}), 400

        # --- Скачиваем голосовое ---
        voice_filename = f"voice_{uuid.uuid4().hex}.ogg"
        resp = requests.get(voice_url, timeout=300)
        resp.raise_for_status()
        with open(voice_filename, "wb") as f:
            f.write(resp.content)
        logger.info(f"📥 Voice saved as {voice_filename} ({os.path.getsize(voice_filename)} bytes)")

        # --- Миксуем ---
        output_filename = f"mixed_{uuid.uuid4().hex}.mp3"
        mix_voice_with_music(voice_filename, output_filename, GITHUB_MUSIC_URL)
        logger.info(f"🎵 Mixed audio created: {output_filename} ({os.path.getsize(output_filename)} bytes)")

        # --- Отправляем в Telegram ---
        send_url = f"{TELEGRAM_API_URL}/sendAudio"
        with open(output_filename, "rb") as audio_file:
            files = {"audio": (f"{uuid.uuid4().hex}.mp3", audio_file, "audio/mpeg")}
            payload = {
                "chat_id": client_id,
                "caption": f"🎶 Ваш микс готов! {name}" if name else "🎶 Ваш микс готов!"
            }
            tg_resp = requests.post(send_url, data=payload, files=files, timeout=300)

        tg_json = {}
        try:
            tg_json = tg_resp.json()
        except Exception:
            tg_json = {"raw_text": tg_resp.text}

        logger.info(f"📦 Telegram response: {tg_json}")

        if tg_resp.status_code != 200 or not tg_json.get("ok"):
            logger.error(f"❌ Telegram API error: {tg_json}")
            return jsonify({"error": "Failed to send audio to Telegram"}), 500

        # --- Достаём file_id для получения ссылки ---
        file_id = tg_json["result"]["audio"]["file_id"]
        file_info_url = f"{TELEGRAM_API_URL}/getFile?file_id={file_id}"
        file_info = requests.get(file_info_url).json()
        file_path = file_info["result"]["file_path"]
        cdn_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"

        logger.info(f"🌍 CDN URL: {cdn_url}")

        # --- Salebot: сохраняем переменную ---
        sb_set_vars_url = "https://salebot.pro/api/set_variables"
        vars_payload = {
            "token": SALEBOT_API_KEY,
            "client_id": str(client_id),
            "variables": {
                "last_mix_url": cdn_url
            }
        }
        sb_vars_resp = requests.post(sb_set_vars_url, json=vars_payload, timeout=30)
        logger.info(f"📨 Salebot set_variables response: {sb_vars_resp.status_code}, {sb_vars_resp.text}")

        # --- Salebot: шлём сообщение ---
        sb_send_msg_url = "https://salebot.pro/api/send_message"
        msg_payload = {
            "token": SALEBOT_API_KEY,
            "client_id": str(client_id),
            "message": f"🔗 Ссылка на ваш микс: {cdn_url}"
        }
        sb_msg_resp = requests.post(sb_send_msg_url, json=msg_payload, timeout=30)
        logger.info(f"📨 Salebot send_message response: {sb_msg_resp.status_code}, {sb_msg_resp.text}")

        # --- Очистка ---
        cleanup(voice_filename)
        cleanup(output_filename)

        return jsonify({
            "status": "sent_to_telegram_and_salebot",
            "client_id": client_id,
            "name": name,
            "processed_at": time.time(),
            "telegram_file_id": file_id,
            "cdn_url": cdn_url
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
