from flask import Flask, request, jsonify, send_file
import os
import uuid
import time
import requests
import logging
import threading
from audio_processor import mix_voice_with_music

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# --- Конфигурация ---
GITHUB_MUSIC_URL = "https://raw.githubusercontent.com/belbotmixer-bot/gitrep/main/background_music.mp3"
PUBLIC_HOST = "https://gitrep-9iwv.onrender.com"  # 💡 Всегда фиксируем базовый URL без порта

# Хранилище задач
MIX_STORAGE = {}  # job_id -> {...}

# ==================== УТИЛИТЫ ====================

def cleanup(filename):
    try:
        if os.path.exists(filename):
            os.remove(filename)
            logger.info(f"🗑️ Deleted: {filename}")
    except Exception as e:
        logger.error(f"⚠️ Cleanup error for {filename}: {e}")


# ==================== ЭНДПОИНТЫ ====================

@app.route("/health")
def health_check():
    return jsonify({
        "status": "healthy",
        "service": "voice-mixer-api",
        "timestamp": time.time(),
        "version": "2.2"
    })


@app.route("/upload_voice", methods=["POST"])
def upload_voice():
    """Принимаем голосовое и запускаем фоновую обработку"""
    try:
        data = request.get_json(force=True)
        voice_url = data.get("voice_url")
        client_id = data.get("client_id")
        name = data.get("name", "")

        if not voice_url or not client_id:
            return jsonify({"error": "voice_url and client_id required"}), 400

        job_id = str(uuid.uuid4())

        logger.info(f"📥 Upload voice for client {client_id} (job_id={job_id}) from {voice_url}")

        # Сохраняем задачу
        MIX_STORAGE[job_id] = {
            "status": "processing",
            "file": None,
            "url": None,
            "client_id": client_id,
            "name": name
        }

        # Фоновая задача
        def process_task():
            start_time = time.time()
            try:
                # увеличенные таймауты: 10 сек соединение, 120 сек скачка
                resp = requests.get(voice_url, timeout=(10, 120))
                resp.raise_for_status()

                voice_filename = f"voice_{job_id}.ogg"
                with open(voice_filename, "wb") as f:
                    f.write(resp.content)

                output_filename = f"mixed_{job_id}.mp3"
                output_path = os.path.join(os.getcwd(), output_filename)
                mix_voice_with_music(voice_filename, output_path, GITHUB_MUSIC_URL)

                # ⚡ генерируем через PUBLIC_HOST
                download_url = f"{PUBLIC_HOST}/download/{output_filename}"

                MIX_STORAGE[job_id].update({
                    "status": "ready",
                    "file": output_path,
                    "url": download_url
                })

                cleanup(voice_filename)

                elapsed = time.time() - start_time
                logger.info(f"✅ Mix ready (job_id={job_id}): {download_url}")
                logger.info(f"⏱️ Job {job_id} обработан за {elapsed:.2f} сек")

            except Exception as e:
                MIX_STORAGE[job_id]["status"] = "error"
                MIX_STORAGE[job_id]["error"] = str(e)
                logger.error(f"❌ Error processing job {job_id}: {e}")

        threading.Thread(target=process_task, daemon=True).start()

        return jsonify({
            "status": "processing",
            "job_id": job_id,
            "client_id": client_id,
            "name": name,
            "requested_at": time.time()
        })

    except Exception as e:
        logger.error(f"❌ Error in /upload_voice: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/get_result/<job_id>", methods=["GET", "POST"])
def get_result(job_id):
    """Получение статуса обработки по job_id"""
    entry = MIX_STORAGE.get(job_id)

    if not entry:
        return jsonify({
            "status": "not_found",
            "message": f"❌ Нет данных для job_id={job_id}"
        }), 404

    if entry["status"] == "processing":
        return jsonify({
            "status": "processing",
            "message": "⌛ Микс ещё готовится",
            "job_id": job_id
        }), 200

    if entry["status"] == "ready":
        return jsonify({
            "status": "success",
            "message": "🎵 Микс готов",
            "download_url": entry["url"],
            "job_id": job_id,
            "client_id": entry["client_id"],
            "name": entry.get("name", "")
        }), 200

    return jsonify({
        "status": "error",
        "message": entry.get("error", "Неизвестная ошибка"),
        "job_id": job_id
    }), 500


@app.route("/download/<filename>", methods=["GET"])
def download_file(filename):
    try:
        safe_filename = os.path.basename(filename)
        file_path = os.path.join(os.getcwd(), safe_filename)

        if not os.path.exists(file_path):
            return jsonify({"status": "error", "message": "File not found"}), 404

        return send_file(
            file_path,
            as_attachment=True,
            download_name=f"voice_mix_{safe_filename}"
        )

    except Exception as e:
        logger.error(f"❌ Download error: {str(e)}")
        return jsonify({"error": str(e)}), 500


# ==================== ЗАПУСК ====================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))  # ⚡ Render подставляет свой порт
    logger.info(f"🌐 Starting Flask server (two-webhook mode) on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=False)
