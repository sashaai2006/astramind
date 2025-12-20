from fastapi import FastAPI
app = FastAPI()
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import jwt
import uvicorn

# Database configuration
SQLALCHEMY_DATABASE_URL = "sqlite:///database.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# JWT configuration
SECRET_KEY = "secret_key"

# Pydantic configuration
from pydantic import BaseModel

class User(BaseModel):
    id: int
    name: str
    email: str


# Main function
if __name__ == "__main__":
    import os
    if os.path.exists("local.env"):
        for line in open("local.env"):
            key, val = line.strip().split("=")
            os.environ[key] = val
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
