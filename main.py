from flask import Flask, request
import requests
import os
import base64

app = Flask(__name__)

BOT_TOKEN = "7989632830:AAF3VKtSPf252DX83aTFXlVbg5jMeBFk6PY"
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/"
PIXELDRAIN_API_KEY = "ee21fba3-0282-46d7-bb33-cf1cf54af822"  # 🔐 Set this to your real API key

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

    if text and text.startswith("/start"):
        send_message(chat_id, "👋 *Hello! I can upload your videos to PixelDrain!*")

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

            send_message(chat_id, "⏫ Uploading to PixelDrain...")

            with open(local_filename, "rb") as f:
                headers = {
                    "Authorization": "Basic " + base64.b64encode(f":{PIXELDRAIN_API_KEY}".encode()).decode()
                }
                response = requests.post(
                    "https://pixeldrain.com/api/file/",
                    headers=headers,
                    files={"file": f}
                ).json()

            os.remove(local_filename)

            if "id" in response:
                file_id = response["id"]
                file_url = f"https://pixeldrain.com/u/{file_id}"
                send_message(chat_id, f"✅ Uploaded!\n🔗 {file_url}")
            else:
                send_message(chat_id, f"❌ Upload failed: `{response.get('message', 'Unknown error')}`")

        except Exception as e:
            send_message(chat_id, f"⚠️ Error during upload: `{str(e)}`")

    return "ok"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
