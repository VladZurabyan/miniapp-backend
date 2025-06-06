import os
from dotenv import load_dotenv
from databases import Database
from sqlalchemy import create_engine, MetaData

# Загружаем переменные окружения из .env
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("❌ DATABASE_URL не задан в окружении!")

database = Database(DATABASE_URL)
metadata = MetaData()
engine = create_engine(DATABASE_URL)
