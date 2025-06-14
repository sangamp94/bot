from flask import Flask, request
import requests
import os
import tempfile
import logging

# === CONFIGURATION ===
BOT_TOKEN = "7989632830:AAF3VKtSPf252DX83aTFXlVbg5jMeBFk6PY"
PIXELDRAIN_API_KEY = "ee21fba3-0282-46d7-bb33-cf1cf54af822"
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
PIXELDRAIN_UPLOAD_URL = "https://pixeldrain.com/api/file"

# === INIT ===
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# === TELEGRAM MESSAGE ===
def send_message(chat_id, text):
    requests.post(f"{API_URL}/sendMessage", json={
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    })

# === PIXELDRAIN UPLOAD FUNCTION ===
def upload_from_url(file_url):
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp_file:
            response = requests.get(file_url, stream=True)
            if not response.ok:
                return None

            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    tmp_file.write(chunk)

            tmp_file_path = tmp_file.name

        # Upload to PixelDrain
        with open(tmp_file_path, "rb") as f:
            headers = {
                "Authorization": f"Bearer {PIXELDRAIN_API_KEY}"
            }
            upload = requests.post(
                PIXELDRAIN_UPLOAD_URL,
                headers=headers,
                files={"file": f}
            )

        os.remove(tmp_file_path)

        if upload.ok and upload.json().get("success"):
            file_id = upload.json()["id"]
            return f"https://pixeldrain.com/u/{file_id}"
        else:
            return None
    except Exception as e:
        logging.error(f"Upload error: {e}")
        return None

# === FLASK TELEGRAM HOOK ===
@app.route("/", methods=["POST"])
def webhook():
    data = request.get_json()
    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text")

    if not text or not text.startswith("http"):
        send_message(chat_id, "⚠️ Please send a valid video URL.")
        return "ok"

    send_message(chat_id, "📥 Downloading and uploading your video...")

    pixeldrain_link = upload_from_url(text)

    if pixeldrain_link:
        send_message(chat_id, f"✅ Uploaded!\n🔗 [Stream Now]({pixeldrain_link})")
    else:
        send_message(chat_id, "❌ Upload failed. Try again later.")

    return "ok"

# === MAIN ===
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
