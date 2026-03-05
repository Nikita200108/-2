import os
import ccxt
import pandas as pd
import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- КОНФИГУРАЦИЯ ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
TOP_COINS = [
    'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT',
    'ADA/USDT', 'AVAX/USDT', 'DOT/USDT', 'DOGE/USDT', 'LINK/USDT',
    'MATIC/USDT', 'NEAR/USDT', 'LTC/USDT', 'UNI/USDT', 'APT/USDT'
]

active_users = set()
last_alerts = {} 

# --- ФУНКЦИИ АНАЛИЗА ---
def find_strong_levels(df):
    levels = []
    # Поиск локальных максимумов и минимумов на 4H (фракталы)
    for i in range(5, len(df) - 5):
        if df['high'][i] == df['high'][i-5:i+6].max():
            levels.append({'price': df['high'][i], 'type': 'Resistance (Сопротивление)'})
        elif df['low'][i] == df['low'][i-5:i+6].min():
            levels.append({'price': df['low'][i], 'type': 'Support (Поддержка)'})
    return levels

def check_shadow_confirmation(df, side):
    """Анализ хвоста свечи для подтверждения отскока"""
    last = df.iloc[-1]
    body = abs(last['close'] - last['open'])
    if side == "LONG":
        tail = min(last['open'], last['close']) - last['low']
        return tail > body * 1.2
    else:
        tail = last['high'] - max(last['open'], last['close'])
        return tail > body * 1.2

# --- ОСНОВНОЙ ЦИКЛ МОНИТОРИНГА ---
async def monitor_market(context: ContextTypes.DEFAULT_TYPE):
    ex = ccxt.binance({'enableRateLimit': True})
    
    while True:
        for symbol in TOP_COINS:
            try:
                # Работаем с 4-часовым ТФ для точности
                bars = ex.fetch_ohlcv(symbol, timeframe='4h', limit=150)
                df = pd.DataFrame(bars, columns=['time', 'open', 'high', 'low', 'close', 'vol'])
                
                current_price = df['close'].iloc[-1]
                avg_vol = df['vol'].tail(100).mean()
                rel_vol = df['vol'].iloc[-1] / avg_vol
                levels = find_strong_levels(df)
                
                for lvl in levels:
                    level_price = lvl['price']
                    diff = abs(current_price - level_price) / current_price
                    alert_key = (symbol, level_price)

                    # --- ЭТАП 1: ВНИМАНИЕ (1.0% - 1.5%) ---
                    if 0.005 < diff <= 0.015:
                        if alert_key not in last_alerts:
                            msg = (f"👀 **ВНИМАНИЕ (4H): {symbol}**\n"
                                   f"Подходим к сильному уровню: `{level_price}`\n"
                                   f"Дистанция: `{diff*100:.2f}%`\n\n"
                                   f"⏳ Готовься. При входе в зону 0.3% пришлю точный план.")
                            await broadcast(context, msg)
                            last_alerts[alert_key] = 'pre'

                    # --- ЭТАП 2: ТОЧНЫЙ ВХОД (до 0.5%) ---
                    elif diff <= 0.005:
                        if last_alerts.get(alert_key) != 'entry':
                            side = "LONG" if current_price >= level_price else "SHORT"
                            
                            # Расчет целей
                            tp = current_price * 1.04 if side == "LONG" else current_price * 0.96
                            sl = level_price * 0.99 if side == "LONG" else level_price * 1.01
                            
                            vol_info = "🔥 ВЫСОКИЙ" if rel_vol > 1.7 else "⚪️ СРЕДНИЙ"
                            
                            msg = (f"🎯 **СИГНАЛ ВХОДА: {symbol}**\n"
                                   f"Цена у уровня: `{level_price}`\n"
                                   f"Текущая: `{current_price}`\n\n"
                                   f"📊 **Анализ объемов:** {vol_info} ({rel_vol:.2f}x)\n"
                                   f"⚔️ **Направление:** {side}\n\n"
                                   f"✅ **Вход:** `{current_price}`\n"
                                   f"🎯 **Take Profit:** `{tp:.4f}`\n"
                                   f"🛑 **Stop Loss:** `{sl:.4f}`\n\n"
                                   f"👉 *Жди закрытия свечи. Если появится длинная тень — отскок подтвержден.*")
                            
                            await broadcast(context, msg)
                            last_alerts[alert_key] = 'entry'

                    # --- ЭТАП 3: КОРРЕКТИРОВКА (ПОСТ-АНАЛИЗ СВЕЧИ) ---
                    # Если сигнал 'entry' был дан недавно, проверяем тень
                    if last_alerts.get(alert_key) == 'entry':
                        has_shadow = check_shadow_confirmation(df, "LONG" if current_price >= level_price else "SHORT")
                        if has_shadow:
                            msg = (f"🕯 **ПОДТВЕРЖДЕНИЕ ({symbol})**\n"
                                   f"На уровне `{level_price}` сформировалась тень.\n"
                                   f"💪 Уровень удерживают. Можно удерживать позицию.")
                            await broadcast(context, msg)
                            last_alerts[alert_key] = 'confirmed' # Чтобы не спамить подтверждением

                    # Сброс, если цена ушла далеко
                    elif diff > 0.03:
                        last_alerts.pop(alert_key, None)

                await asyncio.sleep(1.5)
            except Exception as e:
                print(f"Error {symbol}: {e}")
        
        await asyncio.sleep(60)

async def broadcast(context, text):
    for user_id in active_users:
        try: await context.bot.send_message(chat_id=user_id, text=text, parse_mode='Markdown')
        except: pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    active_users.add(update.effective_user.id)
    await update.message.reply_text("🚀 Бот-снайпер активен (4H/1D).\nИнформирую за 1.5% до уровня и даю сигнал на 0.5%.")

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.job_queue.run_once(monitor_market, when=0)
    app.add_handler(CommandHandler("start", start))
    app.run_polling()
