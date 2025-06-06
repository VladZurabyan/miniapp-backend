from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
from uuid import uuid4
import sqlite3

app = FastAPI()

# 🔓 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://telegram-mini-app-two-lake.vercel.app"],  # Без "/" на конце
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = "database.db"

def get_db():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

# 🗃️ Инициализация БД
def init_db():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT,
            ton_balance REAL DEFAULT 0,
            usdt_balance REAL DEFAULT 0
        );
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS games (
            id TEXT PRIMARY KEY,
            user_id INTEGER,
            game TEXT,
            bet REAL,
            result TEXT,
            win BOOLEAN,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """)
        conn.commit()

init_db()

# 📦 Модели
class UserCreate(BaseModel):
    id: int
    username: str

class BalanceUpdate(BaseModel):
    id: int
    currency: str
    amount: float

class GameRecord(BaseModel):
    user_id: int
    game: str
    bet: float
    result: str
    win: bool

# ✅ Роуты
@app.get("/")
def root():
    return {"status": "Backend работает!"}

@app.post("/register")
def register_user(user: UserCreate):
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO users (id, username) VALUES (?, ?)", (user.id, user.username))
            conn.commit()
        return {"status": "registered"}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="User already exists")

@app.get("/balance/{user_id}")
def get_balance(user_id: int):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT ton_balance, usdt_balance FROM users WHERE id=?", (user_id,))
        row = cursor.fetchone()
        if row:
            return {"ton": row[0], "usdt": row[1]}
        else:
            raise HTTPException(status_code=404, detail="User not found")

@app.post("/balance/update")
def update_balance(update: BalanceUpdate):
    if update.currency not in ["ton", "usdt"]:
        raise HTTPException(status_code=400, detail="Invalid currency")

    column = f"{update.currency}_balance"
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(f"UPDATE users SET {column} = {column} + ? WHERE id=?", (update.amount, update.id))
        conn.commit()
    return {"status": "updated"}

@app.post("/game")
def record_game(game: GameRecord):
    game_id = str(uuid4())
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO games (id, user_id, game, bet, result, win)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (game_id, game.user_id, game.game, game.bet, game.result, game.win))
        conn.commit()
    return {"status": "recorded", "game_id": game_id}

@app.get("/games/{user_id}")
def user_games(user_id: int):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT game, bet, result, win, timestamp FROM games WHERE user_id=? ORDER BY timestamp DESC", (user_id,))
        rows = cursor.fetchall()
        return [{"game": g, "bet": b, "result": r, "win": w, "timestamp": t} for g, b, r, w, t in rows]

@app.post("/init")
def init_user(user: UserCreate):
    with get_db() as conn:
        cursor = conn.cursor()
        # Создание пользователя, если его ещё нет
        cursor.execute("INSERT OR IGNORE INTO users (id, username) VALUES (?, ?)", (user.id, user.username))
        # Получение баланса
        cursor.execute("SELECT ton_balance, usdt_balance FROM users WHERE id=?", (user.id,))
        row = cursor.fetchone()
        if row:
            return {"ton": row[0], "usdt": row[1]}
        else:
            raise HTTPException(status_code=500, detail="Ошибка при инициализации пользователя")

