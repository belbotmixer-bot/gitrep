from flask import Flask, request, jsonify
import os
import uuid
import time
import requests
import logging
import threading
from audio_processor import mix_voice_with_music

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)

# --- Конфигурация ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
GITHUB_MUSIC_URL = "https://raw.githubusercontent.com/belbotmixer-bot/gitrep/main/background_music.mp3"
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# --- Хранилище результатов ---
RESULTS = {}
RESULT_TTL = 600  # время жизни (10 мин)


def cleanup(filename, task_id=None):
    try:
        if filename and os.path.exists(filename):
            os.remove(filename)
            logger.info(f"[task_id={task_id}] 🗑️ Deleted: {filename}")
    except Exception as e:
        logger.error(f"[task_id={task_id}] ⚠️ Cleanup error: {e}")


def auto_cleanup_results():
    while True:
        now = time.time()
        expired = [
            task_id
            for task_id, result in RESULTS.items()
            if now - result.get("created_at", now) > RESULT_TTL
        ]
        for task_id in expired:
            RESULTS.pop(task_id, None)
            logger.info(f"[task_id={task_id}] 🧹 Expired result removed")
        time.sleep(60)


@app.route("/health")
def health_check():
    return jsonify({
        "status": "healthy",
        "service": "voice-mixer-api",
        "timestamp": time.time(),
        "version": "4.1"
    })


@app.route("/process_audio", methods=["POST"])
def process_audio():
    task_id = uuid.uuid4().hex[:8]
    logger.info(f"[task_id={task_id}] 🎯 /process_audio called")

    try:
        data = request.get_json(force=True, silent=True) or request.form.to_dict()

        if not data:
            return jsonify({"error": "No data received", "task_id": task_id}), 400

        voice_url = data.get("voice_url")
        client_id = data.get("client_id")
        name = data.get("name", "")

        if not voice_url or not client_id:
            return jsonify({"error": "voice_url and client_id required", "task_id": task_id}), 400

        logger.info(f"[task_id={task_id}] 🔍 voice_url={voice_url}, client_id={client_id}, name={name}")

        # --- Скачиваем голосовое ---
        voice_filename = f"voice_{task_id}.ogg"
        resp = requests.get(voice_url, timeout=300)
        resp.raise_for_status()
        with open(voice_filename, "wb") as f:
            f.write(resp.content)
        logger.info(f"[task_id={task_id}] 📥 Voice saved: {voice_filename}")

        # --- Миксуем ---
        output_filename = f"mixed_{task_id}.mp3"
        mix_voice_with_music(voice_filename, output_filename, GITHUB_MUSIC_URL)
        logger.info(f"[task_id={task_id}] 🎵 Mixed audio created: {output_filename}")

        # --- Отправляем в Telegram ---
        send_url = f"{TELEGRAM_API_URL}/sendAudio"
        with open(output_filename, "rb") as audio_file:
            files = {"audio": (f"{task_id}.mp3", audio_file, "audio/mpeg")}
            payload = {"chat_id": client_id, "caption": f"🎶 Ваш микс {name}" if name else "🎶 Ваш микс"}
            tg_resp = requests.post(send_url, data=payload, files=files, timeout=300)

        tg_json = tg_resp.json()
        logger.info(f"[task_id={task_id}] 📦 Telegram response: {tg_json}")

        if tg_resp.status_code != 200 or not tg_json.get("ok"):
            raise Exception(f"Telegram API error: {tg_json}")

        file_id = tg_json["result"]["audio"]["file_id"]

        # --- Получаем прямую ссылку ---
        file_info = requests.get(f"{TELEGRAM_API_URL}/getFile", params={"file_id": file_id}).json()
        if file_info.get("ok"):
            file_path = file_info["result"]["file_path"]
            direct_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
        else:
            direct_url = None

        # --- Сохраняем результат ---
        RESULTS[task_id] = {
            "status": "done",
            "client_id": client_id,
            "file_id": file_id,
            "direct_url": direct_url,
            "created_at": time.time(),
        }

        cleanup(voice_filename, task_id)
        cleanup(output_filename, task_id)

        return jsonify({"status": "processing", "task_id": task_id})

    except Exception as e:
        logger.error(f"[task_id={task_id}] ❌ Error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        RESULTS[task_id] = {"status": "error", "error": str(e), "created_at": time.time()}
        return jsonify({"error": str(e), "task_id": task_id}), 500


@app.route("/get_result/<task_id>", methods=["GET"])
def get_result(task_id):
    result = RESULTS.get(task_id)
    if not result:
        return jsonify({"status": "not_found", "task_id": task_id}), 404
    return jsonify(result)


@app.route("/list_results", methods=["GET"])
def list_results():
    now = time.time()
    active_results = {
        task_id: result
        for task_id, result in RESULTS.items()
        if now - result.get("created_at", now) <= RESULT_TTL
    }
    return jsonify(active_results)


if __name__ == "__main__":
    threading.Thread(target=auto_cleanup_results, daemon=True).start()

    port = int(os.environ.get("PORT", 5000))
    logger.info(f"🌐 Starting Flask server on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=False)
