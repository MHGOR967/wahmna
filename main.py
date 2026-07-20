import os
import re
import asyncio
import logging
import json
from collections import deque
from threading import Thread

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telegram import Update, LabeledPrice, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, PreCheckoutQueryHandler
from telegram.constants import ParseMode
from flask import Flask

# Logging
logging.basicConfig(format="%(asctime)s | %(levelname)s | %(name)s | %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Config
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8622460568:AAHKMm5AoPtTMH8pmp-Cz5alCzuOLjmvuig")
API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
SESSION_STRING = os.environ.get("SESSION_STRING", "")
TARGET_BOT = "@kernel70bcc3a_bot"
PAYMENT_AMOUNT_STARS = 250
USER_DATA_FILE = "user_data.json"
FLASK_PORT = int(os.environ.get("PORT", 10000))

request_queue = deque()
pending_payments = {}

def load_user_data():
    if os.path.exists(USER_DATA_FILE):
        try:
            with open(USER_DATA_FILE, "r", encoding="utf-8") as f: return json.load(f)
        except: return {}
    return {}

def save_user_data(data):
    with open(USER_DATA_FILE, "w", encoding="utf-8") as f: json.dump(data, f, indent=4, ensure_ascii=False)

# Regex & Formatting
def parse_response(raw: str) -> dict:
    result = {"name": "غير متوفر", "username": "غير متوفر", "phone": "غير متوفر", "id": "غير متوفر"}
    id_m = re.search(r"ID[:\s]+(\d+)", raw, re.IGNORECASE)
    if id_m: result["id"] = id_m.group(1)
    phone_m = re.search(r"Телефон[:\s]+(\d+)", raw, re.IGNORECASE)
    if phone_m: result["phone"] = phone_m.group(1)
    history_line = re.search(r"\d{2}\.\d{2}\.\d{4}\s*[→>]\s*(.+)", raw)
    if history_line:
        content = history_line.group(1).strip()
        parts = [p.strip() for p in content.split(",")]
        if parts:
            if parts[0].startswith("@"):
                result["username"] = parts[0]
                if len(parts) > 1: result["name"] = parts[1]
            else: result["name"] = parts[0]
    return result

def format_result(data: dict) -> str:
    def esc(t): return re.sub(r"([_*\[\]()~`>#+\-=|{}.!])", r"\\\1", str(t))
    return f"الاسم: *{esc(data['name'])}*\nاليوزر: *{esc(data['username'])}*\nالرقم: *{esc(data['phone'])}*\nالايدي: *{esc(data['id'])}*"

# Flask
app_flask = Flask(__name__)
@app_flask.route("/")
def home(): return "Bot is Alive!", 200

# Main logic
async def run_bot():
    # Initialize Telethon inside the loop
    userbot = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    
    @userbot.on(events.NewMessage(chats=TARGET_BOT))
    async def on_reply(event):
        if event.buttons:
            for row in event.buttons:
                for btn in row:
                    if "Telegram" in btn.text:
                        await event.click(btn)
                        return
        if not request_queue: return
        chat_id = request_queue.popleft()
        parsed = parse_response(event.message.text or "")
        reply = format_result(parsed)
        import aiohttp
        async with aiohttp.ClientSession( ) as s:
            await s.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", 
                         json={"chat_id": chat_id, "text": reply, "parse_mode": "MarkdownV2"} )

    await userbot.start()
    
    # Main Bot
    app = Application.builder().token(BOT_TOKEN).build()
    
    async def start(u, c): await u.message.reply_text("أرسل اليوزر للبحث (أول مرة مجاناً ثم 250 نجمة).")
    
    async def handle(u, c):
        text = u.message.text.strip()
        if not text.startswith("@"): return await u.message.reply_text("أرسل يوزر يبدأ بـ @")
        user_id = str(u.effective_user.id)
        data = load_user_data()
        if user_id not in data:
            data[user_id] = {"free": True}
            save_user_data(data)
            request_queue.append(u.effective_chat.id)
            await userbot.send_message(TARGET_BOT, text)
            await u.message.reply_text("🔍 جاري البحث المجاني...")
        else:
            pending_payments[u.effective_user.id] = text
            await u.message.reply_invoice("بحث يوزر", "تكلفة البحث 250 نجمة", f"pay_{user_id}", "XTR", [LabeledPrice("بحث", 250)], provider_token="", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ادفع 250 ⭐️", pay=True)]]))

    async def pre(u, c): await u.pre_checkout_query.answer(ok=True)
    async def success(u, c):
        uid = u.effective_user.id
        q = pending_payments.pop(uid, None)
        if q:
            request_queue.append(u.effective_chat.id)
            await userbot.send_message(TARGET_BOT, q)
            await u.message.reply_text("✅ تم الدفع، جاري البحث...")

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    app.add_handler(PreCheckoutQueryHandler(pre))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, success))

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    
    # Keep running
    while True: await asyncio.sleep(3600)

if __name__ == "__main__":
    # Start Flask in thread
    Thread(target=lambda: app_flask.run(host="0.0.0.0", port=FLASK_PORT), daemon=True).start()
    # Start Asyncio Loop
    asyncio.run(run_bot())
