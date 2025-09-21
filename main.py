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
        "version": "2.0"
    })


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
    logger.info("🌐 Starting Flask server (two-webhook mode)...")
    app.run(host="0.0.0.0", port=5000, debug=False)
