import os
import json
import threading
from typing import Dict, List, Any

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
PROFILES_FILE = os.path.join(DATA_DIR, "profiles.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
COMPLETED_DIR = os.path.join(DATA_DIR, "completed_tasks")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(COMPLETED_DIR, exist_ok=True)

_lock = threading.Lock()

# Load .env if present
_env_path = os.path.join(BASE_DIR, ".env")
if os.path.exists(_env_path):
    try:
        with open(_env_path, "r", encoding="utf-8") as _ef:
            for _line in _ef:
                if "=" in _line and not _line.strip().startswith("#"):
                    _k, _v = _line.strip().split("=", 1)
                    os.environ.setdefault(_k.strip(), _v.strip())
    except Exception:
        pass

DEFAULT_SETTINGS = {
    "speed": 1.0,
    "doc_time": 25,
    "check_interval": 15,
    "gemini_api_key": os.environ.get("GEMINI_API_KEY", ""),
    "gemini_model": "gemini-3.5-flash-lite",
    "headless": True,
    "batch_mode": False,  # If True, runs for all active profiles sequentially
    "custom_instructions": "Barcha darslar va testlarni to'liq, sifatli va xatosiz bajargin. Test savollariga eng to'g'ri javobni tanla."
}

DEFAULT_PROFILES = [
    {
        "id": "prof_default",
        "name": "Saidislomxo'ja",
        "user_id": "jdu-226516",
        "password": "55ugtk",
        "course": "N3 (2026秋セメスター)",
        "active": True,
        "notes": "Asosiy profil"
    }
]

def load_settings() -> Dict[str, Any]:
    with _lock:
        if not os.path.exists(SETTINGS_FILE):
            save_settings(DEFAULT_SETTINGS)
            return dict(DEFAULT_SETTINGS)
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                for k, v in DEFAULT_SETTINGS.items():
                    if k not in data:
                        data[k] = v
                if not data.get("gemini_api_key") and os.environ.get("GEMINI_API_KEY"):
                    data["gemini_api_key"] = os.environ.get("GEMINI_API_KEY")
                return data
        except Exception:
            return dict(DEFAULT_SETTINGS)

def save_settings(settings: Dict[str, Any]) -> None:
    with _lock:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)

def load_profiles() -> List[Dict[str, Any]]:
    with _lock:
        if not os.path.exists(PROFILES_FILE):
            save_profiles(DEFAULT_PROFILES)
            return list(DEFAULT_PROFILES)
        try:
            with open(PROFILES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return list(DEFAULT_PROFILES)

def save_profiles(profiles: List[Dict[str, Any]]) -> None:
    with _lock:
        with open(PROFILES_FILE, "w", encoding="utf-8") as f:
            json.dump(profiles, f, indent=2, ensure_ascii=False)

def get_completed_tasks_file(user_id: str) -> str:
    safe_name = "".join(c for c in user_id if c.isalnum() or c in ("-", "_"))
    return os.path.join(COMPLETED_DIR, f"completed_{safe_name}.txt")

def load_completed_tasks(user_id: str) -> set:
    filepath = get_completed_tasks_file(user_id)
    completed = set()
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    t = line.strip()
                    if t:
                        completed.add(t)
        except Exception:
            pass
    return completed

def load_completed_tasks_list(user_id: str) -> List[str]:
    filepath = get_completed_tasks_file(user_id)
    items = []
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    t = line.strip()
                    if t and t not in items:
                        items.append(t)
        except Exception:
            pass
    return items

def save_completed_task(user_id: str, task_key: str) -> None:
    filepath = get_completed_tasks_file(user_id)
    try:
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(f"{task_key}\n")
    except Exception:
        pass
