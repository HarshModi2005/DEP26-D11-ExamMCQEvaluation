import os
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

# CORS: the spec forbids combining allow_credentials=True with a wildcard origin
# (browsers reject the preflight). Read a comma-separated list from CORS_ORIGINS;
# when unset, fall back to wildcard WITHOUT credentials — which is what this
# backend actually needs since auth is bearer-token based (Supabase on the
# frontend), not cookie-based.
_raw_origins = os.getenv("CORS_ORIGINS", "").strip()
if _raw_origins:
    _allow_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]
    _allow_credentials = True
else:
    _allow_origins = ["*"]
    _allow_credentials = False

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_credentials=_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# All routers declare their own prefix internally; main.py just mounts them.
app.include_router(endpoints.router)                     # /api/*
app.include_router(batch_endpoints_optimized.router)     # /api/batch/*, /api/pdf-runs/*
app.include_router(code_eval_endpoints.router)           # /api/code-eval/*


@app.get("/")
def read_root():
    return {"message": "Welcome to the Answer Sheet Evaluation API"}


@app.get("/health")
def health_check():
    return {"status": "ok"}

