# acknowledgements.py
"""Haiku-basierte Bestaetigungsnachrichten via OpenRouter API.
Fasst kurz zusammen was der User will — in seiner Sprache.
"""

import logging
import os

import httpx

logger = logging.getLogger(__name__)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
ACK_MODEL = os.getenv("ACK_MODEL", "google/gemini-3.1-flash-lite-preview")
ACK_TIMEOUT = float(os.getenv("ACK_TIMEOUT", "5.0"))
USER_NAME = os.getenv("USER_NAME", "")

FALLBACK = "📨 Nachricht erhalten — Claude arbeitet daran..."


def _build_system_prompt() -> str:
    name_hint = f" The user's name is {USER_NAME} — use it occasionally." if USER_NAME else ""
    return (
        "Confirm incoming tasks in one sentence. "
        "Summarize concretely what the user wants and what will happen now. "
        "Use informal 'du' (never 'Sie'). Be smart and slightly witty. "
        "Rules: Fitting emoji at the start. Max 20 words. No Markdown. ONLY the one sentence. "
        "CRITICAL: Reply in the SAME LANGUAGE the user wrote in. "
        "German message → German reply. English message → English reply."
        + name_hint
    )


async def generate_acknowledgement(user_prompt: str) -> str:
    """Generiert via Haiku eine kurze Zusammenfassung der Aufgabe."""
    if not OPENROUTER_API_KEY:
        return FALLBACK

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                OPENROUTER_URL,
                json={
                    "model": ACK_MODEL,
                    "max_tokens": 80,
                    "messages": [
                        {"role": "system", "content": _build_system_prompt()},
                        {"role": "user", "content": user_prompt[:400]},
                    ],
                },
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                timeout=ACK_TIMEOUT,
            )

        if resp.status_code != 200:
            logger.debug("ACK API error %d: %s", resp.status_code, resp.text[:200])
            return FALLBACK

        result = resp.json()["choices"][0]["message"]["content"].strip()
        if result and len(result) < 300:
            return result

    except httpx.TimeoutException:
        logger.debug("ACK Timeout nach %.1fs", ACK_TIMEOUT)
    except Exception as e:
        logger.debug("ACK fehlgeschlagen: %s", e)

    return FALLBACK
