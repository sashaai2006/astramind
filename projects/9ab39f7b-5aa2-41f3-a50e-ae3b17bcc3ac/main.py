from fastapi import FastAPI
from pydantic import BaseModel
from sqlite3 import connect

app = FastAPI()

class Health(BaseModel):
    status: str

@app.get("/api/health")
def read_health():
    conn = connect(':memory:')
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS health (status TEXT)")
    cur.execute("INSERT INTO health VALUES ('ok')")
    conn.commit()
    conn.close()
    return Health(status="ok")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
