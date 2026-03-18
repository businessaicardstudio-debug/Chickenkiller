import asyncio
import re
from pyrogram import Client, filters
from pyrogram.types import Message
from utils import validate_data, refresh_proxies, scrape_keys
from settings import TOKEN, ADMIN_IDS, API_ID, API_HASH

app = Client("validator_app", api_id=API_ID, api_hash=API_HASH, bot_token=TOKEN)

async def auto_maintenance():
    while True:
        await refresh_proxies()
        await scrape_keys()
        await asyncio.sleep(1800)  # 30min

@app.on_message(filters.private & filters.text)
async def handle_input(_, msg: Message):
    if msg.from_user.id not in ADMIN_IDS:
        return await msg.reply("Access restricted.")
    text = msg.text.strip()
    if re.match(r'^\d{13,19}[\|/ ]?\d{2}[\|/ ]?\d{2}[\|/ ]?\d{3,4}$', text):
        await msg.reply("Processing...")
        result = await validate_data(text)
        await msg.reply(f"```\n{result}\n```", parse_mode="markdown")
        if "Valid" in result:
            await msg.reply(f"Pool stats: Proxies {len(await refresh_proxies())} | Keys {len(await get_keys())}")
    else:
        await msg.reply("Send data: num|mm|yy|cvv")

async def main():
    asyncio.create_task(auto_maintenance())
    await app.start()
    print("Validator app running continuously.")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
