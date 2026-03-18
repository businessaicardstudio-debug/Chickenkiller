import asyncio
import re
from pyrogram import Client, filters
from pyrogram.types import Message
from checker import check_cc, refresh_proxies, scrape_sks
from config import TOKEN, ADMIN_IDS, API_ID, API_HASH

app = Client("cc_auto_killer", api_id=API_ID, api_hash=API_HASH, bot_token=TOKEN)

async def auto_tasks():
    while True:
        await refresh_proxies()
        await scrape_sks()
        await asyncio.sleep(1800)  # 30 mins SK scrape

@app.on_message(filters.private & filters.text)
async def handle_cc(_, msg: Message):
    if msg.from_user.id not in ADMIN_IDS:
        return await msg.reply("Admins only.")
    text = msg.text.strip()
    if re.match(r'^\d{13,19}[\|/ ]?\d{2}[\|/ ]?\d{2}[\|/ ]?\d{3,4}$', text):
        await msg.reply("🔄 Auto-Proxy/SK Check...")
        result = await check_cc(text)
        await msg.reply(f"```\n{result}\n```", parse_mode="markdown")
        if "LIVE" in result:
            await msg.reply(f"Proxies: {len(await refresh_proxies())} | SKs: {len(await get_sks())}")
    else:
        await msg.reply("CC format pls.")

async def main():
    asyncio.create_task(auto_tasks())  # AUTO FOREVER
    await app.start()
    print("🚀 AUTO CC KILLER 24/7 LIVE - Proxies/SKs Auto!")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())

