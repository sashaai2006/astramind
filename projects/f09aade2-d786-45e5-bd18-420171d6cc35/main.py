from fastapi import FastAPI
from pydantic import BaseModel
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

SQLALCHEMY_DATABASE_URL = "sqlite:///database.db"

engine = create_engine(SQLALCHEMY_DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

app = FastAPI()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

@app.get("/items")
def read_items():
    return ["Item 1", "Item 2"]

@app.get("/users")
def read_users():
    return ["User 1", "User 2"]

@app.get("/items/{item_id}")
def read_item(item_id: int):
    return {"item_id": item_id}

from . import routers
app.include_router(routers.users.router)
app.include_router(routers.items.router)
