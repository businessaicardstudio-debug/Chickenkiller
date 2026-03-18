import asyncio
import re
import threading
from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import Message
import utils  # Renamed checker.py
from config import TOKEN, ADMIN_IDS, API_ID, API_HASH

app_flask = Flask(__name__)

@app_flask.route('/')
@app_flask.route('/status')
def status():
    return "Service active"

def run_flask():
    app_flask.run(host='0.0.0.0', port=8080)

flask_thread = threading.Thread(target=run_flask, daemon=True)
flask_thread.start()

client = Client("service", api_id=API_ID, api_hash=API_HASH, bot_token=TOKEN)

async def background_refresh():
    while True:
        await utils.refresh_sources()
        await utils.refresh_keys()
        await asyncio.sleep(1800)  # 30min

@client.on_message(filters.private & filters.text)
async def process_input(_, msg: Message):
    uid = msg.from_user.id
    if uid not in ADMIN_IDS:
        return await msg.reply("Access restricted.")
    txt = msg.text.strip()
    if re.match(r'^\d{13,19}[\|/ ]?\d{2}[\|/ ]?\d{2}[\|/ ]?\d{3,4}$', txt):
        await msg.reply("Processing...")
        result = await utils.process_data(txt)
        await msg.reply(f"```\n{result}\n```", parse_mode="markdown")
    else:
        await msg.reply("Invalid format. Use num|mm|yy|cvv")

async def start_service():
    asyncio.create_task(background_refresh())
    await client.start()
    print("Service operational 24/7")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(start_service())
