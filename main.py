"""
Telegram Bridge & Middleware System
====================================
Main Bot: @wahm_vip6bot
UserBot: Telethon (personal account)
Target Bot: @wahmnamperbot

Architecture:
  User → Main Bot → UserBot → @wahmnamperbot → UserBot (parse) → Main Bot → User

Features:
  - One free lookup attempt per user.
  - Subsequent attempts require 250 Telegram Stars.
  - UserBot automatically clicks 'Telegram' button from @wahmnamperbot options.
"""

import os
import re
import asyncio
import logging
import json
from collections import deque

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telegram import Update, LabeledPrice, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, PreCheckoutQueryHandler
from telegram.constants import ParseMode

# ─────────────────────────────────────────────
#  Logging
# ─────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
#  Configuration  (set these in Render → Environment)
# ─────────────────────────────────────────────
BOT_TOKEN      = os.environ.get("BOT_TOKEN",      "8622460568:AAHKMm5AoPtTMH8pmp-Cz5alCzuOLjmvuig")
API_ID         = int(os.environ.get("API_ID",     "0"))
API_HASH       = os.environ.get("API_HASH",       "")
SESSION_STRING = os.environ.get("SESSION_STRING", "")
TARGET_BOT     = "@kernel70bcc3a_bot"

# Payment configuration
PAYMENT_AMOUNT_STARS = 250 # 250 Telegram Stars
USER_DATA_FILE = "user_data.json"

# ─────────────────────────────────────────────
#  Shared State (thread-safe via asyncio)
# ─────────────────────────────────────────────
# Queue of (chat_id, username_query) tuples waiting for a reply from the target bot
request_queue: deque = deque()

# Dictionary to store pending payment requests: {user_id: username_query}
# This is needed because pre_checkout_query and successful_payment handlers don't directly get the original message context.
pending_payments = {}

# ─────────────────────────────────────────────
#  User Data Management (for free attempts)
# ─────────────────────────────────────────────
def load_user_data():
    if os.path.exists(USER_DATA_FILE):
        with open(USER_DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_user_data(data):
    with open(USER_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# ─────────────────────────────────────────────
#  Telethon Client
# ─────────────────────────────────────────────
if SESSION_STRING:
    userbot = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
else:
    # Fallback: file-based session (for local testing only)
    userbot = TelegramClient("userbot_session", API_ID, API_HASH)

# ─────────────────────────────────────────────
#  Regex Parsing
# ─────────────────────────────────────────────
def parse_response(raw: str) -> dict:
    """
    Extracts Name, Username, Phone, and ID from the raw reply of @wahmnamperbot.
    This version is more robust to variations in the history line format.
    """
    result = {
        "name":     "غير متوفر",
        "username": "غير متوفر",
        "phone":    "غير متوفر",
        "id":       "غير متوفر",
    }

    # ── Telegram ID ──────────────────────────────────────────────────────────
    m = re.search(r"ID[:\s]+(\d{5,})", raw, re.IGNORECASE)
    if m:
        result["id"] = m.group(1)

    # ── Phone Number ─────────────────────────────────────────────────────────
    m = re.search(r"Телефон[:\s]+(\d+)", raw, re.IGNORECASE)
    if m:
        result["phone"] = m.group(1)

    # ── Username & Name from history lines (more flexible) ───────────────────
    # Example: 31.05.2026 → @llUUU9, هيسوكا, 6907582823
    # Example: 31.05.2026 → @llUUU9 هيسوكا 6907582823 (if no commas)
    history_line_match = re.search(r"\d{2}\.\d{2}\.\d{4}\s*[→>]\s*(.+)", raw)
    if history_line_match:
        content = history_line_match.group(1).strip()
        
        # Try to find username first
        username_match = re.search(r"(@\w+)", content)
        if username_match:
            result["username"] = username_match.group(1)
            # Remove username from content to parse name
            content = content.replace(username_match.group(0), "").strip()
        
        # Try to find name (usually before ID, after username if present)
        # This regex tries to capture text that looks like a name, avoiding numbers at the end
        name_match = re.search(r"([\p{L}\s]+)(?:,\s*\d+)?$", content, re.UNICODE)
        if name_match:
            result["name"] = name_match.group(1).strip().replace(",", "")
        elif not result["name"] and content: # Fallback if name not found by previous regex
            # Simple fallback: take remaining content as name if it's not just numbers
            if not re.fullmatch(r"\d+", content.replace(",", "").strip()):
                result["name"] = content.replace(",", "").strip()

    # ── Fallback: standalone @username anywhere in text ──────────────────────
    if result["username"] == "غير متوفر":
        m = re.search(r"(@\w{3,})", raw)
        if m:
            result["username"] = m.group(1)

    return result


def format_result(data: dict) -> str:
    """Returns the clean Arabic-formatted reply."""
    # Escape special characters for MarkdownV2
    def escape_markdown_v2(text):
        return re.sub(r"([_*\[\]()~`>#+\-=|{}.!])", r"\\\1", str(text))

    return (
        f"الاسم: *{escape_markdown_v2(data["name"])}*\n"
        f"اليوزر: *{escape_markdown_v2(data["username"])}*\n"
        f"الرقم: *{escape_markdown_v2(data["phone"])}*\n"
        f"الايدي: *{escape_markdown_v2(data["id"])}*"
    )

# ─────────────────────────────────────────────
#  UserBot — listen to @wahmnamperbot replies
# ─────────────────────────────────────────────
@userbot.on(events.NewMessage(chats=TARGET_BOT))
async def on_target_bot_reply(event):
    """
    Fires whenever @wahmnamperbot sends a message to our UserBot.
    It checks for inline buttons, clicks 'Telegram' if found, otherwise parses the message.
    """
    raw_text = event.message.text or ""
    logger.info("Received message from %s:\n%s", TARGET_BOT, raw_text)

    # Check for inline keyboard buttons
    if event.buttons:
        for row in event.buttons:
            for button in row:
                if button.text == "Telegram":
                    logger.info("Clicking 'Telegram' button for message ID %s", event.id)
                    await event.click(button=button)
                    return # Exit, as we expect another message with the actual data
        logger.warning("No 'Telegram' button found in message ID %s, ignoring buttons.", event.id)

    # If no buttons, or 'Telegram' button not found/clicked, proceed to parse the message
    if not request_queue:
        logger.warning("Got a reply but no pending requests in queue — ignoring.")
        return

    chat_id = request_queue.popleft()

    parsed  = parse_response(raw_text)
    reply   = format_result(parsed)

    # Send the formatted result back to the user through the Main Bot REST API
    import aiohttp
    url     = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": reply, "parse_mode": ParseMode.MARKDOWN_V2}

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            if resp.status != 200:
                body = await resp.text()
                logger.error("Failed to send reply to user %s: %s", chat_id, body)
            else:
                logger.info("Reply sent to user %s", chat_id)

# ─────────────────────────────────────────────
#  Main Bot — handle incoming user messages
# ─────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 أهلاً بك!\n\n"
        "أرسل لي معرف تيليغرام (يوزر) تريد البحث عنه.\n"
        "مثال: @username\n\n"
        "لديك محاولة مجانية واحدة. بعد ذلك، ستكون تكلفة البحث 250 نجمة تيليغرام ⭐️."
    )

async def handle_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text    = (update.message.text or "").strip()
    chat_id = update.message.chat_id
    user_id = update.effective_user.id

    if not text.startswith("@"):
        await update.message.reply_text("⚠️ يرجى إرسال معرف صحيح يبدأ بـ @\nمثال: @username")
        return

    user_data = load_user_data()

    if str(user_id) not in user_data or not user_data[str(user_id)].get("free_attempt_used", False):
        # First free attempt
        user_data.setdefault(str(user_id), {})["free_attempt_used"] = True
        user_data[str(user_id)].setdefault("paid_attempts", 0)
        save_user_data(user_data)
        await update.message.reply_text("🔍 جاري البحث (محاولة مجانية)، يرجى الانتظار...")
        
        # Enqueue the request and forward
        request_queue.append(chat_id)
        try:
            await userbot.send_message(TARGET_BOT, text)
            logger.info("Forwarded query \'%s\' to %s on behalf of chat_id=%s (free attempt)", text, TARGET_BOT, chat_id)
        except Exception as exc:
            request_queue.remove(chat_id)  # rollback
            logger.error("Failed to send message to target bot: %s", exc)
            await update.message.reply_text("❌ حدث خطأ أثناء إرسال الطلب. يرجى المحاولة لاحقاً.")
        return
    else:
        # User has used free attempt, require payment
        title = "بحث عن يوزر تيليغرام"
        description = f"للبحث عن يوزر آخر، يرجى دفع {PAYMENT_AMOUNT_STARS} نجمة تيليغرام."
        payload = f"lookup_{user_id}_{text}" # Unique payload to identify the request
        currency = "XTR"
        prices = [LabeledPrice("بحث عن يوزر", PAYMENT_AMOUNT_STARS)] # Stars are integer, not cents

        # Store the pending request for payment confirmation
        pending_payments[user_id] = text

        await update.message.reply_invoice(
            title=title,
            description=description,
            payload=payload,
            currency=currency,
            prices=prices,
            provider_token="", # Telegram Stars don\'t require a provider token
            need_name=False,
            need_phone_number=False,
            need_email=False,
            need_shipping_address=False,
            send_email_to_provider=False,
            send_phone_number_to_provider=False,
            is_flexible=False,
            disable_notification=False,
            protect_content=False,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ادفع 250 ⭐️", pay=True)]])
        )
        logger.info("Requested payment from user %s for query \'%s\'", user_id, text)

async def pre_checkout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles pre-checkout queries from Telegram Stars.
    """
    query = update.pre_checkout_query
    if query.invoice_payload.startswith("lookup_"):
        # All good, confirm the order
        await query.answer(ok=True)
        logger.info("Pre-checkout query answered OK for user %s", query.from_user.id)
    else:
        # Something went wrong, refuse payment
        await query.answer(ok=False, error_message="حدث خطأ في معالجة طلبك.")
        logger.warning("Pre-checkout query answered with error for user %s", query.from_user.id)

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles successful payment updates from Telegram Stars.
    """
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    successful_payment = update.message.successful_payment

    if successful_payment.invoice_payload.startswith("lookup_"):
        # Extract original username query from payload or pending_payments
        username_query = pending_payments.pop(user_id, None)
        if not username_query:
            # Fallback if pending_payments somehow lost the data
            # Payload format: lookup_{user_id}_{username_query}
            parts = successful_payment.invoice_payload.split("_", 2)
            if len(parts) == 3:
                username_query = parts[2]
            else:
                logger.error("Could not extract username_query from payload: %s", successful_payment.invoice_payload)
                await update.message.reply_text("❌ حدث خطأ داخلي بعد الدفع. يرجى التواصل مع الدعم.")
                return

        user_data = load_user_data()
        user_data.setdefault(str(user_id), {"free_attempt_used": True, "paid_attempts": 0})["paid_attempts"] += 1
        save_user_data(user_data)

        await update.message.reply_text("✅ تم الدفع بنجاح! جاري البحث، يرجى الانتظار...")
        
        # Enqueue the request and forward
        request_queue.append(chat_id)
        try:
            await userbot.send_message(TARGET_BOT, username_query)
            logger.info("Forwarded query \'%s\' to %s on behalf of chat_id=%s (paid attempt)", username_query, TARGET_BOT, chat_id)
        except Exception as exc:
            request_queue.remove(chat_id)  # rollback
            logger.error("Failed to send message to target bot after payment: %s", exc)
            await update.message.reply_text("❌ حدث خطأ أثناء إرسال الطلب بعد الدفع. يرجى المحاولة لاحقاً.")
    else:
        await update.message.reply_text("❌ تم الدفع ولكن حدث خطأ في معالجة طلبك. يرجى التواصل مع الدعم.")

# ─────────────────────────────────────────────
#  Entry Point
# ─────────────────────────────────────────────
async def main():
    # ── Start UserBot ────────────────────────────────────────────────────────
    logger.info("Connecting UserBot...")
    await userbot.start()
    me = await userbot.get_me()
    logger.info("UserBot connected as: %s (id=%s)", me.username, me.id)

    # ── Build Main Bot ───────────────────────────────────────────────────────
    logger.info("Starting Main Bot...")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_username))
    app.add_handler(PreCheckoutQueryHandler(pre_checkout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    logger.info("Main Bot is polling for updates.")

    # ── Keep alive ───────────────────────────────────────────────────────────
    try:
        while True:
            await asyncio.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down...")
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        await userbot.disconnect()


if __name__ == "__main__":
    # Ensure user_data.json exists on startup
    if not os.path.exists(USER_DATA_FILE):
        save_user_data({})
    asyncio.run(main())
