from flask import Flask, request
import requests
import os
import base64

app = Flask(__name__)

BOT_TOKEN = "7989632830:AAF3VKtSPf252DX83aTFXlVbg5jMeBFk6PY"
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/"
PIXELDRAIN_API_KEY = "ee21fba3-0282-46d7-bb33-cf1cf54af822"
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

def split_file(filename, chunk_size=950 * 1024 * 1024):
    parts = []
    with open(filename, "rb") as f:
        i = 0
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            part_name = f"{filename}_part{i}.bin"
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
    file_path = file_info["result"]["file_path"]
    download_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
    local_file = f"file_{file_id}.bin"

    with open(local_file, "wb") as f:
        f.write(requests.get(download_url).content)

    send_message(chat_id, "🧱 Splitting file into 950MB chunks...")

    chunks = split_file(local_file)
    os.remove(local_file)

    links = []
    for part in chunks:
        send_message(chat_id, f"⏫ Uploading `{part}`...")
        pix_id = upload_to_pixeldrain(part)
        if pix_id:
            links.append(f"https://pixeldrain.com/u/{pix_id}")
        else:
            send_message(chat_id, f"❌ Failed to upload `{part}`")
        os.remove(part)

    if links:
        reply = "✅ Uploaded Parts:\n" + "\n".join(links)
        send_message(chat_id, reply)
    else:
        send_message(chat_id, "❌ No parts uploaded successfully.")

    return "ok"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
