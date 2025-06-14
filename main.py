from flask import Flask, request
import requests
import os

app = Flask(__name__)

BOT_TOKEN = "7989632830:AAF3VKtSPf252DX83aTFXlVbg5jMeBFk6PY"
API_KEY = "35948at4rupqy8a1w8hjh"
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/"


def send_message(chat_id, text):
    """Send a message to the Telegram user."""
    url = API_URL + "sendMessage"
    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    requests.post(url, json=data)


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

    # /uploadurl <video_url>
    elif text and text.startswith("/uploadurl"):
        parts = text.split(" ", 1)
        if len(parts) < 2:
            send_message(chat_id, "❗ Usage: `/uploadurl <video_url>`")
        else:
            video_url = parts[1].strip()

            # Optional: basic format check
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
                else:
                    send_message(chat_id, f"❌ Failed: {res.get('msg') or 'Unknown error'}")

            except Exception as e:
                send_message(chat_id, f"⚠️ Upload failed: `{str(e)}`")

    # If user sends a file or video
    elif video:
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
                else:
                    send_message(chat_id, "❌ Upload failed.")
            else:
                send_message(chat_id, "❌ Failed to get upload server.")

        except Exception as e:
            send_message(chat_id, f"⚠️ Error during upload: `{str(e)}`")

    return "ok"


# Flask runs for local dev; Render will use gunicorn
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
