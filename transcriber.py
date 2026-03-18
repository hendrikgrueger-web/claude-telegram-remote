# transcriber.py
"""Sprachnachrichten-Transkription via OpenRouter Whisper API."""

import logging
import os

import httpx

logger = logging.getLogger(__name__)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
# OpenRouter bietet /audio/transcriptions als Whisper-kompatiblen Endpoint
TRANSCRIPTION_URL = "https://openrouter.ai/api/v1/audio/transcriptions"


def transcribe_voice(file_path: str) -> str:
    """Transkribiert eine Audio-Datei via OpenRouter Whisper API.

    Returns:
        Transkribierter Text.

    Raises:
        RuntimeError: Wenn API-Key fehlt oder API-Fehler.
    """
    if not OPENROUTER_API_KEY:
        raise RuntimeError(
            "OPENROUTER_API_KEY nicht gesetzt. Bitte in .env eintragen."
        )

    with open(file_path, "rb") as f:
        audio_data = f.read()

    # Multipart-Upload wie bei OpenAI Whisper
    resp = httpx.post(
        TRANSCRIPTION_URL,
        headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
        data={"model": "openai/whisper-large-v3", "language": "de"},
        files={"file": ("voice.ogg", audio_data, "audio/ogg")},
        timeout=30.0,
    )

    if resp.status_code != 200:
        error_detail = resp.text[:300]
        logger.error("Transcription error %d: %s", resp.status_code, error_detail)
        raise RuntimeError(f"Transkription fehlgeschlagen ({resp.status_code})")

    # Whisper API gibt {"text": "..."} zurueck
    data = resp.json()
    text = data.get("text", "").strip()
    logger.info("Transkription (%d Zeichen): %s", len(text), text[:100])
    return text
