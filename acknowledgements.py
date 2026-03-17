# acknowledgements.py
"""Haiku-basierte Bestaetigungsnachrichten fuer eingehende Prompts.
Haiku fasst kurz zusammen, was der User will und was jetzt passiert.
"""

import asyncio
import logging
import os

logger = logging.getLogger(__name__)

CLAUDE_BIN = os.getenv("CLAUDE_BIN", "claude")
ACK_TIMEOUT = float(os.getenv("ACK_TIMEOUT", "6.0"))

FALLBACK = "📨 Nachricht erhalten — Claude arbeitet daran..."


async def generate_acknowledgement(user_prompt: str) -> str:
    """Generiert via Haiku eine kurze Zusammenfassung der Aufgabe."""
    haiku_prompt = (
        "Du bist ein Assistent der eingehende Auftraege kurz bestaetigt.\n\n"
        f"Auftrag des Users:\n\"{user_prompt[:400]}\"\n\n"
        "Fasse in GENAU einem Satz (max 20 Worte) zusammen:\n"
        "1. Was der User will\n"
        "2. Was Claude jetzt tun wird\n\n"
        "Regeln:\n"
        "- Ein passendes Emoji am Anfang\n"
        "- Konkret und spezifisch, nicht generisch\n"
        "- Deutsch, kein Markdown\n"
        "- NUR der eine Satz, sonst nichts"
    )
    try:
        proc = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                CLAUDE_BIN, "-p", haiku_prompt,
                "--model", "claude-haiku-4-5-20251001",
                "--max-turns", "1",
                "--no-session-persistence",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            ),
            timeout=ACK_TIMEOUT,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=ACK_TIMEOUT)
        result = stdout.decode("utf-8", errors="replace").strip()
        if result and len(result) < 250:
            return result
    except (asyncio.TimeoutError, Exception) as e:
        logger.debug("Haiku-Acknowledgement fehlgeschlagen: %s", e)
    return FALLBACK
