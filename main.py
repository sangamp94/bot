from flask import Flask, request
import requests
import os

# ⛔ HARDCODED values (update these before uploading!)
BOT_TOKEN = "7989632830:AAF3VKtSPf252DX83aTFXlVbg5jMeBFk6PY"
EARNVIDS_API_KEY = "35948at4rupqy8a1w8hjh"
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/"

app = Flask(__name__)

@app.route("/", methods=["GET"])
def index():
    return "✅ Bot is running!"

@app.route("/", methods=["POST"])
def webhook():
    update = request.get_json()
    if not update:
        return "Invalid", 400

    message = update.get("message", {})
    chat_id = message.get("chat", {}).get("id")

    if "text" in message:
        text = message["text"]
        if text.startswith("/start"):
            send_message(chat_id, "👋 Welcome! Send a video or use /uploadurl <link>")
        elif text.startswith("/uploadurl"):
            handle_url_upload(chat_id, text)
    elif "video" in message or "document" in message:
        handle_video_upload(chat_id, message.get("video") or message.get("document"))

    return "OK", 200

def send_message(chat_id, text):
    requests.get(API_URL + "sendMessage", params={
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    })

def handle_url_upload(chat_id, text):
    parts = text.split(" ", 1)
    if len(parts) < 2:
        send_message(chat_id, "❗ Usage: /uploadurl <video_url>")
        return

    video_url = parts[1].strip()
    api = f"https://earnvidsapi.com/api/upload/url?key={EARNVIDS_API_KEY}&url={video_url}"
    response = requests.get(api).json()

    if response["status"] == 200:
        filecode = response["result"]["filecode"]
        send_message(chat_id, f"✅ Uploaded!\n🔗 <code>https://movearnpre.com/embed/{filecode}</code>")
    else:
        send_message(chat_id, f"❌ Failed: {response['msg']}")

def handle_video_upload(chat_id, file):
    send_message(chat_id, "📥 Downloading your video...")
    file_id = file["file_id"]
    file_info = requests.get(API_URL + f"getFile?file_id={file_id}").json()
    file_path = file_info["result"]["file_path"]
    file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"

    local_file = f"video_{chat_id}.mp4"
    with open(local_file, "wb") as f:
        f.write(requests.get(file_url).content)

    send_message(chat_id, "⏫ Uploading to EarnVids...")
    upload_url = requests.get(f"https://api.earnvids.com/api/upload/server?key={EARNVIDS_API_KEY}").json()["result"]["upload_server"]

    with open(local_file, "rb") as f:
        upload_resp = requests.post(upload_url, files={"file": f}).json()

    os.remove(local_file)

    if "result" in upload_resp and "link" in upload_resp["result"]:
        send_message(chat_id, f"✅ Uploaded!\n🔗 {upload_resp['result']['link']}")
    else:
        send_message(chat_id, "❌ Upload failed.")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
