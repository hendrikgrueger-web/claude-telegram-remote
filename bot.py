# bot.py
"""Telegram-Bot als Remote-Interface zu Claude Code.
Entry Point, TelegramHandler, Command-Handler.
"""

import asyncio
import functools
import json
import logging
import os
import subprocess
from pathlib import Path

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from claude_runner import ClaudeRunner, EventType, RunEvent, SessionExpiredError, last_usage, session_usage, CLAUDE_BIN
from event_formatter import EventFormatter
from permission_server import PermissionServer, ToolCategory
from workspace import WorkspaceManager

load_dotenv()

# ── Konfiguration ─────────────────────────────────────────────────────────────

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ALLOWED_USER_ID = int(os.environ["ALLOWED_USER_ID"])
DEFAULT_DIR = os.getenv("DEFAULT_WORKSPACE_DIR", "~/Coding")
MAX_MESSAGE_LEN = 4000
PERMISSION_PORT = int(os.getenv("PERMISSION_SERVER_PORT", "7429"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Globaler State ────────────────────────────────────────────────────────────

ws_manager = WorkspaceManager(default_dir=DEFAULT_DIR)
runner = ClaudeRunner()
perm_server = PermissionServer(port=PERMISSION_PORT)

# Wird in main() mit app.bot verbunden
_bot_instance = None


# ── Permission-Callback ───────────────────────────────────────────────────────

async def on_permission_request(req):
    """Wird vom PermissionServer aufgerufen — zeigt Telegram Inline-Keyboard."""
    if not _bot_instance:
        req.decision = "allow"
        req.event.set()
        return

    import html as html_mod
    icon = "🛑" if req.category == ToolCategory.DESTRUCTIVE else "⚠️"
    timeout_info = ""
    if req.category == ToolCategory.MODIFYING:
        timeout_info = "\n⏱ <i>Auto-accept in 60s</i>"
    elif req.category == ToolCategory.DESTRUCTIVE:
        timeout_info = "\n🛑 <i>Wartet auf deine Entscheidung</i>"

    detail = json.dumps(req.tool_input, indent=2, ensure_ascii=False)
    if len(detail) > 500:
        detail = detail[:500] + "..."

    text = (
        f"{icon} <b>Permission: {html_mod.escape(req.tool_name)}</b>\n"
        f"<pre>{html_mod.escape(detail)}</pre>"
        f"{timeout_info}"
    )

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Erlauben", callback_data=f"perm:allow:{req.request_id}"),
        InlineKeyboardButton("❌ Blockieren", callback_data=f"perm:block:{req.request_id}"),
    ]])

    await _bot_instance.send_message(
        chat_id=ALLOWED_USER_ID,
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


# ── Auth-Decorator ────────────────────────────────────────────────────────────

def authorized_only(func):
    """Ignoriert und loggt alle Nachrichten von nicht-autorisierten Usern."""
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user and update.effective_user.id != ALLOWED_USER_ID:
            user = update.effective_user
            logger.warning(
                "Unauthorized access: user_id=%s username=%s name=%s",
                user.id, user.username, user.full_name,
            )
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
        "`/plan` — Plan-Modus an/aus\n"
        "`/clear` — Session loeschen, neu starten\n"
        "`/compact` — Kontext zuruecksetzen\n"
        "`/usage` — Token-Verbrauch anzeigen\n"
        "`/skills` — Installierte Skills auflisten\n"
        "`/rename <name>` — Workspace umbenennen\n\n"
        "*Permissions:*\n"
        "Claude fragt bei Write/Edit/Bash um Erlaubnis via Button.\n"
        "Harmlose Tools (Read/Grep) laufen automatisch.\n\n"
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
        result = subprocess.run([CLAUDE_BIN, "--version"], capture_output=True, text=True, timeout=5)
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


@authorized_only
async def cmd_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    current = ws_manager.get_plan_mode()
    ws_manager.set_plan_mode(not current)
    state = "aktiviert" if not current else "deaktiviert"
    await update.message.reply_text(
        f"Plan-Modus *{state}*.\n"
        + ("Claude erstellt nur Plaene, implementiert nichts." if not current else "Claude arbeitet normal."),
        parse_mode=ParseMode.MARKDOWN,
    )


@authorized_only
async def cmd_rename(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Usage: `/rename <neuer_name>`", parse_mode=ParseMode.MARKDOWN
        )
        return
    old_name = ws_manager.get_active_name()
    new_name = args[0]
    try:
        ws_manager.rename(old_name, new_name)
        await update.message.reply_text(
            f"Workspace *{old_name}* umbenannt zu *{new_name}*.",
            parse_mode=ParseMode.MARKDOWN,
        )
    except (KeyError, ValueError) as e:
        await update.message.reply_text(f"Fehler: {e}")


@authorized_only
async def cmd_usage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not session_usage["requests"]:
        await update.message.reply_text("Noch keine Anfragen in dieser Session.")
        return

    last_in = last_usage.get("input_tokens", 0)
    last_out = last_usage.get("output_tokens", 0)
    total_in = session_usage["input_tokens"]
    total_out = session_usage["output_tokens"]
    reqs = session_usage["requests"]

    text = (
        "*Letzte Anfrage:*\n"
        f"  Input: `{last_in:,}` | Output: `{last_out:,}` Tokens\n\n"
        f"*Session gesamt ({reqs} Anfragen):*\n"
        f"  Input: `{total_in:,}` | Output: `{total_out:,}` Tokens"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


@authorized_only
async def cmd_skills(update: Update, context: ContextTypes.DEFAULT_TYPE):
    skills_dir = Path.home() / ".claude" / "skills"
    if not skills_dir.exists():
        await update.message.reply_text("Kein Skills-Verzeichnis gefunden.")
        return
    skills = sorted(f.stem for f in skills_dir.iterdir() if f.is_file() and not f.name.startswith("."))
    if not skills:
        await update.message.reply_text("Keine Skills installiert.")
        return
    lines = "\n".join(f"  `{s}`" for s in skills)
    await update.message.reply_text(
        f"*Installierte Skills ({len(skills)}):*\n{lines}",
        parse_mode=ParseMode.MARKDOWN,
    )


# ── Permission-Button Handler ─────────────────────────────────────────────────

async def handle_permission_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Verarbeitet Permission-Button Clicks."""
    query = update.callback_query
    if not query or not query.data:
        return
    if update.effective_user and update.effective_user.id != ALLOWED_USER_ID:
        await query.answer("Nicht autorisiert.")
        return

    try:
        await query.answer()
    except Exception:
        pass  # Query kann veraltet sein — trotzdem resolve versuchen

    parts = query.data.split(":", 2)
    if len(parts) != 3 or parts[0] != "perm":
        return

    action = parts[1]      # "allow" oder "block"
    request_id = parts[2]  # "perm_N"

    decision = "allow" if action == "allow" else "block"
    resolved = perm_server.resolve(request_id, decision)

    try:
        if resolved:
            emoji = "✅ Erlaubt" if decision == "allow" else "❌ Blockiert"
            await query.edit_message_text(emoji)
        else:
            await query.edit_message_text("⏱ Bereits durch Timeout beantwortet")
    except Exception:
        pass  # Message kann bereits editiert sein


# ── Nachrichten-Handler (→ Claude) ───────────────────────────────────────────

@authorized_only
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if runner.is_busy():
        await update.message.reply_text("⏳ Claude arbeitet noch. Mit /stop abbrechen.")
        return

    text = update.message.text
    if len(text) > MAX_MESSAGE_LEN:
        await update.message.reply_text(f"Nachricht zu lang ({len(text)}/{MAX_MESSAGE_LEN} Zeichen).")
        return

    ws = ws_manager.get_active()
    session_id = ws.get("session_id")

    if ws_manager.get_plan_mode():
        text = f"Erstelle einen detaillierten Plan fuer folgende Aufgabe. Implementiere NICHTS, plane nur:\n\n{text}"

    async def send_fn(content: str):
        try:
            return await update.message.reply_text(content, parse_mode=ParseMode.HTML)
        except Exception:
            # Fallback ohne Formatierung bei Parse-Fehlern
            return await update.message.reply_text(content)

    async def edit_fn(msg, content: str):
        try:
            await msg.edit_text(content, parse_mode=ParseMode.HTML)
        except Exception:
            try:
                await msg.edit_text(content)
            except Exception:
                pass

    formatter = EventFormatter(send_fn=send_fn, edit_fn=edit_fn)

    try:
        new_session_id = await runner.run(
            prompt=text,
            directory=ws["directory"],
            session_id=session_id,
            on_event=formatter.handle_event,
            model=ws_manager.get_model(),
        )
        await formatter.finalize()

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
        await update.message.reply_text("Ein Fehler ist aufgetreten. Details im Log.")


# ── Entry Point ───────────────────────────────────────────────────────────────

def main():
    global _bot_instance

    app = Application.builder().token(TOKEN).build()
    _bot_instance = app.bot

    # Permission-Server Callback setzen
    perm_server._on_permission_request = on_permission_request

    # Commands
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("start", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("ws", cmd_ws))
    app.add_handler(CommandHandler("model", cmd_model))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(CommandHandler("compact", cmd_compact))
    app.add_handler(CommandHandler("plan", cmd_plan))
    app.add_handler(CommandHandler("rename", cmd_rename))
    app.add_handler(CommandHandler("usage", cmd_usage))
    app.add_handler(CommandHandler("skills", cmd_skills))

    # Permission-Buttons (VOR dem Message Handler!)
    app.add_handler(CallbackQueryHandler(handle_permission_callback))

    # Messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Permission-Server lifecycle
    async def post_init(application):
        await perm_server.start()

    async def post_shutdown(application):
        await perm_server.stop()

    app.post_init = post_init
    app.post_shutdown = post_shutdown

    logger.info("Bot gestartet. Workspace: %s", ws_manager.get_active_name())
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
