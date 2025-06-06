from sqlalchemy import Table, Column, Integer, String, Boolean, Float, DateTime
from sqlalchemy.sql import func
from db import metadata

users = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("username", String),
    Column("ton_balance", Float, default=0),
    Column("usdt_balance", Float, default=0),
)

games = Table(
    "games",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", Integer),
    Column("game", String),
    Column("bet", Float),
    Column("result", String),
    Column("win", Boolean),
    Column("timestamp", DateTime(timezone=True), server_default=func.now()),
)
