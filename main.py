from flask import Flask, request
import requests
import os
import base64
import math

app = Flask(__name__)

BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/"
PIXELDRAIN_API_KEY = "7989632830:AAF3VKtSPf252DX83aTFXlVbg5jMeBFk6PY"
PIXELDRAIN_UPLOAD_URL = "https://pixeldrain.com/api/file/"

def send_message(chat_id, text):
    requests.post(API_URL + "sendMessage", json={
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    })

def upload_to_pixeldrain(file_path):
    with open(file_path, "rb") as f:
        headers = {
            "Authorization": "Basic " + base64.b64encode(f":{PIXELDRAIN_API_KEY}".encode()).decode()
        }
        response = requests.post(PIXELDRAIN_UPLOAD_URL, headers=headers, files={"file": f}).json()
        return response.get("id")

@app.route("/", methods=["POST"])
def webhook():
    update = request.get_json()
    message = update.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    video = message.get("video") or message.get("document")

    if not video:
        send_message(chat_id, "❗ Please send a video or document.")
        return "ok"

    file_id = video["file_id"]
    send_message(chat_id, "📥 Downloading your file...")

    # Get file download path from Telegram
    file_info = requests.get(API_URL + f"getFile?file_id={file_id}").json()
    file_path = file_info["result"]["file_path"]
    download_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
    local_file = f"file_{file_id}.mp4"

    # Get file size
    file_head = requests.head(download_url)
    file_size = int(file_head.headers.get("Content-Length", 0))
    downloaded = 0
    percent_notified = 0

    # Stream download with progress
    response = requests.get(download_url, stream=True)
    with open(local_file, "wb") as f:
        for chunk in response.iter_content(chunk_size=1024 * 1024):  # 1MB
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                percent = math.floor((downloaded / file_size) * 100)
                if percent >= percent_notified + 10:
                    percent_notified = percent
                    send_message(chat_id, f"⬇️ Downloaded {percent}%...")

    send_message(chat_id, "⏫ Uploading to PixelDrain...")

    file_code = upload_to_pixeldrain(local_file)
    os.remove(local_file)

    if file_code:
        send_message(chat_id, f"✅ Upload Complete!\n🔗 [View File](https://pixeldrain.com/u/{file_code})")
    else:
        send_message(chat_id, "❌ Upload failed.")

    return "ok"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
