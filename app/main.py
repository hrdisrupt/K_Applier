"""
K_AutoApply - Automated Job Application Service
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.database import create_db_and_tables
from .core.config import get_settings
from .api.applications import router as applications_router

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    # Startup
    create_db_and_tables()
    print("[AUTOAPPLY] Database initialized", flush=True)
    yield
    # Shutdown
    print("[AUTOAPPLY] Shutting down", flush=True)


app = FastAPI(
    title="K_AutoApply",
    description="Automated Job Application Service for Kangrats",
    version="1.0.0",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(applications_router, prefix="/api")


@app.get("/")
def root():
    """API info"""
    return {
        "service": "K_AutoApply",
        "version": "1.0.0",
        "description": "Automated Job Application Service",
        "docs": "/docs"
    }


@app.get("/health")
def health():
    """Health check"""
    return {"status": "healthy"}
