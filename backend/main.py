import os
import sys

# Add backend directory to sys.path for seamless relative imports
backend_dir = os.path.dirname(os.path.abspath(__file__))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text

import database
import models
import schemas
import auth
import products
import cart
import orders
import delivery
from ai.router import router as ai_router

# Automatic database table creation
models.Base.metadata.create_all(bind=database.engine)

app = FastAPI(
    title="KisanConnect API",
    description="Backend API for KisanConnect - Connecting Farmers Directly to Buyers with AI Intelligence",
    version="1.0.0",
)

# CORS middleware for frontend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
app.include_router(auth.router)
app.include_router(products.router)
app.include_router(cart.router)
app.include_router(orders.router)
app.include_router(delivery.router)
app.include_router(ai_router)


@app.get("/", response_model=schemas.WelcomeResponse)
def root():
    return {
        "message": "Welcome to KisanConnect API",
        "version": "1.0.0"
    }


@app.get("/health", response_model=schemas.HealthResponse)
def health_check(db: Session = Depends(database.get_db)):
    try:
        # Ping SQLite DB
        db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        db_status = f"disconnected ({str(e)})"

    return {
        "status": "healthy" if db_status == "connected" else "unhealthy",
        "database": db_status
    }
