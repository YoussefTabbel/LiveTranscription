import whisper
import sounddevice as sd
import numpy as np
import queue
import threading
from flask import Flask, jsonify, request
import subprocess
import yt_dlp

app = Flask(__name__)

print("Chargement du modèle Whisper...")
model = whisper.load_model("base")  # tu peux mettre "tiny" pour plus rapide

# ================= MICROPHONE LOCAL =================

current_transcript = ""
audio_queue = queue.Queue()
is_recording = False
stop_event = threading.Event()

def audio_callback(indata, frames, time, status):
    if status:
        print(status)
    audio_queue.put(indata.copy())

def transcribe_audio():
    global current_transcript, is_recording  # <<<<< ici, tout en haut

    samplerate = 16000
    stream = sd.InputStream(
        callback=audio_callback,
        channels=1,
        samplerate=samplerate,
        dtype='float32'
    )

    with stream:
        buffer = np.array([], dtype=np.float32)
        while is_recording and not stop_event.is_set():
            try:
                chunk = audio_queue.get(timeout=1)
                buffer = np.concatenate([buffer, chunk.flatten()])

                if len(buffer) >= 64000:
                    buffer32 = buffer.astype(np.float32)
                    result = model.transcribe(buffer32, fp16=False)
                    text = result["text"].strip()
                    if text:
                        current_transcript += " " + text
                        print("Micro:", text)
                    buffer = buffer[-16000:]
            except queue.Empty:
                continue    

    samplerate = 16000
    stream = sd.InputStream(
        callback=audio_callback,
        channels=1,
        samplerate=samplerate,
        dtype='float32'
    )

    with stream:
        buffer = np.array([], dtype=np.float32)  # forcer float32 dès le départ
        while is_recording and not stop_event.is_set():
            try:
                chunk = audio_queue.get(timeout=1)
                buffer = np.concatenate([buffer, chunk.flatten()])

                if len(buffer) >= 64000:
                    # Convertir en float32 pour Whisper
                    buffer32 = buffer.astype(np.float32)
                    result = model.transcribe(buffer32, fp16=False)
                    text = result["text"].strip()
                    if text:
                        current_transcript += " " + text
                        print("Micro:", text)

                    # Garder les derniers 16000 échantillons
                    buffer = buffer[-16000:]
            except queue.Empty:
                continue    

    samplerate = 16000
    stream = sd.InputStream(
        callback=audio_callback,
        channels=1,
        samplerate=samplerate,
        dtype='float32'
    )

    with stream:
        buffer = np.array([])
        while is_recording and not stop_event.is_set():
            try:
                chunk = audio_queue.get(timeout=1)
                buffer = np.concatenate([buffer, chunk.flatten()])

                if len(buffer) >= 64000:
                    result = model.transcribe(buffer, fp16=False)
                    text = result["text"].strip()
                    if text:
                        current_transcript += " " + text
                        print("Micro:", text)
                    buffer = buffer[-16000:]
            except queue.Empty:
                continue

@app.route('/start')
def start():
    global is_recording, stop_event
    if not is_recording:
        is_recording = True
        stop_event.clear()
        threading.Thread(target=transcribe_audio, daemon=True).start()
    return jsonify({"status": "Micro démarré"})

@app.route('/stop')
def stop():
    global is_recording, stop_event
    is_recording = False
    stop_event.set()
    return jsonify({"status": "Micro arrêté"})

@app.route('/reset')
def reset():
    global current_transcript
    current_transcript = ""
    return jsonify({"status": "Reset OK"})

@app.route('/live_transcript')
def live_transcript():
    return jsonify({"text": current_transcript})

# ================= LIVE STREAM =================

current_stream_transcript = ""
is_stream_recording = False
stream_stop_event = threading.Event()
stream_url = ""

def transcribe_stream_audio():
    global current_stream_transcript, is_stream_recording, stream_stop_event, stream_url

    print("Démarrage live:", stream_url)

    ydl_opts = {
        "format": "bestaudio/best",
        "quiet": True,
         "js_runtimes": {"node": {}},  # Node.js requis pour YouTube live
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(stream_url, download=False)

            # Récupérer le bon flux audio
            formats = info.get("formats", [])
            audio_url = None
            for f in reversed(formats):
                if f.get("acodec") != "none":
                    audio_url = f.get("url")
                    break
            if not audio_url:
                print("Aucun flux audio trouvé")
                return

    except Exception as e:
        print("Erreur yt-dlp :", e)
        return

    print("Flux audio trouvé ✅")

    command = [
        "ffmpeg",
        "-i", audio_url,
        "-f", "s16le",
        "-acodec", "pcm_s16le",
        "-ac", "1",
        "-ar", "16000",
        "-"
    ]

    process = subprocess.Popen(command, stdout=subprocess.PIPE)

    while is_stream_recording and not stream_stop_event.is_set():
        raw_audio = process.stdout.read(16000 * 2 * 15)  # 15 secondes

        if not raw_audio:
            break

        audio_np = np.frombuffer(raw_audio, np.int16).astype(np.float32) / 32768.0

        result = model.transcribe(audio_np, fp16=False)
        text = result["text"].strip()

        if text:
            current_stream_transcript += " " + text
            print("Live:", text)

    process.kill()

@app.route('/start_stream')
def start_stream():
    global is_stream_recording, stream_url
    url = request.args.get("url", "")
    if not url:
        return jsonify({"error": "URL manquante"}), 400

    if not is_stream_recording:
        is_stream_recording = True
        stream_stop_event.clear()
        stream_url = url
        threading.Thread(target=transcribe_stream_audio, daemon=True).start()

    return jsonify({"status": "Stream démarré"})

@app.route('/stop_stream')
def stop_stream():
    global is_stream_recording
    is_stream_recording = False
    stream_stop_event.set()
    return jsonify({"status": "Stream arrêté"})

@app.route('/stream_transcript')
def stream_transcript():
    return jsonify({"text": current_stream_transcript})

@app.route('/health')
def health():
    return jsonify({"status": "OK"})

if __name__ == "__main__":
    print("Serveur live transcription démarré: http://127.0.0.1:5000")
    app.run(debug=False, host='0.0.0.0', port=5000, threaded=True)