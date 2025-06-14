from flask import Flask, request
import requests

BOT_TOKEN = "7989632830:AAF3VKtSPf252DX83aTFXlVbg5jMeBFk6PY"
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

app = Flask(__name__)

@app.route('/', methods=['POST'])
def webhook():
    update = request.json

    if not update or "message" not in update:
        return "ok", 200

    chat_id = update["message"]["chat"]["id"]
    text = update["message"].get("text", "")

    # Simple reply for any text message
    reply_text = "Hello! You said:\n" + text

    # Send reply back to Telegram
    requests.post(API_URL, json={
        "chat_id": chat_id,
        "text": reply_text
    })

    return "ok", 200

@app.route('/')
def index():
    return "Bot is running", 200

if __name__ == '__main__':
    app.run()
