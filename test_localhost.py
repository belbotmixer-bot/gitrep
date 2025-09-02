import threading
import time
from flask import Flask, jsonify
import requests

# --- Flask ---
app = Flask(__name__)

@app.route("/ping")
def ping():
    return jsonify({"status": "ok"})

def run_flask():
    print("Запускаем Flask...")
    app.run(host="0.0.0.0", port=5000)

# --- "Бот" (тестовый запрос) ---
def test_bot():
    time.sleep(3)  # ждём пока Flask стартанёт
    try:
        r = requests.get("http://localhost:5000/ping")
        print("Статус запроса:", r.status_code, r.json())
    except Exception as e:
        print("Ошибка при обращении к localhost:", e)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    test_bot()
