from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import whisper
import json
import os
import tempfile
import uvicorn
import subprocess
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

# ========== ЗАГРУЗКА МОДЕЛИ WHISPER ==========
print("Загрузка модели Whisper...")
from faster_whisper import WhisperModel
whisper_model = WhisperModel("tiny", device="cpu", compute_type="int8")
print("Модель Whisper загружена!")

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
    """Очистка текста от знаков препинания"""
    if not text:
        return ""
    # Удаляем все знаки препинания, кроме дефиса и пробелов
    text = re.sub(r'[^\w\s\-]', '', text)
    # Удаляем лишние пробелы
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def get_topic_keywords(topic):
    keywords = topic.lower().split()
    return [w for w in keywords if len(w) > 2]


def analyze_free_speech(recognized_text, duration, topic=None):
    words = recognized_text.strip().split()
    word_count = len(words)

    if duration > 0 and word_count > 0:
        words_per_minute = (word_count / duration) * 60
        if 100 <= words_per_minute <= 140:
            tempo_score = 100
            tempo_feedback = "Идеальный темп речи"
        elif words_per_minute < 100:
            tempo_score = max(0, round(100 - (100 - words_per_minute) / 100 * 100, 1))
            tempo_feedback = "Речь слишком медленная. Попробуй говорить быстрее"
        else:
            tempo_score = max(0, round(100 - (words_per_minute - 140) / 140 * 100, 1))
            tempo_feedback = "Речь слишком быстрая. Попробуй говорить медленнее"
    else:
        words_per_minute = 0
        tempo_score = 0
        tempo_feedback = "Недостаточно слов для оценки темпа"

    if word_count > 0:
        unique_words = len(set(words))
        unique_ratio = round(unique_words / word_count * 100, 1)
        if unique_ratio >= 60:
            lexical_diversity_feedback = f"Отличное разнообразие лексики ({unique_ratio}% уникальных слов)"
            lexical_diversity_score = 100
        elif unique_ratio >= 40:
            lexical_diversity_feedback = f"Хорошее разнообразие лексики ({unique_ratio}% уникальных слов)"
            lexical_diversity_score = 75
        elif unique_ratio >= 20:
            lexical_diversity_feedback = f"Среднее разнообразие лексики ({unique_ratio}% уникальных слов). Попробуй использовать больше разных слов"
            lexical_diversity_score = 50
        else:
            lexical_diversity_feedback = f"Низкое разнообразие лексики ({unique_ratio}% уникальных слов). Старайся избегать повторений"
            lexical_diversity_score = 30
    else:
        unique_ratio = 0
        lexical_diversity_score = 0
        lexical_diversity_feedback = "Речь не распознана"

    stop_words_found = [w for w in words if w in STOP_WORDS]
    unique_stop_words = list(set(stop_words_found))
    if len(stop_words_found) == 0:
        stop_words_score = 100
        stop_words_feedback = "Слова-паразиты не обнаружены"
    elif len(stop_words_found) <= 2:
        stop_words_score = max(0, 100 - len(stop_words_found) * 15)
        stop_words_feedback = f"Есть слова-паразиты: {', '.join(unique_stop_words)}"
    else:
        stop_words_score = max(0, 100 - len(stop_words_found) * 12)
        stop_words_feedback = f"Много слов-паразитов: {', '.join(unique_stop_words[:4])}"

    topic_score = 100
    topic_feedback = ""
    if topic and topic.strip():
        topic_clean = topic.lower().strip()
        keywords = [w for w in topic_clean.split() if len(w) > 2]

        if keywords:
            recognized_lower = recognized_text.lower()
            found_keywords = [k for k in keywords if k in recognized_lower]

            if len(found_keywords) == 0:
                topic_score = 30
                topic_feedback = f"Тема «{topic}» не раскрыта"
            elif len(found_keywords) < len(keywords):
                topic_score = round(30 + (len(found_keywords) / len(keywords)) * 70, 1)
                topic_feedback = f"Тема «{topic}» раскрыта частично ({len(found_keywords)} из {len(keywords)} ключевых слов)"
            else:
                topic_score = 100
                topic_feedback = f"Тема «{topic}» раскрыта хорошо"
        else:
            topic_score = 100
            topic_feedback = f"Тема принята (нет ключевых слов для оценки)"
    elif topic:
        topic_score = 100
        topic_feedback = "Тема не задана — оценка раскрытия не производится"

    final_score = round(
        tempo_score * 0.3 +
        lexical_diversity_score * 0.3 +
        stop_words_score * 0.2 +
        topic_score * 0.2,
        1
    )

    return {
        "word_count": word_count,
        "duration": round(duration, 1),
        "words_per_minute": int(words_per_minute),
        "tempo_score": tempo_score,
        "tempo_feedback": tempo_feedback,
        "unique_ratio": unique_ratio,
        "lexical_diversity_score": lexical_diversity_score,
        "lexical_diversity_feedback": lexical_diversity_feedback,
        "stop_words_score": stop_words_score,
        "stop_words_feedback": stop_words_feedback,
        "stop_words_found": stop_words_found,
        "topic_score": topic_score,
        "topic_feedback": topic_feedback,
        "final_score": final_score,
        "recognized_text": recognized_text
    }


def convert_to_wav(input_path, output_path):
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", input_path, "-acodec", "pcm_s16le", "-ac", "1", "-ar", "16000", output_path],
            check=True, capture_output=True)
        return True
    except:
        return False


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


def is_absurd_exercise(exercise_name):
    return exercise_name and ("Слон в холодильнике" in exercise_name or
                              "Шла Саша" in exercise_name or
                              "Коллаген" in exercise_name or
                              "Свой абсурд" in exercise_name or
                              "Мой" in exercise_name)


# ========== API ПОЛЬЗОВАТЕЛЬСКИХ УПРАЖНЕНИЙ ==========
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
    # Очищаем эталон от знаков препинания
    clean = clean_text(text)
    current_etalon = clean
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

    with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    wav_path = tempfile.NamedTemporaryFile(delete=False, suffix=".wav").name
    if not convert_to_wav(tmp_path, wav_path):
        try:
            os.unlink(tmp_path)
        except:
            pass
        try:
            os.unlink(wav_path)
        except:
            pass
        return {"error": "Ошибка конвертации аудио"}

    try:
        segments, info = whisper_model.transcribe(wav_path, language="ru", beam_size=5)
        recognized_text = " ".join([seg.text for seg in segments]).lower().strip()
        # ОЧИСТКА ОТ ЗНАКОВ ПРЕПИНАНИЯ
        recognized_text = clean_text(recognized_text)
    except Exception as e:
        recognized_text = ""
        print(f"Ошибка распознавания: {e}")

    try:
        os.unlink(tmp_path)
    except:
        pass
    try:
        os.unlink(wav_path)
    except:
        pass

    ETALON_WORDS = current_etalon.lower().split()
    ETALON_SET = set(ETALON_WORDS)
    recognized_words = recognized_text.split() if recognized_text else []
    word_count = len(recognized_words)

    # Лексика
    if word_count == 0 or len(ETALON_SET) == 0:
        lexical_score = 0
    else:
        recognized_set = set(recognized_words)
        common = recognized_set & ETALON_SET
        lexical_score = round(len(common) / len(ETALON_SET) * 100, 1)

    # Темп (с учётом абсурдных текстов)
    if duration > 0 and word_count > 0:
        words_per_minute = (word_count / duration) * 60

        if is_absurd_exercise(current_etalon_name):
            if 60 <= words_per_minute <= 100:
                tempo_score = 100
                tempo_feedback_text = "идеальный темп для сложного текста"
            elif words_per_minute < 60:
                tempo_score = max(0, round(100 - (60 - words_per_minute) / 60 * 100, 1))
                tempo_feedback_text = "можно чуть быстрее"
            else:
                tempo_score = max(0, round(100 - (words_per_minute - 100) / 100 * 100, 1))
                tempo_feedback_text = "очень быстро для такого текста"
        else:
            if 100 <= words_per_minute <= 140:
                tempo_score = 100
                tempo_feedback_text = "идеальный темп речи"
            elif words_per_minute < 100:
                tempo_score = max(0, round(100 - (100 - words_per_minute) / 100 * 100, 1))
                tempo_feedback_text = "речь слишком медленная"
            else:
                tempo_score = max(0, round(100 - (words_per_minute - 140) / 140 * 100, 1))
                tempo_feedback_text = "речь слишком быстрая"
    else:
        words_per_minute = 0
        tempo_score = 0
        tempo_feedback_text = "недостаточно слов"

    # Слова-паразиты
    orig_words = recognized_text.split() if recognized_text else []
    stop_words_found = [w for w in orig_words if w in STOP_WORDS]
    stop_words_score = max(0, 100 - len(stop_words_found) * 15) if stop_words_found else 100

    # Фонетика
    if word_count == 0 or len(ETALON_WORDS) == 0:
        phonetics_score = 0
    else:
        matches = 0
        min_len = min(len(recognized_words), len(ETALON_WORDS))
        for i in range(min_len):
            if recognized_words[i] == ETALON_WORDS[i]:
                matches += 1
        extra_words = max(0, len(recognized_words) - len(ETALON_WORDS))
        extra_penalty = min(30, extra_words * 10)
        base_score = (matches / len(ETALON_WORDS)) * 100
        phonetics_score = round(max(0, base_score - extra_penalty), 1)

    final_score = round(phonetics_score * 0.4 + lexical_score * 0.3 + tempo_score * 0.2 + stop_words_score * 0.1, 1)

    save_training_result(user_id, {
        "exercise_name": current_etalon_name, "mode": mode, "recognized_text": recognized_text,
        "etalon_text": current_etalon,
        "word_count": word_count, "word_count_etalon": len(ETALON_WORDS), "duration": duration,
        "words_per_minute": int(words_per_minute),
        "phonetics_score": phonetics_score, "lexical_score": lexical_score, "tempo_score": tempo_score,
        "stop_words_score": stop_words_score, "final_score": final_score, "unique_words_ratio": 0, "pauses_count": 0
    })

    return {
        "recognized_text": recognized_text or "(не распознано)",
        "phonetics_score": phonetics_score,
        "lexical_score": lexical_score,
        "tempo_score": tempo_score,
        "stop_words_score": stop_words_score,
        "final_score": final_score,
        "duration": round(duration, 1),
        "words_per_minute": int(words_per_minute),
        "tempo_feedback": tempo_feedback_text
    }


@app.post("/analyze_free")
async def analyze_free(file: UploadFile = File(...), duration: float = Form(10.0), topic: str = Form(""),
                       token: str = Form(None)):
    if not token or token not in session_user:
        return {"error": "Не авторизован"}

    user_id = session_user[token]["id"]

    with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    wav_path = tempfile.NamedTemporaryFile(delete=False, suffix=".wav").name
    if not convert_to_wav(tmp_path, wav_path):
        try:
            os.unlink(tmp_path)
        except:
            pass
        try:
            os.unlink(wav_path)
        except:
            pass
        return {"error": "Ошибка конвертации"}

    try:
        result = whisper_model.transcribe(wav_path, language="ru", fp16=False)
        recognized_text = result["text"].lower().strip()
        # ОЧИСТКА ОТ ЗНАКОВ ПРЕПИНАНИЯ
        recognized_text = clean_text(recognized_text)
    except Exception as e:
        recognized_text = ""
        print(f"Ошибка распознавания: {e}")

    try:
        os.unlink(tmp_path)
    except:
        pass
    try:
        os.unlink(wav_path)
    except:
        pass

    analysis = analyze_free_speech(recognized_text, duration, topic if topic else None)

    save_training_result(user_id, {
        "exercise_name": f"Свободная речь{f' (тема: {topic})' if topic else ''}",
        "mode": "free",
        "recognized_text": recognized_text,
        "etalon_text": "",
        "word_count": analysis["word_count"],
        "word_count_etalon": 0,
        "duration": analysis["duration"],
        "words_per_minute": analysis["words_per_minute"],
        "phonetics_score": 0,
        "lexical_score": 0,
        "tempo_score": analysis["tempo_score"],
        "stop_words_score": analysis["stop_words_score"],
        "final_score": analysis["final_score"],
        "unique_words_ratio": analysis["unique_ratio"],
        "pauses_count": 0
    })

    feedback = f"""Свободная речь{f' (тема: {topic})' if topic else ''}
Длительность: {analysis['duration']} сек
Темп: {analysis['words_per_minute']} слов/мин — {analysis['tempo_feedback']}
Разнообразие лексики: {analysis['lexical_diversity_feedback']}
Слова-паразиты: {analysis['stop_words_feedback']}
{analysis['topic_feedback']}
Общая оценка: {analysis['final_score']} / 100

Распознано: {recognized_text if recognized_text else '(не распознано)'}"""

    return {
        "recognized_text": recognized_text or "(не распознано)",
        "duration": analysis["duration"],
        "words_per_minute": analysis["words_per_minute"],
        "tempo_score": analysis["tempo_score"],
        "ttr_score": analysis["lexical_diversity_score"],
        "stop_words_score": analysis["stop_words_score"],
        "topic_score": analysis["topic_score"],
        "final_score": analysis["final_score"],
        "detailed_feedback": feedback,
        "word_count": analysis["word_count"],
        "unique_ratio": analysis["unique_ratio"],
        "stop_words_found": analysis["stop_words_found"]
    }


# ========== АБСУРД-ТРЕНИНГ ==========
ABSURD_EXERCISES = {
    "elephant": {
        "name": "Слон в холодильнике",
        "parts": {
            "1": "Гипотетически-концептуальная операционализационно-реконфигурационная модель инкорпорации слона в холодильный агрегат предполагает пространственно-геометрическую верификацию внутренне-объёмной архитектоники, сопровождаемую когнитивно-диссонансной редукцией несоразмерности габаритно-массовых параметров и абсурдно-рационализируемой установкой на реализуемость процедуры.",
            "2": "Далее реализуется алгоритмизируемо-декомпозиционная манипуляционно-интервенционная процедура: инициация дверно-открывающего акта холодильник, тотальная экстракция содержимого и компрессионно-пространственная псевдооптимизация, сопровождаемая иллюзорно-когнитивной убеждённостью в редуцируемости слонообразной морфологии до холодильнокамерной форм-фактора.",
            "3": "Финально реализуется интеграционно-коллапсирующая фаза: субъект, игнорируя физико-биомеханическую невозможность, осуществляет квази-завершённую инсталляцию, формируя псевдологически консистентную модель, где холодильник трансформируется в метафорический контейнер иррационально-гипертрофированных амбиций и комбинаторно-абсурдного когнитивного конструирования."
        }
    },
    "sasha": {
        "name": "Шла Саша по шоссе",
        "parts": {
            "1": "Шла Саша по шоссе, синхронизируя шоссейно-логистическо-сегментированные маршрутизационно-регламентационные сверхструктуры, систематизируя социосемантические субординационно-коммуникационные схемы и стабилизируя сенсорно-шумовые спектрально-рекурсивные конфигурации.",
            "2": "Сушку Саша сублимационно-сосредоточенно сосала, сопровождая процесс сверхскоростной спектрально-семантической саморегуляцией, субвокальной синхронизацией и шифрованно-сегментированной артикуляционно-шумовой реконфигурацией.",
            "3": "Шоссейная среда содрогалась: сверхинтенсивные субординационно-сигнальные сообщения смешивались с сейсмоакустическо-шумовыми шорохами, создавая гиперрекурсивную шуморезонансную архитектонику социоинформационно-шоссейной системы с сегментированно-структурированной сверхрегуляционной маршрутизацией."
        }
    },
    "collagen": {
        "name": "Коллагеново-липопротеиновый конгломерат",
        "parts": {
            "1": "Коллагеново-липопротеиновый гастрономическо-эмульсионный конгломерат подвергается высокоамплитудной термокаталитической денатурационно-ферментационной обработке: калиброванная мясобелково-коллагеновая субстанция, карбонизированная полимеризованной хрустяще-кристаллической коркой, инициирует коагуляционно-деструктивную трансформацию коллагеновых микроструктур.",
            "2": "Крупнопористая ферротермическо-конвекционная платформа достигает критико-температурной бифуркационной амплитуды, вследствие чего индуцированное гастрономическо-субстратное кипение катализирует многоуровневые кристаллизационно-денатурационные процессы.",
            "3": "Профессионально сертифицированный гастрономическо-технологический специалист компетентно контролирует структурно-консистентную архитектонику: коагулированный липопротеиново-коллагеновый конгломерат компонуется, сервируется и дегустируется согласно гастрономическо-регламентационным спецификациям."
        }
    }
}


@app.get("/absurd_exercises")
async def get_absurd_exercises():
    return ABSURD_EXERCISES


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)