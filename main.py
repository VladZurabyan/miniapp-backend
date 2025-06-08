from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from uuid import uuid4
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

    # Проверка баланса
    query = users.select().where(users.c.id == data.user_id)
    user = await database.fetch_one(query)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    current_balance = float(user[balance_col.name])
    if current_balance < data.bet:
        raise HTTPException(status_code=400, detail="Недостаточно средств")

    # Списание ставки
    await database.execute(
        users.update()
        .where(users.c.id == data.user_id)
        .values({balance_col: balance_col - data.bet})
    )

    # Генерация кода
    code = [randint(0, 9) for _ in range(3)]
    session_id = str(uuid4())

    # Запись в safe_sessions
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

    # Обновление кэша баланса
    row = await database.fetch_one(users.select().where(users.c.id == data.user_id))
    user_balances_cache[str(data.user_id)] = {"ton": row["ton_balance"], "usdt": row["usdt_balance"]}

    # Запись в игры как pending
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

    return {"session_id": session_id}

@app.post("/safe/guess")
async def safe_guess(data: SafeGuess):
    session = await database.fetch_one(safe_sessions.select().where(safe_sessions.c.id == data.session_id))
    if not session:
        raise HTTPException(status_code=404, detail="Сессия не найдена")
    if session["is_finished"]:
        raise HTTPException(status_code=400, detail="Игра уже завершена")

    correct_code = session["code"]
    attempts = session["attempts"]
    bet = session["bet"]
    currency = session["currency"]

    if attempts >= 3:
        raise HTTPException(status_code=400, detail="Попытки закончились")

    # Проверка кода
    is_win = data.guess == correct_code
    updated_attempts = attempts + 1

    if is_win:
        prize = bet * 3
        balance_col = users.c.ton_balance if currency == "ton" else users.c.usdt_balance

        # Обновляем баланс
        await database.execute(
            users.update()
            .where(users.c.id == data.user_id)
            .values({balance_col: balance_col + prize})
        )

        # Обновляем игру (win)
        await database.execute(
            games.update()
            .where(games.c.id == data.session_id)
            .values(result="win", win=True)
        )

        # Завершаем сессию
        await database.execute(
            safe_sessions.update()
            .where(safe_sessions.c.id == data.session_id)
            .values(attempts=updated_attempts, is_finished=True)
        )

        return {
            "result": "win",
            "prize": prize,
            "code": correct_code
        }

    elif updated_attempts >= 3:
        # Проигрыш
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

        return {
            "result": "lose",
            "code": correct_code
        }

    else:
        # Просто увеличиваем attempts
        await database.execute(
            safe_sessions.update()
            .where(safe_sessions.c.id == data.session_id)
            .values(attempts=updated_attempts)
        )

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

    currency = session["currency"]
    bet = session["bet"]
    hint_cost = round(bet / 3, 2)

    balance_col = users.c.ton_balance if currency == "ton" else users.c.usdt_balance

    # Проверка баланса
    user_row = await database.fetch_one(users.select().where(users.c.id == data.user_id))
    if not user_row:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    current_balance = user_row[balance_col.name]
    if current_balance < hint_cost:
        raise HTTPException(status_code=400, detail="Недостаточно средств для подсказки")

    # Списываем стоимость подсказки
    await database.execute(
        users.update()
        .where(users.c.id == data.user_id)
        .values({balance_col: balance_col - hint_cost})
    )

    # Обновляем used_hint = True
    await database.execute(
        safe_sessions.update()
        .where(safe_sessions.c.id == data.session_id)
        .values(used_hint=True)
    )

    # Возвращаем первую правильную цифру
    correct_code = session["code"]
    hint_digit = correct_code[0]

    return {
        "hint": hint_digit,
        "cost": hint_cost
    }
