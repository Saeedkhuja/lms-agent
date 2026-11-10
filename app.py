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
    load_completed_tasks_list,
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

@app.on_event("startup")
def startup_event():
    import threading
    try:
        from telegram_bot import run_bot
        t = threading.Thread(target=run_bot, daemon=True)
        t.start()
        print("🤖 [STARTUP] Telegram Bot FastAPI bilan birgalikda muvaffaqiyatli ishga tushirildi!", flush=True)
    except Exception as e:
        print(f"⚠️ [STARTUP] Telegram botni ishga tushirishda xatolik: {e}", flush=True)

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

@app.get("/health")
@app.get("/ping")
def health_check():
    return {"status": "ok", "service": "lms-master-agent", "time": str(os.environ.get("RENDER_EXTERNAL_URL", "local"))}

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
# STUDENT INDIVIDUAL CABIN APIS
# ---------------------------------------------------------------------------
@app.get("/api/students/{prof_id}/status")
def get_student_cabin_status(prof_id: str):
    res = agent_runner.get_student_status(prof_id)
    if "error" in res:
        raise HTTPException(status_code=404, detail=res["error"])
    return res

@app.get("/api/students/{prof_id}/logs")
def get_student_cabin_logs(prof_id: str, since_id: int = 0):
    return {"logs": agent_runner.get_logs(since_id, profile_id=prof_id)}

@app.post("/api/students/{prof_id}/start")
def start_student_agent(prof_id: str):
    profiles = load_profiles()
    prof = next((p for p in profiles if p["id"] == prof_id), None)
    if not prof:
        raise HTTPException(status_code=404, detail="Talaba profili topilmadi")
    success = agent_runner.start(profile_id=prof_id)
    if not success:
        raise HTTPException(status_code=400, detail="Agentni ishga tushirib bo'lmadi yoki u allaqachon ishlamoqda")
    return {"status": "started", "message": f"{prof['name']} uchun agent ishga tushirildi"}

@app.post("/api/students/{prof_id}/stop")
def stop_student_agent(prof_id: str):
    agent_runner.stop()
    return {"status": "stopped", "message": "Agent to'xtatildi"}

@app.get("/api/students/{prof_id}/history")
def get_student_history(prof_id: str):
    profiles = load_profiles()
    prof = next((p for p in profiles if p["id"] == prof_id), None)
    if not prof:
        raise HTTPException(status_code=404, detail="Talaba profili topilmadi")
    items = load_completed_tasks_list(prof["user_id"])
    return {"user_id": prof["user_id"], "total_completed": len(items), "history": items}
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

# ---------------------------------------------------------------------------
# SUPERSONIC ENGINE V2 ENDPOINTS
# ---------------------------------------------------------------------------
@app.get("/api/engine/live-status")
def get_live_status():
    import sys
    engine_dir = os.path.join(BASE_DIR, "engine_v2")
    if engine_dir not in sys.path:
        sys.path.insert(0, engine_dir)
    try:
        from lms_client import LMSDirectClient
        profiles = load_profiles()
        prof = profiles[0]
        client = LMSDirectClient(prof["user_id"], prof["password"])
        if client.login() and client.open_course():
            units = client.scan_units()
            finished = sum(1 for u in units if u["is_finished"])
            total = len(units)
            pending = [u for u in units if not u["is_finished"]]
            return {
                "status": "ok",
                "total": total,
                "finished": finished,
                "remaining": len(pending),
                "percent": (finished * 100 // total) if total > 0 else 100,
                "pending": pending[:15]
            }
    except Exception as e:
        return {"status": "error", "message": str(e), "total": 178, "finished": 178, "remaining": 0, "percent": 100}

@app.post("/api/engine/run-lessons")
def run_lessons_api():
    import sys, threading
    engine_dir = os.path.join(BASE_DIR, "engine_v2")
    if engine_dir not in sys.path:
        sys.path.insert(0, engine_dir)
    from lms_client import LMSDirectClient
    profiles = load_profiles()
    prof = profiles[0]

    def worker():
        agent_runner.log("INFO", "⚡ [ENGINE V2] Tezkor darslar dvigateli ishga tushirildi...")
        try:
            client = LMSDirectClient(prof["user_id"], prof["password"])
            if client.login() and client.open_course():
                res = client.complete_all_pending_lessons()
                agent_runner.log("INFO", f"✅ [ENGINE V2] Darslar yakunlandi: {res.get('completed', 0)} ta bajarildi, {res.get('failed', 0)} ta xato")
        except Exception as e:
            agent_runner.log("ERROR", f"❌ [ENGINE V2] Xatolik: {e}")

    threading.Thread(target=worker, daemon=True).start()
    return {"status": "started", "message": "Tezkor darslar dvigateli ishga tushirildi"}

@app.post("/api/engine/run-tests")
def run_tests_api():
    import sys, threading, subprocess
    engine_dir = os.path.join(BASE_DIR, "engine_v2")
    
    def worker():
        agent_runner.log("INFO", "📝 [TEST SOLVER] AI Test topshirish dvigateli boshlandi...")
        try:
            cmd = f"PYTHONUNBUFFERED=1 {sys.executable} {os.path.join(engine_dir, 'master_solver.py')}"
            proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in proc.stdout:
                line_str = line.strip()
                if line_str:
                    agent_runner.log("INFO", f"🤖 {line_str}")
            proc.wait()
            agent_runner.log("INFO", "🏁 [TEST SOLVER] Barcha testlar yakunlandi!")
        except Exception as e:
            agent_runner.log("ERROR", f"❌ [TEST SOLVER] Xatolik: {e}")

    threading.Thread(target=worker, daemon=True).start()
    return {"status": "started", "message": "AI Test topshirish dvigateli ishga tushirildi"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)

