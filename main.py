from flask import Flask, request
import requests
import os

app = Flask(__name__)

# Hardcoded bot token and PixelDrain API key
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
    try:
        with open(file_path, "rb") as f:
            response = requests.post(
                PIXELDRAIN_UPLOAD_URL,
                headers={"Authorization": f"Bearer {PIXELDRAIN_API_KEY}"},
                files={"file": f}
            )
            data = response.json()
            if response.ok and data.get("success") and "id" in data:
                return data["id"]
            print("❌ Upload failed:", data)
            return None
    except Exception as e:
        print(f"❌ Upload error: {e}")
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

    file_info = requests.get(f"{API_URL}/getFile?file_id={file_id}").json()
    file_path = file_info.get("result", {}).get("file_path")

    if not file_path:
        send_message(chat_id, "❌ Error: Couldn't get file info.")
        return "ok"

    download_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
    local_file = f"{file_id}.mp4"

    try:
        r = requests.get(download_url, stream=True)
        with open(local_file, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
    except Exception as e:
        send_message(chat_id, f"❌ Download failed: {str(e)}")
        return "ok"

    send_message(chat_id, "✂️ Splitting file...")
    parts = split_file(local_file)
    os.remove(local_file)

    links = []
    for part in parts:
        send_message(chat_id, f"⏫ Uploading `{part}`...")
        link_id = upload_to_pixeldrain(part)
        if link_id:
            links.append(f"https://pixeldrain.com/u/{link_id}")
        else:
            send_message(chat_id, f"❌ Failed to upload `{part}`")
        os.remove(part)

    if links:
        send_message(chat_id, "✅ Uploaded Parts:\n" + "\n".join(links))
    else:
        send_message(chat_id, "❌ All uploads failed.")

    return "ok"

if __name__ == "__main__":
    import sys
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
