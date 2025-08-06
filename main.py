import os
import json
import time
import fcntl
import shlex
import pytz
import threading
import subprocess
from datetime import datetime, timedelta
from flask import Flask, send_file, jsonify, abort

CONFIG_PATH = "video.json"
OUTPUT_DIR = "static"
OUTPUT_HLS_PLAYLIST = os.path.join(OUTPUT_DIR, "live.m3u8")
LOCK_FILE = "stream_manager.lock"
LOGO_PATH = "logo.png"

# --- Load Config ---
try:
    with open(CONFIG_PATH, "r") as f:
        CONFIG = json.load(f)
except Exception as e:
    print(f"[ERROR] ❌ Cannot load config: {e}")
    exit(1)

CHANNEL_NAME = CONFIG.get("channel_name", "TV Channel")
TIMEZONE = pytz.timezone(CONFIG.get("timezone", "Asia/Kolkata"))
SCHEDULE = sorted(CONFIG.get("timeline", []), key=lambda x: datetime.strptime(x["start"], "%H:%M").time())
PLAYLISTS = CONFIG.get("playlists", {})

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

app = Flask(__name__)
current_process = None
current_show_name = None

def get_current_show_and_start_time():
    now = datetime.now(TIMEZONE)
    for day_offset in [0, -1]:
        check_date = (now + timedelta(days=day_offset)).date()
        for i, entry in enumerate(SCHEDULE):
            start = datetime.combine(check_date, datetime.strptime(entry["start"], "%H:%M").time())
            start_time = TIMEZONE.localize(start)
            next_i = (i + 1) % len(SCHEDULE)
            end = datetime.combine(check_date, datetime.strptime(SCHEDULE[next_i]["start"], "%H:%M").time())
            end_time = TIMEZONE.localize(end)
            if end_time <= start_time:
                end_time += timedelta(days=1)
            if start_time <= now < end_time:
                duration = (end_time - start_time).total_seconds()
                return entry["show"], PLAYLISTS.get(entry["show"], {}), start_time, duration
    fallback = SCHEDULE[0]
    return fallback["show"], PLAYLISTS.get(fallback["show"], {}), now, 3600

def stop_current_stream():
    global current_process
    if current_process:
        current_process.terminate()
        try:
            current_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            current_process.kill()
        current_process = None

def start_stream_for_show(show_name, show_info, show_start_time, show_duration_seconds):
    global current_process
    video_urls = show_info.get("videos", [])
    if not video_urls:
        print(f"[WARN] ⚠️ No videos for {show_name}")
        return

    now = datetime.now(TIMEZONE)
    seek_time = (now - show_start_time).total_seconds()

    # Loop playlist if needed
    total_duration = len(video_urls) * 3600  # rough estimate
    url_index = int(seek_time // 3600) % len(video_urls)
    seek_offset = int(seek_time % 3600)

    video_url = video_urls[url_index]
    print(f"[INFO] 🎬 Streaming {video_url} at {seek_offset}s")

    ffmpeg_cmd = [
        "ffmpeg", "-re", "-ss", str(seek_offset),
        "-i", video_url
    ]

    logo_exists = os.path.exists(LOGO_PATH)
    if logo_exists:
        ffmpeg_cmd += ["-i", LOGO_PATH]
        filter_complex = "[1:v]scale=iw/8:-1[logo];[0:v]scale=854:480[bg];[bg][logo]overlay=W-w-10:10"
    else:
        filter_complex = "scale=854:480"

    ffmpeg_cmd += [
        "-filter_complex", filter_complex,
        "-map", "0:v", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
        "-b:v", "800k", "-maxrate", "800k", "-bufsize", "1600k",
        "-g", "48", "-c:a", "aac", "-b:a", "128k",
        "-f", "hls",
        "-hls_time", "6",
        "-hls_list_size", "10",
        "-hls_flags", "delete_segments+program_date_time",
        "-hls_segment_filename", os.path.join(OUTPUT_DIR, "stream%03d.ts"),
        OUTPUT_HLS_PLAYLIST
    ]

    print(f"[INFO] ▶️ FFmpeg: {' '.join(ffmpeg_cmd)}")
    current_process = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def manage_stream():
    global current_show_name
    try:
        lock_fd = open(LOCK_FILE, 'w')
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except:
        print("[INFO] 🔒 Another stream manager is active.")
        return

    while True:
        try:
            show, info, start, duration = get_current_show_and_start_time()
            if show != current_show_name:
                stop_current_stream()
                time.sleep(1)
                start_stream_for_show(show, info, start, duration)
                current_show_name = show
        except Exception as e:
            print(f"[ERROR] ❌ {e}")
        time.sleep(10)

@app.route("/")
def home():
    return f"<h1>📺 {CHANNEL_NAME}</h1><p>Watch: <a href='/stream/live.m3u8'>/stream/live.m3u8</a></p>"

@app.route("/stream/<path:filename>")
def stream(filename):
    path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(path):
        abort(404, "HLS stream not ready.")
    mimetype = 'application/vnd.apple.mpegurl' if filename.endswith('.m3u8') else 'video/MP2T'
    resp = send_file(path, mimetype=mimetype)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp

@app.route("/status")
def status():
    show, info, start, duration = get_current_show_and_start_time()
    now = datetime.now(TIMEZONE)
    return jsonify({
        "channel": CHANNEL_NAME,
        "current_show": show,
        "videos": info.get("videos", []),
        "show_start": start.isoformat() if start else None,
        "duration": duration,
        "elapsed": (now - start).total_seconds() if start else 0,
        "ffmpeg_running": current_process and current_process.poll() is None
    })

if __name__ == "__main__":
    threading.Thread(target=manage_stream, daemon=True).start()
    app.run(host="0.0.0.0", port=10000, threaded=True)
