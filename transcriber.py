# transcriber.py
"""Sprachnachrichten-Transkription via OpenRouter (Gemini Flash multimodal)."""

import base64
import logging
import os

import httpx

logger = logging.getLogger(__name__)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
STT_MODEL = os.getenv("OPENROUTER_STT_MODEL", "google/gemini-2.0-flash-001")


def transcribe_voice(file_path: str) -> str:
    """Transkribiert eine Audio-Datei via OpenRouter Chat Completions.

    Nutzt Gemini Flash mit multimodalem Audio-Input (base64 data URL).

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
        audio_b64 = base64.b64encode(f.read()).decode("ascii")

    # MIME-Type bestimmen
    ext = os.path.splitext(file_path)[1].lstrip(".").lower()
    mime_map = {"ogg": "audio/ogg", "oga": "audio/ogg", "wav": "audio/wav",
                "mp3": "audio/mpeg", "m4a": "audio/mp4", "flac": "audio/flac"}
    mime = mime_map.get(ext, "audio/ogg")

    resp = httpx.post(
        OPENROUTER_URL,
        json={
            "model": STT_MODEL,
            "max_tokens": 2000,
            "messages": [{
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Transkribiere diese Sprachnachricht wortgetreu. "
                            "Antworte NUR mit dem transkribierten Text, nichts sonst. "
                            "Keine Anführungszeichen, keine Erklärung."
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime};base64,{audio_b64}"
                        },
                    },
                ],
            }],
        },
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        },
        timeout=30.0,
    )

    if resp.status_code != 200:
        error_detail = resp.text[:300]
        logger.error("Transcription error %d: %s", resp.status_code, error_detail)
        raise RuntimeError(f"Transkription fehlgeschlagen ({resp.status_code})")

    data = resp.json()
    text = data["choices"][0]["message"]["content"].strip()
    logger.info("Transkription (%d Zeichen): %s", len(text), text[:100])
    return text
