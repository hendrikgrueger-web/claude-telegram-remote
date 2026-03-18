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
ACK_MODEL = os.getenv("ACK_MODEL", "anthropic/claude-3-5-haiku")
ACK_TIMEOUT = float(os.getenv("ACK_TIMEOUT", "5.0"))

FALLBACK = "📨 Nachricht erhalten — Claude arbeitet daran..."

_SYSTEM_PROMPT = (
    "Confirm incoming tasks in one sentence. "
    "Summarize concretely what the user wants and what will happen now. "
    "Rules: Fitting emoji at the start. Max 20 words. No Markdown. ONLY the one sentence. "
    "CRITICAL: Reply in the SAME LANGUAGE the user wrote in. "
    "German message → German reply. English message → English reply."
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
                        {"role": "system", "content": _SYSTEM_PROMPT},
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
