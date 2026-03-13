# bot.py
"""Telegram-Bot als Remote-Interface zu Claude Code.
Entry Point, TelegramHandler, Command-Handler.
"""

import asyncio
import functools
import logging
import os
import subprocess
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from claude_runner import ClaudeRunner, OutputStreamer, SessionExpiredError
from workspace import WorkspaceManager

load_dotenv()

# ── Konfiguration ─────────────────────────────────────────────────────────────

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ALLOWED_USER_ID = int(os.environ["ALLOWED_USER_ID"])
DEFAULT_DIR = os.getenv("DEFAULT_WORKSPACE_DIR", "~/Coding")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Globaler State ────────────────────────────────────────────────────────────

ws_manager = WorkspaceManager(default_dir=DEFAULT_DIR)
runner = ClaudeRunner()


# ── Auth-Decorator ────────────────────────────────────────────────────────────

def authorized_only(func):
    """Ignoriert alle Nachrichten von nicht-autorisierten Usern."""
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user and update.effective_user.id != ALLOWED_USER_ID:
            return
        return await func(update, context)
    return wrapper


# ── Command Handler ───────────────────────────────────────────────────────────

@authorized_only
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🤖 *Claude Remote Control*\n\n"
        "*Workspace-Befehle:*\n"
        "`/ws list` — Alle Workspaces anzeigen\n"
        "`/ws <name>` — Workspace wechseln / anlegen\n"
        "`/ws <name> <pfad>` — Workspace mit Verzeichnis anlegen\n"
        "`/ws delete <name>` — Workspace löschen\n\n"
        "*Claude-Befehle:*\n"
        "`/model` — Aktuelles Modell anzeigen\n"
        "`/model opus|sonnet|haiku` — Modell wechseln\n"
        "`/clear` — Session löschen, neu starten\n"
        "`/compact` — Kontext zurücksetzen\n\n"
        "*System-Befehle:*\n"
        "`/stop` — Laufende Anfrage abbrechen\n"
        "`/status` — Aktueller Workspace und Verzeichnis\n"
        "`/help` — Diese Hilfe\n\n"
        "Alles andere wird direkt an Claude gesendet."
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


@authorized_only
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ws = ws_manager.get_active()
    name = ws_manager.get_active_name()
    session = ws.get("session_id")
    session_info = f"`{session[:8]}...`" if session else "keine (neue Session)"
    busy = "⏳ Läuft gerade" if runner.is_busy() else "✅ Bereit"

    try:
        result = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=5)
        claude_version = result.stdout.strip() or result.stderr.strip() or "unbekannt"
    except Exception:
        claude_version = "nicht erreichbar"

    text = (
        f"*Workspace:* `{name}`\n"
        f"*Verzeichnis:* `{ws['directory']}`\n"
        f"*Session:* {session_info}\n"
        f"*Status:* {busy}\n"
        f"*Claude:* `{claude_version}`"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


@authorized_only
async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not runner.is_busy():
        await update.message.reply_text("Nichts läuft gerade.")
        return
    await runner.stop()
    await update.message.reply_text("⛔ Abgebrochen.")


@authorized_only
async def cmd_ws(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []

    if not args or args[0] == "list":
        names = ws_manager.list_names()
        active = ws_manager.get_active_name()
        lines = []
        for n in names:
            ws = ws_manager.get(n)
            marker = "▶️" if n == active else "  "
            lines.append(f"{marker} `{n}` — `{ws['directory']}`")
        await update.message.reply_text(
            "*Workspaces:*\n" + "\n".join(lines),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if args[0] == "delete":
        if len(args) < 2:
            await update.message.reply_text("Usage: `/ws delete <name>`", parse_mode=ParseMode.MARKDOWN)
            return
        try:
            ws_manager.delete(args[1])
            await update.message.reply_text(
                f"🗑 Workspace `{args[1]}` gelöscht.", parse_mode=ParseMode.MARKDOWN
            )
        except (ValueError, KeyError) as e:
            await update.message.reply_text(f"Fehler: {e}")
        return

    name = args[0]
    directory = args[1] if len(args) > 1 else None
    ws = ws_manager.switch(name, directory=directory)
    session_info = "bestehende Session" if ws.get("session_id") else "neue Session"
    await update.message.reply_text(
        f"✅ Workspace *{name}*\n📁 `{ws['directory']}`\n💬 {session_info}",
        parse_mode=ParseMode.MARKDOWN,
    )


# ── Claude Code Slash-Commands ───────────────────────────────────────────────

MODEL_ALIASES = {
    "opus": "claude-opus-4-6",
    "sonnet": "claude-sonnet-4-6",
    "haiku": "claude-haiku-4-5-20251001",
}


@authorized_only
async def cmd_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []
    if not args:
        current = ws_manager.get_model() or "default (sonnet)"
        aliases = " | ".join(f"`{a}`" for a in MODEL_ALIASES)
        await update.message.reply_text(
            f"*Aktuelles Modell:* `{current}`\n\n"
            f"*Verfügbar:* {aliases}\n"
            f"*Setzen:* `/model opus`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    choice = args[0].lower()
    if choice in MODEL_ALIASES:
        ws_manager.set_model(MODEL_ALIASES[choice])
        await update.message.reply_text(
            f"Modell auf *{choice}* (`{MODEL_ALIASES[choice]}`) gesetzt.",
            parse_mode=ParseMode.MARKDOWN,
        )
    elif choice == "default":
        ws_manager.set_model(None)
        await update.message.reply_text("Modell auf *default* zurückgesetzt.", parse_mode=ParseMode.MARKDOWN)
    else:
        # Volles Modell-ID übergeben (z.B. claude-sonnet-4-6)
        ws_manager.set_model(choice)
        await update.message.reply_text(
            f"Modell auf `{choice}` gesetzt.", parse_mode=ParseMode.MARKDOWN
        )


@authorized_only
async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ws_manager.clear_session_id()
    name = ws_manager.get_active_name()
    await update.message.reply_text(
        f"Session in *{name}* gelöscht — nächste Nachricht startet neue Unterhaltung.",
        parse_mode=ParseMode.MARKDOWN,
    )


@authorized_only
async def cmd_compact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ws_manager.clear_session_id()
    name = ws_manager.get_active_name()
    await update.message.reply_text(
        f"Kontext in *{name}* zurückgesetzt (Session gelöscht).\n"
        f"Nächste Nachricht startet frisch.",
        parse_mode=ParseMode.MARKDOWN,
    )


# ── Nachrichten-Handler (→ Claude) ───────────────────────────────────────────

@authorized_only
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if runner.is_busy():
        await update.message.reply_text("⏳ Claude arbeitet noch. Mit /stop abbrechen.")
        return

    text = update.message.text
    ws = ws_manager.get_active()
    session_id = ws.get("session_id")

    status_msg = await update.message.reply_text(
        "🤔 _Claude denkt nach..._", parse_mode=ParseMode.MARKDOWN
    )

    async def send_fn(content: str):
        return await update.message.reply_text(content)

    async def edit_fn(msg, content: str):
        try:
            await msg.edit_text(content)
        except Exception:
            pass

    streamer = OutputStreamer(send_fn=send_fn, edit_fn=edit_fn)
    streamer._current_msg = status_msg

    try:
        new_session_id = await runner.run(
            prompt=text,
            directory=ws["directory"],
            session_id=session_id,
            on_chunk=streamer.append,
            model=ws_manager.get_model(),
        )
        await streamer.finalize()

        if new_session_id:
            ws_manager.set_session_id(new_session_id)

    except SessionExpiredError:
        ws_manager.clear_session_id()
        await update.message.reply_text(
            "⚠️ Session abgelaufen — neues Gespräch gestartet. Bitte nochmal senden."
        )
    except asyncio.TimeoutError:
        await update.message.reply_text(
            f"⏱ Timeout nach {os.getenv('CLAUDE_TIMEOUT_SECONDS', '300')}s. "
            "Mit /stop bereinigen und nochmal versuchen."
        )
    except Exception as e:
        logger.error("Unbehandelter Fehler: %s", e, exc_info=True)
        await update.message.reply_text(f"❌ Fehler: {e}")


# ── Entry Point ───────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("start", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("ws", cmd_ws))
    app.add_handler(CommandHandler("model", cmd_model))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(CommandHandler("compact", cmd_compact))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot gestartet. Workspace: %s", ws_manager.get_active_name())
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
