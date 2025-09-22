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

SALEBOT_API_KEY = os.environ.get("SALEBOT_API_KEY", "YOUR_SALEBOT_API_KEY_HERE")
SALEBOT_CALLBACK_URL = f"https://chatter.salebot.pro/api/{SALEBOT_API_KEY}/callback"

# --- Хранилище результатов ---
RESULTS = {}
RESULT_TTL = 3600  # хранение 1 час

# --- Вспомогательные функции ---
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

def send_direct_url_to_salebot(client_id, direct_url):
    payload = {
        "platform_id": client_id,   # Salebot переменная
        "my_message": direct_url    # Salebot переменная для ссылки
    }
    headers = {"Content-Type": "application/json"}
    try:
        resp = requests.post(SALEBOT_CALLBACK_URL, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        logger.info(f"[client_id={client_id}] ✅ Direct URL sent to Salebot: {direct_url}")
    except Exception as e:
        logger.error(f"[client_id={client_id}] ❌ Failed to send direct URL to Salebot: {e}")

# --- Endpoints ---
@app.route("/health")
def health_check():
    return jsonify({
        "status": "healthy",
        "service": "voice-mixer-api",
        "timestamp": time.time(),
        "version": "3.5-direct-url"
    })

@app.route("/process_audio", methods=["POST"])
def process_audio():
    """Обработка запроса Salebot → Render"""
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
            reply_markup = {
                "inline_keyboard": [[
                    {"text": "🔗 Скачать файл", "callback_data": f"{client_id}|{task_id}"}
                ]]
            }
            payload = {
                "chat_id": client_id,
                "caption": f"🎶 Ваш микс готов! {name}" if name else "🎶 Ваш микс готов!",
                "reply_markup": json.dumps(reply_markup)
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

        # --- Отправляем direct_url в Salebot ---
        send_direct_url_to_salebot(client_id, direct_url)

        # --- Очистка файлов ---
        cleanup(voice_filename, task_id)
        cleanup(output_filename, task_id)

        response = {
            "task_id": task_id,
            "file_id": file_id,
            "direct_url": direct_url
        }
        logger.info(f"[task_id={task_id}] ✅ Response to Salebot: {response}")
        return jsonify(response)

    except Exception as e:
        logger.error(f"[task_id={task_id}] ❌ Error in /process_audio: {e}")
        return jsonify({"error": str(e), "task_id": task_id}), 500

@app.route("/get_result/<task_id>", methods=["GET"])
def get_result(task_id):
    result = RESULTS.get(task_id)
    if not result:
        return jsonify({"error": "Task not found", "task_id": task_id}), 404
    if time.time() - result.get("created_at", 0) > RESULT_TTL:
        return jsonify({"error": "Result expired", "task_id": task_id}), 410
    return jsonify(result)

@app.route("/list_results", methods=["GET"])
def list_results():
    now = time.time()
    active_results = {
        task_id: {"status": result.get("status", "unknown")}
        for task_id, result in RESULTS.items()
        if now - result.get("created_at", now) <= RESULT_TTL
    }
    return jsonify(active_results)

@app.route("/webhook", methods=["POST"])
def telegram_webhook():
    """Обработка callback_query от Telegram (кнопка)"""
    try:
        update = request.get_json(force=True, silent=True)
        if "callback_query" in update:
            cq = update["callback_query"]
            data = cq.get("data", "")
            chat_id = cq["message"]["chat"]["id"]

            try:
                client_id, task_id = data.split("|", 1)
            except ValueError:
                client_id, task_id = data, None

            result = RESULTS.get(task_id)
            if result and result.get("direct_url"):
                text = f"🔗 Ваша ссылка: {result['direct_url']}"
            else:
                text = "⚠️ Ссылка недоступна или устарела."

            requests.post(
                f"{TELEGRAM_API_URL}/sendMessage",
                json={"chat_id": chat_id, "text": text},
                timeout=30
            )

        return jsonify({"ok": True})
    except Exception as e:
        logger.error(f"❌ Error in /webhook: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
