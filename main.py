import flask
from flask import Flask, send_file, jsonify, abort
from datetime import datetime, timedelta
import threading
import subprocess
import json
import os
import pytz
import time
import fcntl

# --- Configuration ---
CONFIG_PATH = "video.json"
try:
    with open(CONFIG_PATH, "r") as f:
        CONFIG = json.load(f)
    print("[INFO] ✅ Configuration loaded successfully from video.json")
except FileNotFoundError:
    print(f"[ERROR] ❌ Configuration file not found at: {CONFIG_PATH}. Please create it.")
    exit(1)
except json.JSONDecodeError:
    print(f"[ERROR] ❌ Could not decode JSON from {CONFIG_PATH}. Check for syntax errors.")
    exit(1)

# --- Constants and Global State ---
CHANNEL_NAME = CONFIG.get("channel_name", "TV Channel")
TIMEZONE = pytz.timezone(CONFIG.get("timezone", "Asia/Kolkata"))
SCHEDULE = sorted(CONFIG.get("timeline", []), key=lambda x: datetime.strptime(x["start"], "%H:%M").time())
PLAYLISTS = CONFIG.get("playlists", {})
OUTPUT_DIR = "static"
OUTPUT_HLS_PLAYLIST = os.path.join(OUTPUT_DIR, "stream.m3u8")
PLAYLIST_FILE = "playlist.txt"
LOCK_FILE = "stream_manager.lock"
LOGO_PATH = "logo.png" # <--- Path to your logo file

# --- Global State Management ---
current_process = None
current_show_name = None
_duration_cache = {}

app = Flask(__name__)
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

# --- Core Streaming Logic ---

def get_video_duration(video_path):
    """Gets video duration using ffprobe and caches the result."""
    if video_path in _duration_cache:
        return _duration_cache[video_path]
    try:
        cmd = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", video_path
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        duration = float(result.stdout.strip())
        _duration_cache[video_path] = duration
        return duration
    except (subprocess.CalledProcessError, ValueError, FileNotFoundError):
        print(f"[WARN] ⚠️ Could not get duration for '{video_path}'. Skipping.")
        return 0

def get_playlist_total_duration(video_urls):
    """Calculates the total duration of a list of videos."""
    return sum(get_video_duration(url) for url in video_urls)

def get_current_show_and_start_time():
    """
    Determines the current show based on the schedule, correctly handling overnight shows.
    Returns the show details, its precise start time, and its duration.
    """
    now = datetime.now(TIMEZONE)
    for day_offset in [0, -1]:
        check_date = (now + timedelta(days=day_offset)).date()
        for i, entry in enumerate(SCHEDULE):
            naive_start = datetime.combine(check_date, datetime.strptime(entry["start"], "%H:%M").time())
            start_time = TIMEZONE.localize(naive_start)

            next_i = (i + 1) % len(SCHEDULE)
            next_show_start_str = SCHEDULE[next_i]["start"]
            naive_end = datetime.combine(check_date, datetime.strptime(next_show_start_str, "%H:%M").time())
            end_time = TIMEZONE.localize(naive_end)

            if end_time <= start_time:
                end_time += timedelta(days=1)

            if start_time <= now < end_time:
                show_name = entry["show"]
                show_info = PLAYLISTS.get(show_name, {})
                show_duration_seconds = (end_time - start_time).total_seconds()
                return show_name, show_info, start_time, show_duration_seconds

    print("[WARN] ⚠️ No current show found in schedule. Defaulting to the first show.")
    fallback_show = SCHEDULE[0]
    show_name = fallback_show["show"]
    return show_name, PLAYLISTS.get(show_name, {}), None, 3600

def stop_current_stream():
    """Stops the currently running FFmpeg process."""
    global current_process
    if current_process:
        print(f"[INFO] 🔄 Stopping current stream for '{current_show_name}'...")
        current_process.terminate()
        try:
            current_process.wait(timeout=10)
            print("[INFO] ✅ Stream stopped gracefully.")
        except subprocess.TimeoutExpired:
            print("[WARN] ⚠️ FFmpeg did not terminate gracefully, killing.")
            current_process.kill()
        current_process = None

def start_stream_for_show(show_name, show_info, show_start_time, show_duration_seconds):
    """
    Starts a new FFmpeg stream, calculating the correct starting point and adding a logo.
    """
    global current_process
    video_urls = show_info.get("videos", [])

    if not video_urls:
        print(f"[WARN] ⚠️ No videos found for show '{show_name}'. Waiting.")
        return

    playlist_total_duration = get_playlist_total_duration(video_urls)
    if playlist_total_duration == 0:
        print(f"[WARN] ⚠️ Playlist for '{show_name}' has zero duration. Cannot play.")
        return

    now = datetime.now(TIMEZONE)
    elapsed_since_show_start = (now - show_start_time).total_seconds()
    seek_time = elapsed_since_show_start % playlist_total_duration
    print(f"[INFO] 🎬 Starting new stream for '{show_name}'.")
    print(f"[INFO] 🕒 Playlist loops every {playlist_total_duration:.2f}s. Seeking to {seek_time:.2f}s.")

    with open(PLAYLIST_FILE, "w") as f:
        for url in video_urls:
            f.write(f"file '{url}'\n")

    # --- Build the FFmpeg Command ---
    ffmpeg_cmd = [
        "ffmpeg", "-re",
        "-ss", str(seek_time)
    ]

    # --- Video Filter and Input Setup ---
    logo_exists = os.path.exists(LOGO_PATH)
    if logo_exists:
        ffmpeg_cmd.extend(["-i", LOGO_PATH]) # Add logo as an input
        print("[INFO] 🏞️ Logo found. Applying overlay.")

    ffmpeg_cmd.extend([
        "-f", "concat", "-safe", "0",
        "-protocol_whitelist", "file,crypto,data,http,https,tls,tcp",
        "-i", PLAYLIST_FILE,
    ])

    # Build the complex video filter string
    video_filter = "scale=854:480" # Performance fix: scale to 480p
    if logo_exists:
        # Overlay the logo (input 1) on top of the scaled video (input 0)
        # Position: 10 pixels from top-right corner
        video_filter = "[1:v]scale=iw/8:-1[logo];[0:v]scale=854:480[bg];[bg][logo]overlay=W-w-10:10"

    ffmpeg_cmd.extend(["-filter_complex", video_filter])

    # --- Output and Encoding Options ---
    ffmpeg_cmd.extend([
        "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
        "-b:v", "800k", "-maxrate", "800k", "-bufsize", "1600k", # Bitrate for 480p
        "-g", "48",
        "-c:a", "aac", "-b:a", "128k",
        "-f", "hls",
        "-hls_time", "6",
        "-hls_list_size", "10",
        "-hls_flags", "delete_segments+program_date_time",
        "-hls_segment_filename", f"{OUTPUT_DIR}/stream%03d.ts",
        OUTPUT_HLS_PLAYLIST
    ])
    
    print(f"[INFO] ▶️ Running FFmpeg command: {' '.join(ffmpeg_cmd)}")
    current_process = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def manage_stream():
    """The main loop to manage starting and stopping streams with a lock."""
    global current_show_name
    
    try:
        lock_fd = open(LOCK_FILE, 'w')
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, BlockingIOError):
        print("[INFO] 🔒 Another stream manager is already running. This worker will not manage the stream.")
        return

    print("[INFO] 👑 This process has acquired the stream manager lock.")
    
    while True:
        try:
            new_show, show_info, start_time, duration = get_current_show_and_start_time()
            if new_show != current_show_name:
                stop_current_stream()
                time.sleep(1)
                start_stream_for_show(new_show, show_info, start_time, duration)
                current_show_name = new_show
        except Exception as e:
            print(f"[ERROR] ❌ Unhandled error in management loop: {e}")
        
        time.sleep(15)

# --- Flask Web Server Routes ---
# (Flask routes are unchanged and remain the same as the previous version)

@app.route("/")
def home():
    """Homepage to confirm the server is running."""
    return f"<h1>📺 {CHANNEL_NAME} is live!</h1><p>Access the stream at <a href='/stream/live.m3u8'>/stream/live.m3u8</a></p>"

@app.route("/stream/<path:filename>")
def stream(filename):
    """Serves the HLS playlist and video segments."""
    file_path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(file_path):
        abort(404, description="Resource not found. The stream may be starting up.")
    
    mimetype = 'application/vnd.apple.mpegurl' if filename.endswith('.m3u8') else 'video/MP2T'
    response = send_file(file_path, mimetype=mimetype)
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response

@app.route("/status")
def current_status():
    """Returns the current status of the channel as JSON."""
    show, info, start, duration = get_current_show_and_start_time()
    now = datetime.now(TIMEZONE)
    time_elapsed = (now - start).total_seconds() if start else 0
    
    return jsonify({
        "channel": CHANNEL_NAME,
        "current_show": show,
        "playlist": info.get("videos", []),
        "show_start_time": start.isoformat() if start else None,
        "show_duration_seconds": duration,
        "time_elapsed_seconds": time_elapsed,
        "is_ffmpeg_running": current_process is not None and current_process.poll() is None
    })


# --- Main Application Start ---
if __name__ == "__main__":
    manager_thread = threading.Thread(target=manage_stream, daemon=True)
    manager_thread.start()
    
    print("[INFO] 🚀 Starting Flask development server...")
    app.run(host="0.0.0.0", port=10000, threaded=True)
