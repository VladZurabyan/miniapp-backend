from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from uuid import uuid4
from random import random
from db import database, metadata, engine
import asyncio
import logging

from sqlalchemy.dialects.postgresql import insert as pg_insert

from models import users, games, safe_sessions  
from random import randint

# ✅ Инициализация FastAPI
app = FastAPI()

# ✅ CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://telegram-mini-app-two-lake.vercel.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ Подключение к БД
@app.on_event("startup")
async def startup():
    await database.connect()

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()

# ✅ Pydantic модели
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
    result: str  # "pending", "win", "lose"
    win: bool
    currency: str
    prize_amount: float = 0.0
    final: bool = False  # 👈 добавили

class BalanceSubscribe(BaseModel):
    user_id: int
    current_ton: float
    current_usdt: float

class UserIdOnly(BaseModel):
    id: int

class SafeStart(BaseModel):
    user_id: int
    currency: str
    bet: float

class SafeGuess(BaseModel):
    session_id: str
    user_id: int
    guess: list[int]

class SafeHint(BaseModel):
    session_id: str
    user_id: int

class CoinStart(BaseModel):
    user_id: int
    username: str
    currency: str  # "ton" или "usdt"
    bet: float
    choice: str     # "heads" или "tails"

class BoxesRequest(BaseModel):
    user_id: int
    username: str
    currency: str
    bet: float
    choice: int  # 👈 добавлен выбор коробки игроком (1, 2 или 3)


# 🧠 Хранилище балансов в памяти
user_balances_cache = {}

# ✅ Создаём таблицы (если не существует)
metadata.create_all(engine)

# ✅ Роуты
@app.get("/")
async def root():
    return {"status": "Backend работает через PostgreSQL!"}

@app.post("/init")
async def init_user(user: UserCreate):
    stmt = pg_insert(users).values(
        id=user.id,
        username=user.username,
        ton_balance=0.0,
        usdt_balance=0.0
    ).on_conflict_do_nothing(index_elements=["id"])
    await database.execute(stmt)

    row = await database.fetch_one(users.select().where(users.c.id == user.id))
    if not row:
        raise HTTPException(status_code=500, detail="Пользователь не найден")
    return {"ton": row["ton_balance"], "usdt": row["usdt_balance"]}

@app.post("/balance/add")
async def update_balance(update: BalanceUpdate):
    if update.currency not in ["ton", "usdt"]:
        raise HTTPException(status_code=400, detail="Invalid currency")
    col = users.c.ton_balance if update.currency == "ton" else users.c.usdt_balance
    query = users.update().where(users.c.id == update.id).values({col: col + update.amount})
    await database.execute(query)

    # 💾 Обновляем кэш
    row = await database.fetch_one(users.select().where(users.c.id == update.id))
    user_balances_cache[str(update.id)] = {"ton": row["ton_balance"], "usdt": row["usdt_balance"]}

    return {"status": "updated"}

@app.post("/game")
async def record_game(game: GameRecord):
    currency = game.currency.lower()
    if currency not in ["ton", "usdt"]:
        raise HTTPException(status_code=400, detail="Invalid currency")

    balance_col = users.c.ton_balance if currency == "ton" else users.c.usdt_balance

    if not game.final:
        query = (
            users.update()
            .where(users.c.id == game.user_id)
            .where(balance_col >= game.bet)
            .values({balance_col: balance_col - game.bet})
            .returning(balance_col)
        )
        updated = await database.fetch_one(query)
        if not updated:
            raise HTTPException(status_code=400, detail="Недостаточно средств")
    else:
        if game.win and game.prize_amount > 0:
            await database.execute(
                users.update()
                .where(users.c.id == game.user_id)
                .values({balance_col: balance_col + game.prize_amount})
            )

    # 🧾 Записываем игру
    game_id = str(uuid4())
    await database.execute(
        games.insert().values(
            id=game_id,
            user_id=game.user_id,
            game=game.game,
            bet=game.bet,
            result=game.result,
            win=game.win
        )
    )

    # 💾 Обновляем кэш
    row = await database.fetch_one(users.select().where(users.c.id == game.user_id))
    user_balances_cache[str(game.user_id)] = {"ton": row["ton_balance"], "usdt": row["usdt_balance"]}

    return await get_balance(game.user_id)

@app.post("/balance/prize")
async def add_prize(update: BalanceUpdate):
    if update.currency not in ["ton", "usdt"]:
        raise HTTPException(status_code=400, detail="Invalid currency")

    col = users.c.ton_balance if update.currency == "ton" else users.c.usdt_balance

    query = users.update().where(users.c.id == update.id).values({col: col + update.amount}).returning(col)
    result = await database.fetch_one(query)

    # 💾 Обновляем кэш
    row = await database.fetch_one(users.select().where(users.c.id == update.id))
    user_balances_cache[str(update.id)] = {"ton": row["ton_balance"], "usdt": row["usdt_balance"]}

    return {"status": "prize_added", "new_balance": result[0]}

@app.get("/games/{user_id}")
async def get_games(user_id: int):
    query = games.select().where(games.c.user_id == user_id).order_by(games.c.timestamp.desc())
    rows = await database.fetch_all(query)
    return [dict(row) for row in rows]

@app.get("/balance/{user_id}")
async def get_balance(user_id: int):
    row = await database.fetch_one(users.select().where(users.c.id == user_id))
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return {"ton": row["ton_balance"], "usdt": row["usdt_balance"]}

# ✅ Настройка логирования один раз (в начале backend)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

@app.post("/balance/subscribe")
async def subscribe_balance(data: BalanceSubscribe):
    user_id = data.user_id
    client_ton = round(data.current_ton, 2)
    client_usdt = round(data.current_usdt, 2)

    logging.info(f"📡 Подписка от user_id={user_id} | client TON={client_ton}, USDT={client_usdt}")

    for _ in range(30):
        await asyncio.sleep(0.1)

        row = await database.fetch_one(users.select().where(users.c.id == user_id))
        if row:
            ton = round(float(row["ton_balance"]), 2)
            usdt = round(float(row["usdt_balance"]), 2)

            if ton != client_ton or usdt != client_usdt:
                logging.info(f"🔄 Баланс обновился у user_id={user_id} → TON={ton}, USDT={usdt}")
                return {
                    "update": True,
                    "ton": ton,
                    "usdt": usdt
                }

    logging.info(f"⏱ Нет изменений за 60 сек у user_id={user_id}")
    return {"update": False}




@app.post("/balance/force")
async def force_balance(user: UserIdOnly):
    row = await database.fetch_one(users.select().where(users.c.id == user.id))
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "ton": float(row["ton_balance"]),
        "usdt": float(row["usdt_balance"])
    }

@app.post("/safe/start")
async def start_safe_game(data: SafeStart):
    currency = data.currency.lower()
    if currency not in ["ton", "usdt"]:
        raise HTTPException(status_code=400, detail="Неверная валюта")

    balance_col = users.c.ton_balance if currency == "ton" else users.c.usdt_balance

    # Получаем пользователя и проверяем баланс
    user = await database.fetch_one(users.select().where(users.c.id == data.user_id))
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    current_balance = float(user[balance_col.name])
    if current_balance < data.bet:
        raise HTTPException(status_code=400, detail="Недостаточно средств")

    # ❌ Удалено: списание баланса здесь

    # Генерация кода и создание сессии
    code = [randint(0, 9) for _ in range(3)]
    session_id = str(uuid4())

    await database.execute(
        safe_sessions.insert().values(
            id=session_id,
            user_id=data.user_id,
            currency=currency,
            bet=data.bet,
            code=code,
            attempts=0,
            used_hint=False,
            is_finished=False
        )
    )

    # Обновляем кэш (баланс не менялся, но пусть будет)
    row = await database.fetch_one(users.select().where(users.c.id == data.user_id))
    user_balances_cache[str(data.user_id)] = {"ton": row["ton_balance"], "usdt": row["usdt_balance"]}

    # Запись в таблицу games
    await database.execute(
        games.insert().values(
            id=session_id,
            user_id=data.user_id,
            game="Safe Cracker",
            bet=data.bet,
            result="pending",
            win=False
        )
    )

    return {
        "success": True,
        "session_id": session_id
    }


@app.post("/safe/guess")
async def safe_guess(data: SafeGuess):
    session = await database.fetch_one(safe_sessions.select().where(safe_sessions.c.id == data.session_id))
    if not session:
        raise HTTPException(status_code=404, detail="Сессия не найдена")

    if session["is_finished"]:
        raise HTTPException(status_code=400, detail="Игра уже завершена")

    if session["user_id"] != data.user_id:
        raise HTTPException(status_code=403, detail="Сессия не принадлежит пользователю")

    if not isinstance(data.guess, list) or len(data.guess) != 3 or not all(isinstance(d, int) for d in data.guess):
        raise HTTPException(status_code=400, detail="Неверный формат кода")

    correct_code = session["code"]
    attempts = session["attempts"]
    bet = session["bet"]
    currency = session["currency"]

    if attempts >= 3:
        raise HTTPException(status_code=400, detail="Попытки закончились")

    is_win = data.guess == correct_code
    updated_attempts = attempts + 1

    if is_win:
        prize = bet * 10
        balance_col = users.c.ton_balance if currency == "ton" else users.c.usdt_balance

        await database.execute(
            users.update()
            .where(users.c.id == data.user_id)
            .values({balance_col: balance_col + prize})
        )

        await database.execute(
            games.update()
            .where(games.c.id == data.session_id)
            .values(result="win", win=True)
        )

        await database.execute(
            safe_sessions.update()
            .where(safe_sessions.c.id == data.session_id)
            .values(attempts=updated_attempts, is_finished=True)
        )

        # 🧠 Обновляем кэш
        row = await database.fetch_one(users.select().where(users.c.id == data.user_id))
        user_balances_cache[str(data.user_id)] = {"ton": row["ton_balance"], "usdt": row["usdt_balance"]}

        logging.info(f"🎉 Победа! user_id={data.user_id} выиграл {prize} {currency.upper()}")

        return {
            "result": "win",
            "prize": prize,
            "code": correct_code
        }

    elif updated_attempts >= 3:
        await database.execute(
            games.update()
            .where(games.c.id == data.session_id)
            .values(result="lose", win=False)
        )
        await database.execute(
            safe_sessions.update()
            .where(safe_sessions.c.id == data.session_id)
            .values(attempts=updated_attempts, is_finished=True)
        )

        logging.info(f"❌ Проигрыш. user_id={data.user_id}, код был: {correct_code}")

        return {
            "result": "lose",
            "code": correct_code
        }

    else:
        await database.execute(
            safe_sessions.update()
            .where(safe_sessions.c.id == data.session_id)
            .values(attempts=updated_attempts)
        )

        logging.info(f"➖ Попытка {updated_attempts} от user_id={data.user_id}")

        return {
            "result": "try_again",
            "attempts_left": 3 - updated_attempts
        }

@app.post("/safe/hint")
async def safe_hint(data: SafeHint):
    session = await database.fetch_one(safe_sessions.select().where(safe_sessions.c.id == data.session_id))
    if not session:
        raise HTTPException(status_code=404, detail="Сессия не найдена")

    if session["is_finished"]:
        raise HTTPException(status_code=400, detail="Игра уже завершена")

    if session["used_hint"]:
        raise HTTPException(status_code=400, detail="Подсказка уже использована")

    if session["user_id"] != data.user_id:
        raise HTTPException(status_code=403, detail="Сессия не принадлежит пользователю")

    currency = session["currency"]
    hint_cost = 1.0

    balance_col = users.c.ton_balance if currency == "ton" else users.c.usdt_balance

    user_row = await database.fetch_one(users.select().where(users.c.id == data.user_id))
    if not user_row:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    current_balance = user_row[balance_col.name]
    if current_balance < hint_cost:
        raise HTTPException(status_code=400, detail="Недостаточно средств для подсказки")

    await database.execute(
        users.update()
        .where(users.c.id == data.user_id)
        .values({balance_col: balance_col - hint_cost})
    )

    await database.execute(
        safe_sessions.update()
        .where(safe_sessions.c.id == data.session_id)
        .values(used_hint=True)
    )

    # 🧠 Обновляем кэш
    row = await database.fetch_one(users.select().where(users.c.id == data.user_id))
    user_balances_cache[str(data.user_id)] = {"ton": row["ton_balance"], "usdt": row["usdt_balance"]}

    correct_code = session["code"]
    hint_digit = correct_code[0]

    logging.info(f"💡 Подсказка для user_id={data.user_id}: {hint_digit}")

    return {
        "hint": hint_digit,
        "cost": hint_cost
    }







@app.post("/coin/start")
async def coin_start(data: CoinStart):
    if data.choice not in ["heads", "tails"]:
        raise HTTPException(status_code=400, detail="Сторона может быть только 'heads' или 'tails'")

    currency = data.currency.lower()
    if currency not in ["ton", "usdt"]:
        raise HTTPException(status_code=400, detail="Неверная валюта")

    balance_col = users.c.ton_balance if currency == "ton" else users.c.usdt_balance

    # 🔍 Проверка пользователя и баланса
    row = await database.fetch_one(users.select().where(users.c.id == data.user_id))
    if not row:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if row[balance_col.name] < data.bet:
        raise HTTPException(status_code=400, detail="Недостаточно средств")

    # 💳 Списываем ставку
    await database.execute(
        users.update()
        .where(users.c.id == data.user_id)
        .values({balance_col: balance_col - data.bet})
    )

    # 🎯 Вероятность победы — 2 из 12 (≈16.7%)
    is_win = random() < (2 / 12)
    result = data.choice if is_win else ("tails" if data.choice == "heads" else "heads")
    prize = round(data.bet * 2, 2) if is_win else 0.0

    # 💰 Если выиграл — начисляем приз
    if is_win:
        await database.execute(
            users.update()
            .where(users.c.id == data.user_id)
            .values({balance_col: balance_col + prize})
        )

    # 🧾 Записываем игру
    await database.execute(
        games.insert().values(
            id=str(uuid4()),
            user_id=data.user_id,
            game="Coin",
            bet=data.bet,
            result="win" if is_win else "lose",
            win=is_win
        )
    )

    # 🔁 Обновляем кэш
    new_row = await database.fetch_one(users.select().where(users.c.id == data.user_id))
    user_balances_cache[str(data.user_id)] = {
        "ton": new_row["ton_balance"],
        "usdt": new_row["usdt_balance"]
    }

    return {
        "result": result,   # "heads" / "tails"
        "win": is_win,
        "prize": prize
    }





@app.post("/boxes/start")
async def boxes_start(data: BoxesRequest):
    currency = data.currency.lower()
    if currency not in ["ton", "usdt"]:
        raise HTTPException(status_code=400, detail="Неверная валюта")

    balance_col = users.c.ton_balance if currency == "ton" else users.c.usdt_balance

    row = await database.fetch_one(users.select().where(users.c.id == data.user_id))
    if not row:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if row[balance_col.name] < data.bet:
        raise HTTPException(status_code=400, detail="Недостаточно средств")

    # 🧾 Списываем ставку
    await database.execute(
        users.update()
        .where(users.c.id == data.user_id)
        .values({balance_col: balance_col - data.bet})
    )

    # 🎯 Логика победы
    chosen_box = data.choice
    force_win = random.random() < 0.2  # 20%
    regular_win = random.random() < 0.01  # 1%
    is_win = force_win or regular_win

    if is_win:
        winning_box = chosen_box
    else:
        other_boxes = [b for b in [1, 2, 3] if b != chosen_box]
        winning_box = random.choice(other_boxes)

    prize = round(data.bet * 2, 2) if is_win else 0.0

    if is_win:
        await database.execute(
            users.update()
            .where(users.c.id == data.user_id)
            .values({balance_col: balance_col + prize})
        )

    # 📝 Запись игры
    await database.execute(
        games.insert().values(
            id=str(uuid4()),
            user_id=data.user_id,
            game="Boxes",
            bet=data.bet,
            result=f"Выбрал {chosen_box}, приз в {winning_box}",
            win=is_win
        )
    )

    # 🔄 Обновление кеша
    new_row = await database.fetch_one(users.select().where(users.c.id == data.user_id))
    user_balances_cache[str(data.user_id)] = {
        "ton": new_row["ton_balance"],
        "usdt": new_row["usdt_balance"]
    }

    return {
        "win": is_win,
        "prize": prize,
        "chosenBox": chosen_box,
        "winningBox": winning_box
    }



























@app.get("/health")
async def health_check():
    try:
        if not database.is_connected:
            await database.connect()
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

