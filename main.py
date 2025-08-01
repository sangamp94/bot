from flask import Flask, send_file, jsonify, abort
from datetime import datetime, timedelta
import threading
import subprocess
import json
import os
import pytz
import time

# --- Configuration ---
CONFIG_PATH = "video.json"
with open(CONFIG_PATH, "r") as f:
    CONFIG = json.load(f)
print("[✅] Configuration loaded successfully from video.json")

CHANNEL_NAME = CONFIG.get("channel_name", "TV Channel")
TIMEZONE = pytz.timezone(CONFIG.get("timezone", "Asia/Kolkata"))
SCHEDULE = CONFIG.get("timeline", [])
PLAYLISTS = CONFIG.get("playlists", {})
OUTPUT_HLS = "static/stream.m3u8"
PLAYLIST_FILE = "playlist.txt"

# --- Global State Management ---
current_process = None
current_show_name = None

app = Flask(__name__)
if not os.path.exists("static"):
    os.makedirs("static")


def get_current_show():
    """Determines the current show based on the schedule."""
    now = datetime.now(TIMEZONE)
    today = now.date()
    schedule = sorted(SCHEDULE, key=lambda x: datetime.strptime(x["start"], "%H:%M").time())

    for i, entry in enumerate(schedule):
        naive_start = datetime.combine(today, datetime.strptime(entry["start"], "%H:%M").time())
        start_time = TIMEZONE.localize(naive_start)

        next_i = (i + 1) % len(schedule)
        naive_end = datetime.combine(today, datetime.strptime(schedule[next_i]["start"], "%H:%M").time())
        end_time = TIMEZONE.localize(naive_end)

        if end_time <= start_time:
            end_time += timedelta(days=1)

        if start_time <= now < end_time:
            return entry["show"], PLAYLISTS.get(entry["show"], {})

    fallback_show = schedule[0]
    return fallback_show["show"], PLAYLISTS.get(fallback_show["show"], {})


def stop_current_stream():
    """Stops the currently running FFmpeg process."""
    global current_process
    if current_process:
        print(f"[🔄] Stopping current stream for '{current_show_name}'...")
        current_process.terminate()
        try:
            current_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            print("[⚠️] FFmpeg did not terminate gracefully, killing.")
            current_process.kill()
        print("[✅] Stream stopped.")
        current_process = None


def start_stream_for_show(show_name, show_info):
    """Starts a new FFmpeg stream for a given show."""
    global current_process
    video_urls = show_info.get("videos", [])

    if not video_urls:
        print(f"[⚠️] No videos found for show '{show_name}'. Waiting.")
        return

    with open(PLAYLIST_FILE, "w") as f:
        for url in video_urls:
            f.write(f"file '{url}'\n")

    print(f"[🎬] Starting new stream for: {show_name}")

    ffmpeg_cmd = [
        "ffmpeg", "-re",
        "-f", "concat", "-safe", "0",
        "-protocol_whitelist", "file,crypto,data,http,https,tls,tcp",
        "-i", PLAYLIST_FILE,
        "-vf", "setpts=PTS-STARTPTS",
        "-c:v", "libx264", "-preset", "ultrafast",
        "-maxrate", "800k", "-bufsize", "1000k",
        "-c:a", "aac", "-b:a", "128k",
        "-f", "hls",
        "-hls_time", "10",
        "-hls_list_size", "5",
        "-hls_flags", "delete_segments+program_date_time",
        OUTPUT_HLS
    ]
    
    print(f"Running FFmpeg command: {' '.join(ffmpeg_cmd)}")
    current_process = subprocess.Popen(ffmpeg_cmd)


def manage_stream():
    """The main loop to manage starting and stopping streams based on the schedule."""
    global current_show_name
    while True:
        try:
            new_show, show_info = get_current_show()
            if new_show != current_show_name:
                stop_current_stream()
                start_stream_for_show(new_show, show_info)
                current_show_name = new_show
        except Exception as e:
            print(f"[❌] Error in management loop: {e}")
        
        time.sleep(15)


# --- Flask Routes ---
@app.route("/")
def home():
    return f"{CHANNEL_NAME} is live 🎥"


@app.route("/stream/live.m3u8")
def stream():
    if not os.path.exists(OUTPUT_HLS):
        abort(404, description="HLS playlist not available yet. Please try again.")

    response = send_file(OUTPUT_HLS, mimetype='application/vnd.apple.mpegurl')
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response

@app.route("/stream/<segment>")
def stream_segment(segment):
    segment_path = os.path.join("static", segment)
    if not os.path.exists(segment_path):
        abort(404, description="Segment not found.")
    
    response = send_file(segment_path, mimetype='video/MP2T')
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response

@app.route("/status")
def current_status():
    show, info = get_current_show()
    return jsonify({
        "channel": CHANNEL_NAME,
        "current_show": show,
        "playlist": info.get("videos", [])
    })

# --- Main Application Start ---

# Start the background thread that manages FFmpeg when Gunicorn loads the app
threading.Thread(target=manage_stream, daemon=True).start()

if __name__ == "__main__":
    # This block is for local testing only (e.g., running `python app.py`)
    # It will not be used by Gunicorn on your server.
    print("[🚀] Starting local development server...")
    app.run(host="0.0.0.0", port=10000)
