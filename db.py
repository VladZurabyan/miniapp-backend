import os
from databases import Database
from sqlalchemy import create_engine, MetaData

DATABASE_URL = os.getenv("DATABASE_URL")  # ⚠️ Получаем из окружения

if not DATABASE_URL:
    raise RuntimeError("❌ DATABASE_URL is not set!")

database = Database(DATABASE_URL)
metadata = MetaData()
engine = create_engine(DATABASE_URL)


