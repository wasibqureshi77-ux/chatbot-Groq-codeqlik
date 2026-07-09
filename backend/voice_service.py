import os
import time
import logging
import shutil

logger = logging.getLogger("voice_service")
logger.setLevel(logging.INFO)

# --- STT Setup ---
USE_FASTER_WHISPER = False
try:
    from faster_whisper import WhisperModel, download_model
    import shutil
    
    # Dynamically resolve model size from the target directory name
    model_size = "base" 
    model_dir = os.path.join(os.path.dirname(__file__), "models", model_size)
    
    # Check if the model directory has finished downloading by verifying model.bin exists
    model_bin_path = os.path.join(model_dir, "model.bin")
    if not os.path.exists(model_bin_path):
        if os.path.exists(model_dir):
            logger.info(f"Incomplete model directory found, removing: {model_dir}")
            shutil.rmtree(model_dir, ignore_errors=True)
        
        logger.info(f"Downloading faster-whisper {model_size} model locally...")
        download_model(model_size, output_dir=model_dir)

    stt_model = WhisperModel(model_dir, device="cpu", compute_type="int8")
    USE_FASTER_WHISPER = True
    logger.info(f"faster-whisper {model_size} model loaded successfully.")
except Exception as e:
    logger.warning(f"Could not load faster-whisper model ({model_size}): {e}. Using fallback SpeechRecognition.")

# Fallback STT using speech_recognition library
def transcribe_fallback(file_path: str) -> str:
    try:
        import speech_recognition as sr
        r = sr.Recognizer()
        with sr.AudioFile(file_path) as source:
            audio = r.record(source)
        # Recognize using Google Web Speech API (free, supports Hindi & English)
        text = r.recognize_google(audio, language="hi-IN" if "hi" in file_path.lower() else "en-US")
        return text
    except Exception as e:
        logger.error(f"Fallback transcription failed: {e}")
        return ""

def transcribe_audio(file_path: str) -> str:
    if USE_FASTER_WHISPER:
        try:
            segments, info = stt_model.transcribe(file_path, beam_size=5)
            text = " ".join([segment.text for segment in segments])
            return text.strip()
        except Exception as e:
            logger.error(f"faster-whisper transcription failed: {e}. Falling back...")
            return transcribe_fallback(file_path)
    else:
        return transcribe_fallback(file_path)


# --- TTS Setup ---
# We will use gTTS as the primary fast TTS generator (as it supports English, Hindi, and Hinglish beautifully without heavy setup),
# and fallback to pyttsx3 or offline tools if offline is required.
def generate_speech(text: str, output_dir: str, lang_hint: str = "en") -> str:
    os.makedirs(output_dir, exist_ok=True)
    filename = f"tts_{int(time.time() * 1000)}.mp3"
    file_path = os.path.join(output_dir, filename)

    # Detect language based on hint or content
    lang = "en"
    text_lower = text.lower()
    
    # Check for common Hinglish/Hindi markers
    hindi_markers = ["chahiye", "banana", "kya", "kaise", "hoga", "aap", "liye", "btao", "batao"]
    if lang_hint in {"hinglish", "hindi"} or any(m in text_lower for m in hindi_markers):
        lang = "hi"

    try:
        from gtts import gTTS
        # Clean text from markdown bold tags **
        clean_text = text.replace("**", "").replace("*", "")
        tts = gTTS(text=clean_text, lang=lang, slow=False)
        tts.save(file_path)
        logger.info(f"Speech generated successfully with gTTS at: {file_path}")
        return filename
    except Exception as e:
        logger.warning(f"gTTS failed: {e}. Trying pyttsx3 offline fallback...")
        try:
            import pyttsx3
            engine = pyttsx3.init()
            # Clean text
            clean_text = text.replace("**", "").replace("*", "")
            engine.save_to_file(clean_text, file_path)
            engine.runAndWait()
            logger.info(f"Speech generated successfully with pyttsx3 fallback at: {file_path}")
            return filename
        except Exception as ex:
            logger.error(f"TTS fallback failed: {ex}")
            return ""


def _valid_wav_output(path: str) -> bool:
    try:
        return os.path.exists(path) and os.path.getsize(path) > 44
    except Exception:
        return False


def _convert_with_ffmpeg(input_path: str, output_path: str) -> bool:
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        return False

    try:
        import subprocess
        cmd = [
            ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            input_path,
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "16000",
            "-ac",
            "1",
            output_path,
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode == 0 and _valid_wav_output(output_path):
            logger.info("Successfully converted audio to WAV using system FFmpeg.")
            return True

        logger.error(f"FFmpeg audio conversion failed: {result.stderr.strip() or 'unknown error'}")
    except Exception as exc:
        logger.error(f"FFmpeg audio conversion exception: {exc}")
    return False


def _convert_with_pyav(input_path: str, output_path: str) -> bool:
    try:
        import av
        import wave
        container = av.open(input_path)
        stream = container.streams.audio[0]

        # Open wav file for writing
        wav_file = wave.open(output_path, "wb")
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2) # 16-bit PCM (s16)
        wav_file.setframerate(16000)

        # Resampler to convert to mono, 16000Hz, s16 format
        resampler = av.AudioResampler(
            format="s16",
            layout="mono",
            rate=16000
        )

        frames_written = 0
        for frame in container.decode(stream):
            resampled_frames = resampler.resample(frame)
            if resampled_frames:
                for resampled in resampled_frames:
                    data = resampled.to_ndarray().tobytes()
                    wav_file.writeframes(data)
                    frames_written += len(data)

        # Flush resampler
        resampled_frames = resampler.resample(None)
        if resampled_frames:
            for resampled in resampled_frames:
                data = resampled.to_ndarray().tobytes()
                wav_file.writeframes(data)
                frames_written += len(data)

        wav_file.close()
        container.close()

        if frames_written == 0:
            raise Exception("No audio frames decoded by PyAV (possibly empty or corrupt input)")

        logger.info(f"Successfully converted audio to WAV using PyAV: {output_path} ({frames_written} bytes)")
        return True
    except Exception as e:
        logger.error(f"PyAV audio conversion failed: {e}")
        return False


def convert_to_wav(input_path: str, output_path: str) -> bool:
    """
    Convert browser-recorded audio to mono 16 kHz PCM WAV for STT.

    Browsers can send WebM/Opus, Ogg/Opus, or MP4 depending on support. FFmpeg
    is the most reliable decoder for these containers, so use it first when it
    is installed and keep PyAV as a Python fallback.
    """
    try:
        if os.path.exists(output_path):
            os.remove(output_path)
    except Exception:
        pass

    if _convert_with_ffmpeg(input_path, output_path):
        return True

    try:
        if os.path.exists(output_path):
            os.remove(output_path)
    except Exception:
        pass

    return _convert_with_pyav(input_path, output_path)
