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
# Ссылка на твой Web App (замени на свою рабочую ссылку, если она отличается)
WEB_APP_URL = "https://vlad-sakik.github.io/tg-mini-app/" 

# === ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ ===
def init_db():
    conn = sqlite3.connect("vlad_coaching.db")
    cursor = conn.cursor()
    # Таблица пользователей
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT,
            last_name TEXT,
            phone TEXT,
            birthday TEXT
        )
    """)
    # Таблица отзывов
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
    # Таблица записей на тренировки
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            category TEXT,
            service TEXT,
            price TEXT,
            date_str TEXT, -- Формат ГГГГ-ММ-ДД
            time_str TEXT  -- Формат ЧЧ:ММ
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
    raw_date: str  # ГГГГ-ММ-ДД
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
        "Это помогает мне становиться лучше и развивать приложение! 🏒\n\n"
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
    
    admin_msg = f"👤 <b>Новый клиент!</b>\n\n<b>Имя:</b> {data.first_name} {data.last_name}\n<b>Телефон:</b> {data.phone}\n<b>ДР:</b> {data.birthday}"
    send_telegram_message(ADMIN_CHAT_ID, admin_msg)
    return {"success": True}

# Получение списка заблокированных часов на выбранную дату
@app.get("/get_blocked_slots/{date_str}")
def get_blocked_slots(date_str: str):
    conn = sqlite3.connect("vlad_coaching.db")
    cursor = conn.cursor()
    cursor.execute("SELECT time_str FROM bookings WHERE date_str = ?", (date_str,))
    booked_times = [row[0] for row in cursor.fetchall()]
    conn.close()

    blocked_slots = set()
    for t in booked_times:
        blocked_slots.add(t) # Само время записи занято
        try:
            # Вычисляем час ДО и час ПОСЛЕ
            dt = datetime.strptime(t, "%H:%M")
            time_before = (dt - timedelta(hours=1)).strftime("%H:%M")
            time_after = (dt + timedelta(hours=1)).strftime("%H:%M")
            blocked_slots.add(time_before)
            blocked_slots.add(time_after)
        except Exception as e:
            print(f"Ошибка расчета буфера времени: {e}")

    return {"blocked_slots": list(blocked_slots)}

@app.post("/webhook")
async def receive_booking(data: BookingData):
    conn = sqlite3.connect("vlad_coaching.db")
    cursor = conn.cursor()
    
    # Сначала проверяем, не заняли ли это время (или буферное время) пока клиент думал
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
        raise HTTPException(status_code=400, detail="Это время или соседний час уже забронированы!")

    # Сохраняем запись в БД
    cursor.execute(
        "INSERT INTO bookings (user_id, category, service, price, date_str, time_str) VALUES (?, ?, ?, ?, ?, ?)",
        (data.user_id, data.category, data.service, data.price, data.raw_date, data.time)
    )
    conn.commit()

    cursor.execute("SELECT first_name, last_name, phone, birthday FROM users WHERE user_id = ?", (data.user_id,))
    user = cursor.fetchone()
    conn.close()

    client_info = f"{user[0]} {user[1]} ({user[2]})" if user else "Неизвестный клиент"
    is_birthday = False

    if user and user[3]:
        try:
            b_date = datetime.strptime(user[3], "%Y-%m-%d")
            book_date = datetime.strptime(data.raw_date, "%Y-%m-%d")
            if b_date.month == book_date.month and b_date.day == book_date.day:
                is_birthday = True
        except: pass

    bd_alert = "\n\n🎁 <b>У КЛИЕНТА ДЕНЬ РОЖДЕНИЯ В ЭТОТ ДЕНЬ!</b>" if is_birthday else ""
    admin_text = (
        f"🔥 <b>Новая запись!</b>\n\n"
        f"👤 <b>Клиент:</b> {client_info}\n"
        f"🗂 <b>Категория:</b> {data.category}\n"
        f"🛠 <b>Услуга:</b> {data.service}\n"
        f"💰 <b>Стоимость:</b> {data.price}\n"
        f"📅 <b>Дата:</b> {data.date}\n"
        f"⏰ <b>Время:</b> {data.time}"
        f"{bd_alert}"
    )
    send_telegram_message(ADMIN_CHAT_ID, admin_text)
    
    gift_text = "\n\n🎁 В честь вашего дня рождения вас ждет специальный подарок на тренировке! 🎉" if is_birthday else ""
    if data.user_id != 0:
        client_welcome_text = f"✅ <b>Вы успешно записались!</b>\n\n🎯 <b>Занятие:</b> {data.service}\n📅 <b>Когда:</b> {data.date} в {data.time}{gift_text}\n\nЖду вас! 🙌"
        send_telegram_message(data.user_id, client_welcome_text)

        try:
            booking_datetime = datetime.strptime(f"{data.raw_date} {data.time}", "%Y-%m-%d %H:%M")
            now = datetime.now()

            # 1. Напоминания за 24 часа и за 1 час
            remind_24h = booking_datetime - timedelta(hours=24)
            remind_1h = booking_datetime - timedelta(hours=1)
            
            if remind_24h > now:
                scheduler.add_job(send_telegram_message, 'date', run_date=remind_24h, args=[data.user_id, f"⏳ <b>Напоминание:</b> Завтра в {data.time} у вас «{data.service}»!"])
            if remind_1h > now:
                scheduler.add_job(send_telegram_message, 'date', run_date=remind_1h, args=[data.user_id, f"⚡ <b>Напоминание:</b> Через 1 час ({data.time}) тренировка «{data.service}»!"])

            # 2. ПЛАНИРУЕМ ССЫЛКУ НА ОТЗЫВ (через 2 часа после начала тренировки)
            review_trigger_time = booking_datetime + timedelta(hours=2)
            if review_trigger_time > now:
                scheduler.add_job(send_review_request, 'date', run_date=review_trigger_time, args=[data.user_id, data.service])

        except Exception as e:
            print(f"Ошибка планировщика: {e}")
        
    return {"success": True}

@app.post("/review")
def add_review(data: ReviewData):
    conn = sqlite3.connect("vlad_coaching.db")
    cursor = conn.cursor()
    cursor.execute("SELECT first_name, last_name FROM users WHERE user_id = ?", (data.user_id,))
    user = cursor.fetchone()
    
    name = f"{user[0]} {user[1]}" if user else "Клиент"
    today_str = datetime.now().strftime("%d.%m.%Y")
    
    cursor.execute("INSERT INTO reviews (user_id, name, rating, text, date) VALUES (?, ?, ?, ?, ?)", (data.user_id, name, data.rating, data.text, today_str))
    conn.commit()
    conn.close()

    send_telegram_message(ADMIN_CHAT_ID, f"💬 <b>Получен новый отзыв!</b>\n\n<b>От:</b> {name}\n<b>Оценка:</b> {'⭐'*data.rating}\n<b>Текст:</b> {data.text}")
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
    # Порт назначается облаком автоматически
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host='0.0.0.0', port=port)