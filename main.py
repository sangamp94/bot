from flask import Flask, request
import requests

# Replace with your actual Telegram Bot Token
BOT_TOKEN = "7989632830:AAF3VKtSPf252DX83aTFXlVbg5jMeBFk6PY"
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/"
UPLOAD_API_KEY = "35948at4rupqy8a1w8hjh"
UPLOAD_API_URL = "https://earnvidsapi.com/api/upload/url"

app = Flask(__name__)

def send_message(chat_id, text):
    requests.post(API_URL + "sendMessage", json={
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    })

@app.route("/", methods=["GET"])
def home():
    return "✅ Hello, I am URL to Stream Upload Bot."

@app.route("/", methods=["POST"])
def webhook():
    data = request.get_json()

    if "message" in data:
        message = data["message"]
        chat_id = message["chat"]["id"]

        if "text" in message:
            text = message["text"]

            if text.startswith("/start"):
                send_message(chat_id, "👋 Hello! I am a *URL to Stream Upload Bot*.\nJust send me a video URL and I will upload it.")
            elif text.startswith("http://") or text.startswith("https://"):
                send_message(chat_id, "📥 Uploading your video, please wait...")
                filecode = upload_url(text)
                if filecode:
                    send_message(chat_id, f"✅ Uploaded!\nFileCode: `{filecode}`\nIt will be available soon.")
                else:
                    send_message(chat_id, "❌ Upload failed. Please try again later.")
            else:
                send_message(chat_id, "⚠️ Please send a valid video URL starting with http:// or https://")

    return "ok"

def upload_url(url):
    try:
        response = requests.get(f"{UPLOAD_API_URL}?key={UPLOAD_API_KEY}&url={url}")
        result = response.json()
        if result["status"] == 200:
            return result["result"]["filecode"]
    except Exception as e:
        print("Upload error:", e)
    return None

# Web server for Render
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
