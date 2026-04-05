#!/usr/bin/env python3
"""qBittorrent Telegram Bot

Environment variables (loaded from .env or exported):
    BOT_TOKEN         – Telegram bot token from @BotFather
    BOT_ALLOWED_USERS – Comma-separated Telegram user IDs (e.g. 508582264)

All other settings live in config.json.
"""

import asyncio
import json
import logging
import os

from dotenv import load_dotenv
from telegram import (
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    Application,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

load_dotenv()

import qb_client  # noqa: E402
import formatters  # noqa: E402

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Conversation states
# ---------------------------------------------------------------------------
CATEGORY, TORRENT_TYPE, TORRENT_INPUT = range(3)

# ---------------------------------------------------------------------------
# Persistent menu keyboard
# ---------------------------------------------------------------------------
PERSISTENT_KB = ReplyKeyboardMarkup(
    [
        [KeyboardButton("/add"), KeyboardButton("/addpaused"), KeyboardButton("/list")],
        [KeyboardButton("/down"), KeyboardButton("/up"), KeyboardButton("/paused")],
        [KeyboardButton("/help")],
    ],
    resize_keyboard=True,
    is_persistent=True,
)

# States that mean "download finished" (transitioning here triggers notification)
DONE_STATES = {
    "uploading", "pausedUP", "stoppedUP", "queuedUP", "stalledUP",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _qb(ctx):
    """Return the shared QBClient instance."""
    return ctx.bot_data["qb"]


def _is_authorized(uid, allowed):
    return uid in allowed


# ---------------------------------------------------------------------------
# Background notification poller (defined before post_init which calls it)
# ---------------------------------------------------------------------------
async def _notify_all(app, text):
    for uid in app.bot_data.get("allowed_users", set()):
        try:
            await app.bot.send_message(chat_id=uid, text=text, parse_mode="HTML")
        except Exception as e:
            logger.warning("Notification to %s failed: %s", uid, e)


async def notification_poller(app):
    """Periodically poll qBittorrent and notify on add / completion."""
    cfg = _qb(app).config
    interval = max(10, cfg.get("notification_interval", 30))
    notify_add = cfg.get("notify_on_add", True)
    notify_done = cfg.get("notify_on_complete", True)

    if not notify_add and not notify_done:
        logger.info("Notifications disabled – poller idle")
        return

    logger.info("Notification poller running every %ds (add=%s, done=%s)",
                interval, notify_add, notify_done)

    # known_hashes = plain set of hashes we've seen
    known_hashes = app.bot_data.get("known_hashes", set())
    # known_states = {hash: state} for completion detection
    known_states = app.bot_data.get("known_states", {})

    while True:
        try:
            await asyncio.sleep(interval)
            torrents = await _qb(app).list_torrents()
            current_hashes = {t.hash for t in torrents}
            current_states = {t.hash: t.state for t in torrents}

            for t in torrents:
                h = t.hash
                # --- new torrent ---
                if notify_add and h not in known_hashes:
                    await _notify_all(app,
                        f"✅ <b>Torrent added</b>\n<code>{t.name}</code>")

                # --- torrent completed ---
                elif notify_done:
                    old_state = known_states.get(h)
                    if old_state and old_state != t.state:
                        if t.state in DONE_STATES:
                            sz = t.size
                            if sz >= 1_073_741_824:
                                sz_str = f"{sz / 1_073_741_824:.1f} GB"
                            elif sz >= 1_048_576:
                                sz_str = f"{sz / 1_048_576:.1f} MB"
                            else:
                                sz_str = f"{sz / 1024:.1f} KB"
                            await _notify_all(app,
                                f"🎉 <b>Torrent complete</b>\n<code>{t.name}</code>\n"
                                f"Size: {sz_str}  |  Ratio: {t.ratio:.2f}")

            known_hashes = current_hashes
            known_states = current_states
            app.bot_data["known_hashes"] = known_hashes
            app.bot_data["known_states"] = known_states

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Notification poller error: %s", e)
            await asyncio.sleep(interval)


# ---------------------------------------------------------------------------
# post_init  (starts notifier + seeds tracker)
# ---------------------------------------------------------------------------
async def post_init(app):
    """Send welcome message, seed known torrents, start notification poller."""
    for uid in app.bot_data.get("allowed_users", set()):
        try:
            await app.bot.send_message(
                chat_id=uid,
                text="☠️ qbittorrent bot is online\\. Send /help to get started\\.",
                parse_mode="MarkdownV2",
                reply_markup=PERSISTENT_KB,
            )
            logger.info("Sent welcome to user %s", uid)
        except Exception as e:
            logger.warning("Could not message user %s: %s", uid, e)

    # Seed known torrents so we don't spam on startup
    try:
        torrents = await _qb(app).list_torrents()
        app.bot_data["known_hashes"] = {t.hash for t in torrents}
        app.bot_data["known_states"] = {t.hash: t.state for t in torrents}
        logger.info("Tracker seeded with %d torrents", len(torrents))
    except Exception as e:
        app.bot_data["known_hashes"] = set()
        app.bot_data["known_states"] = {}
        logger.warning("Could not seed tracker: %s", e)

    # Launch background poller
    asyncio.create_task(notification_poller(app))


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
def load_config():
    defaults = {
        "qb_url": "http://localhost:8080",
        "qb_username": "admin",
        "qb_password": "adminadmin",
        "notify_on_add": True,
        "notify_on_complete": True,
        "torrent_list_limit": 10,
        "torrent_format": "detailed",
        "categories": [{"name": "Default", "save_path": ""}],
    }
    cfg_path = os.environ.get("BOT_CONFIG", "config.json")
    if os.path.exists(cfg_path):
        with open(cfg_path) as f:
            defaults.update(json.load(f))
    return defaults


# ---------------------------------------------------------------------------
# /help
# ---------------------------------------------------------------------------
async def cmd_help(update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not _is_authorized(str(update.effective_user.id), context.bot_data["allowed_users"]):
        return
    text = (
        "*Available Commands:*\n\n"
        "/add \\- Add a new torrent\n"
        "/addpaused \\- Add a new torrent paused\n"
        "/list \\- List all torrents\n"
        "/down \\- List downloading torrents\n"
        "/up \\- List seeding torrents\n"
        "/paused \\- List paused torrents\n"
        "/cancel \\- Cancel the current operation\n"
        "/help \\- Show this help\n\n"
        "You can also send a magnet link or \\.torrent file directly\\."
    )
    try:
        await update.message.reply_text(text, parse_mode="MarkdownV2")
    except Exception as e:
        logger.error("Help message failed: %s", e)
        await update.message.reply_text(text.replace("\\", ""))


# ---------------------------------------------------------------------------
# List commands
# ---------------------------------------------------------------------------
async def _send_torrents(update, context, filter_states, label):
    if not update.message:
        return
    if not _is_authorized(str(update.effective_user.id), context.bot_data["allowed_users"]):
        return
    try:
        torrents = await _qb(context).list_torrents(state_filter=filter_states)
    except Exception as e:
        await update.message.reply_text(f"qBittorrent error: {e}")
        return
    cfg = _qb(context).config
    limit = cfg.get("torrent_list_limit", 10)
    fmt = cfg.get("torrent_format", "detailed")
    text = formatters.format_torrent_list(torrents, limit=limit, fmt=fmt)
    for chunk in formatters.chunk_text(text):
        try:
            await update.message.reply_text(chunk)
        except Exception as e:
            logger.error("Failed to send chunk: %s", e)


async def cmd_list(update, context: ContextTypes.DEFAULT_TYPE):
    await _send_torrents(update, context, None, "All Torrents")


async def cmd_down(update, context: ContextTypes.DEFAULT_TYPE):
    await _send_torrents(update, context, {"downloading", "forcedDL"}, "Downloading")


async def cmd_up(update, context: ContextTypes.DEFAULT_TYPE):
    await _send_torrents(update, context, {"uploading", "forcedUP"}, "Seeding")


async def cmd_paused(update, context: ContextTypes.DEFAULT_TYPE):
    await _send_torrents(update, context, {"pausedDL", "pausedUP"}, "Paused")


# ---------------------------------------------------------------------------
# /add conversation
# ---------------------------------------------------------------------------
async def add_start(update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not _is_authorized(str(update.effective_user.id), context.bot_data["allowed_users"]):
        return ConversationHandler.END
    context.user_data["paused"] = False
    return await _show_categories(update, context)


async def add_paused_start(update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not _is_authorized(str(update.effective_user.id), context.bot_data["allowed_users"]):
        return ConversationHandler.END
    context.user_data["paused"] = True
    return await _show_categories(update, context)


async def _show_categories(update, context):
    cats = _qb(context).config.get("categories", [])
    kb = [[KeyboardButton(c["name"])] for c in cats] if cats else [[KeyboardButton("Default")]]
    try:
        await update.message.reply_text(
            "Choose a save location:",
            reply_markup=ReplyKeyboardMarkup(kb, one_time_keyboard=True, resize_keyboard=True),
        )
    except Exception as e:
        logger.error("Category selection failed: %s", e)
        await update.message.reply_text("Something went wrong\\. Try again or send /cancel\\.", parse_mode="MarkdownV2")
        return ConversationHandler.END
    return CATEGORY


async def category_choice(update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    cfg = _qb(context).config
    save_path = cat_name = None
    for c in cfg.get("categories", []):
        if c["name"] == text:
            save_path = c["save_path"]
            cat_name = c["name"]
            break
    context.user_data["save_path"] = save_path or None
    context.user_data["category"] = cat_name
    try:
        await update.message.reply_text(
            "Magnet / URL   or   .torrent file?",
            reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton("Magnet/URL"), KeyboardButton(".torrent File")]],
                one_time_keyboard=True, resize_keyboard=True,
            ),
        )
    except Exception as e:
        logger.error("Type prompt failed: %s", e)
    return TORRENT_TYPE


async def torrent_type_choice(update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.startswith("Magnet"):
        context.user_data["input_type"] = "url"
        prompt = "Paste a magnet link or HTTP(s) URL to a .torrent file."
    else:
        context.user_data["input_type"] = "file"
        prompt = "Send the .torrent file as a document."
    try:
        await update.message.reply_text(prompt, reply_markup=ReplyKeyboardRemove())
    except Exception as e:
        logger.error("Input prompt failed: %s", e)
    return TORRENT_INPUT


async def torrent_input_handle(update, context: ContextTypes.DEFAULT_TYPE):
    itype = context.user_data.get("input_type")
    sp  = context.user_data.get("save_path")
    paused = context.user_data.get("paused")
    cat = context.user_data.get("category")
    qb  = _qb(context)

    if itype == "url":
        source = update.message.text.strip()
        ok, msg = await qb.add_torrent_url(source, save_path=sp, paused=paused, category=cat)
    elif itype == "file":
        doc = update.message.document
        if not doc or not doc.file_name.lower().endswith(".torrent"):
            await update.message.reply_text("That doesn't look like a .torrent file\\. Try again or /cancel\\.", parse_mode="MarkdownV2")
            return TORRENT_INPUT
        try:
            file_obj = await context.bot.get_file(doc.file_id)
            content = await file_obj.download_as_bytearray()
        except Exception as e:
            await update.message.reply_text(f"Failed to download file: {e}")
            return ConversationHandler.END
        ok, msg = await qb.add_torrent_file(content, save_path=sp, paused=paused, category=cat)
    else:
        await update.message.reply_text("Internal error – try again or send /cancel\\.", parse_mode="MarkdownV2")
        return ConversationHandler.END

    emoji = "✅" if ok else "❌"
    await update.message.reply_text(f"{emoji} {msg}")
    return ConversationHandler.END


async def cancel_convo(update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.reply_text("Operation cancelled\\.", reply_markup=ReplyKeyboardRemove(), parse_mode="MarkdownV2")
    except Exception:
        pass
    context.user_data.clear()
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Direct magnet / .torrent (outside conversations)
# ---------------------------------------------------------------------------
def _in_conversation(user_data):
    return "input_type" in user_data or "paused" in user_data


async def on_magnet_text(update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if _in_conversation(context.user_data):
        return
    if not _is_authorized(str(update.effective_user.id), context.bot_data["allowed_users"]):
        return
    text = update.message.text.strip()
    qb = _qb(context)
    ok, msg = await qb.add_torrent_url(text)
    await update.message.reply_text(f"{'✅' if ok else '❌'} {msg}")


async def on_torrent_doc(update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if _in_conversation(context.user_data):
        return
    if not _is_authorized(str(update.effective_user.id), context.bot_data["allowed_users"]):
        return
    doc = update.message.document
    if not doc or not doc.file_name.lower().endswith(".torrent"):
        return
    try:
        file_obj = await context.bot.get_file(doc.file_id)
        content = await file_obj.download_as_bytearray()
    except Exception as e:
        await update.message.reply_text(f"Failed to download file: {e}")
        return
    qb = _qb(context)
    ok, msg = await qb.add_torrent_file(content)
    await update.message.reply_text(f"{'✅' if ok else '❌'} {msg}")


# ---------------------------------------------------------------------------
# Build & run
# ---------------------------------------------------------------------------
def build_app():
    cfg = load_config()

    token = os.environ.get("BOT_TOKEN") or cfg.get("bot_token", "")
    if not token:
        logger.error("BOT_TOKEN not set")
        raise SystemExit(1)

    raw = os.environ.get("BOT_ALLOWED_USERS", "")
    if raw.strip():
        allowed = {x.strip() for x in raw.split(",") if x.strip()}
    else:
        allowed = {str(x) for x in cfg.get("bot_allowed_users", [])}

    qb = qb_client.QBClient(cfg)

    app = Application.builder().token(token).post_init(post_init).build()
    app.bot_data["allowed_users"] = allowed
    app.bot_data["qb"] = qb

    # Commands
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("down", cmd_down))
    app.add_handler(CommandHandler("up", cmd_up))
    app.add_handler(CommandHandler("paused", cmd_paused))

    # /add
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("add", add_start)],
        states={
            CATEGORY:      [MessageHandler(filters.TEXT & ~filters.COMMAND, category_choice)],
            TORRENT_TYPE:  [MessageHandler(filters.TEXT & ~filters.COMMAND, torrent_type_choice)],
            TORRENT_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, torrent_input_handle),
                MessageHandler(filters.Document.ALL, torrent_input_handle),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_convo)],
    ))

    # /addpaused
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("addpaused", add_paused_start)],
        states={
            CATEGORY:      [MessageHandler(filters.TEXT & ~filters.COMMAND, category_choice)],
            TORRENT_TYPE:  [MessageHandler(filters.TEXT & ~filters.COMMAND, torrent_type_choice)],
            TORRENT_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, torrent_input_handle),
                MessageHandler(filters.Document.ALL, torrent_input_handle),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_convo)],
    ))

    # Direct magnet / torrent
    app.add_handler(MessageHandler(
        filters.Regex(r"(?i)^magnet:\?") & ~filters.COMMAND, on_magnet_text,
    ))
    app.add_handler(MessageHandler(filters.Document.ALL, on_torrent_doc))

    # Error handler
    async def error_handler(update, context):
        logger.error("Update %s caused error: %s", update, context.error)
    app.add_error_handler(error_handler)

    return app


def main():
    app = build_app()
    logger.info("Starting qbittorrent telegram bot …")
    logger.info("Allowed user IDs: %s", app.bot_data["allowed_users"])
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
