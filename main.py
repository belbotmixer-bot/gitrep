from flask import Flask, request, jsonify
import os
import uuid
import time
import requests
import logging
import json
from audio_processor import mix_voice_with_music

# --- Логирование ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)

# --- Конфигурация ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
GITHUB_MUSIC_URL = "https://raw.githubusercontent.com/belbotmixer-bot/gitrep/main/background_music.mp3"
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
TELEGRAM_FILE_API_URL = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}"

# --- Salebot callback ---
SALEBOT_API_KEY = os.environ.get("SALEBOT_API_KEY", "YOUR_SALEBOT_API_KEY_HERE")
SALEBOT_CALLBACK_URL = f"https://chatter.salebot.pro/api/{SALEBOT_API_KEY}/callback"

# --- Хранилище результатов ---
RESULTS = {}
RESULT_TTL = 3600  # хранение 1 час

def cleanup(filename, task_id=None):
    try:
        if filename and os.path.exists(filename):
            os.remove(filename)
            logger.info(f"[task_id={task_id}] 🗑️ Deleted: {filename}")
    except Exception as e:
        logger.error(f"[task_id={task_id}] ⚠️ Cleanup error for {filename}: {e}")

def get_direct_url(file_id):
    try:
        resp = requests.get(f"{TELEGRAM_API_URL}/getFile", params={"file_id": file_id}, timeout=30)
        resp.raise_for_status()
        file_path = resp.json()["result"]["file_path"]
        return f"{TELEGRAM_FILE_API_URL}/{file_path}"
    except Exception as e:
        logger.error(f"⚠️ Failed to get direct_url for file_id={file_id}: {e}")
        return None

def send_salebot_callback(client_id, direct_url):
    try:
        payload = {
            "my_client": client_id,
            "my_message": direct_url
        }
        resp = requests.post(
            SALEBOT_CALLBACK_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        resp.raise_for_status()
        logger.info(f"[client_id={client_id}] ✅ Salebot callback sent successfully: {resp.text}")
    except Exception as e:
        logger.error(f"[client_id={client_id}] ❌ Failed to send Salebot callback: {e}")

@app.route("/process_audio", methods=["POST"])
def process_audio():
    """Первый вебхук: Salebot → Render"""
    task_id = uuid.uuid4().hex[:8]
    logger.info(f"[task_id={task_id}] 🎯 /process_audio called")

    try:
        data = request.get_json(force=True, silent=True) or request.form.to_dict()
        logger.info(f"[task_id={task_id}] 🔍 Incoming data: {data}")

        if not data:
            return jsonify({"error": "No data received", "task_id": task_id}), 400

        voice_url = data.get("voice_url")
        client_id = data.get("client_id")
        name = data.get("name", "")

        if not voice_url or not client_id:
            return jsonify({"error": "voice_url and client_id required", "task_id": task_id}), 400

        # --- Скачиваем голос ---
        voice_filename = f"voice_{task_id}.ogg"
        resp = requests.get(voice_url, timeout=300)
        resp.raise_for_status()
        with open(voice_filename, "wb") as f:
            f.write(resp.content)
        logger.info(f"[task_id={task_id}] 📥 Voice saved as {voice_filename}")

        # --- Миксуем ---
        output_filename = f"mixed_{task_id}.mp3"
        mix_voice_with_music(voice_filename, output_filename, GITHUB_MUSIC_URL)
        logger.info(f"[task_id={task_id}] 🎵 Mixed audio created: {output_filename}")

        # --- Отправляем в Telegram ---
        send_url = f"{TELEGRAM_API_URL}/sendAudio"
        with open(output_filename, "rb") as audio_file:
            files = {"audio": (f"{task_id}.mp3", audio_file, "audio/mpeg")}
            payload = {
                "chat_id": client_id,
                "caption": f"🎶 Ваш микс готов! {name}" if name else "🎶 Ваш микс готов!"
            }
            tg_resp = requests.post(send_url, data=payload, files=files, timeout=300)

        tg_json = tg_resp.json()
        logger.info(f"[task_id={task_id}] 📦 Telegram response: {tg_json}")

        if tg_resp.status_code != 200 or not tg_json.get("ok"):
            logger.error(f"[task_id={task_id}] ❌ Telegram API error")
            return jsonify({"error": "Failed to send audio to Telegram", "task_id": task_id}), 500

        file_id = tg_json["result"]["audio"]["file_id"]
        direct_url = get_direct_url(file_id)

        # --- Сохраняем результат ---
        RESULTS[task_id] = {
            "status": "done",
            "file_id": file_id,
            "direct_url": direct_url,
            "client_id": client_id,
            "name": name,
            "created_at": time.time(),
        }

        # --- Отправляем callback в Salebot с прямым URL ---
        def send_salebot_callback(client_id, direct_url):
    try:
        payload = {
            "client_id": client_id,
            "callback_message": direct_url
        }
        resp = requests.post(
            SALEBOT_CALLBACK_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        resp.raise_for_status()
        logger.info(f"[client_id={client_id}] ✅ Salebot callback sent successfully: {resp.text}")
    except Exception as e:
        logger.error(f"[client_id={client_id}] ❌ Failed to send Salebot callback: {e}")
        return jsonify({"error": str(e), "task_id": task_id}), 500

@app.route("/webhook", methods=["POST"])
def telegram_webhook():
    """Обработка callback_query от Telegram"""
    try:
        update = request.get_json(force=True, silent=True)
        logger.info(f"🌐 Incoming update: {update}")

        if "callback_query" in update:
            cq = update["callback_query"]
            chat_id = cq["message"]["chat"]["id"]
            data = cq.get("data", "")

            # В data уже можем хранить прямую ссылку
            # Если нужно, можно передавать f"{client_id}|{direct_url}"
            try:
                client_id, task_id_or_url = data.split("|", 1)
            except ValueError:
                client_id, task_id_or_url = data, None

            if task_id_or_url and task_id_or_url.startswith("http"):
                # Если в callback_data уже URL
                url = task_id_or_url
            else:
                # Иначе ищем в RESULTS по task_id
                result = RESULTS.get(task_id_or_url)
                url = result.get("direct_url") if result else None

            text = f"🔗 Ваша ссылка: {url}" if url else "⚠️ Ссылка недоступна или устарела."

            # --- Отправляем пользователю сообщение в Telegram ---
            requests.post(
                f"{TELEGRAM_API_URL}/sendMessage",
                json={"chat_id": chat_id, "text": text},
                timeout=30
            )

            # --- Отправляем callback в Salebot с прямым URL ---
            if url:
                send_salebot_callback(client_id, url)

        return jsonify({"ok": True})
    except Exception as e:
        logger.error(f"❌ Error in /webhook: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"🌐 Starting Flask server on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=False)
