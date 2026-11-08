#!/usr/bin/env python3
"""
=============================================================================
e-JDU LMS — Telegram Bot Controller (AI & Supersonic Automation)
=============================================================================
Telefonda Telegram orqali LMS kursini to'liq nazorat qilish, dars va testlarni
masofadan ishga tushirish, jonli holat va skrinshotlarni qabul qilish boti.
=============================================================================
"""

import os
import sys
import time
import json
import logging
import threading
import requests
from datetime import datetime

# Add engine_v2 to path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENGINE_V2_DIR = os.path.join(BASE_DIR, "engine_v2")
if ENGINE_V2_DIR not in sys.path:
    sys.path.insert(0, ENGINE_V2_DIR)

from lms_client import LMSDirectClient
from config import load_profiles, load_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("LMS_Telegram_Bot")

# Load .env
ENV_FILE = os.path.join(BASE_DIR, ".env")
if os.path.exists(ENV_FILE):
    with open(ENV_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.strip().split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# State tracker
solver_lock = threading.Lock()
is_solver_running = False

def send_message(chat_id: int, text: str, reply_markup: dict = None) -> bool:
    if not BOT_TOKEN:
        return False
    url = f"{TELEGRAM_API}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        r = requests.post(url, json=payload, timeout=10)
        return r.status_code == 200
    except Exception as e:
        logger.error(f"Xabar yuborishda xatolik: {e}")
        return False

def send_photo(chat_id: int, photo_path: str, caption: str = "") -> bool:
    if not BOT_TOKEN or not os.path.exists(photo_path):
        return False
    url = f"{TELEGRAM_API}/sendPhoto"
    try:
        with open(photo_path, "rb") as f:
            r = requests.post(
                url,
                data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"},
                files={"photo": f},
                timeout=30
            )
        return r.status_code == 200
    except Exception as e:
        logger.error(f"Rasm yuborishda xatolik: {e}")
        return False

def answer_callback_query(callback_query_id: str, text: str = ""):
    if not BOT_TOKEN:
        return
    url = f"{TELEGRAM_API}/answerCallbackQuery"
    try:
        requests.post(url, json={"callback_query_id": callback_query_id, "text": text}, timeout=5)
    except Exception:
        pass

def get_main_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "📊 Holatni tekshirish", "callback_data": "status"},
                {"text": "📸 Jonli skrinshot", "callback_data": "screenshot"}
            ],
            [
                {"text": "⚡ Tezkor darslar (HTTP)", "callback_data": "run_lessons"},
                {"text": "📝 Testlarni topshirish", "callback_data": "run_tests"}
            ],
            [
                {"text": "🔄 Yangilash", "callback_data": "refresh"}
            ]
        ]
    }

def handle_status(chat_id: int):
    profiles = load_profiles()
    prof = profiles[0] if profiles else {"user_id": "jdu-226516", "password": "55ugtk", "course": "N3"}
    
    send_message(chat_id, "🔍 <i>LMS tizimiga ulanib, ma'lumotlar olinmoqda...</i>")
    
    client = LMSDirectClient(prof["user_id"], prof["password"])
    if not client.login() or not client.open_course():
        send_message(chat_id, "❌ <b>LMS tizimiga ulanib bo'lmadi!</b> Login yoki parol xato.")
        return

    units = client.scan_units()
    total = len(units)
    finished = sum(1 for u in units if u["is_finished"])
    pending = [u for u in units if not u["is_finished"]]
    pct = (finished * 100 // total) if total > 0 else 0

    progress_bar = "▓" * (pct // 10) + "░" * (10 - (pct // 10))

    msg = f"""<b>🎓 e-JDU LMS Kurs Holati</b>

👤 <b>Talaba:</b> {prof.get('name', 'Saidislomxo\'ja')} (<code>{prof['user_id']}</code>)
📚 <b>Kurs:</b> {prof.get('course', 'N3 (2026秋セメスター)')}
📈 <b>Jarayon:</b> {progress_bar} <b>{pct}%</b>
📊 <b>Bajarilgan:</b> {finished} / {total} ta
⏳ <b>Qolgan:</b> {len(pending)} ta

"""
    if pending:
        msg += "<b>Qolgan darslar/testlar ro'yxati:</b>\n"
        for i, p in enumerate(pending[:10], 1):
            msg += f"{i}. <code>{p['title']}</code>\n"
        if len(pending) > 10:
            msg += f"<i>...va yana {len(pending) - 10} ta</i>\n"
    else:
        msg += "🎉 <b>BARCHA DARSLAR VA TESTLAR 100% YAKUNLANGAN!</b> 🏆"

    send_message(chat_id, msg, get_main_keyboard())

def handle_run_lessons(chat_id: int):
    global is_solver_running
    with solver_lock:
        if is_solver_running:
            send_message(chat_id, "⚠️ <i>Jarayon allaqachon fonda ishlamoqda. Kuting...</i>")
            return
        is_solver_running = True

    def worker():
        global is_solver_running
        try:
            profiles = load_profiles()
            prof = profiles[0]
            send_message(chat_id, "⚡ <b>Supersonic HTTP dvigateli ishga tushirildi...</b>")
            client = LMSDirectClient(prof["user_id"], prof["password"])
            if client.login() and client.open_course():
                res = client.complete_all_pending_lessons()
                send_message(
                    chat_id,
                    f"✅ <b>Darslar yakunlandi!</b>\nMuvaffaqiyatli: {res.get('completed', 0)} ta\nXatolik: {res.get('failed', 0)} ta",
                    get_main_keyboard()
                )
            else:
                send_message(chat_id, "❌ LMS ga ulanishda xatolik yuz berdi.")
        finally:
            with solver_lock:
                is_solver_running = False

    threading.Thread(target=worker, daemon=True).start()

def handle_run_tests(chat_id: int):
    global is_solver_running
    with solver_lock:
        if is_solver_running:
            send_message(chat_id, "⚠️ <i>Avtomatlashtirish jarayoni allaqachon ishlamoqda.</i>")
            return
        is_solver_running = True

    def worker():
        global is_solver_running
        try:
            send_message(chat_id, "🚀 <b>Master Test Solver ishga tushirildi!</b>\nSavollar AI (Gemini) va SQLite keshi yordamida topshiriladi...")
            cmd = f"PYTHONUNBUFFERED=1 {sys.executable} {os.path.join(ENGINE_V2_DIR, 'master_solver.py')}"
            import subprocess
            proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in proc.stdout:
                line_str = line.strip()
                if "TEST TOPSHIRISH:" in line_str or "Test turi:" in line_str or "Barcha javoblar belgilandi" in line_str or "Test yakunlandi" in line_str:
                    send_message(chat_id, f"📝 <code>{line_str}</code>")
            proc.wait()
            send_message(chat_id, "🏁 <b>Barcha testlar topshirildi!</b>", get_main_keyboard())
        except Exception as e:
            send_message(chat_id, f"❌ Test topshirishda xatolik: {e}")
        finally:
            with solver_lock:
                is_solver_running = False

    threading.Thread(target=worker, daemon=True).start()

def handle_screenshot(chat_id: int):
    send_message(chat_id, "📸 <i>LMS kursidan jonli skrinshot olinmoqda... (5-10 soniya)</i>")
    
    def worker():
        shot_path = f"/tmp/lms_shot_{chat_id}.png"
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1280, "height": 850})
                page.goto("https://e-jdu.uz/default.aspx", timeout=30000)
                profiles = load_profiles()
                prof = profiles[0]
                page.locator('input[name*="txtUserID"]').first.fill(prof["user_id"])
                page.locator('input[name*="txtPassword"]').first.fill(prof["password"])
                page.locator('button:has-text("ログイン"), input[value*="ログイン"]').first.click()
                page.wait_for_load_state("load")
                page.wait_for_timeout(2000)
                page.goto("https://e-jdu.uz/home/course/default.aspx?id=953", timeout=30000)
                page.wait_for_load_state("load")
                page.wait_for_timeout(2500)
                page.screenshot(path=shot_path, full_page=False)
                browser.close()
            send_photo(chat_id, shot_path, "📸 <b>Jonli LMS Kurs Skrinshoti</b>\n100% holat tasdig'i.")
        except Exception as e:
            send_message(chat_id, f"❌ Skrinshot olishda xatolik: {e}")
        finally:
            if os.path.exists(shot_path):
                try:
                    os.remove(shot_path)
                except Exception:
                    pass

    threading.Thread(target=worker, daemon=True).start()

def process_update(update: dict):
    # Handle message
    if "message" in update:
        msg = update["message"]
        chat_id = msg["chat"]["id"]
        text = msg.get("text", "").strip()

        if text in ("/start", "/menu"):
            welcome_text = f"""👋 <b>Assalomu alaykum!</b>

<b>e-JDU LMS Autonomous AI Bot</b> boshqaruv tizimiga xush kelibsiz.

Ushbu bot orqali siz:
• LMS kursingizning real holatini bilib turishingiz;
• Yangi dars va videolarni 1 soniyada yakunlashingiz;
• Murakkab testlarni Gemini AI orqali yechishingiz;
• Jonli skrinshot olishingiz mumkin.

👇 <b>Quyidagi tugmalardan birini tanlang:</b>"""
            send_message(chat_id, welcome_text, get_main_keyboard())

        elif text == "/status":
            handle_status(chat_id)

        elif text == "/run_lessons":
            handle_run_lessons(chat_id)

        elif text == "/run_tests":
            handle_run_tests(chat_id)

        elif text == "/screenshot":
            handle_screenshot(chat_id)

        elif text == "/help":
            help_text = """<b>📖 Bot Buyruqlari:</b>

/menu - Asosiy boshqaruv tugmalarini chiqarish
/status - Kursdagi darslar va foiz holatini tekshirish
/run_lessons - Qolib ketgan video/o'qish darslarini bir zumda topshirish
/run_tests - Barcha testlarni AI bilan yechish
/screenshot - LMS dan real vaqt skrinshotini olish"""
            send_message(chat_id, help_text, get_main_keyboard())

    # Handle callback query
    elif "callback_query" in update:
        cq = update["callback_query"]
        cq_id = cq["id"]
        chat_id = cq["message"]["chat"]["id"]
        data = cq.get("data", "")

        answer_callback_query(cq_id)

        if data in ("status", "refresh"):
            handle_status(chat_id)
        elif data == "run_lessons":
            handle_run_lessons(chat_id)
        elif data == "run_tests":
            handle_run_tests(chat_id)
        elif data == "screenshot":
            handle_screenshot(chat_id)

def run_bot():
    if not BOT_TOKEN:
        print("\n" + "=" * 65, flush=True)
        print("⚠️ TELEGRAM_BOT_TOKEN topilmadi!", flush=True)
        print("Botni ulash uchun:", flush=True)
        print("1. Telegramda @BotFather ga kiring va /newbot buyrug'ini bering.")
        print("2. Bot nomi va username kiriting (masalan: ejdu_ai_agent_bot).")
        print("3. Olingan tokenni .env fayliga TELEGRAM_BOT_TOKEN=... qilib qo'ying.")
        print("=" * 65 + "\n", flush=True)
        return

    print("🤖 Telegram Bot muvaffaqiyatli ishga tushmoqda...", flush=True)
    offset = 0
    while True:
        try:
            r = requests.get(f"{TELEGRAM_API}/getUpdates", params={"offset": offset, "timeout": 25}, timeout=30)
            if r.status_code == 200:
                data = r.json()
                for item in data.get("result", []):
                    offset = item["update_id"] + 1
                    process_update(item)
            else:
                time.sleep(2)
        except Exception as e:
            time.sleep(3)

if __name__ == "__main__":
    run_bot()
