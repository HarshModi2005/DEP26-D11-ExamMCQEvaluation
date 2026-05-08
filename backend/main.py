from contextlib import asynccontextmanager
from fastapi import FastAPI
from dotenv import load_dotenv

load_dotenv()

from fastapi.middleware.cors import CORSMiddleware
from api import endpoints
from api import batch_endpoints_optimized
from api import code_eval_endpoints


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: warm up Supabase pool if cache is configured to use it
    import os
    if os.getenv("CACHE_BACKEND", "sqlite").strip().lower() == "supabase":
        try:
            from services.supabase_client import get_pool
            await get_pool()
        except Exception as e:
            print(f"⚠️  Supabase pool init failed at startup: {e}")
    yield
    # Shutdown: cleanly close any remaining connection pools
    await endpoints.optimized_ocr.cleanup()
    try:
        from services.supabase_client import close_pool
        await close_pool()
    except Exception as e:
        print(f"⚠️  Supabase pool close failed at shutdown: {e}")


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

# Code evaluation endpoints  →  /api/code-eval/*
app.include_router(code_eval_endpoints.router)


@app.get("/")
def read_root():
    return {"message": "Welcome to the Answer Sheet Evaluation API"}


@app.get("/health")
def health_check():
    return {"status": "ok"}

