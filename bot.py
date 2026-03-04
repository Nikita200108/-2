import os
import ccxt
import pandas as pd
import asyncio
import sqlite3
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- КОНФИГУРАЦИЯ ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
TOP_COINS = [
    'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT',
    'ADA/USDT', 'AVAX/USDT', 'DOT/USDT', 'DOGE/USDT', 'LINK/USDT',
    'MATIC/USDT', 'NEAR/USDT', 'LTC/USDT', 'UNI/USDT', 'APT/USDT'
]

# Хранилище для рассылки и состояний (чтобы не спамить)
active_users = set()
last_alerts = {} # Формат: { (user_id, symbol, level_price): 'pre_alert' или 'entry_alert' }

# --- ПОИСК УРОВНЕЙ ---
def find_levels(df):
    levels = []
    for i in range(3, len(df) - 3):
        if df['high'][i] == df['high'][i-3:i+4].max():
            levels.append({'price': df['high'][i], 'type': 'Resistance'})
        elif df['low'][i] == df['low'][i-3:i+4].min():
            levels.append({'price': df['low'][i], 'type': 'Support'})
    return levels

# --- МОНИТОРИНГ ---
async def monitor_market(context: ContextTypes.DEFAULT_TYPE):
    ex = ccxt.binance({'enableRateLimit': True})
    print("Глобальный мониторинг уровней запущен...")
    
    while True:
        for symbol in TOP_COINS:
            try:
                bars = ex.fetch_ohlcv(symbol, timeframe='15m', limit=100)
                df = pd.DataFrame(bars, columns=['time', 'open', 'high', 'low', 'close', 'vol'])
                current_price = df['close'].iloc[-1]
                levels = find_levels(df)
                
                for lvl in levels:
                    level_price = lvl['price']
                    diff = abs(current_price - level_price) / current_price
                    alert_key = (symbol, level_price)

                    # 1. ЗОНА ВХОДА (0.3%)
                    if diff <= 0.003:
                        if last_alerts.get(alert_key) != 'entry':
                            side = "LONG (Отскок)" if current_price > level_price else "SHORT (Отскок)"
                            tp = current_price * 1.02 if "LONG" in side else current_price * 0.98
                            sl = level_price * 0.994 if "LONG" in side else level_price * 1.006
                            
                            msg = (f"🔥 **СИГНАЛ НА ВХОД: {symbol}**\n"
                                   f"Расстояние: `{diff*100:.2f}%` (КРИТИЧЕСКОЕ)\n"
                                   f"Уровень: `{level_price}`\n"
                                   f"Цена сейчас: `{current_price}`\n\n"
                                   f"✅ **Рекомендация:** {side}\n"
                                   f"🎯 TP: `{tp:.4f}`\n"
                                   f"🛑 SL: `{sl:.4f}`\n\n"
                                   f"⚠️ *Следи за пробоем! Если свеча закроется за уровнем — сценарий меняется.*")
                            
                            await broadcast(context, msg)
                            last_alerts[alert_key] = 'entry'

                    # 2. ЗОНА ВНИМАНИЯ (1.0%)
                    elif diff <= 0.01:
                        if alert_key not in last_alerts:
                            msg = (f"👀 **ВНИМАНИЕ: {symbol} подходит к уровню**\n"
                                   f"До уровня: `{diff*100:.2f}%`\n"
                                   f"Тип уровня: `{lvl['type']}`\n"
                                   f"Цена уровня: `{level_price}`\n\n"
                                   f"⏳ Готовь терминал. При достижении 0.3% пришлю точку входа.")
                            
                            await broadcast(context, msg)
                            last_alerts[alert_key] = 'pre'
                    
                    # Сброс состояния, если цена ушла далеко от уровня (чтобы снова сработал алерт)
                    elif diff > 0.02:
                        last_alerts.pop(alert_key, None)

                await asyncio.sleep(1) # Пауза между монетами
                
            except Exception as e:
                print(f"Ошибка {symbol}: {e}")
        
        await asyncio.sleep(10) # Пауза перед новым кругом по ТОП-15

async def broadcast(context, text):
    for user_id in active_users:
        try:
            await context.bot.send_message(chat_id=user_id, text=text, parse_mode='Markdown')
        except: pass

# --- КОМАНДЫ ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    active_users.add(update.effective_user.id)
    await update.message.reply_text("🚀 Радар ТОП-15 запущен!\n\nЯ пришлю:\n1. Уведомление на **1%** (подготовка)\n2. Сигнал на **0.3%** (вход)")

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.job_queue.run_once(monitor_market, when=0)
    app.add_handler(CommandHandler("start", start))
    print("Бот в работе...")
    app.run_polling()