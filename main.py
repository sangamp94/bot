from flask import Flask, request
import requests
import os
import base64

app = Flask(__name__)

# Directly set your tokens here
BOT_TOKEN = "7989632830:AAF3VKtSPf252DX83aTFXlVbg5jMeBFk6PY"
PIXELDRAIN_API_KEY = "ee21fba3-0282-46d7-bb33-cf1cf54af822"

API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/"
PIXELDRAIN_UPLOAD_URL = "https://pixeldrain.com/api/file/"

CHUNK_SIZE_MB = 9500  # 9500MB per part
CHUNK_SIZE = CHUNK_SIZE_MB * 1024 * 1024

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

def split_file_binary(file_path, prefix):
    parts = []
    with open(file_path, "rb") as f:
        i = 0
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            part_name = f"{prefix}_part{i}.mp4"
            with open(part_name, "wb") as pf:
                pf.write(chunk)
            parts.append(part_name)
            i += 1
    return parts

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

    file_info = requests.get(API_URL + f"getFile?file_id={file_id}").json()

    if "result" not in file_info:
        send_message(chat_id, f"❌ Failed to get file info:\n{file_info}")
        return "ok"

    file_path = file_info["result"]["file_path"]
    download_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
    local_file = f"file_{file_id}.mp4"

    with open(local_file, "wb") as f:
        f.write(requests.get(download_url).content)

    send_message(chat_id, "🔪 Splitting the file...")

    split_files = split_file_binary(local_file, f"chunk_{file_id}")
    os.remove(local_file)

    links = []
    for part in split_files:
        send_message(chat_id, f"⏫ Uploading `{part}`...")
        pid = upload_to_pixeldrain(part)
        if pid:
            links.append(f"https://pixeldrain.com/u/{pid}")
            os.remove(part)
        else:
            send_message(chat_id, f"❌ Failed to upload `{part}`")

    if links:
        reply = "✅ Uploaded Parts:\n" + "\n".join(links)
        send_message(chat_id, reply)
    else:
        send_message(chat_id, "❌ No parts uploaded successfully.")

    return "ok"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
