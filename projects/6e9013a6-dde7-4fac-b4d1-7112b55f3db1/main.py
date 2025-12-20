from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.requests import Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

app = FastAPI()

# Enable CORS for all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

# Define a Pydantic schema for the user
class User(BaseModel):
    username: str
    email: str

# Define a route for the user
@app.get('/user')
async def read_user(request: Request):
    return JSONResponse(content={'message': 'Hello, user!'}, media_type='application/json')

# Run the application with uvicorn
if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8000)
