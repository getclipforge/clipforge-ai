
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="ClipForge AI Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://getclipforge.github.io"
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.get("/")
def home():
    return {
        "app": "ClipForge AI",
        "status": "Backend is running"
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "video_processing": "not_connected",
        "target_clips": 10
    }
  
