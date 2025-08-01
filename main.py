import os
import subprocess
import shutil

# === CONFIGURATION ===
MPD_URL = "https://deadpooll.fun/JIOSSTAR78/1373.mpd"
KEY_ID = "5181d3e6698055578cedc5bfc86b3e56"
KEY = "3dca7917d8cf9bb7095dc72b48bdcd3c"
OUTPUT_DIR = "output_hls"
HLS_PLAYLIST = "output.m3u8"
SEGMENT_NAME = "segment_%03d.ts"

# === Check ffmpeg is installed ===
if not shutil.which("ffmpeg"):
    raise SystemExit("❌ ffmpeg not found. Please install it and add to PATH.")

# === Create output directory ===
os.makedirs(OUTPUT_DIR, exist_ok=True)

# === Build ffmpeg command ===
ffmpeg_command = [
    "ffmpeg",
    "-allowed_extensions", "ALL",
    "-protocol_whitelist", "file,http,https,tcp,tls,crypto",
    "-decryption_key", KEY,
    "-i", MPD_URL,
    "-c", "copy",
    "-f", "hls",
    "-hls_time", "6",
    "-hls_playlist_type", "vod",
    "-hls_segment_filename", os.path.join(OUTPUT_DIR, SEGMENT_NAME),
    os.path.join(OUTPUT_DIR, HLS_PLAYLIST)
]

# === Run ffmpeg ===
print("🔄 Converting DASH to HLS...")
process = subprocess.run(ffmpeg_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

# === Output handling ===
if process.returncode == 0:
    print(f"✅ Done! HLS stream saved in ./{OUTPUT_DIR}/{HLS_PLAYLIST}")
    print("▶️ You can open it in VLC or HLS-compatible players.")
else:
    print("❌ FFmpeg failed. Output:")
    print(process.stderr)
