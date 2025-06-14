from flask import Flask, request
import requests
import os
import tempfile
import logging
from urllib.parse import quote

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuration
BOT_TOKEN = "7989632830:AAF3VKtSPf252DX83aTFXlVbg5jMeBFk6PY"
PIXELDRAIN_API_KEY = "ee21fba3-0282-46d7-bb33-cf1cf54af822"
MAX_FILE_SIZE_MB = 2000
CHUNK_SIZE_MB = 950

API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
PIXELDRAIN_UPLOAD_URL = "https://pixeldrain.com/api/file"

def send_message(chat_id, text):
    try:
        response = requests.post(
            f"{API_URL}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True
            },
            timeout=10
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to send message to chat {chat_id}: {str(e)}")

def upload_to_pixeldrain(file_path):
    try:
        if not os.path.exists(file_path):
            logger.error(f"File not found: {file_path}")
            return None
            
        with open(file_path, "rb") as f:
            response = requests.post(
                PIXELDRAIN_UPLOAD_URL,
                headers={"Authorization": f"Bearer {PIXELDRAIN_API_KEY}"},
                files={"file": f},
                timeout=60*10
            )
            response.raise_for_status()
            data = response.json()
            if data.get("success"):
                return data["id"]
            logger.error(f"PixelDrain upload failed: {data}")
            return None
    except Exception as e:
        logger.error(f"Error uploading to PixelDrain: {str(e)}")
        return None

def split_file(filename, chunk_size_mb=CHUNK_SIZE_MB):
    parts = []
    part_num = 1
    chunk_size = chunk_size_mb * 1024 * 1024
    
    try:
        file_size = os.path.getsize(filename)
        if file_size <= chunk_size:
            return [filename]
        
        with open(filename, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                
                part_filename = f"{filename}_part{part_num}.mp4"
                with open(part_filename, "wb") as part:
                    part.write(chunk)
                parts.append(part_filename)
                part_num += 1
        return parts
    except Exception as e:
        logger.error(f"Error splitting file: {str(e)}")
        for part in parts:
            try:
                os.remove(part)
            except:
                pass
        raise

def cleanup_files(*files):
    for file_path in files:
        try:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
        except Exception as e:
            logger.warning(f"Could not delete file {file_path}: {str(e)}")

@app.route("/", methods=["POST"])
def webhook():
    try:
        update = request.get_json()
        if not update:
            return "ok"

        message = update.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        file = message.get("video") or message.get("document")

        if not chat_id or not file:
            return "ok"

        file_size = file.get("file_size", 0)
        if file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
            send_message(chat_id, f"❌ File too large. Maximum size is {MAX_FILE_SIZE_MB}MB.")
            return "ok"

        file_id = file["file_id"]
        send_message(chat_id, "📥 Downloading your file...")

        try:
            file_info = requests.get(f"{API_URL}/getFile?file_id={file_id}", timeout=10).json()
            if not file_info.get("result"):
                send_message(chat_id, "❌ Error: Couldn't get file info.")
                return "ok"
        except requests.exceptions.RequestException as e:
            send_message(chat_id, "❌ Error connecting to Telegram servers.")
            logger.error(f"Telegram API error: {str(e)}")
            return "ok"

        file_path = file_info["result"]["file_path"]
        download_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{quote(file_path)}"
        
        # Create a temporary directory for all files
        temp_dir = tempfile.mkdtemp()
        local_file = os.path.join(temp_dir, f"{file_id}.mp4")

        try:
            with requests.get(download_url, stream=True, timeout=60*15) as r:
                r.raise_for_status()
                with open(local_file, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
        except requests.exceptions.RequestException as e:
            send_message(chat_id, "❌ Error downloading file.")
            logger.error(f"Download error: {str(e)}")
            cleanup_files(local_file)
            os.rmdir(temp_dir)
            return "ok"

        send_message(chat_id, "✂️ Splitting file...")
        try:
            parts = split_file(local_file)
            cleanup_files(local_file)
        except Exception as e:
            send_message(chat_id, "❌ Error splitting file.")
            logger.error(f"File split error: {str(e)}")
            cleanup_files(local_file)
            os.rmdir(temp_dir)
            return "ok"

        links = []
        for part in parts:
            send_message(chat_id, f"⏫ Uploading `{os.path.basename(part)}`...")
            link_id = upload_to_pixeldrain(part)
            if link_id:
                links.append(f"https://pixeldrain.com/u/{link_id}")
            else:
                send_message(chat_id, f"❌ Failed to upload `{os.path.basename(part)}`")
            cleanup_files(part)

        if links:
            send_message(chat_id, "✅ Uploaded Parts:\n" + "\n".join(links))
        else:
            send_message(chat_id, "❌ All uploads failed.")

        # Clean up temp directory
        try:
            os.rmdir(temp_dir)
        except:
            pass

    except Exception as e:
        logger.error(f"Unexpected error in webhook: {str(e)}", exc_info=True)
        if chat_id:
            send_message(chat_id, "❌ An unexpected error occurred. Please try again.")

    return "ok"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
