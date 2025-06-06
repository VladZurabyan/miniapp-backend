from sqlalchemy import Table, Column, BigInteger, String, Boolean, Float, DateTime, ForeignKey, Text
from sqlalchemy.sql import func
from db import metadata

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
