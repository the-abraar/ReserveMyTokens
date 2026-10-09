from fastapi import FastAPI
from .database import engine, Base
from .models import ledger
from .routers import users, transactions

# Create tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="ReserveMyTokens API")

app.include_router(users.router, prefix="/users", tags=["users"])
app.include_router(transactions.router, prefix="/transactions", tags=["transactions"])

@app.get("/")
def read_root():
    return {"message": "Welcome to ReserveMyTokens API"}
