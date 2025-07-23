import subprocess, time, os, requests, json, urllib.request
from threading import Thread
from flask import Flask, send_from_directory, render_template_string, jsonify
from datetime import datetime
import pytz
import shutil # Import shutil for file copying

app = Flask(__name__)
HLS_DIR = "/tmp/hls"
TIMEZONE = pytz.timezone("Asia/Kolkata")

BIN_ID = "6880d04f7b4b8670d8a5ed02"
API_KEY = "$2a$10$PIOW5cERiCAJX3idNpMDXO93/stUEHE5OLlqgNbRZhUx12PHeVWiO" # Using the provided API key

os.makedirs(HLS_DIR, exist_ok=True)

def fetch_playlists_local():
    """Fetches the show playlists from a local video.json file."""
    try:
        with open("video.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        print("[ERROR] video.json not found. Please create it.")
        return {}
    except json.JSONDecodeError as e:
        print(f"[ERROR] Invalid JSON in video.json: {e}")
        return {}
    except Exception as e:
        print(f"[ERROR] Failed to load video.json: {e}")
        return {}

def fetch_progress_from_jsonbin():
    """
    Fetches the current playback progress from JSONBin.io.
    Handles potential nested 'record' keys if the bin was previously mis-saved.
    """
    try:
        res = requests.get(f"https://api.jsonbin.io/v3/b/{BIN_ID}/latest", headers={"X-Master-Key": API_KEY})
        res.raise_for_status() # Raise an HTTPError for bad responses (4xx or 5xx)
        full_response_payload = res.json()
        
        # JSONBin.io wraps the actual content in a 'record' key.
        # Ensure we extract the correct level, and handle potential accidental nesting.
        actual_record_data = full_response_payload.get('record', {})

        # If, due to previous errors, 'record' itself contains another 'record' key, unnest it.
        if 'record' in actual_record_data and isinstance(actual_record_data['record'], dict):
            print("[INFO] Found nested 'record' in JSONBin data. Unnesting it for proper parsing.")
            return actual_record_data['record']
        
        return actual_record_data # This is the expected structure after initial cleanup
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] JSONBin load request failed: {e}")
        return {}
    except json.JSONDecodeError:
        print("[ERROR] JSONBin response is not valid JSON.")
        return {}
    except KeyError:
        print("[ERROR] JSONBin response missing expected 'record' key. The bin might be empty or malformed.")
        return {}
    except Exception as e:
        print(f"[ERROR] JSONBin load unexpected error: {e}")
        return {}

def save_progress_to_jsonbin(data):
    """Saves the current playback progress to JSONBin.io."""
    try:
        res = requests.put(f"https://api.jsonbin.io/v3/b/{BIN_ID}", json=data, headers={
            "Content-Type": "application/json",
            "X-Master-Key": API_KEY
        })
        res.raise_for_status() # Raise an HTTPError for bad responses (4xx or 5xx)
        if res.status_code == 200:
            print(f"[DEBUG] Successfully saved progress to JSONBin: {data}") # Added data to log
            return True
        else:
            print(f"[ERROR] JSONBin save failed with status {res.status_code}: {res.text}")
            return False
    except requests.exceptions.HTTPError as e: # Catch HTTPError specifically
        if e.response.status_code == 401:
            print(f"[CRITICAL ERROR] JSONBin save failed with 401 Unauthorized. Please check your API_KEY and ensure it is a Master Key with write permissions for bin {BIN_ID}.")
        else:
            print(f"[ERROR] JSONBin save request failed: {e}")
        return False
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] JSONBin save request failed: {e}")
        return False
    except Exception as e:
        print(f"[ERROR] JSONBin save unexpected error: {e}")
        return False

def download_logo_if_needed(url, local_path_in_hls_dir):
    """Downloads a logo from a URL to a specified path in HLS_DIR and validates its format.
    Returns True if a valid image is downloaded, False otherwise."""
    if not url:
        return False # No URL provided to download from

    temp_path = local_path_in_hls_dir + ".tmp"
    try:
        # Download the content first to a temporary file
        urllib.request.urlretrieve(url, temp_path)
        
        # Read a small part of the file to check its signature
        with open(temp_path, 'rb') as f:
            header = f.read(8) # Read enough bytes for common image signatures

        is_png = header.startswith(b'\x89PNG\r\n\x1a\n')
        is_jpeg = header.startswith(b'\xFF\xD8\xFF')
        
        is_svg = False
        try:
            # Check for SVG by reading a small portion as text
            with open(temp_path, 'r', encoding='utf-8') as f:
                content_start = f.read(100).strip().lower()
                if content_start.startswith('<svg'):
                    is_svg = True
        except UnicodeDecodeError:
            pass # Not a text file, so not SVG

        if is_png or is_jpeg:
            os.rename(temp_path, local_path_in_hls_dir)
            print(f"[✅] Downloaded valid image: {local_path_in_hls_dir}")
            return True
        elif is_svg:
            print(f"[WARNING] Downloaded SVG file from {url}. FFmpeg cannot directly overlay SVG without librsvg support. Please provide a PNG or JPG URL instead. Skipping logo: {local_path_in_hls_dir}")
            os.remove(temp_path)
            return False
        else:
            print(f"[ERROR] Downloaded file from {url} is not a recognized image format (PNG/JPEG/SVG). Skipping logo: {local_path_in_hls_dir} (Header: {header.hex()})")
            os.remove(temp_path)
            return False

    except Exception as e:
        print(f"[ERROR] Downloading or validating logo failed for {url}: {e}")
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return False

def validate_image_file(file_path):
    """Checks if a local file is a valid PNG or JPEG."""
    if not os.path.exists(file_path):
        return False
    try:
        with open(file_path, 'rb') as f:
            header = f.read(8)
        is_png = header.startswith(b'\x89PNG\r\n\x1a\n')
        is_jpeg = header.startswith(b'\xFF\xD8\xFF')
        
        if is_png or is_jpeg:
            return True
        else:
            # Check for SVG signature if it's not PNG/JPEG
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content_start = f.read(100).strip().lower()
                    if content_start.startswith('<svg'):
                        print(f"[WARNING] Local file {file_path} is an SVG. FFmpeg cannot directly overlay SVG. Please convert to PNG/JPG.")
                        return False
            except UnicodeDecodeError:
                pass # Not a text file, so not SVG

            print(f"[WARNING] Local file {file_path} is not a valid PNG or JPEG. Signature: {header.hex()}")
            return False
    except Exception as e:
        print(f"[ERROR] Error validating local image file {file_path}: {e}")
        return False

def get_video_duration(url):
    """Gets the duration of a video from its URL using ffprobe."""
    try:
        # Add a timeout to ffprobe command
        result = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", url
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True, timeout=10) # 10 second timeout
        duration = float(result.stdout.strip())
        if duration <= 0:
            print(f"[WARNING] FFprobe returned non-positive duration ({duration}s) for {url}.")
            return 0
        return duration
    except subprocess.TimeoutExpired:
        print(f"[ERROR] FFprobe timed out for {url}.")
        return 0
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] FFprobe failed for {url}: {e.stderr.strip()}")
        return 0
    except ValueError:
        print(f"[ERROR] FFprobe returned non-numeric duration for {url}: {result.stdout.strip()}.")
        return 0
    except Exception as e:
        print(f"[ERROR] FFprobe unexpected error for {url}: {e}")
        return 0

def get_video_dimensions(url):
    """Gets the width and height of a video from its URL using ffprobe."""
    try:
        result = subprocess.run([
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "default=noprint_wrappers=1:nokey=1", url
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True, timeout=10)
        lines = result.stdout.strip().split('\n')
        if len(lines) >= 2:
            width = int(lines[0])
            height = int(lines[1])
            return width, height
        print(f"[WARNING] FFprobe could not determine dimensions for {url}: {result.stderr.strip()}")
        return 0, 0
    except subprocess.TimeoutExpired:
        print(f"[ERROR] FFprobe dimensions timed out for {url}.")
        return 0, 0
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] FFprobe dimensions failed for {url}: {e.stderr.strip()}")
        return 0, 0
    except Exception as e:
        print(f"[ERROR] FFprobe dimensions unexpected error for {url}: {e}")
        return 0, 0

def get_current_show():
    """Determines the current show based on the scheduled time."""
    now = datetime.now(TIMEZONE)
    current_minutes = now.hour * 60 + now.minute
    playlists = fetch_playlists_local()
    show_times = []

    for show_name, show_data in playlists.items():
        time_str = show_data.get("time")
        if time_str:
            try:
                hour, minute = map(int, time_str.split(":"))
                show_times.append((hour * 60 + minute, show_name))
            except ValueError:
                print(f"[ERROR] Invalid time format for show '{show_name}': {time_str}. Skipping.")

    if not show_times:
        print("[INFO] No valid show times found in video.json.")
        return None, 0, 0

    # Sort by time
    sorted_times = sorted(show_times)

    # Add a sentinel for the end of the day to simplify time range calculation
    # Using 23:59 to ensure the last actual show slot is correctly captured before midnight.
    sorted_times.append((23 * 60 + 59, "__end_of_day__")) # Adjusted to 23:59 for robustness

    for i in range(len(sorted_times) - 1):
        start_minutes, show_name = sorted_times[i]
        end_minutes, _ = sorted_times[i + 1]

        if start_minutes <= current_minutes < end_minutes:
            # Return show name, elapsed time in current slot (seconds), remaining time in current slot (seconds)
            return show_name, (current_minutes - start_minutes) * 60, (end_minutes - current_minutes) * 60

    # Handle cases where current_minutes is past the last scheduled show (e.g., after 23:59)
    # In such a case, it rolls over to the first show of the next day, but for the current day's logic,
    # it means no show is active *within the defined time slots*.
    # You might want to define a "default" show or simply wait.
    print("[INFO] Current time is outside all defined show slots. Waiting for next show.")
    return None, 0, 0


def start_ffmpeg_stream():
    """Main function to manage and start the FFmpeg streaming process."""
    while True:
        print("\n--- Starting new FFmpeg stream iteration ---")
        # Get current show and its time slot details
        show_name, show_slot_elapsed_seconds, show_slot_remaining_seconds = get_current_show()
        print(f"[DEBUG] Current show: {show_name}, Slot Elapsed: {show_slot_elapsed_seconds:.1f}s, Slot Remaining: {show_slot_remaining_seconds:.1f}s")
        
        if not show_name:
            print("[INFO] No scheduled show at this moment. Waiting 30 seconds...")
            time.sleep(30)
            continue

        playlists = fetch_playlists_local()
        show_data = playlists.get(show_name, {})
        playlist_items = show_data.get("episodes", []) # Renamed to avoid conflict with `playlist` variable
        show_logo_url = show_data.get("logo")

        if not playlist_items:
            print(f"[ERROR] No episodes defined for show: {show_name}. Waiting 10 seconds...")
            time.sleep(10)
            continue

        # Define paths for logos within the HLS_DIR
        show_logo_filename = f"{show_name}_logo.png" # Added _logo to avoid potential conflicts
        channel_logo_filename = "channel_logo.png" # Standard internal name for channel logo

        final_show_logo_path = os.path.join(HLS_DIR, show_logo_filename)
        final_channel_logo_path = os.path.join(HLS_DIR, channel_logo_filename)

        # --- Logic for Channel Logo (prioritizing user's logo.png) ---
        user_provided_logo_root_path = "logo.png" # Path to the user's logo.png in the root
        channel_logo_downloaded = False

        if os.path.exists(user_provided_logo_root_path) and validate_image_file(user_provided_logo_root_path):
            try:
                # If user provided a valid logo.png, copy it to the HLS_DIR
                shutil.copy(user_provided_logo_root_path, final_channel_logo_path)
                channel_logo_downloaded = True
                print(f"[INFO] Using user-provided channel logo: {user_provided_logo_root_path}")
            except Exception as e:
                print(f"[ERROR] Could not copy user-provided logo.png: {e}. Falling back to placeholder.")
                channel_logo_downloaded = False
        
        if not channel_logo_downloaded: # If user's logo.png wasn't used or was invalid/missing
            # Download the reliable PNG placeholder
            channel_logo_downloaded = download_logo_if_needed("https://via.placeholder.com/200x100.png?text=Channel+Logo", final_channel_logo_path)
            if channel_logo_downloaded:
                print(f"[INFO] Downloaded placeholder channel logo to {final_channel_logo_path}")
            else:
                print(f"[WARNING] Failed to download placeholder channel logo. Channel logo will not be shown.")

        # --- Logic for Show Logo ---
        show_logo_downloaded = download_logo_if_needed(show_logo_url, final_show_logo_path)
        if not show_logo_downloaded:
            print(f"[WARNING] Show logo for {show_name} will not be shown.")


        # Fetch current progress for the show
        print("[DEBUG] Fetching progress from JSONBin.io...")
        progress = fetch_progress_from_jsonbin()
        print(f"[DEBUG] Raw progress fetched: {progress}")

        # Log the current state of progress for the specific show BEFORE any potential modification
        current_show_progress_before_update = progress.get(show_name, {"current_episode_index": 0, "current_episode_playback_position_seconds": 0})
        print(f"[DEBUG] Current show progress (before update logic): {current_show_progress_before_update}")

        show_progress = progress.get(show_name)
        if not isinstance(show_progress, dict):
            show_progress = {"current_episode_index": 0, "current_episode_playback_position_seconds": 0}
            print(f"[INFO] No valid progress found for {show_name}. Initializing to default: {show_progress}")
            # Ensure the progress dict is updated with the default if it was missing
            progress[show_name] = show_progress 
            save_progress_to_jsonbin(progress) # Save the initialized state
            time.sleep(1) # Small delay to ensure save before next loop iteration
            continue

        current_episode_index = show_progress.get("current_episode_index", 0)
        current_episode_playback_position_seconds = show_progress.get("current_episode_playback_position_seconds", 0)
        print(f"[DEBUG] Loaded progress for {show_name}: Episode Index={current_episode_index}, Playback Position={current_episode_playback_position_seconds:.1f}s")
        
        # Ensure index is within bounds of the current playlist
        if current_episode_index >= len(playlist_items):
            current_episode_index = 0
            current_episode_playback_position_seconds = 0
            print(f"[INFO] Episode index out of bounds for {show_name}. Resetting to first episode.")
            # Important: Update the progress dict immediately
            progress[show_name] = {
                "current_episode_index": current_episode_index,
                "current_episode_playback_position_seconds": current_episode_playback_position_seconds
            }
            save_progress_to_jsonbin(progress) # Save the reset state
            time.sleep(1) # Small delay to ensure save before next loop iteration
            continue

        # --- Handle Live vs. File based on `type` in video.json ---
        current_episode_info = playlist_items[current_episode_index]
        video_url = current_episode_info.get("url")
        video_type = current_episode_info.get("type", "file") # Default to 'file' if not specified

        print(f"[DEBUG] Current video URL: {video_url} (Type: {video_type})")

        video_duration = 0
        is_live_stream = False

        if video_type == "live":
            is_live_stream = True
            video_duration = float('inf') # Treat live stream as having infinite duration for calculation purposes
            current_episode_playback_position_seconds = 0 # Live streams don't "resume" from a point
            print(f"[INFO] Detected live stream: {video_url}. Duration treated as infinite.")
        else: # Default to 'file'
            video_duration = get_video_duration(video_url)
            print(f"[DEBUG] Video duration for {video_url}: {video_duration:.1f}s")

        if video_duration == 0 and not is_live_stream: # Only skip if it's a file and duration is 0
            print(f"[ERROR] Could not get duration for video: {video_url}. Skipping episode.")
            current_episode_index += 1
            current_episode_playback_position_seconds = 0
            # Update progress to skip this problematic episode
            progress[show_name] = {
                "current_episode_index": current_episode_index,
                "current_episode_playback_position_seconds": current_episode_playback_position_seconds
            }
            save_progress_to_jsonbin(progress)
            time.sleep(5) # Wait a bit before trying next
            continue
            
        effective_video_remaining_seconds = video_duration - current_episode_playback_position_seconds
        # If it's a live stream, effective_video_remaining_seconds will be inf
        print(f"[DEBUG] Effective video remaining: {effective_video_remaining_seconds:.1f}s (Total: {video_duration:.1f}s, Started at: {current_episode_playback_position_seconds:.1f}s)")

        # For live streams, actual_duration_to_play will be capped by show_slot_remaining_seconds
        actual_duration_to_play = min(show_slot_remaining_seconds, effective_video_remaining_seconds)
        print(f"[DEBUG] Actual duration to play: {actual_duration_to_play:.1f}s (Min of slot remaining {show_slot_remaining_seconds:.1f}s and video remaining {effective_video_remaining_seconds:.1f}s)")

        if actual_duration_to_play < 10: # Minimum play duration
            print(f"[SKIP] Not enough time left ({actual_duration_to_play:.1f}s) in show slot to play meaningful segment for {show_name}. Waiting...")
            # If current slot is almost over, wait until next slot. Else wait a bit.
            wait_time = show_slot_remaining_seconds + 5 if show_slot_remaining_seconds > 0 else 10
            time.sleep(max(wait_time, 1)) # Ensure at least 1 second wait
            continue

        print(f"[PLAY] {video_url} (Episode {current_episode_index}, Start: {current_episode_playback_position_seconds:.1f}s, Play For: {actual_duration_to_play:.1f}s)")

        OUTPUT_WIDTH = 854 # Reverted to higher resolution
        OUTPUT_HEIGHT = 480 # Reverted to higher resolution
        
        current_video_stream_name = "[0:v]"
        filter_parts = []

        # Aspect Ratio Conversion: Force video to 854x480 (16:9), stretching if necessary
        filter_parts.append(f"{current_video_stream_name}scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}[ar_corrected_video]")
        current_video_stream_name = "[ar_corrected_video]"
        print(f"[INFO] Applying aspect ratio conversion to {OUTPUT_WIDTH}x{OUTPUT_HEIGHT} (16:9). 4:3 videos will be stretched.")

        logo_input_index = 1 # Index for additional input streams (logos)
        
        # FFmpeg -ss needs to be 0 for live streams, or the position for files
        ss_param = str(current_episode_playback_position_seconds) if not is_live_stream else "0"
        inputs = ["ffmpeg", "-y", "-re", "-ss", ss_param, "-i", video_url] # -y for overwrite output

        # Prepare logo inputs and filters
        logo_filters = []
        if show_logo_downloaded:
            inputs += ["-i", final_show_logo_path]
            # scale show logo to 180x100
            logo_filters.append(f"[{logo_input_index}:v]scale=180:100[showlogo]")
            # overlay show logo at top-left (10,10)
            filter_parts.append(f"{current_video_stream_name}[showlogo]overlay=10:10[temp_overlay_show]")
            current_video_stream_name = "[temp_overlay_show]"
            logo_input_index += 1
            print(f"[INFO] Show logo added from {final_show_logo_path}")
        
        if channel_logo_downloaded:
            inputs += ["-i", final_channel_logo_path]
            # scale channel logo to 200x100
            logo_filters.append(f"[{logo_input_index}:v]scale=200:100[channellogo]")
            # overlay channel logo at top-right (W-w-10,10)
            filter_parts.append(f"{current_video_stream_name}[channellogo]overlay=W-w-10:10[temp_overlay_channel]")
            current_video_stream_name = "[temp_overlay_channel]"
            logo_input_index += 1
            print(f"[INFO] Channel logo added from {final_channel_logo_path}")
        
        # Ensure the output stream is named '[out]' for the final map
        filter_parts.append(f"{current_video_stream_name}null[out]")
        current_video_stream_name = "[out]"

        filter_complex_str = ";".join(logo_filters + filter_parts)

        cmd = inputs + [
            "-t", str(actual_duration_to_play),
            "-filter_complex", filter_complex_str,
            "-map", current_video_stream_name,
            "-map", "0:a?", # Map audio if available
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", # Reverted CRF to 23 for higher quality
            "-c:a", "aac", "-b:a", "128k", # Reverted audio bitrate to 128k
            "-f", "hls", "-hls_time", "5", "-hls_list_size", "3",
            "-hls_flags", "delete_segments+omit_endlist",
            "-hls_playlist_type", "event", # Use event type for live-like streams
            os.path.join(HLS_DIR, "stream.m3u8")
        ]
        
        print(f"\n[FFMPEG CMD] {' '.join(cmd)}\n") # Log the full FFmpeg command for debugging

        process = None
        try:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            start_time = time.time()
            last_save_time = start_time # Track when we last saved
            
            # Wait for FFmpeg to likely complete its segment
            # Add a small buffer to actual_duration_to_play for FFmpeg to finish writing segments
            time_to_wait = actual_duration_to_play + 2 # 2 seconds buffer
            print(f"[DEBUG] Waiting for FFmpeg process for {time_to_wait:.1f} seconds...")
            
            while time.time() - start_time < time_to_wait and process.poll() is None:
                # Read stderr in real-time to prevent buffer overflow and see live logs
                line = process.stderr.readline()
                if line:
                    print(f"[FFmpeg STDERR] {line.decode().strip()}")
                
                current_elapsed_time = time.time() - start_time
                
                # Auto-save progress for files. For live streams, position tracking isn't meaningful for resumption.
                if not is_live_stream and current_elapsed_time - (last_save_time - start_time) >= 1.0: # Check if at least 1 second has passed since last save point
                    # Calculate current playback position based on elapsed time from start of segment
                    estimated_playback_position = current_episode_playback_position_seconds + current_elapsed_time
                    
                    # Ensure it doesn't exceed video duration
                    if estimated_playback_position > video_duration:
                        estimated_playback_position = video_duration

                    # Update progress object in memory
                    progress[show_name] = {
                        "current_episode_index": current_episode_index,
                        "current_episode_playback_position_seconds": estimated_playback_position
                    }
                    print(f"[DEBUG] Auto-saving progress at {estimated_playback_position:.1f}s...")
                    save_progress_to_jsonbin(progress)
                    last_save_time = time.time() # Update last save time
                
                time.sleep(0.1) # Small sleep to prevent busy-waiting

            # After waiting, check if the process is still running
            if process.poll() is None: # Still running, probably exceeded our expected duration
                print(f"[INFO] FFmpeg process still running after {time_to_wait:.1f}s. Terminating.")
                process.terminate()
                process.wait(timeout=5) # Give it some time to terminate
                if process.poll() is None:
                    print("[WARNING] FFmpeg process did not terminate gracefully. Killing.")
                    process.kill()
            
            stdout, stderr = process.communicate() # Collect any remaining output
            if stdout:
                print("[FFmpeg STDOUT]", stdout.decode().strip())
            if stderr: # Print remaining stderr if any
                print("[FFmpeg STDERR]", stderr.decode().strip())
            
            if process.returncode != 0:
                print(f"[ERROR] FFmpeg process exited with non-zero code {process.returncode}.")
                # This could indicate a problem with the video or command.
                # Consider backing off or skipping the episode.
            else:
                print("[✅] FFmpeg process completed successfully for this segment.")

            # Calculate new playback position based on what was *intended* to be played
            # This final calculation is important for precise transition to the next segment/episode
            # For live streams, the position is effectively reset to 0 for the next iteration of the same live stream.
            if is_live_stream:
                new_playback_position = 0
                # If a live stream is about to end its slot, we ensure the index moves on IF there are other live streams
                # or content in the same show slot. Otherwise, it just stays at 0.
                if actual_duration_to_play < show_slot_remaining_seconds: # Meaning the slot ended the stream
                    print(f"[INFO] Live stream slot ended. Resetting playback position for {show_name}.")
            else: # For file-based videos
                new_playback_position = current_episode_playback_position_seconds + actual_duration_to_play
                print(f"[DEBUG] Calculated final new playback position for segment: {new_playback_position:.1f}s (Video duration: {video_duration:.1f}s)")

                # Check if episode is considered finished
                # Using a small buffer (e.g., 2 seconds) for comparison due to float precision and FFmpeg internal timing
                if new_playback_position >= video_duration - 2: # Episode considered finished if within 2 seconds of end
                    current_episode_index += 1
                    new_playback_position = 0
                    if current_episode_index >= len(playlist_items):
                        current_episode_index = 0 # Wrap around if at end of playlist
                    print(f"[INFO] Episode completed. Moving to next episode {current_episode_index}.")
                else:
                    print(f"[INFO] Episode partially played. Resuming from {new_playback_position:.1f}s next time.")

            # Update and save progress (final save for the segment)
            progress[show_name] = {
                "current_episode_index": current_episode_index,
                "current_episode_playback_position_seconds": new_playback_position
            }
            print(f"[DEBUG] Progress object BEFORE final saving to JSONBin: {progress}")
            save_progress_to_jsonbin(progress)
            print(f"[💾] Saved final progress for {show_name}: index={current_episode_index}, playback_pos={new_playback_position:.1f}s")
            
            time.sleep(1) # Small delay before checking for next show segment

        except FileNotFoundError:
            print("[CRITICAL ERROR] FFmpeg command not found. Please ensure FFmpeg is installed and in your system's PATH.")
            time.sleep(60) # Wait longer if FFmpeg isn't found
            continue
        except Exception as e:
            print(f"[ERROR] FFmpeg process execution failed: {e}")
            if process:
                try:
                    process.terminate()
                    process.wait(timeout=5)
                except Exception as term_e:
                    print(f"[ERROR] Failed to terminate FFmpeg process: {term_e}")
            
        time.sleep(1) # Small delay before checking for next show segment

@app.route("/")
def index():
    """Renders the main HTML page with the video player."""
    return render_template_string("""
    <html>
    <head>
        <title>📺 Streamify Live</title>
        <style>
            body {
                background: black;
                color: white;
                text-align: center;
                font-family: 'Inter', sans-serif;
                margin: 0;
                padding: 20px;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                min-height: 100vh;
            }
            h1 {
                color: #00ffcc;
                margin-bottom: 20px;
                font-size: 2.5em;
                text-shadow: 0 0 10px rgba(0, 255, 204, 0.5);
            }
            video {
                width: 90%;
                max-width: 960px;
                height: auto;
                border-radius: 15px;
                box-shadow: 0 0 20px rgba(0, 255, 204, 0.7);
                background-color: #333;
            }
            #now-playing {
                margin-top: 20px;
                font-size: 1.2em;
                color: #fff;
                font-weight: bold;
            }
            #progress-bar-container {
                width: 90%;
                max-width: 960px;
                background-color: #333;
                border-radius: 5px;
                height: 10px;
                margin-top: 10px;
                overflow: hidden;
            }
            #progress-bar {
                height: 100%;
                width: 0%;
                background-color: #00ffcc;
                border-radius: 5px;
                transition: width 1s linear; /* Smooth transition for progress bar */
            }
            @media (max-width: 768px) {
                h1 {
                    font-size: 1.8em;
                }
                video {
                    width: 100%;
                    max-width: none;
                }
                #now-playing {
                    font-size: 1em;
                }
            }
        </style>
    </head>
    <body>
        <h1>📺 Streamify Live TV</h1>
        <video controls autoplay playsinline>
            <source src="/stream.m3u8" type="application/vnd.apple.mpegurl">
            Your browser does not support the video tag.
        </video>
        <p id="now-playing">Loading current show information...</p>
        <div id="progress-bar-container">
            <div id="progress-bar"></div>
        </div>
        <p style="margin-top: 10px; font-size: 0.9em; color: #aaa;">
            Live stream will start shortly. Please ensure your browser supports HLS.
        </p>

        <script>
            function fetchNowPlaying() {
                fetch('/progress')
                    .then(response => response.json())
                    .then(data => {
                        const nowPlayingElement = document.getElementById('now-playing');
                        const progressBar = document.getElementById('progress-bar');
                        let progressText = '';
                        let progressPercentage = 0;

                        if (data.current_show) {
                            progressText = `Now Playing: ${data.current_show}`;
                            if (data.current_episode_total_duration_seconds > 0) {
                                progressText += ` (Episode ${data.current_episode_index + 1} - ${formatTime(data.current_episode_playback_position_seconds)} / ${formatTime(data.current_episode_total_duration_seconds)})`;
                                progressPercentage = (data.current_episode_playback_position_seconds / data.current_episode_total_duration_seconds) * 100;
                            } else {
                                progressText += ` (Episode ${data.current_episode_index + 1})`;
                            }
                            // Update progress bar based on episode progress
                            progressBar.style.width = `${progressPercentage}%`;

                        } else {
                            progressText = 'No show currently scheduled.';
                            progressBar.style.width = '0%';
                        }
                        nowPlayingElement.innerText = progressText;
                    })
                    .catch(error => {
                        console.error('Error fetching now playing info:', error);
                        document.getElementById('now-playing').innerText = 'Could not fetch show information.';
                        document.getElementById('progress-bar').style.width = '0%';
                    });
            }

            function formatTime(seconds) {
                const minutes = Math.floor(seconds / 60);
                const remainingSeconds = Math.floor(seconds % 60);
                return `${minutes}:${remainingSeconds < 10 ? '0' : ''}${remainingSeconds}`;
            }

            // Fetch immediately and then every 5 seconds
            fetchNowPlaying();
            setInterval(fetchNowPlaying, 5000);

            // Optional: Reload video on network errors
            const videoElement = document.querySelector('video');
            videoElement.addEventListener('error', function() {
                console.error('Video playback error. Attempting to reload...');
                setTimeout(() => {
                    videoElement.load();
                    videoElement.play();
                }, 3000); // Wait 3 seconds before trying to reload
            });

        </script>
    </body>
    </html>
    """)

@app.route("/progress")
def get_progress():
    """Returns the current show and playback progress as JSON."""
    show_name, show_slot_elapsed_seconds, show_slot_remaining_seconds = get_current_show()
    progress_data = fetch_progress_from_jsonbin()
    
    show_progress = progress_data.get(show_name)
    if not isinstance(show_progress, dict):
        show_progress = {"current_episode_index": 0, "current_episode_playback_position_seconds": 0}

    current_episode_index = show_progress.get("current_episode_index", 0)
    current_episode_playback_position_seconds = show_progress.get("current_episode_playback_position_seconds", 0)

    # Fetch total duration of the current episode to provide more context
    playlists = fetch_playlists_local()
    current_episode_url = None
    current_episode_type = "file" # Default
    # Ensure current_episode_index is valid before attempting to access playlist
    if show_name and 0 <= current_episode_index < len(playlists.get(show_name, {}).get("episodes", [])):
        episode_info = playlists[show_name]["episodes"][current_episode_index]
        current_episode_url = episode_info.get("url")
        current_episode_type = episode_info.get("type", "file")
            
    current_episode_total_duration_seconds = 0
    if current_episode_url and current_episode_type == "file": # Only get duration for file types
        current_episode_total_duration_seconds = get_video_duration(current_episode_url)
    elif current_episode_type == "live":
        # For live streams, report the remaining slot time as "total duration" for UI purposes,
        # or a large number if you want the progress bar to just fill up.
        # Let's use remaining slot time as a proxy for the current "segment" total.
        current_episode_total_duration_seconds = show_slot_remaining_seconds


    return jsonify({
        "current_show": show_name,
        "show_slot_elapsed_seconds": show_slot_elapsed_seconds, # Time elapsed in the current show slot
        "show_slot_remaining_seconds": show_slot_remaining_seconds, # Time remaining in the current show slot
        "current_episode_index": current_episode_index,
        "current_episode_playback_position_seconds": current_episode_playback_position_seconds,
        "current_episode_total_duration_seconds": current_episode_total_duration_seconds
    })

@app.route("/<path:path>")
def serve_file(path):
    """Serves HLS segments and manifest files from the HLS_DIR."""
    return send_from_directory(HLS_DIR, path)

if __name__ == "__main__":
    # Start the FFmpeg streaming thread in the background
    Thread(target=start_ffmpeg_stream, daemon=True).start()
    # Run the Flask application
    app.run(host="0.0.0.0", port=10000)
