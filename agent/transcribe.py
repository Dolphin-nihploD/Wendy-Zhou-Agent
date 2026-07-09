"""
agent/transcribe.py
====================
Phase 11b (built 2026-07-09, switched to local Whisper same day) — lets
Wendy read/understand an audio or video file the user uploads directly
(not a link — see agent/youtube.py for that).

Claude's API has no native audio/video input (confirmed 2026-07-09 — the
Messages API only has text, image, and document/PDF content blocks), so
this transcribes the file to text first — same idea as extract_text() in
exporters.py for PDFs/Word/Excel, just a different extraction step.

Runs LOCALLY via faster-whisper — an open-source, MIT-licensed Whisper
implementation (CTranslate2 runtime). No API key, no account, no per-use
cost, no audio ever leaves this machine. The user chose this over a cloud
API specifically to avoid any OpenAI dependency and ongoing cost.

This only makes sense to run on whichever machine actually handles the
transcription request. Locally (the user's own PC) that's fine — decent
CPU, or a GPU if configured (see WHISPER_DEVICE below). On Railway's cloud
plan this would be slow (limited CPU, no GPU on typical plans) — expect
this feature to mostly matter for the LOCAL instance, not the deployed one.

ENV VARS (all optional — sensible CPU-only defaults below)
------------------------------------------------------------
    WHISPER_MODEL_SIZE   tiny | base | small | medium | large-v3
                         (default: "small" — good speed/accuracy balance
                         on CPU; go bigger if accuracy matters more than
                         speed, smaller if you want faster turnaround)
    WHISPER_DEVICE       "cpu" (default) or "cuda" if you've set up an
                         NVIDIA GPU with CUDA 12 + cuDNN 9 libraries
    WHISPER_COMPUTE_TYPE "int8" (default on CPU, fastest) or "float16"
                         (default on CUDA) / "float32"

Install: pip install faster-whisper   (added to requirements.txt)
NOTE: unlike the original openai-whisper package, faster-whisper does NOT
need a separate system ffmpeg install — audio decoding is bundled via the
PyAV library, so `pip install faster-whisper` alone is genuinely enough.

First call downloads the chosen model from Hugging Face (the default
"small" model is roughly 500MB) — this can take a minute or two the very
first time only; after that it's cached on disk and loads fast. The model
itself is also kept loaded in memory across requests (see _get_model())
so only the FIRST transcription in a run pays the load cost.

Supported inputs: anything faster-whisper/PyAV can decode — mp3, mp4, wav,
m4a, webm, mov, mkv, ogg, flac, etc. Video-with-audio works directly, no
separate audio-extraction step needed.
"""

import os
import base64
import tempfile

MAX_BYTES = 300 * 1024 * 1024  # generous local cap — no cloud-API 25MB ceiling here

SUPPORTED_EXTENSIONS = ("mp3", "mp4", "mpeg", "mpga", "m4a", "wav", "webm", "mov", "mkv", "ogg", "flac", "aac")

_EXT_BY_MEDIA_TYPE = {
    "audio/mpeg": "mp3", "audio/mp3": "mp3",
    "video/mp4": "mp4", "audio/mp4": "mp4",
    "audio/wav": "wav", "audio/x-wav": "wav",
    "audio/webm": "webm", "video/webm": "webm",
    "audio/m4a": "m4a", "audio/x-m4a": "m4a",
    "video/quicktime": "mov", "video/x-matroska": "mkv",
    "audio/ogg": "ogg", "audio/flac": "flac", "audio/aac": "aac",
}


def _guess_extension(name, media_type):
    lname = (name or "").lower()
    for ext in SUPPORTED_EXTENSIONS:
        if lname.endswith("." + ext):
            return ext
    return _EXT_BY_MEDIA_TYPE.get((media_type or "").lower(), "mp3")


_model = None


def _get_model():
    """Load the Whisper model once and reuse it across requests.

    Loading is the slow part (reading the model into memory/GPU) — we don't
    want to redo that on every single transcription, just once per process.
    """
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        size = os.environ.get("WHISPER_MODEL_SIZE", "small").strip()
        device = os.environ.get("WHISPER_DEVICE", "cpu").strip()
        default_compute = "float16" if device == "cuda" else "int8"
        compute_type = os.environ.get("WHISPER_COMPUTE_TYPE", default_compute).strip()
        print(f"[transcribe] loading Whisper model '{size}' (device={device}, "
              f"compute_type={compute_type})... first run downloads it, may take a minute.")
        _model = WhisperModel(size, device=device, compute_type=compute_type)
        print("[transcribe] model loaded.")
    return _model


def transcribe_audio_b64(name, media_type, b64):
    """Decode a base64 audio/video file and return its transcript as text.

    Mirrors exporters.extract_text()'s contract: never raises, always
    returns a string — either the transcript or a short bracketed note
    explaining why it couldn't be produced, so the chat can still proceed
    and Wendy can relay the failure honestly instead of guessing at content.
    """
    try:
        raw = base64.b64decode(b64 or "")
    except Exception as e:
        return f"[Could not decode {name or 'file'}: {e}]"

    if not raw:
        return f"[{name or 'This file'} came through empty — nothing to transcribe.]"

    if len(raw) > MAX_BYTES:
        mb = len(raw) / (1024 * 1024)
        return f"[Could not transcribe {name or 'this file'}: {mb:.0f} MB is too large to process locally.]"

    ext = _guess_extension(name, media_type)
    tmp_path = None

    try:
        model = _get_model()
        with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp:
            tmp.write(raw)
            tmp_path = tmp.name
        # delete=False + close-then-reopen-by-path avoids a Windows file-lock
        # issue where faster-whisper/PyAV can't reopen a still-open handle.
        # Language is auto-detected (no language= passed) — info carries what
        # it guessed, logged here purely for debugging, e.g. if a transcript
        # looks garbled it's worth checking what language it thought this was.
        segments, info = model.transcribe(tmp_path, beam_size=5)
        text = " ".join(seg.text.strip() for seg in segments).strip()
        print(f"[transcribe] {name}: detected language '{info.language}' "
              f"(confidence {info.language_probability:.2f})")
    except Exception as e:
        print(f"[transcribe] failed for {name}: {type(e).__name__}: {e}")
        return f"[Could not transcribe {name or 'this file'}: {e}]"
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    if not text:
        return (f"[Transcription of {name or 'this file'} came back empty — the audio "
                f"may be silent, or in a format that decoded but produced no speech.]")
    return text
