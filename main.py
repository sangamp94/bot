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
import shlex

# --- Configuration ---
CONFIG_PATH = "video.json"
try:
    with open(CONFIG_PATH, "r") as f:
        CONFIG = json.load(f)
    print("[INFO] ✅ Configuration loaded successfully from video.json")
except FileNotFoundError:
    print(f"[ERROR] ❌ Configuration file not found at: {CONFIG_PATH}")
    exit(1)
except json.JSONDecodeError:
    print(f"[ERROR] ❌ Invalid JSON in {CONFIG_PATH}")
    exit(1)

CHANNEL_NAME = CONFIG.get("channel_name", "TV Channel")
try:
    TIMEZONE = pytz.timezone(CONFIG.get("timezone", "Asia/Kolkata"))
except pytz.UnknownTimeZoneError:
    print("[ERROR] ❌ Invalid timezone. Using Asia/Kolkata.")
    TIMEZONE = pytz.timezone("Asia/Kolkata")

SCHEDULE = CONFIG.get("timeline", [])
if not SCHEDULE:
    print("[ERROR] ❌ Schedule is empty.")
    exit(1)

for entry in SCHEDULE:
    if "start" not in entry or "show" not in entry:
        print(f"[ERROR] ❌ Invalid entry in schedule: {entry}")
        exit(1)

SCHEDULE = sorted(SCHEDULE, key=lambda x: datetime.strptime(x["start"], "%H:%M").time())
PLAYLISTS = CONFIG.get("playlists", {})
OUTPUT_DIR = "static"
OUTPUT_HLS_PLAYLIST = os.path.join(OUTPUT_DIR, "live.m3u8")
PLAYLIST_FILE = "playlist.txt"
LOCK_FILE = "stream_manager.lock"
LOGO_PATH = "logo.png"

current_process = None
current_show_name = None
_duration_cache = {}

app = Flask(__name__)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# --- Helpers ---
def get_video_duration(video_path):
    if video_path in _duration_cache:
        return _duration_cache[video_path]
    try:
        cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=noprint_wrappers=1:nokey=1", video_path]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        duration = float(result.stdout.strip())
        _duration_cache[video_path] = duration
        return duration
    except Exception:
        print(f"[WARN] ⚠️ Could not get duration for {video_path}")
        return 0

def get_playlist_total_duration(video_urls):
    return sum(get_video_duration(url) for url in video_urls)

def get_current_show_and_start_time():
    now = datetime.now(TIMEZONE)
    for day_offset in [0, -1]:
        check_date = (now + timedelta(days=day_offset)).date()
        for i, entry in enumerate(SCHEDULE):
            naive_start = datetime.combine(check_date, datetime.strptime(entry["start"], "%H:%M").time())
            start_time = TIMEZONE.localize(naive_start)

            next_i = (i + 1) % len(SCHEDULE)
            next_show_start = datetime.combine(check_date, datetime.strptime(SCHEDULE[next_i]["start"], "%H:%M").time())
            end_time = TIMEZONE.localize(next_show_start)

            if end_time <= start_time:
                end_time += timedelta(days=1)

            if start_time <= now < end_time:
                show_name = entry["show"]
                return show_name, PLAYLISTS.get(show_name, {}), start_time, (end_time - start_time).total_seconds()

    fallback = SCHEDULE[0]
    return fallback["show"], PLAYLISTS.get(fallback["show"], {}), None, 3600

def stop_current_stream():
    global current_process
    if current_process:
        print(f"[INFO] 🔄 Stopping stream for '{current_show_name}'")
        current_process.terminate()
        try:
            current_process.wait(timeout=10)
            print("[INFO] ✅ Stopped cleanly.")
        except subprocess.TimeoutExpired:
            current_process.kill()
        current_process = None

def start_stream_for_show(show_name, show_info, show_start_time, show_duration_seconds):
    global current_process

    video_urls = show_info.get("videos", [])
    if not video_urls:
        print(f"[WARN] ⚠️ No videos for '{show_name}'")
        return

    duration = get_playlist_total_duration(video_urls)
    if duration == 0:
        print(f"[WARN] ⚠️ Playlist for '{show_name}' has zero duration.")
        return

    now = datetime.now(TIMEZONE)
    seek_time = (now - show_start_time).total_seconds() % duration if show_start_time else 0
    print(f"[INFO] 🎬 Starting stream: {show_name} @ {seek_time:.2f}s")

    # Clean stale HLS files
    for f in os.listdir(OUTPUT_DIR):
        if f.endswith(".ts") or f.endswith(".m3u8"):
            try:
                os.remove(os.path.join(OUTPUT_DIR, f))
            except Exception:
                pass

    with open(PLAYLIST_FILE, "w") as f:
        for url in video_urls:
            f.write(f"file {shlex.quote(url)}\n")

    logo_exists = os.path.exists(LOGO_PATH)
    cmd = [
        "ffmpeg", "-re",
        "-f", "concat", "-safe", "0",
        "-protocol_whitelist", "file,crypto,data,http,https,tls,tcp",
        "-i", PLAYLIST_FILE,
        "-ss", str(seek_time)
    ]

    if logo_exists:
        cmd.extend(["-i", LOGO_PATH])
        print("[INFO] 🖼️ Logo overlay enabled")

    video_filter = "scale=854:480"
    if logo_exists:
        video_filter = "[1:v]scale=iw/8:-1[logo];[0:v]scale=854:480[bg];[bg][logo]overlay=W-w-10:10"

    cmd.extend([
        "-filter_complex", video_filter,
        "-af", "aresample=async=1",
        "-map", "0:v", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
        "-b:v", "800k", "-maxrate", "800k", "-bufsize", "1600k",
        "-g", "48",
        "-c:a", "aac", "-b:a", "128k",
        "-f", "hls",
        "-hls_time", "6",
        "-hls_list_size", "10",
        "-hls_flags", "delete_segments+program_date_time",
        "-hls_segment_filename", f"{OUTPUT_DIR}/live%03d.ts",
        OUTPUT_HLS_PLAYLIST
    ])

    print(f"[INFO] ▶️ FFmpeg started for {show_name}")
    current_process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def manage_stream():
    global current_show_name
    try:
        lock_fd = open(LOCK_FILE, 'w')
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except Exception:
        print("[INFO] 🔒 Another instance is managing the stream.")
        return

    print("[INFO] 👑 Stream manager started.")
    while True:
        try:
            show, info, start, duration = get_current_show_and_start_time()
            if show != current_show_name:
                stop_current_stream()
                time.sleep(1)
                start_stream_for_show(show, info, start, duration)
                current_show_name = show
        except Exception as e:
            print(f"[ERROR] ❌ Stream manager crashed: {e}")
        time.sleep(15)

# --- Routes ---
@app.route("/")
def home():
    return f"<h1>📺 {CHANNEL_NAME} is live!</h1><p>Access it at <a href='/stream/live.m3u8'>/stream/live.m3u8</a></p>"

@app.route("/stream/<path:filename>")
def stream(filename):
    path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(path):
        abort(404, "Stream not ready.")
    mime = 'application/vnd.apple.mpegurl' if filename.endswith('.m3u8') else 'video/MP2T'
    resp = send_file(path, mimetype=mime)
    resp.headers['Access-Control-Allow-Origin'] = '*'
    return resp

@app.route("/status")
def status():
    show, info, start, duration = get_current_show_and_start_time()
    now = datetime.now(TIMEZONE)
    return jsonify({
        "channel": CHANNEL_NAME,
        "current_show": show,
        "playlist": info.get("videos", []),
        "show_start_time": start.isoformat() if start else None,
        "show_duration_seconds": duration,
        "time_elapsed_seconds": (now - start).total_seconds() if start else 0,
        "is_ffmpeg_running": current_process is not None and current_process.poll() is None
    })

# --- Start ---
if __name__ == "__main__":
    threading.Thread(target=manage_stream, daemon=True).start()
    print("[INFO] 🚀 Flask server starting on port 10000...")
    app.run(host="0.0.0.0", port=10000, threaded=True)
