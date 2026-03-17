# transcriber.py
"""Sprachnachrichten-Transkription via OpenAI Whisper API."""

import logging
import os

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")


def transcribe_voice(file_path: str) -> str:
    """Transkribiert eine Audio-Datei via OpenAI Whisper API (synchron).

    Returns:
        Transkribierter Text.

    Raises:
        RuntimeError: Wenn API-Key fehlt oder openai nicht installiert.
    """
    if not OPENAI_API_KEY:
        raise RuntimeError(
            "OPENAI_API_KEY nicht gesetzt. "
            "Fuer Sprachnachrichten bitte in .env eintragen."
        )

    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError(
            "openai Package nicht installiert. "
            "Bitte: .venv/bin/pip install openai"
        )

    client = OpenAI(api_key=OPENAI_API_KEY)

    with open(file_path, "rb") as audio_file:
        response = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            language="de",
        )

    text = response.text.strip()
    logger.info("Transkription (%d Zeichen): %s", len(text), text[:100])
    return text
