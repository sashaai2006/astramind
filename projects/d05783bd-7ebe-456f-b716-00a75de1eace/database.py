import sqlite3
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Database configuration
DATABASE_URL = "sqlite:///database.db"

# Create engine
engine = create_engine(DATABASE_URL)

# Create session maker
Session = sessionmaker(bind=engine)

# Create base class
Base = declarative_base()

# Define User table
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String)
    email = Column(String)

# Create tables
Base.metadata.create_all(engine)

# Create session
session = Session()

# Function to get all users
def get_users():
    return session.query(User).all()

# Function to add user
def add_user(username, email):
    user = User(username=username, email=email)
    session.add(user)
    session.commit()

# Function to delete user
def delete_user(id):
    user = session.query(User).get(id)
    if user:
        session.delete(user)
        session.commit()
