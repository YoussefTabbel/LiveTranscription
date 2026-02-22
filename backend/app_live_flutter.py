import os
import sys

# ==============================================================================
# WINDOWS CUDA DLL FIX (Must run BEFORE any other imports)
# ==============================================================================
if sys.platform == "win32":
    print("🛠️ Initializing CUDA DLL paths...", flush=True)
    # Search in all paths to be 100% sure
    site_packages_dirs = [p for p in sys.path if "site-packages" in p]
    if sys.prefix:
        site_packages_dirs.append(os.path.join(sys.prefix, "Lib", "site-packages"))

    found_any = False
    for sp in set(site_packages_dirs):
        if not os.path.exists(sp):
            continue
        
        nvidia_path = os.path.join(sp, "nvidia")
        if os.path.exists(nvidia_path):
            for root, dirs, files in os.walk(nvidia_path):
                if "bin" in dirs:
                    bin_path = os.path.abspath(os.path.join(root, "bin"))
                    print(f"📦 Adding DLL directory: {bin_path}", flush=True)
                    try:
                        os.add_dll_directory(bin_path)
                    except Exception as e:
                        print(f"⚠️ Error adding DLL dir {bin_path}: {e}", flush=True)
                    
                    # Also add to PATH just in case os.add_dll_directory isn't enough
                    os.environ["PATH"] = bin_path + os.pathsep + os.environ["PATH"]
                    
                    # Explicitly tell ctranslate2 where components might be
                    if "cublas" in root:
                        os.environ["CTRANSLATE2_CUDA_PATH"] = root
                    found_any = True
    
    if not found_any:
        print("⚠️ Warning: No NVIDIA library directories found in site-packages.", flush=True)
    sys.stdout.flush()

# Now it is safe to import everything else
import numpy as np
import threading
import subprocess
import time
from collections import deque
from flask import Flask, jsonify, request
from faster_whisper import WhisperModel
import yt_dlp

try:
    from flask_cors import CORS
except ImportError:
    CORS = None

app = Flask(__name__)
if CORS:
    CORS(app)

# ================= CONFIG RTX 3050 =================
MODEL_SIZE = "small"
SAMPLE_RATE = 16000
CHUNK_SECONDS = 3            # 3s chunks — best balance of latency vs VAD accuracy
OVERLAP_SECONDS = 0.5        # 0.5s overlap for context continuity
MAX_TRANSCRIPT_CHARS = 50000


print("🚀 Chargement modèle GPU RTX 3050...")
model = WhisperModel(
    MODEL_SIZE,
    device="cuda",
    compute_type="float16",
)


# ================= STATE =================
current_transcript = ""
transcript_lock = threading.Lock()
transcript_version = 0          # incremented on every new text append

is_stream_recording = False
stream_stop_event = threading.Event()
stream_url = ""
stream_status = "idle"         # idle | connecting | streaming | error
stream_error = ""
last_prompt = ""               # fed back to Whisper for cross-chunk coherence


# ───────────────────────────────────────────
#  TRANSCRIPTION LOOP
# ───────────────────────────────────────────
def transcribe_stream_audio():
    global current_transcript, is_stream_recording
    global stream_status, stream_error, last_prompt, transcript_version

    stream_status = "connecting"
    stream_error = ""
    last_prompt = ""

    print("🎬 Live:", stream_url)

    # ── yt-dlp: extract audio URL + HTTP headers ──
    # YouTube HLS URLs REQUIRE proper HTTP headers (User-Agent, cookies, etc.)
    # Without them, ffmpeg gets "Invalid data found when processing input"
    ydl_opts = {
        "format": "bestaudio/best",
        "quiet": True,
        "no_warnings": True,
    }

    audio_url = None
    http_headers = {}

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(stream_url, download=False)

        # Try top-level URL first
        audio_url = info.get("url")
        http_headers = info.get("http_headers", {})

        if not audio_url:
            formats = info.get("formats", [])
            # prefer audio-only, highest quality
            audio_only = [f for f in formats
                          if f.get("acodec") != "none"
                          and f.get("vcodec") in (None, "none")]
            candidates = audio_only if audio_only else [
                f for f in formats if f.get("acodec") != "none"
            ]
            if candidates:
                chosen = candidates[-1]
                audio_url = chosen["url"]
                http_headers = chosen.get("http_headers", http_headers)

        if not audio_url:
            print("❌ Aucun flux audio trouvé")
            stream_status = "error"
            stream_error = "No audio stream found"
            is_stream_recording = False
            return

    except Exception as e:
        print("❌ yt-dlp error:", e)
        stream_status = "error"
        stream_error = f"yt-dlp: {e}"
        is_stream_recording = False
        return

    print(f"✅ Flux audio URL extrait: {audio_url[:100]}...", flush=True)
    print(f"📦 Headers: {list(http_headers.keys())}", flush=True)

    # ── ffmpeg: decode to raw PCM ──
    # YouTube HLS URLs REQUIRE proper HTTP headers
    command = ["ffmpeg", "-hide_banner", "-loglevel", "warning"]
    
    # Add protocol whitelist for HLS stability
    command += ["-protocol_whitelist", "file,http,https,tcp,tls,crypto"]

    if http_headers.get("User-Agent"):
        command += ["-user_agent", http_headers["User-Agent"]]
    
    if http_headers.get("Referer"):
        command += ["-referer", http_headers["Referer"]]
    
    # Combine other headers if needed
    other_headers = {k: v for k, v in http_headers.items() if k not in ["User-Agent", "Referer"]}
    if other_headers:
        headers_str = "".join(f"{k}: {v}\r\n" for k, v in other_headers.items())
        command += ["-headers", headers_str]

    command += [
        "-i", audio_url,
        "-f", "s16le",
        "-acodec", "pcm_s16le",
        "-ac", "1",
        "-ar", str(SAMPLE_RATE),
        "-",
    ]

    ydl_process = None

    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=SAMPLE_RATE * 2 * CHUNK_SECONDS * 4,
        )
    except Exception as e:
        print("❌ ffmpeg launch error:", e, flush=True)
        stream_status = "error"
        stream_error = f"ffmpeg: {e}"
        is_stream_recording = False
        return

    print("✅ ffmpeg démarré", flush=True)
    sys.stdout.flush()
    stream_status = "streaming"


    # how many bytes = one chunk of int16 mono samples
    chunk_bytes = SAMPLE_RATE * CHUNK_SECONDS * 2       # 2 bytes per int16 sample
    overlap_samples = int(SAMPLE_RATE * OVERLAP_SECONDS)

    overlap_tail = np.array([], dtype=np.float32)        # carry-over from previous chunk

    try:
        while is_stream_recording and not stream_stop_event.is_set():

            if process.poll() is not None:
                stderr_out = ""
                try:
                    stderr_out = process.stderr.read().decode(errors="replace")[-500:]
                except Exception:
                    pass
                print("⚠️ ffmpeg stopped unexpectedly, exit code:", process.returncode)
                if stderr_out:
                    print("⚠️ ffmpeg stderr:", stderr_out)
                stream_status = "error"
                stream_error = f"ffmpeg exited ({process.returncode}): {stderr_out[:200]}"
                break

            # ── Read exactly one chunk ──
            raw = process.stdout.read(chunk_bytes)
            if not raw:
                continue

            new_audio = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0

            # Prepend overlap from previous iteration for context continuity
            if len(overlap_tail) > 0:
                audio_window = np.concatenate([overlap_tail, new_audio])
            else:
                audio_window = new_audio

            # ── Transcribe ──
            t0 = time.perf_counter()

            segments, seg_info = model.transcribe(
                audio_window,
                beam_size=1,                          # greedy — 2× faster, negligible loss
                best_of=1,
                temperature=0.0,                      # deterministic
                vad_filter=True,
                vad_parameters=dict(
                    threshold=0.35,                   # slightly more sensitive
                    min_silence_duration_ms=300,
                    speech_pad_ms=200,
                ),
                condition_on_previous_text=True,
                initial_prompt=last_prompt[-200:] if last_prompt else None,
                no_speech_threshold=0.5,
                log_prob_threshold=-0.8,
                suppress_blank=True,
            )

            dt = time.perf_counter() - t0

            detected_language = seg_info.language
            text = " ".join(s.text for s in segments).strip()

            if text:
                with transcript_lock:
                    current_transcript += " " + text
                    current_transcript = current_transcript[-MAX_TRANSCRIPT_CHARS:]
                    transcript_version += 1

                last_prompt = text  # feed back for next chunk coherence
                print(f"📝 [{detected_language}] ({dt:.2f}s) {text}")
            else:
                print(f"🔇 silence ({dt:.2f}s)")

            # Keep only tail for overlap
            overlap_tail = new_audio[-overlap_samples:] if overlap_samples > 0 else np.array([], dtype=np.float32)

    except Exception as e:
        print("❌ Transcription error:", e)
        stream_status = "error"
        stream_error = str(e)
    finally:
        for proc in [process, ydl_process]:
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:
                pass
        if stream_status == "streaming":
            stream_status = "idle"
        is_stream_recording = False
        print("🛑 Stream stoppé")


# ───────────────────────────────────────────
#  ROUTES
# ───────────────────────────────────────────
@app.route('/start_stream')
def start_stream():
    global is_stream_recording, stream_url, stream_status, stream_error

    url = request.args.get("url", "")
    if not url:
        return jsonify({"error": "URL manquante"}), 400

    if is_stream_recording:
        return jsonify({"status": "Déjà en cours", "stream_status": stream_status})

    is_stream_recording = True
    stream_stop_event.clear()
    stream_url = url
    stream_status = "connecting"
    stream_error = ""
    threading.Thread(target=transcribe_stream_audio, daemon=True).start()

    return jsonify({"status": "Stream démarré"})


@app.route('/stop_stream')
def stop_stream():
    global is_stream_recording
    is_stream_recording = False
    stream_stop_event.set()
    return jsonify({"status": "Stream arrêté"})


@app.route('/stream_transcript')
def get_stream_transcript():
    with transcript_lock:
        return jsonify({
            "text": current_transcript,
            "version": transcript_version,
        })


@app.route('/stream_transcript_delta')
def get_stream_transcript_delta():
    """Return only text added since the client's last known version."""
    client_version = request.args.get("since", 0, type=int)
    with transcript_lock:
        if client_version >= transcript_version:
            return jsonify({"delta": "", "version": transcript_version})
        # We can't reconstruct exact deltas, so return full text
        # with version — client can diff locally or just append.
        return jsonify({
            "text": current_transcript,
            "version": transcript_version,
        })


@app.route('/stream_status')
def get_stream_status():
    return jsonify({
        "status": stream_status,
        "error": stream_error,
        "recording": is_stream_recording,
    })


@app.route('/reset')
def reset():
    global current_transcript, transcript_version, last_prompt
    with transcript_lock:
        current_transcript = ""
        transcript_version = 0
        last_prompt = ""
    return jsonify({"status": "Reset OK"})


@app.route('/health')
def health():
    return jsonify({"status": "OK", "model": MODEL_SIZE, "device": "cuda"})


if __name__ == "__main__":
    print("🔥 Serveur LIVE GPU: http://127.0.0.1:5000")
    app.run(debug=False, host="0.0.0.0", port=5000, threaded=True)