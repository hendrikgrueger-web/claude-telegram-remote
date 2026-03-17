# transcriber.py
"""Sprachnachrichten-Transkription via OpenRouter (Chat Completions + Audio Input)."""

import base64
import logging
import os

import httpx

logger = logging.getLogger(__name__)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_STT_MODEL = os.getenv("OPENROUTER_STT_MODEL", "openai/gpt-4o-mini-audio-preview")
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"


def transcribe_voice(file_path: str) -> str:
    """Transkribiert eine Audio-Datei via OpenRouter Chat Completions API.

    Liest die OGG-Datei, base64-encodiert sie und sendet sie als
    input_audio an das konfigurierte Modell.

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

    # Dateiendung erkennen (Telegram liefert .ogg)
    ext = os.path.splitext(file_path)[1].lstrip(".").lower()
    if ext == "oga":
        ext = "ogg"
    if ext not in ("ogg", "wav", "mp3", "m4a", "flac", "aac"):
        ext = "ogg"

    payload = {
        "model": OPENROUTER_STT_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Transkribiere diese deutschsprachige Sprachnachricht wortgetreu. "
                            "Antworte NUR mit dem transkribierten Text, nichts sonst."
                        ),
                    },
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": audio_b64,
                            "format": ext,
                        },
                    },
                ],
            }
        ],
    }

    resp = httpx.post(
        OPENROUTER_API_URL,
        json=payload,
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        },
        timeout=30.0,
    )

    if resp.status_code != 200:
        error_detail = resp.text[:300]
        logger.error("OpenRouter STT error %d: %s", resp.status_code, error_detail)
        raise RuntimeError(f"OpenRouter API Fehler ({resp.status_code})")

    data = resp.json()
    text = data["choices"][0]["message"]["content"].strip()
    logger.info("Transkription (%d Zeichen): %s", len(text), text[:100])
    return text
