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
try:
    with open(CONFIG_PATH, "r") as f:
        CONFIG = json.load(f)
    print("[✅] Configuration loaded successfully from video.json")
except FileNotFoundError:
    print(f"[❌] ERROR: Configuration file not found at '{CONFIG_PATH}'. Please create it.")
    exit(1)
except json.JSONDecodeError:
    print(f"[❌] ERROR: Could not parse '{CONFIG_PATH}'. Please check for valid JSON.")
    exit(1)


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
    
    # Ensure schedule is not empty to prevent errors
    if not SCHEDULE:
        return None, {}

    schedule = sorted(SCHEDULE, key=lambda x: datetime.strptime(x["start"], "%H:%M").time())

    for i, entry in enumerate(schedule):
        naive_start = datetime.combine(today, datetime.strptime(entry["start"], "%H:%M").time())
        start_time = TIMEZONE.localize(naive_start)

        next_i = (i + 1) % len(schedule)
        naive_end = datetime.combine(today, datetime.strptime(schedule[next_i]["start"], "%H:%M").time())
        end_time = TIMEZONE.localize(naive_end)

        # Handle schedules that cross midnight
        if end_time <= start_time:
            if now.time() >= start_time.time(): # e.g., it's 23:00, show starts at 22:00
                end_time += timedelta(days=1)
            else: # e.g., it's 01:00, show started at 22:00 yesterday
                start_time -= timedelta(days=1)

        if start_time <= now < end_time:
            return entry["show"], PLAYLISTS.get(entry["show"], {})

    # Fallback if no current show is found (should not happen in a well-configured schedule)
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
    """Starts a new FFmpeg stream for a given show with audio sync fix."""
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
        # --- FIX: Add the audio filter to sync audio with video ---
        "-af", "asetpts=PTS-STARTPTS,aresample=async=1",
        # ---------------------------------------------------------
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
    # Use Popen to run FFmpeg in the background
    current_process = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def manage_stream():
    """The main loop to manage starting and stopping streams based on the schedule."""
    global current_show_name
    while True:
        try:
            new_show, show_info = get_current_show()
            
            if new_show is None:
                print("[INFO] No schedule configured. Waiting...")
                time.sleep(60)
                continue

            if new_show != current_show_name:
                stop_current_stream()
                start_stream_for_show(new_show, show_info)
                current_show_name = new_show
        except Exception as e:
            print(f"[❌] Error in management loop: {e}")
        
        # Check every 15 seconds for a schedule change
        time.sleep(15)


# --- Flask Routes ---
@app.route("/")
def home():
    """Home page showing the channel name."""
    return f"<h1>{CHANNEL_NAME} is live 🎥</h1>"


@app.route("/stream/live.m3u8")
def stream():
    """Serves the main HLS playlist file."""
    if not os.path.exists(OUTPUT_HLS):
        abort(404, description="HLS playlist not available yet. Please try again.")

    response = send_file(OUTPUT_HLS, mimetype='application/vnd.apple.mpegurl')
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response

@app.route("/stream/<segment>")
def stream_segment(segment):
    """Serves the HLS video segments (.ts files)."""
    segment_path = os.path.join("static", segment)
    if not os.path.exists(segment_path):
        abort(404, description="Segment not found.")
    
    response = send_file(segment_path, mimetype='video/MP2T')
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response

@app.route("/status")
def current_status():
    """Provides a JSON status of the current show."""
    show, info = get_current_show()
    return jsonify({
        "channel": CHANNEL_NAME,
        "current_show": show,
        "playlist": info.get("videos", []),
        "streaming_process_active": current_process is not None
    })

# --- Main Application Start ---

# Start the background thread that manages FFmpeg when the app loads.
# The 'daemon=True' flag ensures the thread will exit when the main app exits.
threading.Thread(target=manage_stream, daemon=True).start()

if __name__ == "__main__":
    # This block is for local testing only (e.g., running `python app.py`).
    # A production server like Gunicorn will use the `app` object directly.
    print("[🚀] Starting local development server...")
    app.run(host="0.0.0.0", port=10000, debug=False)
