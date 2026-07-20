"""
generate_session.py
====================
Run this script ONCE on your local machine to generate a Telethon StringSession.
The output string must be stored in the SESSION_STRING environment variable on Render.

Requirements:
    pip install telethon

Usage:
    python generate_session.py
"""

from telethon.sync import TelegramClient
from telethon.sessions import StringSession

print("=" * 60)
print("  Telethon Session Generator")
print("  Get your API_ID and API_HASH from: https://my.telegram.org")
print("=" * 60)

API_ID   = int(input("\nأدخل API_ID الخاص بك: ").strip())
API_HASH = input("أدخل API_HASH الخاص بك: ").strip()

print("\nجاري تسجيل الدخول إلى حسابك على تيليغرام...")
print("ستصلك رسالة على تيليغرام برمز التحقق.\n")

with TelegramClient(StringSession(), API_ID, API_HASH) as client:
    session_string = client.session.save()

print("\n" + "=" * 60)
print("✅ تم توليد الجلسة بنجاح!")
print("انسخ النص التالي بالكامل وضعه في متغير SESSION_STRING على Render:")
print("=" * 60 + "\n")
print(session_string)
print("\n" + "=" * 60)
print("⚠️  تحذير: لا تشارك هذا النص مع أي أحد — فهو يمنح وصولاً كاملاً لحسابك.")
print("=" * 60)
