from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

#DATABASE_URL = "postgresql://postgres:Dd1122@localhost:5432/mujeebkau_db1"
DATABASE_URL = "postgresql://postgres:135246@localhost:5432/database"
#DATABASE_URL = "postgresql://postgres:ssaa56@localhost:5432/mujeebkau"

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

