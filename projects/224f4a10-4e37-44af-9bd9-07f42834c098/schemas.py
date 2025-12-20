from pydantic import BaseModel
from pydantic import EmailStr

class User(BaseModel):
    id: int
    name: str

class Token(BaseModel):
    access_token: str
    token_type: str

class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str

class UserUpdate(BaseModel):
    name: str
    email: EmailStr

class OAuth2PasswordRequestForm(BaseModel):
    username: str
    password: str
    grant_type: str = "password"
