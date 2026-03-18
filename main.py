import asyncio
import re
from pyrogram import Client, filters
from pyrogram.types import Message
from checker import process_card, update_proxy_list, harvest_authkeys
from config import TOKEN, ADMIN_IDS, API_ID, API_HASH

app = Client("card_processor", api_id=API_ID, api_hash=API_HASH, bot_token=TOKEN)

async def background_updates():
    while True:
        await update_proxy_list()
        await harvest_authkeys()
        await asyncio.sleep(1800)  # 30min

@app.on_message(filters.private & filters.text)
async def handle_input(_, message: Message):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        return await message.reply("Access restricted.")
    txt = message.text.strip()
    if re.match(r'^\d{13,19}[\|/ ]?\d{2}[\|/ ]?\d{2}[\|/ ]?\d{3,4}$', txt):
        await message.reply("Processing...")
        res = await process_card(txt)
        await message.reply(f"```\n{res}\n```", parse_mode="markdown")
    else:
        await message.reply("Format: 4111111111111111|12|25|123")

async def start_bot():
    asyncio.create_task(background_updates())
    await app.start()
    print("Card Processor Bot ACTIVE 24/7")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(start_bot())
