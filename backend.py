from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import json
import os
import tempfile
import uvicorn
import sqlite3
import re
import uuid
import bcrypt
from datetime import datetime

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========== БАЗА ДАННЫХ ==========
DB_PATH = "speechcraft.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            username TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trainings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            exercise_name TEXT,
            mode TEXT,
            recognized_text TEXT,
            etalon_text TEXT,
            word_count INTEGER,
            word_count_etalon INTEGER,
            duration REAL,
            words_per_minute INTEGER,
            phonetics_score REAL,
            lexical_score REAL,
            tempo_score REAL,
            stop_words_score REAL,
            final_score REAL,
            unique_words_ratio REAL,
            pauses_count INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_tongue_twisters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            text TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_absurd_texts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT NOT NULL,
            text TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    conn.commit()
    conn.close()


init_db()
session_user = {}

# ========== БИБЛИОТЕКА УПРАЖНЕНИЙ ==========
TONGUE_TWISTERS = {
    "1": "На дворе трава на траве дрова",
    "2": "Шла Саша по шоссе и сосала сушку",
    "3": "Карл у Клары украл кораллы а Клара у Карла украла кларнет",
    "4": "Тридцать три корабля лавировали лавировали да не вылавировали",
    "5": "Бык тупогуб тупогубенький бычок у быка бела губа была тупа",
    "6": "Ехал Грека через реку видит Грека в реке рак",
    "7": "Сшит колпак не по колпаковски надо его переколпаковать",
    "8": "Кукушка кукушонку купила капюшон как в капюшоне он смешон",
    "9": "От топота копыт пыль по полю летит",
    "10": "Король орёл орел король",
    "11": "Везёт Сенька Саньку с Сонькой на санках санки скок Саньку с ног Соньку в лоб",
    "12": "У нас во дворе подворье погода размокропогодилась",
    "13": "Рыла свинья белорыла тупорыла полдвора рылом изрыла вырыла подрыла",
    "14": "Белые бараны били в барабаны",
    "15": "Шестнадцать шли мышей и шесть нашли грошей",
    "16": "Ткач ткёт ткань на платки Тане",
    "17": "Хохлатые хохотушки хохотом хохотали ха ха ха",
    "18": "Интервьюер интервента интервьюировал",
    "19": "Милости просим на наш хлеб-соль",
    "20": "Проворонила ворона воронёнка"
}

DICTION_EXERCISES = {
    "1": {"name": "Чистоговорка на Р", "text": "Ра-ра-ра высокая гора ры-ры-ры летят комары"},
    "2": {"name": "Чистоговорка на С и Ш", "text": "Саша шапкой шишку сшиб"},
    "3": {"name": "Чистоговорка на Ж и З", "text": "Жужжит жужелица жужжит кружится"},
    "4": {"name": "Чистоговорка на Ч и Щ", "text": "Щёткой чищу я щенка щекочу ему бока"},
    "5": {"name": "Чистоговорка на Л", "text": "Ла-ла-ла лопата пила ло-ло-ло тепло как в седле"}
}

BREATHING_EXERCISES = {
    "1": {"name": "Свеча", "description": "Представь свечку и попробуй задуть её ровным долгим выдохом",
          "tips": "Вдох носом (2-3 сек), выдох ртом (5-10 сек)"},
    "2": {"name": "Насос", "description": "Наклоны вперёд с резким вдохом в нижней точке",
          "tips": "8-10 раз, отдых 30 секунд"},
    "3": {"name": "Счёт на выдохе", "description": "На одном выдохе посчитать до 10, затем до 15, до 20",
          "tips": "Следи, чтобы выдох был плавным"},
    "4": {"name": "Ёжик", "description": "Резкий носовой вдох, свободный выдох через рот",
          "tips": "32 раза без остановки"},
    "5": {"name": "Трубач", "description": "Представь, что играешь на трубе — мощный выдох короткими импульсами",
          "tips": "5-7 раз, отдых после каждого"}
}

ARTICULATION_EXERCISES = {
    "1": {"name": "Улыбка-трубочка", "description": "Растянуть губы в улыбку → вытянуть в трубочку", "tips": "10 раз"},
    "2": {"name": "Лошадка", "description": "Пощёлкать языком, присасывая его к нёбу", "tips": "15-20 раз"},
    "3": {"name": "Часики", "description": "Кончиком языка водить влево-вправо по губам",
          "tips": "10 раз в каждую сторону"},
    "4": {"name": "Качели", "description": "Язык тянется к носу → к подбородку", "tips": "10-15 раз"},
    "5": {"name": "Маляр", "description": "Языком красить нёбо от зубов к горлу", "tips": "10 раз"}
}

BASIC_EXERCISE = {"name": "Базовое упражнение", "text": "привет как дела у меня все хорошо"}

current_etalon = BASIC_EXERCISE["text"]
current_etalon_name = BASIC_EXERCISE["name"]

STOP_WORDS = ["это", "эта", "этот", "ну", "вот", "типа", "как бы", "так сказать", "вообще", "короче", "значит"]

FREE_TOPICS = [
    "Моё хобби",
    "Как прошёл мой день",
    "Мои планы на выходные",
    "Что я читал(а) в последнее время",
    "Мой любимый фильм или сериал",
    "Путешествия, которые я запомнил(а)",
    "Что меня вдохновляет",
    "Моя будущая профессия",
    "Важное событие в моей жизни",
    "Что бы я изменил(а) в мире"
]


def clean_text(text):
    if not text:
        return ""
    text = re.sub(r'[^\w\s\-]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def save_training_result(user_id, data):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        '''INSERT INTO trainings (user_id, exercise_name, mode, recognized_text, etalon_text, word_count, word_count_etalon, duration, words_per_minute, phonetics_score, lexical_score, tempo_score, stop_words_score, final_score, unique_words_ratio, pauses_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (user_id, data.get("exercise_name", ""), data.get("mode", ""), data.get("recognized_text", ""),
         data.get("etalon_text", ""), data.get("word_count", 0), data.get("word_count_etalon", 0),
         data.get("duration", 0), data.get("words_per_minute", 0), data.get("phonetics_score", 0),
         data.get("lexical_score", 0), data.get("tempo_score", 0), data.get("stop_words_score", 0),
         data.get("final_score", 0), data.get("unique_words_ratio", 0), data.get("pauses_count", 0)))
    conn.commit()
    conn.close()


def validate_email(email):
    return re.match(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$', email)


def validate_password(password):
    return len(password) >= 6


# ========== API ЭНДПОИНТЫ ==========
@app.get("/", response_class=HTMLResponse)
async def home():
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()


@app.get("/tongue_twisters")
async def get_tongue_twisters():
    return TONGUE_TWISTERS


@app.get("/diction_exercises")
async def get_diction_exercises():
    return DICTION_EXERCISES


@app.get("/breathing_exercises")
async def get_breathing_exercises():
    return BREATHING_EXERCISES


@app.get("/articulation_exercises")
async def get_articulation_exercises():
    return ARTICULATION_EXERCISES


@app.get("/free_topics")
async def get_free_topics():
    return FREE_TOPICS


@app.post("/set_etalon")
async def set_etalon(text: str = Form(...), name: str = Form(...)):
    global current_etalon, current_etalon_name
    current_etalon = clean_text(text)
    current_etalon_name = name
    return {"status": "ok"}


@app.post("/register")
async def register(email: str = Form(...), username: str = Form(...), password: str = Form(...)):
    if not validate_email(email):
        return {"status": "error", "message": "Неверный формат email"}
    if not validate_password(password):
        return {"status": "error", "message": "Пароль должен быть не менее 6 символов"}
    if not username or len(username) < 2:
        return {"status": "error", "message": "Имя пользователя должно быть не менее 2 символов"}

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        cursor.execute("INSERT INTO users (email, username, password_hash) VALUES (?, ?, ?)",
                       (email, username, password_hash))
        conn.commit()
        conn.close()
        return {"status": "ok"}
    except sqlite3.IntegrityError:
        conn.close()
        return {"status": "error", "message": "Пользователь с таким email уже существует"}


@app.post("/login")
async def login(email: str = Form(...), password: str = Form(...)):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, password_hash FROM users WHERE email = ?", (email,))
    row = cursor.fetchone()
    conn.close()
    if row and bcrypt.checkpw(password.encode(), row[2].encode()):
        token = str(uuid.uuid4())
        session_user[token] = {"id": row[0], "username": row[1], "email": email}
        return {"status": "ok", "token": token, "username": row[1]}
    return {"status": "error", "message": "Неверный email или пароль"}


@app.post("/logout")
async def logout(token: str = Form(...)):
    if token in session_user:
        del session_user[token]
    return {"status": "ok"}


@app.get("/current_user")
async def get_current_user(token: str = None):
    if token and token in session_user:
        return {"status": "ok", "user_id": session_user[token]["id"], "username": session_user[token]["username"],
                "email": session_user[token]["email"]}
    return {"status": "error"}


@app.get("/history")
async def get_history(token: str = None):
    if not token or token not in session_user:
        return []
    user_id = session_user[token]["id"]
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        'SELECT id, exercise_name, mode, final_score, created_at FROM trainings WHERE user_id = ? ORDER BY created_at DESC LIMIT 50',
        (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "exercise_name": r[1], "mode": r[2], "final_score": r[3], "created_at": r[4]} for r in rows]


@app.get("/stats")
async def get_stats(token: str = None):
    if not token or token not in session_user:
        return {"avg_score": 0, "max_score": 0, "total_trainings": 0, "avg_phonetics": 0, "avg_tempo": 0}
    user_id = session_user[token]["id"]
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        'SELECT AVG(final_score), MAX(final_score), COUNT(*), AVG(tempo_score) FROM trainings WHERE user_id = ?',
        (user_id,))
    row = cursor.fetchone()
    conn.close()
    return {"avg_score": round(row[0], 1) if row[0] else 0, "max_score": round(row[1], 1) if row[1] else 0,
            "total_trainings": row[2] if row[2] else 0, "avg_tempo": round(row[3], 1) if row[3] else 0}


@app.get("/progress_data")
async def get_progress_data(token: str = None):
    if not token or token not in session_user:
        return {"dates": [], "scores": []}
    user_id = session_user[token]["id"]
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT DATE(created_at) as date, AVG(final_score) as avg_score
        FROM trainings
        WHERE user_id = ?
        GROUP BY DATE(created_at)
        ORDER BY date ASC
        LIMIT 30
    ''', (user_id,))
    rows = cursor.fetchall()
    conn.close()
    dates = [row[0] for row in rows]
    scores = [round(row[1], 1) for row in rows]
    return {"dates": dates, "scores": scores}


@app.post("/analyze")
async def analyze(file: UploadFile = File(...), mode: str = Form("strict"), duration: float = Form(10.0),
                  token: str = Form(None)):
    if not token or token not in session_user:
        return {"error": "Не авторизован"}

    user_id = session_user[token]["id"]
    global current_etalon, current_etalon_name

    # ВРЕМЕННО: возвращаем заглушку
    return {
        "recognized_text": "привет как дела",
        "phonetics_score": 85,
        "lexical_score": 90,
        "tempo_score": 80,
        "stop_words_score": 100,
        "final_score": 86,
        "duration": round(duration, 1),
        "words_per_minute": 120,
        "tempo_feedback": "хороший темп"
    }


@app.post("/analyze_free")
async def analyze_free(file: UploadFile = File(...), duration: float = Form(10.0), topic: str = Form(""),
                       token: str = Form(None)):
    if not token or token not in session_user:
        return {"error": "Не авторизован"}

    user_id = session_user[token]["id"]

    return {
        "recognized_text": "привет как дела у меня все хорошо",
        "duration": round(duration, 1),
        "words_per_minute": 120,
        "tempo_score": 80,
        "ttr_score": 85,
        "stop_words_score": 100,
        "topic_score": 90,
        "final_score": 86,
        "detailed_feedback": "Хорошая речь! Темп нормальный, слова-паразиты не обнаружены.",
        "word_count": 5,
        "unique_ratio": 80,
        "stop_words_found": []
    }


@app.post("/add_tongue_twister")
async def add_tongue_twister(text: str = Form(...), token: str = Form(None)):
    if not token or token not in session_user:
        return {"status": "error", "message": "Не авторизован"}
    user_id = session_user[token]["id"]
    clean = clean_text(text)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO user_tongue_twisters (user_id, text) VALUES (?, ?)", (user_id, clean))
    conn.commit()
    conn.close()
    return {"status": "ok"}


@app.get("/my_tongue_twisters")
async def get_my_tongue_twisters(token: str = None):
    if not token or token not in session_user:
        return []
    user_id = session_user[token]["id"]
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, text FROM user_tongue_twisters WHERE user_id = ? ORDER BY created_at DESC", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "text": r[1]} for r in rows]


@app.post("/delete_tongue_twister")
async def delete_tongue_twister(id: int = Form(...), token: str = Form(None)):
    if not token or token not in session_user:
        return {"status": "error", "message": "Не авторизован"}
    user_id = session_user[token]["id"]
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM user_tongue_twisters WHERE id = ? AND user_id = ?", (id, user_id))
    conn.commit()
    conn.close()
    return {"status": "ok"}


@app.post("/add_absurd_text")
async def add_absurd_text(name: str = Form(...), text: str = Form(...), token: str = Form(None)):
    if not token or token not in session_user:
        return {"status": "error", "message": "Не авторизован"}
    user_id = session_user[token]["id"]
    clean = clean_text(text)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO user_absurd_texts (user_id, name, text) VALUES (?, ?, ?)", (user_id, name, clean))
    conn.commit()
    conn.close()
    return {"status": "ok"}


@app.get("/my_absurd_texts")
async def get_my_absurd_texts(token: str = None):
    if not token or token not in session_user:
        return []
    user_id = session_user[token]["id"]
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, text FROM user_absurd_texts WHERE user_id = ? ORDER BY created_at DESC",
                   (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "name": r[1], "text": r[2]} for r in rows]


@app.post("/delete_absurd_text")
async def delete_absurd_text(id: int = Form(...), token: str = Form(None)):
    if not token or token not in session_user:
        return {"status": "error", "message": "Не авторизован"}
    user_id = session_user[token]["id"]
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM user_absurd_texts WHERE id = ? AND user_id = ?", (id, user_id))
    conn.commit()
    conn.close()
    return {"status": "ok"}


# ========== АБСУРД-ТРЕНИНГ ==========
ABSURD_EXERCISES = {
    "elephant": {
        "name": "Слон в холодильнике",
        "parts": {
            "1": "Гипотетически-концептуальная операционализационно-реконфигурационная модель инкорпорации слона в холодильный агрегат предполагает пространственно-геометрическую верификацию внутренне-объёмной архитектоники.",
            "2": "Далее реализуется алгоритмизируемо-декомпозиционная манипуляционно-интервенционная процедура: инициация дверно-открывающего акта холодильник, тотальная экстракция содержимого.",
            "3": "Финально реализуется интеграционно-коллапсирующая фаза: субъект, игнорируя физико-биомеханическую невозможность, осуществляет квази-завершённую инсталляцию."
        }
    },
    "sasha": {
        "name": "Шла Саша по шоссе",
        "parts": {
            "1": "Шла Саша по шоссе, синхронизируя шоссейно-логистическо-сегментированные маршрутизационно-регламентационные сверхструктуры.",
            "2": "Сушку Саша сублимационно-сосредоточенно сосала, сопровождая процесс сверхскоростной спектрально-семантической саморегуляцией.",
            "3": "Шоссейная среда содрогалась: сверхинтенсивные субординационно-сигнальные сообщения смешивались с сейсмоакустическо-шумовыми шорохами."
        }
    },
    "collagen": {
        "name": "Коллагеново-липопротеиновый конгломерат",
        "parts": {
            "1": "Коллагеново-липопротеиновый гастрономическо-эмульсионный конгломерат подвергается высокоамплитудной термокаталитической денатурационно-ферментационной обработке.",
            "2": "Крупнопористая ферротермическо-конвекционная платформа достигает критико-температурной бифуркационной амплитуды.",
            "3": "Профессионально сертифицированный гастрономическо-технологический специалист компетентно контролирует структурно-консистентную архитектонику."
        }
    }
}


@app.get("/absurd_exercises")
async def get_absurd_exercises():
    return ABSURD_EXERCISES


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)