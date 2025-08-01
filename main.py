from flask 
import Flask, send_from_directory, render_template_string
import subprocess
import os

app = Flask(__name__)
OUTPUT_DIR = "output_hls"

# Your stream info (⚠️ Make sure it's a valid .mpd)
MPD_URL = "https://deadpooll.fun/JIOSSTAR78/1373.mpd"
KEY = "3dca7917d8cf9bb7095dc72b48bdcd3c"

@app.before_first_request
def convert_dash_to_hls():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    hls_playlist = os.path.join(OUTPUT_DIR, "output.m3u8")
    hls_segment_path = os.path.join(OUTPUT_DIR, "segment_%03d.ts")

    if os.path.exists(hls_playlist):
        print("✅ HLS already exists.")
        return

    print("🔄 Converting DASH to HLS using FFmpeg...")

    command = [
        "ffmpeg", "-allowed_extensions", "ALL",
        "-protocol_whitelist", "file,http,https,tcp,tls,crypto",
        "-decryption_key", KEY,
        "-i", MPD_URL,
        "-c", "copy", "-f", "hls",
        "-hls_time", "6",
        "-hls_playlist_type", "vod",
        "-hls_segment_filename", hls_segment_path,
        hls_playlist
    ]

    try:
        subprocess.run(command, check=True)
        print("✅ FFmpeg completed successfully.")
    except subprocess.CalledProcessError as e:
        print("❌ FFmpeg failed:")
        print(e)

@app.route("/")
def index():
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Disney Channel HLS</title>
        <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
    </head>
    <body>
        <h2>📺 Disney Channel (via ClearKey HLS)</h2>
        <video id="video" width="640" controls autoplay></video>
        <script>
        if (Hls.isSupported()) {
            var video = document.getElementById('video');
            var hls = new Hls();
            hls.loadSource('/stream/output.m3u8');
            hls.attachMedia(video);
            hls.on(Hls.Events.MANIFEST_PARSED,function() {
                video.play();
            });
        } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
            video.src = '/stream/output.m3u8';
        }
        </script>
    </body>
    </html>
    """)

@app.route("/stream/<path:filename>")
def serve_hls(filename):
    return send_from_directory(OUTPUT_DIR, filename)

if __name__ == "__main__":
    app.run(debug=True, port=5000)
