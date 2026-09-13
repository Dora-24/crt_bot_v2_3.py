import os
import time
import requests
import pandas as pd
import numpy as np

# Secrets/Environment Variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# Trading Config
PAIRS = ["XAUUSD", "EURUSD", "GBPUSD", "BTCUSD"]
TIMEFRAME = "15m"  # 15 Minute Candles

def send_telegram_message(message):
    """Send alert message to Telegram channel/chat."""
    if not BOT_TOKEN or not CHAT_ID:
        print("Error: BOT_TOKEN or CHAT_ID missing.")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Failed to send Telegram message: {e}")

def fetch_kline_data(symbol, interval="15m", limit=250):
    """Fetch OHLCV market data from Binance Public API."""
    # Convert symbol for Binance format if needed
    binance_symbol = symbol.replace("XAUUSD", "PAXGUSDT").replace("BTCUSD", "BTCUSDT")
    if not binance_symbol.endswith("USDT"):
        binance_symbol += "USDT"

    url = f"https://api.binance.com/api/v3/klines?symbol={binance_symbol}&interval={interval}&limit={limit}"
    try:
        res = requests.get(url, timeout=10)
        data = res.json()
        df = pd.DataFrame(data, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_av', 'trades', 'tb_base_av', 'tb_quote_av', 'ignore'
        ])
        df['open'] = df['open'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        df['close'] = df['close'].astype(float)
        return df
    except Exception as e:
        print(f"Error fetching data for {symbol}: {e}")
        return None

def calculate_ema(series, window=200):
    """Calculate Exponential Moving Average."""
    return series.ewm(span=window, adjust=False).mean()

def check_crt_v2_5_signals(symbol, df):
    """
    Enhanced CRT v2.5 Strategy Logic:
    1. Filter 1: C3 Body Close beyond C2 High/Low (Prevents Fake Wick Sweeps)
    2. Filter 2: EMA 200 Trend Alignment
    3. Filter 3: ATR Range Volatility Check
    """
    if df is None or len(df) < 200:
        return None

    # Calculate Indicators
    df['ema200'] = calculate_ema(df['close'], 200)
    df['range'] = df['high'] - df['low']
    df['atr'] = df['range'].rolling(14).mean()

    # Get Candles
    c2 = df.iloc[-2]
    c3 = df.iloc[-1]

    # Volatility Check: Skip small noise candles
    if c3['range'] < (c3['atr'] * 0.75):
        return None

    c3_body_top = max(c3['open'], c3['close'])
    c3_body_bottom = min(c3['open'], c3['close'])

    signal = None

    # --- BUY SIGNAL (Uptrend Only) ---
    if c3['close'] > c3['open']:  # Bullish C3
        # C3 Body Close ABOVE C2 High AND Price ABOVE EMA 200
        if c3_body_top > c2['high'] and c3['close'] > c3['ema200']:
            entry = c3['close']
            sl = min(c2['low'], c3['low'])
            risk = entry - sl
            if risk <= 0:
                return None
            tp = entry + (risk * 2.0)  # R:R = 1:2

            signal = (
                f"🚨 <b>CRT v2.5 HIGH ACCURACY SIGNAL</b> 🚨\n\n"
                f"<b>Pair:</b> {symbol}\n"
                f"<b>Type:</b> BUY 🟢\n"
                f"<b>Timeframe:</b> {TIMEFRAME}\n\n"
                f"<b>Entry:</b> {round(entry, 4)}\n"
                f"<b>SL:</b> {round(sl, 4)}\n"
                f"<b>TP (1:2):</b> {round(tp, 4)}\n\n"
                f"<i>Filter Status: EMA200 Bullish | C3 Body Breakout Valid</i>"
            )

    # --- SELL SIGNAL (Downtrend Only) ---
    elif c3['close'] < c3['open']:  # Bearish C3
        # C3 Body Close BELOW C2 Low AND Price BELOW EMA 200
        if c3_body_bottom < c2['low'] and c3['close'] < c3['ema200']:
            entry = c3['close']
            sl = max(c2['high'], c3['high'])
            risk = sl - entry
            if risk <= 0:
                return None
            tp = entry - (risk * 2.0)  # R:R = 1:2

            signal = (
                f"🚨 <b>CRT v2.5 HIGH ACCURACY SIGNAL</b> 🚨\n\n"
                f"<b>Pair:</b> {symbol}\n"
                f"<b>Type:</b> SELL 🔴\n"
                f"<b>Timeframe:</b> {TIMEFRAME}\n\n"
                f"<b>Entry:</b> {round(entry, 4)}\n"
                f"<b>SL:</b> {round(sl, 4)}\n"
                f"<b>TP (1:2):</b> {round(tp, 4)}\n\n"
                f"<i>Filter Status: EMA200 Bearish | C3 Body Breakout Valid</i>"
            )

    return signal

def main():
    print("Starting CRT v2.5 Enhanced Bot Monitor...")
    send_telegram_message("🤖 <b>CRT v2.5 Scanner Active (Fly.io)</b>\nFilters Applied: EMA200 Trend + C3 Body Close.")
    
    last_processed_time = None

    while True:
        try:
            for pair in PAIRS:
                df = fetch_kline_data(pair, interval=TIMEFRAME)
                if df is not None and not df.empty:
                    current_candle_time = df.iloc[-1]['timestamp']
                    
                    # Check for new candle formation
                    signal = check_crt_v2_5_signals(pair, df)
                    if signal:
                        send_telegram_message(signal)
                        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Signal sent for {pair}")
            
            # Wait 60 seconds before next scan loop
            time.sleep(60)

        except Exception as e:
            print(f"Error in main loop: {e}")
            time.sleep(30)

if __name__ == "__main__":
    main()
