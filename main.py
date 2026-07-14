from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import sqlite3
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
import os
import uvicorn
import threading
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BOT_TOKEN = "8937187144:AAHWkS3gh5FZC7lwXkJpFCdKnL5KNhBXVyU"
ADMIN_CHAT_ID = 788136689
WEB_APP_URL = "https://vlad-sakik.github.io/tg-booking-app/"

# === ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ ===
def init_db():
    conn = sqlite3.connect("vlad_coaching.db")
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, first_name TEXT, last_name TEXT, phone TEXT, birthday TEXT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS reviews (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT, rating INTEGER, text TEXT, date TEXT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS bookings (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, category TEXT, service TEXT, price TEXT, date_str TEXT, time_str TEXT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS blocked_slots (id INTEGER PRIMARY KEY AUTOINCREMENT, date_str TEXT, time_str TEXT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS suggestions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, text TEXT, date TEXT)")
    conn.commit()
    conn.close()

init_db()

# === МОДЕЛИ ДАННЫХ ===
class RegisterData(BaseModel):
    user_id: int
    first_name: str
    last_name: str
    phone: str
    birthday: str

class BookingData(BaseModel):
    category: str
    service: str
    price: str
    date: str
    time: str
    raw_date: str
    user_id: int

class ReviewData(BaseModel):
    user_id: int
    rating: int
    text: str

class SuggestionData(BaseModel):
    user_id: int
    text: str

# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===
def send_telegram_message(chat_id: int, text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
    except Exception as e:
        print(f"Ошибка TG: {e}")

def get_location(category: str) -> str:
    locs = {"gym": "Gym24 на Немиге", "skating": "ТРЦ Замок", "dry-ice": "Бросковая зона на Кальварийской"}
    return locs.get(category, "Уточняйте у тренера")

# === TELEGRAM БОТ ДЛЯ ТРЕНЕРА ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет, Влад!\n\n"
        "Доступные команды:\n"
        "/bookings_today - Записи на сегодня\n"
        "/bookings_week - Записи на неделю\n"
        "/bookings_all - Все записи\n"
        "/stats - Статистика за месяц\n"
        "/block 2026-07-20 10:00 - Заблокировать слот\n"
        "/unblock 2026-07-20 10:00 - Разблокировать слот\n"
        "/help - Помощь"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 <b>Команды бота:</b>\n\n"
        "/bookings_today - Записи на сегодня\n"
        "/bookings_week - Записи на неделю (7 дней)\n"
        "/bookings_all - Все записи\n"
        "/stats - Статистика за текущий месяц\n"
        "/block YYYY-MM-DD HH:MM - Заблокировать время\n"
        "/unblock YYYY-MM-DD HH:MM - Разблокировать время\n"
        "/help - Эта справка",
        parse_mode="HTML"
    )

async def bookings_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect("vlad_coaching.db")
    cursor = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    cursor.execute("SELECT category, service, price, date_str, time_str FROM bookings WHERE date_str = ? ORDER BY time_str", (today,))
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        await update.message.reply_text(f"📅 На сегодня ({today}) записей нет")
        return
    
    text = f"📅 <b>Записи на сегодня ({today}):</b>\n\n"
    for row in rows:
        cat, service, price, date_str, time_str = row
        loc = get_location(cat)
        text += f"⏰ {time_str} - {service}\n {loc}\n💰 {price}\n\n"
    
    await update.message.reply_text(text, parse_mode="HTML")

async def bookings_week(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect("vlad_coaching.db")
    cursor = conn.cursor()
    today = datetime.now().date()
    week_later = today + timedelta(days=7)
    cursor.execute("SELECT category, service, price, date_str, time_str FROM bookings WHERE date_str BETWEEN ? AND ? ORDER BY date_str, time_str", 
                   (today.strftime("%Y-%m-%d"), week_later.strftime("%Y-%m-%d")))
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        await update.message.reply_text("📅 На ближайшую неделю записей нет")
        return
    
    text = f"📅 <b>Записи на неделю:</b>\n\n"
    current_date = None
    for row in rows:
        cat, service, price, date_str, time_str = row
        if date_str != current_date:
            text += f"\n📆 {date_str}:\n"
            current_date = date_str
        loc = get_location(cat)
        text += f"  ⏰ {time_str} - {service} ({loc})\n"
    
    await update.message.reply_text(text, parse_mode="HTML")

async def bookings_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect("vlad_coaching.db")
    cursor = conn.cursor()
    cursor.execute("SELECT category, service, price, date_str, time_str FROM bookings ORDER BY date_str DESC, time_str LIMIT 50")
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        await update.message.reply_text("📋 Записей пока нет")
        return
    
    text = f"📋 <b>Последние 50 записей:</b>\n\n"
    for row in rows:
        cat, service, price, date_str, time_str = row
        text += f"📅 {date_str} {time_str} - {service} ({price})\n"
    
    await update.message.reply_text(text, parse_mode="HTML")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect("vlad_coaching.db")
    cursor = conn.cursor()
    
    # Статистика за текущий месяц
    now = datetime.now()
    month_start = now.replace(day=1).strftime("%Y-%m-%d")
    
    cursor.execute("SELECT COUNT(*) FROM bookings WHERE date_str >= ?", (month_start,))
    total_bookings = cursor.fetchone()[0]
    
    cursor.execute("SELECT category, COUNT(*) FROM bookings WHERE date_str >= ? GROUP BY category", (month_start,))
    by_category = cursor.fetchall()
    
    cursor.execute("SELECT SUM(CAST(REPLACE(price, ' BYN', '') AS INTEGER)) FROM bookings WHERE date_str >= ?", (month_start,))
    total_revenue = cursor.fetchone()[0] or 0
    
    conn.close()
    
    text = f"📊 <b>Статистика за {now.strftime('%B %Y')}:</b>\n\n"
    text += f"📝 Всего записей: {total_bookings}\n"
    text += f"💰 Общий доход: {total_revenue} BYN\n\n"
    
    if by_category:
        text += "<b>По категориям:</b>\n"
        for cat, count in by_category:
            text += f"  • {cat}: {count} записей\n"
    
    await update.message.reply_text(text, parse_mode="HTML")

async def block_slot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("❌ Формат: /block YYYY-MM-DD HH:MM\nПример: /block 2026-07-20 10:00")
        return
    
    date_str = context.args[0]
    time_str = context.args[1]
    
    conn = sqlite3.connect("vlad_coaching.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO blocked_slots (date_str, time_str) VALUES (?, ?)", (date_str, time_str))
    conn.commit()
    conn.close()
    
    await update.message.reply_text(f"✅ Слот заблокирован: {date_str} {time_str}")

async def unblock_slot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("❌ Формат: /unblock YYYY-MM-DD HH:MM\nПример: /unblock 2026-07-20 10:00")
        return
    
    date_str = context.args[0]
    time_str = context.args[1]
    
    conn = sqlite3.connect("vlad_coaching.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM blocked_slots WHERE date_str = ? AND time_str = ?", (date_str, time_str))
    conn.commit()
    conn.close()
    
    await update.message.reply_text(f"✅ Слот разблокирован: {date_str} {time_str}")

def run_bot():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("bookings_today", bookings_today))
    application.add_handler(CommandHandler("bookings_week", bookings_week))
    application.add_handler(CommandHandler("bookings_all", bookings_all))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("block", block_slot))
    application.add_handler(CommandHandler("unblock", unblock_slot))
    application.run_polling()

# === ПЛАНИРОВЩИК НАПОМИНАНИЙ ===
def check_reminders():
    conn = sqlite3.connect("vlad_coaching.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, category, service, date_str, time_str FROM bookings")
    rows = cursor.fetchall()
    conn.close()
    
    now = datetime.now()
    for row in rows:
        user_id, cat, service, date_str, time_str = row
        try:
            booking_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        except:
            continue
        
        hours_until = (booking_dt - now).total_seconds() / 3600
        loc = get_location(cat)
        
        if 23 <= hours_until <= 25:
            send_telegram_message(user_id, f"🔔 <b>Напоминание: завтра тренировка!</b>\n\n📅 Дата: {date_str}\n⏰ Время: {time_str}\n Занятие: {service}\n Место: {loc}\n👤 Тренер: Влад")
        elif 1.5 <= hours_until <= 2.5:
            send_telegram_message(user_id, f"⏰ <b>Напоминание: тренировка через 2 часа!</b>\n\n📅 Дата: {date_str}\n⏰ Время: {time_str}\n🏒 Занятие: {service}\n📍 Место: {loc}\n👤 Тренер: Влад")

scheduler = BackgroundScheduler()
scheduler.add_job(check_reminders, 'interval', minutes=30)
scheduler.start()

# === ЭНДПОИНТЫ ===
@app.get("/check_user/{user_id}")
def check_user(user_id: int):
    conn = sqlite3.connect("vlad_coaching.db")
    cursor = conn.cursor()
    cursor.execute("SELECT first_name, last_name FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()
    return {"registered": bool(user), "name": f"{user[0]} {user[1]}" if user else ""}

@app.post("/register")
def register_user(data: RegisterData):
    conn = sqlite3.connect("vlad_coaching.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO users (user_id, first_name, last_name, phone, birthday) VALUES (?, ?, ?, ?, ?)",
                   (data.user_id, data.first_name, data.last_name, data.phone, data.birthday))
    conn.commit()
    conn.close()
    send_telegram_message(ADMIN_CHAT_ID, f"👤 <b>Новый клиент!</b>\n{data.first_name} {data.last_name}")
    return {"success": True}

@app.get("/get_blocked_slots/{date_str}")
def get_blocked_slots(date_str: str):
    conn = sqlite3.connect("vlad_coaching.db")
    cursor = conn.cursor()
    cursor.execute("SELECT time_str FROM bookings WHERE date_str = ?", (date_str,))
    booked_times = [row[0] for row in cursor.fetchall()]
    cursor.execute("SELECT time_str FROM blocked_slots WHERE date_str = ?", (date_str,))
    blocked_times = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    all_blocked = set(booked_times + blocked_times)
    expanded_blocked = set(all_blocked)
    for t in all_blocked:
        h, m = map(int, t.split(':'))
        for i in range(1, 4):
            new_m = m + 30
            new_h = h
            if new_m == 60:
                new_m = 0
                new_h += 1
            expanded_blocked.add(f"{new_h:02d}:{new_m:02d}")
    
    return {"blocked_slots": list(expanded_blocked)}

@app.post("/webhook")
async def receive_booking(data: BookingData):
    conn = sqlite3.connect("vlad_coaching.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO bookings (user_id, category, service, price, date_str, time_str) VALUES (?, ?, ?, ?, ?, ?)",
                   (data.user_id, data.category, data.service, data.price, data.raw_date, data.time))
    conn.commit()
    conn.close()
    loc = get_location(data.category)
    send_telegram_message(ADMIN_CHAT_ID, f"🔥 <b>Новая запись!</b>\n👤 ID: {data.user_id}\n🏒 {data.service}\n📅 {data.date} в {data.time}\n📍 {loc}\n💰 {data.price}")
    return {"success": True}

@app.post("/review")
def add_review(data: ReviewData):
    conn = sqlite3.connect("vlad_coaching.db")
    cursor = conn.cursor()
    cursor.execute("SELECT first_name FROM users WHERE user_id = ?", (data.user_id,))
    user = cursor.fetchone()
    name = user[0] if user else "Аноним"
    cursor.execute("INSERT INTO reviews (user_id, name, rating, text, date) VALUES (?, ?, ?, ?, ?)", 
                   (data.user_id, name, data.rating, data.text, datetime.now().strftime("%d.%m.%Y")))
    conn.commit()
    conn.close()
    return {"success": True}

@app.post("/suggestion")
def add_suggestion(data: SuggestionData):
    conn = sqlite3.connect("vlad_coaching.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO suggestions (user_id, text, date) VALUES (?, ?, ?)", 
                   (data.user_id, data.text, datetime.now().strftime("%d.%m.%Y %H:%M")))
    conn.commit()
    conn.close()
    send_telegram_message(ADMIN_CHAT_ID, f"💡 <b>Новое пожелание!</b>\nОт пользователя {data.user_id}:\n{data.text}")
    return {"success": True}

@app.get("/reviews")
def get_reviews():
    conn = sqlite3.connect("vlad_coaching.db")
    cursor = conn.cursor()
    cursor.execute("SELECT name, rating, text, date FROM reviews ORDER BY id DESC LIMIT 15")
    rows = cursor.fetchall()
    conn.close()
    return [{"name": r[0], "rating": r[1], "text": r[2], "date": r[3]} for r in rows]

# === ЗАПУСК ===
if __name__ == '__main__':
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host='0.0.0.0', port=port)
