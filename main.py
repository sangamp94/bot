from flask import Flask, request
import requests
import os
import tempfile
import logging
from urllib.parse import quote
import shutil

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
            logger.error(f"File not found for upload: {file_path}")
            return None
            
        logger.info(f"Attempting to upload file: {file_path} (size: {os.path.getsize(file_path)} bytes)")
        
        with open(file_path, "rb") as f:
            response = requests.post(
                PIXELDRAIN_UPLOAD_URL,
                headers={"Authorization": f"Bearer {PIXELDRAIN_API_KEY}"},
                files={"file": f},
                timeout=60*30  # 30 minute timeout for large files
            )
            response.raise_for_status()
            data = response.json()
            if data.get("success"):
                logger.info(f"Upload successful for {file_path}")
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
        logger.info(f"Splitting file {filename} (size: {file_size} bytes)")
        
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
                logger.info(f"Created part {part_num}: {part_filename}")
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

@app.route("/", methods=["POST"])
def webhook():
    temp_dir = None
    local_file = None
    parts = []
    
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
        logger.info(f"Created temp directory: {temp_dir}")
        logger.info(f"Downloading to: {local_file}")

        try:
            with requests.get(download_url, stream=True, timeout=60*15) as r:
                r.raise_for_status()
                with open(local_file, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
            logger.info(f"Download complete. File size: {os.path.getsize(local_file)} bytes")
        except requests.exceptions.RequestException as e:
            send_message(chat_id, "❌ Error downloading file.")
            logger.error(f"Download error: {str(e)}")
            return "ok"

        send_message(chat_id, "✂️ Splitting file...")
        try:
            parts = split_file(local_file)
            logger.info(f"Split into {len(parts)} parts")
        except Exception as e:
            send_message(chat_id, "❌ Error splitting file.")
            logger.error(f"File split error: {str(e)}")
            return "ok"

        links = []
        for part in parts:
            if not os.path.exists(part):
                logger.error(f"Part file missing: {part}")
                send_message(chat_id, f"❌ File part missing: {os.path.basename(part)}")
                continue
                
            send_message(chat_id, f"⏫ Uploading `{os.path.basename(part)}`...")
            link_id = upload_to_pixeldrain(part)
            if link_id:
                links.append(f"https://pixeldrain.com/u/{link_id}")
            else:
                send_message(chat_id, f"❌ Failed to upload `{os.path.basename(part)}`")

        if links:
            send_message(chat_id, "✅ Uploaded Parts:\n" + "\n".join(links))
        else:
            send_message(chat_id, "❌ All uploads failed.")

    except Exception as e:
        logger.error(f"Unexpected error in webhook: {str(e)}", exc_info=True)
        if chat_id:
            send_message(chat_id, "❌ An unexpected error occurred. Please try again.")
    finally:
        # Clean up all files and directory
        logger.info("Cleaning up temporary files...")
        try:
            if local_file and os.path.exists(local_file):
                os.remove(local_file)
            for part in parts:
                if part and os.path.exists(part):
                    os.remove(part)
            if temp_dir and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")

    return "ok"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
