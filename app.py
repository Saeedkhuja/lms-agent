import os
import uuid
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from fastapi.middleware.cors import CORSMiddleware
from config import (
    load_settings,
    save_settings,
    load_profiles,
    save_profiles,
    load_completed_tasks,
    BASE_DIR
)
from agent_runner import agent_runner

app = FastAPI(title="LMS Autonomous AI Agent Dashboard", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = os.path.join(BASE_DIR, "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# ---------------------------------------------------------------------------
# MODELS
# ---------------------------------------------------------------------------
class ProfileModel(BaseModel):
    id: Optional[str] = None
    name: str
    user_id: str
    password: str
    course: str = "N3 (2026秋セメスター)"
    active: bool = True
    notes: Optional[str] = ""

class SettingsModel(BaseModel):
    speed: float = 1.0
    doc_time: int = 25
    check_interval: int = 15
    gemini_api_key: str
    gemini_model: str = "gemini-3.8-flash"
    headless: bool = True
    batch_mode: bool = False
    custom_instructions: str = ""

class StartAgentRequest(BaseModel):
    profile_id: Optional[str] = None
    custom_task: Optional[str] = None

class CustomTaskRequest(BaseModel):
    task: str

# ---------------------------------------------------------------------------
# ROUTES
# ---------------------------------------------------------------------------
@app.get("/")
def get_index():
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return HTMLResponse("<h1>LMS Agent Web Dashboard</h1>")

@app.get("/style.css")
def get_style_css():
    return FileResponse(os.path.join(STATIC_DIR, "style.css"), media_type="text/css")

@app.get("/app.js")
def get_app_js():
    return FileResponse(os.path.join(STATIC_DIR, "app.js"), media_type="application/javascript")

@app.get("/api/status")
def get_status():
    return agent_runner.get_status()

@app.post("/api/agent/start")
def start_agent(req: StartAgentRequest):
    success = agent_runner.start(
        profile_id=req.profile_id,
        custom_task=req.custom_task
    )
    if not success:
        raise HTTPException(status_code=400, detail="Agentni ishga tushirib bo'lmadi yoki u allaqachon ishlamoqda.")
    return {"status": "started", "message": "Agent muvaffaqiyatli ishga tushirildi"}

@app.post("/api/agent/stop")
def stop_agent():
    agent_runner.stop()
    return {"status": "stopped", "message": "Agent to'xtatildi"}

@app.get("/api/logs")
def get_logs(since_id: int = 0):
    return {"logs": agent_runner.get_logs(since_id)}

@app.get("/api/screenshot")
def get_screenshot():
    if agent_runner.latest_screenshot_b64:
        return {"screenshot": agent_runner.latest_screenshot_b64}
    return {"screenshot": None}

# ---------------------------------------------------------------------------
# PROFILES CRUD
# ---------------------------------------------------------------------------
@app.get("/api/profiles")
def list_profiles():
    profiles = load_profiles()
    # Enrich with completed task count
    for p in profiles:
        completed = load_completed_tasks(p["user_id"])
        p["completed_count"] = len(completed)
    return {"profiles": profiles}

@app.post("/api/profiles")
def add_profile(item: ProfileModel):
    profiles = load_profiles()
    new_profile = item.dict()
    new_profile["id"] = f"prof_{uuid.uuid4().hex[:8]}"
    profiles.append(new_profile)
    save_profiles(profiles)
    agent_runner.log("INFO", f"➕ Yangi profil qo'shildi: {new_profile['name']} ({new_profile['user_id']})")
    return {"status": "ok", "profile": new_profile}

@app.put("/api/profiles/{prof_id}")
def update_profile(prof_id: str, item: ProfileModel):
    profiles = load_profiles()
    for idx, p in enumerate(profiles):
        if p["id"] == prof_id:
            updated = item.dict()
            updated["id"] = prof_id
            profiles[idx] = updated
            save_profiles(profiles)
            return {"status": "ok", "profile": updated}
    raise HTTPException(status_code=404, detail="Profil topilmadi")

@app.delete("/api/profiles/{prof_id}")
def delete_profile(prof_id: str):
    profiles = load_profiles()
    initial_len = len(profiles)
    profiles = [p for p in profiles if p["id"] != prof_id]
    if len(profiles) == initial_len:
        raise HTTPException(status_code=404, detail="Profil topilmadi")
    save_profiles(profiles)
    return {"status": "ok", "message": "Profil o'chirildi"}

# ---------------------------------------------------------------------------
# SETTINGS & CUSTOM TASKS
# ---------------------------------------------------------------------------
@app.get("/api/settings")
def get_settings():
    return load_settings()

@app.post("/api/settings")
def update_settings(item: SettingsModel):
    save_settings(item.dict())
    agent_runner.log("INFO", "⚙️ Sozlamalar yangilandi")
    return {"status": "ok", "settings": load_settings()}

@app.post("/api/custom-task")
def set_custom_task(req: CustomTaskRequest):
    agent_runner.custom_task_prompt = req.task
    agent_runner.log("INFO", f"🎯 Yangi AI vazifa / buyruq qabul qilindi: '{req.task}'")
    return {"status": "ok", "message": "Vazifa qabul qilindi"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
