from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import sqlite3
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler

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
WEB_APP_URL = "https://vlad-sakik.github.io/tg-mini-app/" 

# === ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ ===
def init_db():
    conn = sqlite3.connect("vlad_coaching.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT,
            last_name TEXT,
            phone TEXT,
            birthday TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT,
            rating INTEGER,
            text TEXT,
            date TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            category TEXT,
            service TEXT,
            price TEXT,
            date_str TEXT,
            time_str TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

scheduler = BackgroundScheduler()
scheduler.start()

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

# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===
def send_telegram_message(chat_id: int, text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    try: requests.post(url, json=payload)
    except Exception as e: print(f"Ошибка TG: {e}")

def send_review_request(user_id: int, service_name: str):
    link = f"{WEB_APP_URL}?action=leave_review"
    text = (
        f"💪 <b>Как вам тренировка «{service_name}»?</b>\n\n"
        "Буду очень благодарен, если уделите полминуты и оставите честный отзыв. "
        f"👉 <a href='{link}'>Оставить отзыв здесь</a>"
    )
    send_telegram_message(user_id, text)

# === ЭНДПОИНТЫ ===

@app.get("/check_user/{user_id}")
def check_user(user_id: int):
    conn = sqlite3.connect("vlad_coaching.db")
    cursor = conn.cursor()
    cursor.execute("SELECT first_name, last_name FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()
    if user:
        return {"registered": True, "name": f"{user[0]} {user[1]}"}
    return {"registered": False}

@app.post("/register")
def register_user(data: RegisterData):
    conn = sqlite3.connect("vlad_coaching.db")
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO users (user_id, first_name, last_name, phone, birthday) VALUES (?, ?, ?, ?, ?)",
        (data.user_id, data.first_name, data.last_name, data.phone, data.birthday)
    )
    conn.commit()
    conn.close()
    admin_msg = f"👤 <b>Новый клиент!</b>\n\n<b>Имя:</b> {data.first_name} {data.last_name}\n<b>Телефон:</b> {data.phone}"
    send_telegram_message(ADMIN_CHAT_ID, admin_msg)
    return {"success": True}

@app.get("/get_blocked_slots/{date_str}")
def get_blocked_slots(date_str: str):
    conn = sqlite3.connect("vlad_coaching.db")
    cursor = conn.cursor()
    cursor.execute("SELECT time_str FROM bookings WHERE date_str = ?", (date_str,))
    booked_times = [row[0] for row in cursor.fetchall()]
    conn.close()
    blocked_slots = set()
    for t in booked_times:
        blocked_slots.add(t)
        try:
            dt = datetime.strptime(t, "%H:%M")
            blocked_slots.add((dt - timedelta(hours=1)).strftime("%H:%M"))
            blocked_slots.add((dt + timedelta(hours=1)).strftime("%H:%M"))
        except: pass
    return {"blocked_slots": list(blocked_slots)}

@app.post("/webhook")
async def receive_booking(data: BookingData):
    conn = sqlite3.connect("vlad_coaching.db")
    cursor = conn.cursor()
    cursor.execute("SELECT time_str FROM bookings WHERE date_str = ?", (data.raw_date,))
    existing_bookings = [row[0] for row in cursor.fetchall()]
    
    conflict = False
    for t in existing_bookings:
        if t == data.time: conflict = True
        dt = datetime.strptime(t, "%H:%M")
        if (dt - timedelta(hours=1)).strftime("%H:%M") == data.time: conflict = True
        if (dt + timedelta(hours=1)).strftime("%H:%M") == data.time: conflict = True
        
    if conflict:
        conn.close()
        raise HTTPException(status_code=400, detail="Это время уже занято!")

    cursor.execute("INSERT INTO bookings (user_id, category, service, price, date_str, time_str) VALUES (?, ?, ?, ?, ?, ?)",
        (data.user_id, data.category, data.service, data.price, data.raw_date, data.time))
    conn.commit()
    conn.close()
    
    admin_text = f"🔥 <b>Новая запись!</b>\n\n👤 <b>Клиент:</b> {data.user_id}\n🛠 <b>Услуга:</b> {data.service}\n📅 <b>Дата:</b> {data.date} в {data.time}"
    send_telegram_message(ADMIN_CHAT_ID, admin_text)
    
    return {"success": True}

@app.post("/review")
def add_review(data: ReviewData):
    conn = sqlite3.connect("vlad_coaching.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO reviews (user_id, rating, text, date) VALUES (?, ?, ?, ?)", 
                   (data.user_id, data.rating, data.text, datetime.now().strftime("%d.%m.%Y")))
    conn.commit()
    conn.close()
    return {"success": True}

@app.get("/reviews")
def get_reviews():
    conn = sqlite3.connect("vlad_coaching.db")
    cursor = conn.cursor()
    cursor.execute("SELECT name, rating, text, date FROM reviews ORDER BY id DESC LIMIT 15")
    rows = cursor.fetchall()
    conn.close()
    return [{"name": r[0], "rating": r[1], "text": r[2], "date": r[3]} for r in rows]

if __name__ == '__main__':
    import uvicorn
    import os
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host='0.0.0.0', port=port)
