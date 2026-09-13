import json
import time
import urllib.request
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# =====================================================================
# DUMMY HTTP SERVER FOR RENDER WEB SERVICE
# =====================================================================
class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bybit CRT Bot v2.3 is Running!")

def run_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), SimpleHTTPRequestHandler)
    server.serve_forever()

# Background Thread ဖြင့် Web Server စတင်ခြင်း
Thread(target=run_dummy_server, daemon=True).start()

# =====================================================================
# CONFIGURATION SETTINGS
# =====================================================================
BOT_TOKEN = "8842544212:AAFqc5ajT9dDzZQf1iLv_4CTrWWlJ6dl3os"
CHAT_ID = "6748141311"

BYBIT_TICKERS_URL = "https://api.bybit.com/v5/market/tickers?category=linear"
BYBIT_KLINES_URL = "https://api.bybit.com/v5/market/kline"
TIMEFRAMES = ['15', '30', '60']

sent_signals = set()

# =====================================================================
# BYBIT DATA ENGINE
# =====================================================================
def get_bybit_pairs():
    try:
        req = urllib.request.Request(BYBIT_TICKERS_URL, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            
        pairs = []
        if data.get('retCode') == 0:
            for item in data['result']['list']:
                symbol = item['symbol']
                if symbol.endswith('USDT'):
                    pairs.append(symbol)
                    
        if 'XAUUSDT' not in pairs:
            pairs.append('XAUUSDT')
            
        return pairs
    except Exception:
        return ['XAUUSDT', 'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'OGUSDT']

def fetch_bybit_klines(symbol, interval, limit=10):
    url = f"{BYBIT_KLINES_URL}?category=linear&symbol={symbol}&interval={interval}&limit={limit}"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=6) as response:
            data = json.loads(response.read().decode())
            
        if data.get('retCode') != 0:
            return None

        raw_list = data['result']['list']
        raw_list.reverse()

        klines = []
        for item in raw_list:
            klines.append({
                'time': datetime.fromtimestamp(int(item[0])/1000).strftime('%H:%M'),
                'open': float(item[1]),
                'high': float(item[2]),
                'low': float(item[3]),
                'close': float(item[4])
            })
        return klines
    except Exception:
        return None

# =====================================================================
# CRT V2.3 STRATEGY ENGINE
# =====================================================================
def analyze_crt_pattern(symbol, tf):
    klines = fetch_bybit_klines(symbol, tf, limit=10)
    if not klines or len(klines) < 4:
        return None

    c1 = klines[-3]
    c2 = klines[-2]
    c3 = klines[-1]

    c1_high, c1_low = c1['high'], c1['low']
    c1_open, c1_close = c1['open'], c1['close']
    
    c2_high, c2_low = c2['high'], c2['low']
    c2_open, c2_close = c2['open'], c2['close']
    c2_body_max = max(c2_open, c2_close)
    c2_body_min = min(c2_open, c2_close)

    c3_close = c3['close']
    tf_label = "1h" if tf == '60' else f"{tf}m"

    # BULLISH CRT
    is_bullish_sweep = (c2_low < c1_low) and (c2_body_min >= c1_low)
    c1_valid_range = (c1_high - c1_low) > 0
    c2_clean_sweep = c2_close > c2_low
    is_buy_triggered = c3_close > c2_high

    if is_bullish_sweep and c2_clean_sweep and c1_valid_range and is_buy_triggered:
        entry = c3_close
        sl_buffer = 0.9990 if "XAU" in symbol else 0.9995
        sl = c2_low * sl_buffer
        tp = c1_high

        if sl < entry < tp:
            risk = entry - sl
            reward = tp - entry
            rr = round(reward / risk, 2) if risk > 0 else 0

            if rr >= 1.2:
                sig_id = f"{symbol}_{tf_label}_BUY_{c3['time']}"
                return {
                    'id': sig_id,
                    'symbol': symbol,
                    'tf': tf_label,
                    'direction': '🟢 BUY / LONG (PURE CRT V2.3)',
                    'entry': f"{entry:.4f}",
                    'sl': f"{sl:.4f}",
                    'tp': f"{tp:.4f}",
                    'rr': f"1:{rr}",
                    'time': c3['time']
                }

    # BEARISH CRT
    is_bearish_sweep = (c2_high > c1_high) and (c2_body_max <= c1_high)
    c2_clean_bear_sweep = c2_close < c2_high
    is_sell_triggered = c3_close < c2_low

    if is_bearish_sweep and c2_clean_bear_sweep and c1_valid_range and is_sell_triggered:
        entry = c3_close
        sl_buffer = 1.0010 if "XAU" in symbol else 1.0005
        sl = c2_high * sl_buffer
        tp = c1_low

        if sl > entry > tp:
            risk = sl - entry
            reward = entry - tp
            rr = round(reward / risk, 2) if risk > 0 else 0

            if rr >= 1.2:
                sig_id = f"{symbol}_{tf_label}_SELL_{c3['time']}"
                return {
                    'id': sig_id,
                    'symbol': symbol,
                    'tf': tf_label,
                    'direction': '🔴 SELL / SHORT (PURE CRT V2.3)',
                    'entry': f"{entry:.4f}",
                    'sl': f"{sl:.4f}",
                    'tp': f"{tp:.4f}",
                    'rr': f"1:{rr}",
                    'time': c3['time']
                }

    return None

def scan_all_markets():
    symbols = get_bybit_pairs()
    tasks = []
    results = []

    with ThreadPoolExecutor(max_workers=30) as executor:
        for symbol in symbols:
            for tf in TIMEFRAMES:
                tasks.append(executor.submit(analyze_crt_pattern, symbol, tf))

        for future in as_completed(tasks):
            res = future.result()
            if res:
                results.append(res)
    return results

def format_telegram_message(item):
    return (
        f"🚨 <b>PURE CRT V2.3 SIGNAL</b> 🚨\n\n"
        f"🎯 <b>Symbol:</b> #{item['symbol']} ({item['tf']})\n"
        f"⚡ <b>Signal:</b> {item['direction']}\n"
        f"💵 <b>Entry Price:</b> <code>{item['entry']}</code>\n"
        f"🛑 <b>Stop Loss:</b> <code>{item['sl']}</code>\n"
        f"🚀 <b>Target TP:</b> <code>{item['tp']}</code>\n"
        f"⚖️ <b>Risk/Reward:</b> {item['rr']}\n"
        f"⏰ <b>Candle Time:</b> {item['time']}\n"
    )

# =====================================================================
# TELEGRAM BOT & AUTOMATION JOBS
# =====================================================================
async def auto_scan_job(context: ContextTypes.DEFAULT_TYPE):
    setups = scan_all_markets()
    for item in setups:
        if item['id'] not in sent_signals:
            sent_signals.add(item['id'])
            msg = format_telegram_message(item)
            await context.bot.send_message(
                chat_id=CHAT_ID,
                text=msg,
                parse_mode='HTML'
            )

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "🤖 <b>Bybit CRT Scanner Bot v2.3 Active!</b>\n\n"
        "• Strict Filter များဖြင့် Pure CRT Signal များကို Noti ပို့ပေးပါမည်။\n"
        "• /scan ဟု ရိုက်ပြီး Manual Scan ဖတ်နိုင်ပါသည်။"
    )
    await update.message.reply_text(welcome_text, parse_mode='HTML')

async def manual_scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔎 Pure CRT v2.3 Engine ဖြင့် Scan ဖတ်နေပါသည်...")
    setups = scan_all_markets()

    if not setups:
        await update.message.reply_text("❌ လတ်တလော V2.3 Rules နှင့် ညီသော Setup မရှိသေးပါ။")
        return

    for item in setups:
        msg = format_telegram_message(item)
        await update.message.reply_text(msg, parse_mode='HTML')

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("scan", manual_scan_command))

    job_queue = app.job_queue
    job_queue.run_repeating(auto_scan_job, interval=300, first=10)

    print("🚀 Telegram Bot v2.3 is running...")
    app.run_polling()

if __name__ == "__main__":
    main()

