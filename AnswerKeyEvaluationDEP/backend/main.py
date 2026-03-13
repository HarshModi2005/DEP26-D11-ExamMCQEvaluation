from fastapi import FastAPI
from dotenv import load_dotenv

load_dotenv()

from fastapi.middleware.cors import CORSMiddleware
from api import endpoints

app = FastAPI(title="Automated Answer Sheet Evaluation System")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(endpoints.router, prefix="/api")

@app.get("/")
def read_root():
    return {"message": "Welcome to the Answer Sheet Evaluation API"}

@app.get("/health")
def health_check():
    return {"status": "ok"}
