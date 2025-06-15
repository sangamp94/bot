from flask import Flask, request
import requests
import os
from datetime import datetime, timedelta

app = Flask(__name__)

BOT_TOKEN = "7989632830:AAF3VKtSPf252DX83aTFXlVbg5jMeBFk6PY"
API_KEY = "35948at4rupqy8a1w8hjh"
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/"

VALID_TOKEN = "12345678"  # Replace this with your private token
user_tokens = {}         # chat_id: expiry time
last_upload_time = {}    # chat_id: last upload time
TOKEN_EXPIRY_HOURS = 5
UPLOAD_COOLDOWN_MINUTES = 2


def send_message(chat_id, text):
    url = API_URL + "sendMessage"
    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    requests.post(url, json=data)


def is_user_verified(chat_id):
    expiry = user_tokens.get(chat_id)
    return expiry and datetime.now() < expiry


def is_upload_allowed(chat_id):
    last_time = last_upload_time.get(chat_id)
    if not last_time:
        return True
    return datetime.now() >= last_time + timedelta(minutes=UPLOAD_COOLDOWN_MINUTES)


@app.route('/', methods=['POST'])
def webhook():
    update = request.get_json()
    if not update:
        return "No update received"

    message = update.get("message")
    if not message:
        return "No message"

    chat_id = message["chat"]["id"]
    text = message.get("text")
    video = message.get("video") or message.get("document")

    # /start command
    if text and text.startswith("/start"):
        send_message(chat_id, "👋 *Hello, I am URL to Stream & Upload Bot!*")
        return "ok"

    # /token <your_token>
    if text and text.startswith("/token"):
        parts = text.split(" ", 1)
        if len(parts) < 2:
            send_message(chat_id, "❗ Usage: `/token <your_token>`")
            return "ok"

        input_token = parts[1].strip()
        if input_token == VALID_TOKEN:
            expiry = datetime.now() + timedelta(hours=TOKEN_EXPIRY_HOURS)
            user_tokens[chat_id] = expiry
            send_message(chat_id, f"✅ *Access granted for 5 hours!*")
        else:
            send_message(chat_id, "⛔ *Invalid token.*")
        return "ok"

    # /uploadurl <video_url>
    elif text and text.startswith("/uploadurl"):
        if not is_user_verified(chat_id):
            send_message(chat_id, "⛔ *Your token is not verified.*\nUse `/token <your_token>` to activate access.")
            return "ok"

        if not is_upload_allowed(chat_id):
            send_message(chat_id, f"⏳ Please wait 10 minutes between uploads.")
            return "ok"

        parts = text.split(" ", 1)
        if len(parts) < 2:
            send_message(chat_id, "❗ Usage: `/uploadurl <video_url>`")
            return "ok"

        video_url = parts[1].strip()
        if not video_url.startswith("http"):
            send_message(chat_id, "❗ Please provide a valid video URL.")
            return "ok"

        send_message(chat_id, "🔄 Uploading via URL...")

        try:
            res = requests.get(
                f"https://earnvidsapi.com/api/upload/url?key={API_KEY}&url={video_url}",
                timeout=15
            ).json()

            if res.get("status") == 200:
                filecode = res["result"]["filecode"]
                send_message(chat_id, f"✅ Uploaded!\n🔗 https://movearnpre.com/embed/{filecode}")
                last_upload_time[chat_id] = datetime.now()
            else:
                send_message(chat_id, f"❌ Failed: {res.get('msg') or 'Unknown error'}")

        except Exception as e:
            send_message(chat_id, f"⚠️ Upload failed: `{str(e)}`")
        return "ok"

    # If user sends a file or video
    elif video:
        if not is_user_verified(chat_id):
            send_message(chat_id, "⛔ *Your token is not verified.*\nUse `/token <your_token>` to activate access.")
            return "ok"

        if not is_upload_allowed(chat_id):
            send_message(chat_id, f"⏳ Please wait 10 minutes between uploads.")
            return "ok"

        file_id = video["file_id"]
        send_message(chat_id, "📥 Downloading your file...")

        try:
            file_info = requests.get(API_URL + f"getFile?file_id={file_id}").json()
            file_path = file_info["result"]["file_path"]
            download_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"

            local_filename = f"temp_{file_id}.mp4"
            with open(local_filename, "wb") as f:
                f.write(requests.get(download_url).content)

            send_message(chat_id, "⏫ Uploading to EarnVids...")

            upload_server = requests.get(
                f"https://earnvidsapi.com/api/upload/server?key={API_KEY}"
            ).json()

            if upload_server.get("status") == 200:
                upload_url = upload_server["result"]

                with open(local_filename, "rb") as f:
                    files = {
                        "file": (local_filename, f),
                        "key": (None, API_KEY)
                    }
                    upload_response = requests.post(upload_url, files=files).json()

                os.remove(local_filename)

                if upload_response.get("status") == 200:
                    filecode = upload_response["files"][0]["filecode"]
                    send_message(chat_id, f"✅ Uploaded!\n🔗 https://movearnpre.com/embed/{filecode}")
                    last_upload_time[chat_id] = datetime.now()
                else:
                    send_message(chat_id, "❌ Upload failed.")
            else:
                send_message(chat_id, "❌ Failed to get upload server.")

        except Exception as e:
            send_message(chat_id, f"⚠️ Error during upload: `{str(e)}`")

    return "ok"


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
