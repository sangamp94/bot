from flask import Flask, request
import requests
import os
import tempfile
import subprocess
import logging
from urllib.parse import quote

BOT_TOKEN = "7989632830:AAF3VKtSPf252DX83aTFXlVbg5jMeBFk6PY"
PIXELDRAIN_API_KEY = "ee21fba3-0282-46d7-bb33-cf1cf54af822"
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
PIXELDRAIN_UPLOAD_URL = "https://pixeldrain.com/api/file"
CHUNK_SIZE_MB = 950
MAX_FILE_SIZE_MB = 2000

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def send_message(chat_id, text):
    try:
        requests.post(f"{API_URL}/sendMessage", json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        })
    except Exception as e:
        logger.error(f"❌ Error sending message: {e}")

def upload_to_pixeldrain(file_path):
    try:
        with open(file_path, "rb") as f:
            res = requests.post(
                PIXELDRAIN_UPLOAD_URL,
                headers={"Authorization": f"Bearer {PIXELDRAIN_API_KEY}"},
                files={"file": f}
            )
        if res.ok and res.json().get("success"):
            return res.json()["id"]
        logger.error(f"❌ Upload failed: {res.text}")
    except Exception as e:
        logger.error(f"❌ Exception during upload: {e}")
    return None

def ffmpeg_split(file_path, output_dir):
    split_files = []
    try:
        duration = float(subprocess.check_output([
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", file_path
        ]).decode().strip())

        chunk_sec = 600  # ~10 minutes per part (~950MB approx)

        i = 0
        while True:
            part_path = os.path.join(output_dir, f"{os.path.basename(file_path)}_part{i+1}.mp4")
            cmd = [
                "ffmpeg", "-y", "-ss", str(i * chunk_sec), "-i", file_path,
                "-t", str(chunk_sec), "-c", "copy", part_path
            ]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if os.path.exists(part_path) and os.path.getsize(part_path) > 0:
                split_files.append(part_path)
                i += 1
                if i * chunk_sec >= duration:
                    break
            else:
                break
    except Exception as e:
        logger.error(f"❌ FFmpeg split failed: {e}")
    return split_files

@app.route("/", methods=["POST"])
def webhook():
    data = request.get_json()
    msg = data.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    file = msg.get("video") or msg.get("document")

    if not chat_id or not file:
        return "ok"

    file_id = file["file_id"]
    file_size = file.get("file_size", 0)
    if file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
        send_message(chat_id, f"❌ File too large. Max allowed is {MAX_FILE_SIZE_MB}MB.")
        return "ok"

    send_message(chat_id, "📥 Downloading your file...")

    try:
        file_info = requests.get(f"{API_URL}/getFile?file_id={file_id}").json()
        file_path = file_info["result"]["file_path"]
        download_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{quote(file_path)}"
    except Exception as e:
        send_message(chat_id, "❌ Error getting file info.")
        logger.error(f"Error: {e}")
        return "ok"

    with tempfile.TemporaryDirectory() as tmpdir:
        local_path = os.path.join(tmpdir, os.path.basename(file_path))
        try:
            with open(local_path, "wb") as f:
                f.write(requests.get(download_url).content)
        except Exception as e:
            send_message(chat_id, "❌ Failed to download the file.")
            logger.error(f"❌ Download error: {e}")
            return "ok"

        send_message(chat_id, "✂️ Splitting file..." if file_size > CHUNK_SIZE_MB * 1024 * 1024 else "⏫ Uploading file...")

        if file_size < CHUNK_SIZE_MB * 1024 * 1024:
            parts = [local_path]
        else:
            parts = ffmpeg_split(local_path, tmpdir)

        links = []
        for part in parts:
            send_message(chat_id, f"⏫ Uploading `{os.path.basename(part)}`...")
            file_id = upload_to_pixeldrain(part)
            if file_id:
                links.append(f"https://pixeldrain.com/u/{file_id}")
            else:
                send_message(chat_id, f"❌ Failed to upload `{os.path.basename(part)}`")

        if links:
            send_message(chat_id, "✅ Uploaded:\n" + "\n".join(links))
        else:
            send_message(chat_id, "❌ Upload failed.")

    return "ok"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
