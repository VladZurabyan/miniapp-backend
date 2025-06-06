from databases import Database
from sqlalchemy import create_engine, MetaData

DATABASE_URL = "postgresql://admin:kfL519NsqWjfOgRe5eUQqZF3QFSgefNX@dpg-d11gaf0gjchc73807k4g-a.oregon-postgres.render.com/miniapp"

database = Database(DATABASE_URL)
metadata = MetaData()
engine = create_engine(DATABASE_URL)
