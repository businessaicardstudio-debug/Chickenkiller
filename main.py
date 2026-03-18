import asyncio
import re
from pyrogram import Client, filters
from pyrogram.types import Message
from checker import process_data, refresh_proxies, scrape_keys
from config import TOKEN, ADMIN_IDS, API_ID, API_HASH
from flask import Flask
import threading

app_flask = Flask(__name__)

@app_flask.route('/')
def alive():
    return "Service active 24/7"

flask_thread = threading.Thread(target=lambda: app_flask.run(host='0.0.0.0', port=8080))
flask_thread.daemon = True
flask_thread.start()

tg_app = Client("auto_checker", api_id=API_ID, api_hash=API_HASH, bot_token=TOKEN)

async def auto_loop():
    while True:
        await refresh_proxies()
        await scrape_keys()
        await asyncio.sleep(1800)  # 30min

@tg_app.on_message(filters.private & filters.text)
async def handler(_, msg: Message):
    uid = msg.from_user.id
    if uid not in ADMIN_IDS:
        return await msg.reply("Access restricted.")
    txt = msg.text.strip()
    if re.match(r'^\d{13,19}[\|/ ]?\d{2}[\|/ ]?\d{2}[\|/ ]?\d{3,4}$', txt):
        await msg.reply("Processing...")
        result = await process_data(txt)
        await msg.reply(f"```\n{result}\n```", parse_mode="markdown")
    else:
        await msg.reply("Format: 4111111111111111|12|25|123")

async def start():
    asyncio.create_task(auto_loop())
    await tg_app.start()
    print("Auto service 24/7 online")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(start())
