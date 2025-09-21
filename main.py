from flask import Flask, request, jsonify
import os
import uuid
import time
import requests
import logging
import json
from audio_processor import mix_voice_with_music

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)

# --- Конфигурация ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
GITHUB_MUSIC_URL = "https://raw.githubusercontent.com/belbotmixer-bot/gitrep/main/background_music.mp3"
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


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
    """Эндпоинт для проверки работоспособности"""
    return jsonify({
        "status": "healthy",
        "service": "voice-mixer-api",
        "timestamp": time.time(),
        "version": "3.1"
    })


@app.route("/process_audio", methods=["POST"])
def process_audio():
    """Основной эндпоинт: скачиваем голосовое → миксуем → отправляем в Telegram"""
    task_id = uuid.uuid4().hex[:8]  # короткий ID для отслеживания
    logger.info(f"[task_id={task_id}] 🎯 /process_audio called")

    try:
        # --- Получаем данные из вебхука ---
        if request.is_json:
            data = request.get_json()
        else:
            data = request.get_json(force=True, silent=True) or request.form.to_dict()

        if not data:
            return jsonify({"error": "No data received", "task_id": task_id}), 400

        voice_url = data.get("voice_url")
        client_id = data.get("client_id")  # chat_id в Telegram
        name = data.get("name", "")

        logger.info(f"[task_id={task_id}] 🔍 voice_url={voice_url}, client_id={client_id}, name={name}")

        if not voice_url or not client_id:
            return jsonify({"error": "voice_url and client_id required", "task_id": task_id}), 400

        # --- Скачиваем голосовое ---
        voice_filename = f"voice_{task_id}.ogg"
        resp = requests.get(voice_url, timeout=300)
        resp.raise_for_status()
        with open(voice_filename, "wb") as f:
            f.write(resp.content)
        logger.info(f"[task_id={task_id}] 📥 Voice saved as {voice_filename} ({os.path.getsize(voice_filename)} bytes)")

        # --- Миксуем с музыкой ---
        output_filename = f"mixed_{task_id}.mp3"
        mix_voice_with_music(voice_filename, output_filename, GITHUB_MUSIC_URL)
        logger.info(f"[task_id={task_id}] 🎵 Mixed audio created: {output_filename} ({os.path.getsize(output_filename)} bytes)")

        # --- Отправляем файл в Telegram с кнопкой callback ---
        send_url = f"{TELEGRAM_API_URL}/sendAudio"
        with open(output_filename, "rb") as audio_file:
            files = {"audio": (f"{task_id}.mp3", audio_file, "audio/mpeg")}
            payload = {
                "chat_id": client_id,
                "caption": f"🎶 Ваш микс готов! {name}" if name else "🎶 Ваш микс готов!",
                "reply_markup": {
                    "inline_keyboard": [
                        [{"text": "Сохранить ссылку на микс", "callback_data": f"save_mix:{task_id}"}]
                    ]
                }
            }
            tg_resp = requests.post(send_url, data={"chat_id": client_id, "caption": payload["caption"], 
                                                    "reply_markup": json.dumps(payload["reply_markup"])},
                                    files=files, timeout=300)

        try:
            tg_json = tg_resp.json()
        except Exception:
            tg_json = {"raw_text": tg_resp.text}

        logger.info(f"[task_id={task_id}] 📦 Telegram response: {tg_json}")

        if tg_resp.status_code != 200 or not tg_json.get("ok"):
            logger.error(f"[task_id={task_id}] ❌ Telegram API error: {tg_json}")
            return jsonify({"error": "Failed to send audio to Telegram", "task_id": task_id}), 500

        # --- Очистка ---
        cleanup(voice_filename, task_id)
        cleanup(output_filename, task_id)

        return jsonify({
            "status": "sent_to_telegram",
            "task_id": task_id,
            "client_id": client_id,
            "name": name,
            "processed_at": time.time(),
            "telegram_file_id": tg_json["result"]["audio"]["file_id"]
        })

    except Exception as e:
        logger.error(f"[task_id={task_id}] ❌ Error in /process_audio: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e), "task_id": task_id}), 500


@app.route("/callback_query", methods=["POST"])
def handle_callback():
    """Обработчик callback от кнопки в Telegram"""
    try:
        data = request.get_json()
        callback_data = data["callback_query"]["data"]
        chat_id = data["callback_query"]["message"]["chat"]["id"]
        message_id = data["callback_query"]["message"]["message_id"]

        logger.info(f"Callback received: {callback_data} from chat {chat_id}")

        if callback_data.startswith("save_mix:"):
            task_id = callback_data.split(":")[1]
            # Здесь можно отправить task_id или file_id в Salebot через API
            logger.info(f"User wants to save mix: {task_id}")

            # Ответ на callback (убирает "часики" в Telegram)
            requests.post(f"{TELEGRAM_API_URL}/answerCallbackQuery", data={
                "callback_query_id": data["callback_query"]["id"],
                "text": "Ссылка на микс сохранена!"
            })

        return jsonify({"status": "ok"})
    except Exception as e:
        logger.error(f"❌ Error in /callback_query: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"🌐 Starting Flask server on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=False)
