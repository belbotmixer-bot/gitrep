import os
import json
import uuid
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

TELEGRAM_API_URL = f"https://api.telegram.org/bot{os.getenv('TELEGRAM_BOT_TOKEN')}"
SALEBOT_CALLBACK_URL = os.getenv("SALEBOT_CALLBACK_URL", "")

@app.route("/process_audio", methods=["POST"])
def process_audio():
    try:
        data = request.json
        print("📦 Received data:", data)

        client_id = data.get("platform_id")   # ID клиента в Salebot
        name = data.get("name", "")
        direct_url = data.get("direct_url", "")  # ссылка на готовый микс

        # --- В реальном коде здесь у тебя будет генерация аудио файла ---
        task_id = str(uuid.uuid4())
        output_filename = f"/tmp/{task_id}.mp3"

        # тестовый пустой файл
        with open(output_filename, "wb") as f:
            f.write(b"FAKEAUDIO")

        # --- Отправляем в Telegram аудио + кнопку ---
        send_url = f"{TELEGRAM_API_URL}/sendAudio"
        with open(output_filename, "rb") as audio_file:
            files = {"audio": (f"{task_id}.mp3", audio_file, "audio/mpeg")}
            payload = {
                "chat_id": client_id,
                "caption": f"🎶 Ваш микс готов! {name}" if name else "🎶 Ваш микс готов!",
                "reply_markup": {
                    "inline_keyboard": [[
                        {
                            "text": "📥 Сохранить ссылку",
                            "callback_data": f'callback({client_id}, "{direct_url}")'
                        }
                    ]]
                }
            }
            resp = requests.post(
                send_url,
                data={
                    "chat_id": client_id,
                    "caption": payload["caption"],
                    "reply_markup": json.dumps(payload["reply_markup"])
                },
                files=files,
                timeout=300
            )
            print("📨 Telegram resp:", resp.text)

        return jsonify({"status": "ok", "direct_url": direct_url})

    except Exception as e:
        print("❌ Ошибка:", str(e))
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
