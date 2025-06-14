from flask import Flask, request
import requests
import os
import base64
import subprocess

app = Flask(__name__)

BOT_TOKEN = "YOUR_BOT_TOKEN"
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
    local_file = f"file_{file_id}.mp4"

    # Download file
    with open(local_file, "wb") as f:
        f.write(requests.get(download_url).content)

    send_message(chat_id, "🧱 Splitting file...")

    # Split using ffmpeg into 9500MB parts
    split_prefix = f"split_{file_id}_"
    subprocess.run([
        "ffmpeg", "-i", local_file, "-fs", "9500M", f"{split_prefix}%03d.mp4"
    ], check=True)

    os.remove(local_file)

    # Upload each split part
    links = []
    for fname in sorted(os.listdir(".")):
        if fname.startswith(split_prefix) and fname.endswith(".mp4"):
            send_message(chat_id, f"⏫ Uploading `{fname}`...")
            file_id = upload_to_pixeldrain(fname)
            if file_id:
                links.append(f"https://pixeldrain.com/u/{file_id}")
                os.remove(fname)
            else:
                send_message(chat_id, f"❌ Failed to upload `{fname}`")

    if links:
        reply = "✅ Uploaded Parts:\n" + "\n".join(links)
        send_message(chat_id, reply)
    else:
        send_message(chat_id, "❌ No parts uploaded successfully.")

    return "ok"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
