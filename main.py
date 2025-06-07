from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from uuid import uuid4
import asyncio
import logging

from sqlalchemy.dialects.postgresql import insert as pg_insert

from db import database, metadata, engine
from models import users, games

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
    user_id = str(data.user_id)
    client_ton = round(data.current_ton, 2)
    client_usdt = round(data.current_usdt, 2)

    logging.info(f"📡 Подписка от user_id={user_id} | client TON={client_ton}, USDT={client_usdt}")

    for i in range(60):  # ⏳ до 60 сек
        await asyncio.sleep(1)

        latest = user_balances_cache.get(user_id)
        if latest:
            ton = round(latest["ton"], 2)
            usdt = round(latest["usdt"], 2)

            if ton != client_ton or usdt != client_usdt:
                logging.info(f"🔄 Обновление для user_id={user_id} → TON={ton}, USDT={usdt}")
                return {
                    "update": True,
                    "ton": ton,
                    "usdt": usdt
                }

    logging.info(f"⏱ Нет изменений за 60 сек для user_id={user_id}")
    return {"update": False}
