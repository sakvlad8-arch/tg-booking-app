from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import sqlite3
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
import os
import uvicorn

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

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
            send_telegram_message(user_id, f"🔔 <b>Напоминание: завтра тренировка!</b>\n\n📅 Дата: {date_str}\n⏰ Время: {time_str}\n🏒 Занятие: {service}\n📍 Место: {loc}\n👤 Тренер: Влад")
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
    conn.close()
    expanded_blocked = set(booked_times)
    for t in booked_times:
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
    send_telegram_message(ADMIN_CHAT_ID, f"🔥 <b>Новая запись!</b>\n👤 ID: {data.user_id}\n🏒 {data.service}\n📅 {data.date} в {data.time}\n📍 {get_location(data.category)}\n💰 {data.price}")
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

# === ЗАПУСК СЕРВЕРА ===
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host='0.0.0.0', port=port)
