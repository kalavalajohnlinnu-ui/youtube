import os
import uuid
import threading
import time
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import trimmer_engine

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOADS_DIR = os.path.join(BASE_DIR, "downloads")
STATIC_DIR = os.path.join(BASE_DIR, "static")

os.makedirs(DOWNLOADS_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)

app = FastAPI(title="ClipTube PRO - YouTube Video & Audio Trimmer")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

tasks_db: Dict[str, Dict[str, Any]] = {}
history_db: List[Dict[str, Any]] = []

class VideoInfoRequest(BaseModel):
    url: str

class TrimRequest(BaseModel):
    url: str
    start_time: str
    end_time: str
    format: str = "mp4"
    quality: str = "best"
    audio_only: bool = False
    is_full_download: bool = False

@app.post("/api/info")
async def get_video_info(req: VideoInfoRequest):
    import asyncio
    try:
        if not req.url or not req.url.strip():
            raise HTTPException(status_code=400, detail="YouTube URL is required")
        loop = asyncio.get_event_loop()
        info = await asyncio.wait_for(
            loop.run_in_executor(None, trimmer_engine.fetch_video_info, req.url.strip()),
            timeout=20.0
        )
        return info
    except asyncio.TimeoutError:
        # Still return partial info based on URL parsing alone
        video_id = trimmer_engine.extract_video_id(req.url.strip())
        if video_id:
            return {
                "id": video_id,
                "title": "YouTube Video",
                "uploader": "YouTube Channel",
                "duration": 0,
                "duration_string": "00:00:00",
                "thumbnail": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
                "is_live": False,
                "description": ""
            }
        raise HTTPException(status_code=408, detail="Request timed out fetching video info")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

def process_trim_task(task_id: str, req: TrimRequest):
    def update_progress(pct: int, msg: str, eta_seconds: int = 0):
        if task_id in tasks_db:
            tasks_db[task_id]["progress"] = pct
            tasks_db[task_id]["message"] = msg
            tasks_db[task_id]["eta_seconds"] = max(0, eta_seconds)

    try:
        tasks_db[task_id]["status"] = "processing"
        output_filename = trimmer_engine.run_trim_download(
            url=req.url.strip(),
            start_time=req.start_time,
            end_time=req.end_time,
            output_dir=DOWNLOADS_DIR,
            task_id=task_id,
            progress_callback=update_progress,
            out_format=req.format,
            quality=req.quality,
            audio_only=req.audio_only,
            is_full_download=req.is_full_download
        )
        
        filepath = os.path.join(DOWNLOADS_DIR, output_filename)
        file_size = os.path.getsize(filepath) if os.path.exists(filepath) else 0
        
        tasks_db[task_id]["status"] = "completed"
        tasks_db[task_id]["progress"] = 100
        tasks_db[task_id]["message"] = "Processing completed!"
        tasks_db[task_id]["eta_seconds"] = 0
        tasks_db[task_id]["filename"] = output_filename
        tasks_db[task_id]["download_url"] = f"/api/download/{output_filename}"
        tasks_db[task_id]["file_size_mb"] = round(file_size / (1024 * 1024), 2)
        
        mode_label = "Full Audio (MP3)" if (req.audio_only and req.is_full_download) else \
                     ("Full Video" if req.is_full_download else \
                     ("Trimmed MP3" if req.audio_only else "Trimmed Video"))

        history_item = {
            "task_id": task_id,
            "url": req.url,
            "mode": mode_label,
            "start_time": req.start_time,
            "end_time": req.end_time,
            "filename": output_filename,
            "download_url": f"/api/download/{output_filename}",
            "created_at": time.strftime("%H:%M:%S, %d %b"),
            "size_mb": round(file_size / (1024 * 1024), 2)
        }
        history_db.insert(0, history_item)
        if len(history_db) > 20:
            history_db.pop()

    except Exception as e:
        import traceback
        traceback.print_exc()
        err_msg = str(e)
        # Clean up common yt-dlp noise for user-facing message
        if "exit code" in err_msg and "\n" in err_msg:
            err_msg = err_msg.split("\n")[0]
        tasks_db[task_id]["status"] = "error"
        tasks_db[task_id]["message"] = f"Error: {err_msg[:200]}"
        tasks_db[task_id]["progress"] = tasks_db[task_id].get("progress", 0)
        tasks_db[task_id]["eta_seconds"] = 0

@app.post("/api/trim")
def create_trim_task(req: TrimRequest):
    if not req.url or not req.url.strip():
        raise HTTPException(status_code=400, detail="YouTube URL is required")
    
    task_id = str(uuid.uuid4())[:8]
    tasks_db[task_id] = {
        "task_id": task_id,
        "status": "pending",
        "progress": 0,
        "eta_seconds": 10,
        "message": "Task queued...",
        "filename": None,
        "download_url": None,
        "created_at": time.time()
    }
    
    thread = threading.Thread(target=process_trim_task, args=(task_id, req), daemon=True)
    thread.start()
    
    return {"task_id": task_id, "status": "pending"}

@app.get("/api/status/{task_id}")
def get_task_status(task_id: str):
    if task_id not in tasks_db:
        raise HTTPException(status_code=404, detail="Task not found")
    return tasks_db[task_id]

@app.get("/api/download/{filename}")
def download_file(filename: str):
    safe_filename = os.path.basename(filename)
    filepath = os.path.join(DOWNLOADS_DIR, safe_filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="File not found")
    
    return FileResponse(
        path=filepath,
        filename=safe_filename,
        media_type="application/octet-stream"
    )

@app.get("/api/history")
def get_history():
    return {"history": history_db}

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/manifest.json")
def get_manifest():
    return FileResponse(os.path.join(STATIC_DIR, "manifest.json"))

@app.get("/sw.js")
def get_sw():
    return FileResponse(os.path.join(STATIC_DIR, "sw.js"))

@app.get("/")
def read_root():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

if __name__ == "__main__":
    import uvicorn
    print("Starting ClipTube Server on http://localhost:8000 and http://0.0.0.0:8000 ...", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=8000)
