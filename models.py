from sqlalchemy import Table, Column, BigInteger, String, Boolean, Float, DateTime, ForeignKey, Text
from sqlalchemy.sql import func
from db import metadata
from sqlalchemy import Integer, JSON

users = Table(
    "users",
    metadata,
    Column("id", BigInteger, primary_key=True, nullable=False),  # ← исправлено
    Column("username", String(100), nullable=False),
    Column("ton_balance", Float, nullable=False, default=0.0),
    Column("usdt_balance", Float, nullable=False, default=0.0),
)

games = Table(
    "games",
    metadata,
    Column("id", String, primary_key=True, nullable=False),
    Column("user_id", BigInteger, ForeignKey("users.id"), nullable=False),  # ← исправлено
    Column("game", String(50), nullable=False),
    Column("bet", Float, nullable=False),
    Column("result", Text, nullable=False),
    Column("win", Boolean, nullable=False),
    Column("timestamp", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

safe_sessions = Table(
    "safe_sessions",
    metadata,
    Column("id", String, primary_key=True, nullable=False),  # UUID или любой уникальный ID игры
    Column("user_id", BigInteger, ForeignKey("users.id"), nullable=False),
    Column("currency", String(10), nullable=False),          # 'ton' или 'usdt'
    Column("bet", Float, nullable=False),
    Column("code", JSON, nullable=False),                    # Например: [1, 4, 7]
    Column("attempts", Integer, default=0, nullable=False),
    Column("used_hint", Boolean, default=False, nullable=False),
    Column("is_finished", Boolean, default=False, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)
