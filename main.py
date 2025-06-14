from flask import Flask, request
import requests
import os

app = Flask(__name__)

# Hardcoded tokens
BOT_TOKEN = "7989632830:AAF3VKtSPf252DX83aTFXlVbg5jMeBFk6PY"
PIXELDRAIN_API_KEY = "ee21fba3-0282-46d7-bb33-cf1cf54af822"
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
PIXELDRAIN_UPLOAD_URL = "https://pixeldrain.com/api/file"

def send_message(chat_id, text):
    requests.post(f"{API_URL}/sendMessage", json={
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    })

def upload_to_pixeldrain(file_path):
    with open(file_path, "rb") as f:
        response = requests.post(
            PIXELDRAIN_UPLOAD_URL,
            headers={"Authorization": f"Bearer {PIXELDRAIN_API_KEY}"},
            files={"file": f}
        )
        if response.ok and response.json().get("success"):
            return response.json()["id"]
        return None

def split_file(filename, chunk_size_mb=950):
    parts = []
    part_num = 1
    with open(filename, "rb") as f:
        while True:
            chunk = f.read(chunk_size_mb * 1024 * 1024)
            if not chunk:
                break
            part_filename = f"{filename}_part{part_num}.mp4"
            with open(part_filename, "wb") as part:
                part.write(chunk)
            parts.append(part_filename)
            part_num += 1
    return parts

@app.route("/", methods=["POST"])
def webhook():
    update = request.get_json()
    message = update.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    file = message.get("video") or message.get("document")

    if not chat_id or not file:
        return "ok"

    file_id = file["file_id"]
    send_message(chat_id, "📥 Downloading your file...")

    # Get download URL
    file_info = requests.get(f"{API_URL}/getFile?file_id={file_id}").json()
    if "result" not in file_info:
        send_message(chat_id, "❌ Error: Couldn't get file info.")
        return "ok"

    file_path = file_info["result"]["file_path"]
    download_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
    local_file = f"{file_id}.mp4"

    # Download file
    with open(local_file, "wb") as f:
        f.write(requests.get(download_url).content)

    send_message(chat_id, "✂️ Splitting file...")
    parts = split_file(local_file)
    os.remove(local_file)

    links = []
    for part in parts:
        send_message(chat_id, f"⏫ Uploading `{part}`...")
        link_id = upload_to_pixeldrain(part)
        if link_id:
            links.append(f"https://pixeldrain.com/u/{link_id}")
            os.remove(part)
        else:
            send_message(chat_id, f"❌ Failed to upload `{part}`")

    if links:
        send_message(chat_id, "✅ Uploaded Parts:\n" + "\n".join(links))
    else:
        send_message(chat_id, "❌ All uploads failed.")

    return "ok"

if __name__ == "__main__":
    from gunicorn.app.base import BaseApplication

    class FlaskApp(BaseApplication):
        def load_config(self): pass
        def load(self): return app

    FlaskApp().run()
