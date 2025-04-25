import time
import requests
import hmac
import hashlib
import json
import math
from datetime import datetime
import os

# Параметры бота

API_KEY = os.getenv('API_KEY')
API_SECRET = os.getenv('API_SECRET')
SYMBOL = 'KASUSDT'
LEVERAGE = 10
TRADE_SIZE_PERCENT = 70
TIMEFRAME = '5'
BASE_URL = 'https://api.bybit.com'

# Функции для работы с Bybit

def send_signed_request(http_method, url_path, payload=None):
    if payload is None:
        payload = {}
    timestamp = str(int(time.time() * 1000))
    payload_str = json.dumps(payload) if http_method == "POST" else ""
    param_str = '' if http_method == "POST" else "&".join([f"{k}={v}" for k, v in sorted(payload.items())])
    sign = hmac.new(bytes(API_SECRET, "utf-8"), bytes(timestamp + API_KEY + param_str + payload_str, "utf-8"), hashlib.sha256).hexdigest()
    headers = {
        "X-BAPI-API-KEY": API_KEY,
        "X-BAPI-TIMESTAMP": timestamp,
        "X-BAPI-SIGN": sign,
        "Content-Type": "application/json"
    }
    if http_method == "POST":
        response = requests.post(BASE_URL + url_path, headers=headers, data=payload_str)
    else:
        response = requests.get(BASE_URL + url_path + ("?" + param_str if param_str else ""), headers=headers)
    return response.json()

def get_balance():
    res = send_signed_request("GET", "/v5/account/wallet-balance", {"accountType": "UNIFIED"})
    balance = float(res['result']['list'][0]['coin'][0]['equity'])
    return balance

def get_position():
    res = send_signed_request("GET", "/v5/position/list", {"category": "linear", "symbol": SYMBOL})
    for pos in res['result']['list']:
        if pos['size'] != '0':
            return pos
    return None

def set_leverage():
    send_signed_request("POST", "/v5/position/set-leverage", {"category": "linear", "symbol": SYMBOL, "buyLeverage": LEVERAGE, "sellLeverage": LEVERAGE})

def place_order(side, qty, stop_loss, take_profit):
    payload = {
        "category": "linear",
        "symbol": SYMBOL,
        "side": side,
        "orderType": "Market",
        "qty": qty,
        "timeInForce": "GoodTillCancel",
        "reduceOnly": False,
        "stopLoss": stop_loss,
        "takeProfit": take_profit,
    }
    send_signed_request("POST", "/v5/order/create", payload)

# Расчёт индикаторов

def ema(values, length):
    ema_vals = []
    k = 2 / (length + 1)
    for i in range(len(values)):
        if i == 0:
            ema_vals.append(values[i])
        else:
            ema_vals.append(values[i] * k + ema_vals[i-1] * (1 - k))
    return ema_vals

def sma(values, length):
    sma_vals = []
    for i in range(len(values)):
        if i < length:
            sma_vals.append(sum(values[:i+1]) / (i+1))
        else:
            sma_vals.append(sum(values[i-length+1:i+1]) / length)
    return sma_vals

def atr(highs, lows, closes, length):
    trs = []
    for i in range(1, len(highs)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        trs.append(tr)
    return sma(trs, length)

def fetch_candles():
    url = f"https://api.bybit.com/v5/market/kline?category=linear&symbol={SYMBOL}&interval={TIMEFRAME}&limit=200"
    response = requests.get(url)
    data = response.json()['result']['list']
    data.reverse()
    highs = [float(c[3]) for c in data]
    lows = [float(c[4]) for c in data]
    closes = [float(c[5]) for c in data]
    volumes = [float(c[6]) for c in data]
    opens = [float(c[1]) for c in data]
    return highs, lows, closes, volumes, opens

# Логика сигналов

def check_signals():
    highs, lows, closes, volumes, opens = fetch_candles()
    price = [(h+l+c)/3 for h, l, c in zip(highs, lows, closes)]
    esa = ema(price, 18)
    deviation = ema([abs(p - e) for p, e in zip(price, esa)], 18)
    ci = [(p - e) / (0.015 * d) if d != 0 else 0 for p, e, d in zip(price, esa, deviation)]
    wt1 = ema(ci, 21)
    wt2 = sma(wt1, 4)

    lastOB = wt1[-2] > 70
    lastOS = wt1[-2] < -40

    bearCross = wt2[-1] < wt1[-1] and lastOB and wt1[-1] > 70
    bullCross = wt1[-1] > wt2[-1] and lastOS and wt1[-1] < -40

    bearEngulf = closes[-2] > opens[-2] and closes[-1] < opens[-1] and closes[-1] <= opens[-2] and opens[-1] >= closes[-2]
    bullEngulf = closes[-2] < opens[-2] and closes[-1] > opens[-1] and closes[-1] >= opens[-2] and opens[-1] <= closes[-2]
    bearPin = (highs[-1] - max(opens[-1], closes[-1]) > 2 * abs(closes[-1] - opens[-1])) and (closes[-1] < opens[-1])
    bullPin = (min(opens[-1], closes[-1]) - lows[-1] > 2 * abs(closes[-1] - opens[-1])) and (closes[-1] > opens[-1])

    candleDown = bearEngulf or bearPin
    candleUp = bullEngulf or bullPin

    avgVol = sma(volumes, 28)[-1]
    volSpike = volumes[-1] > 1.3 * avgVol

    sellCond = bearCross
    buyCond = bullCross

    sellConfirmed = sellCond and (candleDown or (volSpike and closes[-1] < opens[-1]))
    buyConfirmed = buyCond and (candleUp or (volSpike and closes[-1] > opens[-1]))

    atr_val = atr(highs, lows, closes, 14)[-1]
    sl = atr_val * 2.5
    tp = atr_val * 2.5

    return buyConfirmed, sellConfirmed, closes[-1], sl, tp

# Основной цикл

if __name__ == "__main__":
    set_leverage()
    print("\ud83d\ude80 \u0411\u043e\u0442 \u0437\u0430\u043f\u0443\u0449\u0435\u043d!")

    while True:
        try:
            pos = get_position()
            if pos:
                print(f"\ud83d\udd04 \u041f\u043eз\u0438ция \u0443\u0436\u0435 \u043e\u0442\u043a\u0440\u044b\u0442\u0430: {pos['side']}, {pos['size']} \u043a\u043e\u043d\u0442\u0440\u0430\u043a\u0442\u043e\u0432")
            else:
                buySignal, sellSignal, close_price, sl_distance, tp_distance = check_signals()
                balance = get_balance()
                qty = round((balance * TRADE_SIZE_PERCENT / 100) * LEVERAGE / close_price, 3)
                if buySignal:
                    place_order("Buy", qty, round(close_price - sl_distance, 5), round(close_price + tp_distance, 5))
                    print(f"\u2705 \u041e\u0442\u043a\u0440\u044b\u0442 \u043b\u043e\u043d\u0433: {qty} \u043a\u043e\u043d\u0442\u0440\u0430\u043a\u0442\u043e\u0432 \u043d\u0430 \u0446\u0435\u043d\u0435 {close_price}")
                elif sellSignal:
                    place_order("Sell", qty, round(close_price + sl_distance, 5), round(close_price - tp_distance, 5))
                    print(f"\u2705 \u041e\u0442\u043a\u0440\u044b\u0442 \u0448\u043e\u0440\u0442: {qty} \u043a\u043e\u043d\u0442\u0440\u0430\u043a\u0442\u043e\u0432 \u043d\u0430 \u0446\u0435\u043d\u0435 {close_price}")
        except Exception as e:
            print(f"\u26a0\ufe0f \u041e\u0448\u0438\u0431\u043a\u0430: {e}")
        time.sleep(300)  # 5 минут
