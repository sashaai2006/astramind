
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import jwt, JWTError
from pydantic import BaseModel
from datetime import datetime, timedelta
from database import Session, User

# Define the secret key for JWT
SECRET_KEY = "09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7"

# Define the algorithm for JWT
ALGORITHM = "HS256"

# Define the expiration time for JWT
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Define the Pydantic schema for user credentials
class UserCredentials(BaseModel):
    username: str
    password: str

# Define the OAuth2 scheme for JWT authentication
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# Function to verify user credentials
def verify_user_credentials(username: str, password: str):
    session = Session()
    user = session.query(User).filter(User.username == username).first()
    if user and user.password == password:
        return user
    return None

# Function to generate a JWT token
def generate_token(user: User):
    payload = {
        "sub": user.username,
        "exp": datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

# Function to authenticate a user
async def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if username:
            session = Session()
            user = session.query(User).filter(User.username == username).first()
            return user
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    return None
