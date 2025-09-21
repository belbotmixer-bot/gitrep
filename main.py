from flask import Flask, request, jsonify, send_file
import os
import uuid
import time
import requests
import logging
from audio_processor import mix_voice_with_music

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# --- Конфигурация ---
GITHUB_MUSIC_URL = "https://raw.githubusercontent.com/belbotmixer-bot/gitrep/main/background_music.mp3"

# Хранилище миксов (вместо базы данных)
MIX_STORAGE = {}  # client_id -> {"status": "processing|ready|error", "file": path, "url": url}

# ==================== УТИЛИТЫ ====================

def cleanup(filename):
    """Удаление временных файлов после обработки"""
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


@app.route("/upload_voice", methods=["POST"])
def upload_voice():
    """Принимаем голосовое и начинаем обработку (но не ждём завершения)"""
    try:
        data = request.get_json(force=True)
        voice_url = data.get("voice_url")
        client_id = data.get("client_id")
        name = data.get("name", "")

        if not voice_url or not client_id:
            return jsonify({"error": "voice_url and client_id required"}), 400

        logger.info(f"📥 Upload voice for client {client_id} from {voice_url}")

        # Помечаем статус клиента
        MIX_STORAGE[client_id] = {"status": "processing", "file": None, "url": None}

        # Скачиваем голос
        resp = requests.get(voice_url, timeout=300)
        resp.raise_for_status()

        voice_filename = f"voice_{uuid.uuid4().hex}.ogg"
        with open(voice_filename, "wb") as f:
            f.write(resp.content)

        # Миксуем
        output_filename = f"mixed_{uuid.uuid4().hex}.mp3"
        output_path = os.path.join(os.getcwd(), output_filename)
        mix_voice_with_music(voice_filename, output_path, GITHUB_MUSIC_URL)

        # Генерируем URL
        download_url = f"{request.host_url}download/{output_filename}"

        # Сохраняем в хранилище
        MIX_STORAGE[client_id] = {
            "status": "ready",
            "file": output_path,
            "url": download_url
        }

        cleanup(voice_filename)

        logger.info(f"✅ Mix ready for {client_id}: {download_url}")

        return jsonify({
            "status": "processing",
            "message": "🎤 Голосовое принято, микс обрабатывается",
            "client_id": client_id,
            "requested_at": time.time()
        })

    except Exception as e:
        logger.error(f"❌ Error in /upload_voice: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/get_mix", methods=["POST"])
def get_mix():
    """Отдаём готовый микс по client_id"""
    try:
        data = request.get_json(force=True)
        client_id = data.get("client_id")

        if not client_id:
            return jsonify({"error": "client_id required"}), 400

        entry = MIX_STORAGE.get(client_id)

        if not entry:
            return jsonify({"status": "not_found", "message": "Нет данных для этого клиента"}), 404

        if entry["status"] == "processing":
            return jsonify({
                "status": "processing",
                "message": "⌛ Микс ещё готовится"
            }), 200

        if entry["status"] == "ready":
            return jsonify({
                "status": "success",
                "message": "🎵 Микс готов",
                "download_url": entry["url"],
                "client_id": client_id
            }), 200

        return jsonify({"status": "error", "message": "Ошибка обработки"}), 500

    except Exception as e:
        logger.error(f"❌ Error in /get_mix: {e}")
        return jsonify({"error": str(e)}), 500


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


# ==================== ЗАПУСК СЕРВЕРА ====================
if __name__ == "__main__":
    logger.info("🌐 Starting Flask server (two-webhook mode)...")
    app.run(host="0.0.0.0", port=5000, debug=False)
