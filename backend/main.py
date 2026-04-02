from contextlib import asynccontextmanager
from fastapi import FastAPI
from dotenv import load_dotenv

load_dotenv()

from fastapi.middleware.cors import CORSMiddleware
from api import endpoints
from api import batch_endpoints_optimized


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: nothing extra needed (services self-initialise)
    yield
    # Shutdown: cleanly close any remaining connection pools
    await endpoints.optimized_ocr.cleanup()


app = FastAPI(
    title="Automated Answer Sheet Evaluation System",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Standard pipeline endpoints  →  /api/*
app.include_router(endpoints.router, prefix="/api")

# Ultra-optimized batch endpoints  →  /api/batch/*
app.include_router(batch_endpoints_optimized.router)


@app.get("/")
def read_root():
    return {"message": "Welcome to the Answer Sheet Evaluation API"}


@app.get("/health")
def health_check():
    return {"status": "ok"}

