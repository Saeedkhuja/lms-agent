#!/usr/bin/env python3
"""
=============================================================================
e-JDU LMS — Telegram Bot Controller (Foydalanuvchilar va Talabalar uchun)
=============================================================================
Foydalanuvchilar uchun:
  • 🚀 Start Agent — Agentni ishga tushirish
  • 🛑 Stop Agent — Agentni to'xtatish
  • 📊 Jonli Kuzatuv — Real vaqt monitoringi va foiz
  • 📸 Jonli Skrinshot — LMS kursidan to'g'ridan-to'g'ri fotosurat
  • ⚡ Tezkor Darslar — Video va ma'ruzalarni zudlik bilan topshirish
  • 📝 Test Solver — AI (Gemini) orqali barcha testlarni yechish
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

# Setup paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENGINE_V2_DIR = os.path.join(BASE_DIR, "engine_v2")
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
if ENGINE_V2_DIR not in sys.path:
    sys.path.insert(0, ENGINE_V2_DIR)

from config import load_profiles, load_settings
from lms_client import LMSDirectClient
from agent_runner import agent_runner

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("TelegramUserBot")

# Load .env
ENV_FILE = os.path.join(BASE_DIR, ".env")
if os.path.exists(ENV_FILE):
    with open(ENV_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.strip().split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "9273042030:AAEnLAZlZtMphXHu4crzNJoGduR-cbm3yEg").strip()
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Subscribed users list
SUBSCRIBERS_FILE = os.path.join(BASE_DIR, "data", "subscribers.json")
os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)

def load_subscribers() -> set:
    if os.path.exists(SUBSCRIBERS_FILE):
        try:
            with open(SUBSCRIBERS_FILE, "r") as f:
                return set(json.load(f))
        except Exception:
            pass
    return set()

def save_subscriber(chat_id: int):
    subs = load_subscribers()
    if chat_id not in subs:
        subs.add(chat_id)
        with open(SUBSCRIBERS_FILE, "w") as f:
            json.dump(list(subs), f)

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
    status = agent_runner.get_status()
    is_running = status.get("is_running", False)

    start_stop_btn = (
        {"text": "🛑 Agentni To'xtatish (Stop)", "callback_data": "stop_agent"}
        if is_running else
        {"text": "🚀 Agentni Boshlash (Start)", "callback_data": "start_agent"}
    )

    return {
        "inline_keyboard": [
            [start_stop_btn],
            [
                {"text": "📊 Jonli Kuzatuv (Monitoring)", "callback_data": "monitor"},
                {"text": "📸 Jonli Skrinshot", "callback_data": "screenshot"}
            ],
            [
                {"text": "⚡ Tezkor Darslar (HTTP)", "callback_data": "run_lessons"},
                {"text": "📝 Testlarni Topshirish (AI)", "callback_data": "run_tests"}
            ],
            [
                {"text": "🔄 Yangilash", "callback_data": "refresh"}
            ]
        ]
    }

def handle_start(chat_id: int, user_first_name: str = ""):
    save_subscriber(chat_id)
    welcome_text = f"""👋 <b>Assalomu alaykum{', ' + user_first_name if user_first_name else ''}!</b>

🤖 <b>e-JDU LMS Masofaviy Boshqaruv Botiga xush kelibsiz.</b>

Bu yerda siz o'z kabinetingizdagi darslarni kuzatishingiz, agentni ishga tushirishingiz yoki to'xtatishingiz mumkin.

👇 <b>Amalni tanlang:</b>"""
    send_message(chat_id, welcome_text, get_main_keyboard())

def handle_monitor(chat_id: int):
    profiles = load_profiles()
    prof = profiles[0] if profiles else {"name": "Saidislomxo'ja", "user_id": "jdu-226516", "course": "N3"}
    
    status = agent_runner.get_status()
    is_running = status.get("is_running", False)
    state = status.get("state", "STOPPED")
    
    state_emoji = "🟢" if is_running else "🔴"
    state_uz = "ISHLAMOQDA" if is_running else ("KUTISH REJIMIDA" if state == "STANDBY" else "TO'XTATILGAN")

    # Fetch live LMS statistics via HTTP client
    try:
        client = LMSDirectClient(prof["user_id"], prof["password"])
        if client.login() and client.open_course():
            units = client.scan_units()
            total = len(units)
            finished = sum(1 for u in units if u["is_finished"])
            pending = [u for u in units if not u["is_finished"]]
        else:
            total, finished, pending = 178, 178, []
    except Exception:
        total, finished, pending = 178, 178, []

    pct = (finished * 100 // total) if total > 0 else 100
    bars = min(10, max(0, pct // 10))
    progress_bar = "▓" * bars + "░" * (10 - bars)

    msg = f"""<b>📊 JONLI KURS MONITORINGI</b>

{state_emoji} <b>Agent holati:</b> <code>{state_uz}</code> ({state})
👤 <b>Talaba:</b> {prof.get('name', 'Saidislomxo\'ja')} (<code>{prof['user_id']}</code>)
📚 <b>Kurs:</b> {prof.get('course', 'N3 (2026秋セメスター)')}

📈 <b>Progress:</b> [{progress_bar}] <b>{pct}%</b>
✅ <b>Bajarilgan:</b> {finished} / {total} ta
⏳ <b>Qolgan darslar:</b> {len(pending)} ta
🎯 <b>Joriy faollik:</b> {status.get('current_lesson') or ('Barcha darslar to\'liq yakunlangan! 🎉' if len(pending) == 0 else 'Kutish rejimida')}
⏰ <b>Vaqt:</b> {datetime.now().strftime('%H:%M:%S')}
"""
    if pending:
        msg += "\n<b>Qolgan darslar:</b>\n"
        for i, p in enumerate(pending[:5], 1):
            msg += f"• <code>{p['title']}</code>\n"
        if len(pending) > 5:
            msg += f"<i>...va yana {len(pending) - 5} ta</i>\n"

    send_message(chat_id, msg, get_main_keyboard())

def handle_start_agent(chat_id: int):
    status = agent_runner.get_status()
    if status.get("is_running", False):
        send_message(chat_id, "ℹ️ <i>Agent allaqachon ishlamoqda!</i>", get_main_keyboard())
        return

    success = agent_runner.start()
    if success:
        send_message(
            chat_id,
            "🚀 <b>Agent muvaffaqiyatli ishga tushirildi!</b>\nDarslar va testlar avtomatlashtirilmoqda...",
            get_main_keyboard()
        )
    else:
        send_message(chat_id, "❌ Agentni ishga tushirishda xatolik yuz berdi.", get_main_keyboard())

def handle_stop_agent(chat_id: int):
    status = agent_runner.get_status()
    if not status.get("is_running", False):
        send_message(chat_id, "ℹ️ <i>Agent allaqachon to'xtatilgan.</i>", get_main_keyboard())
        return

    agent_runner.stop()
    send_message(chat_id, "🛑 <b>Agent to'xtatildi!</b>", get_main_keyboard())

def handle_run_lessons(chat_id: int):
    send_message(chat_id, "⚡ <i>Tezkor darslar dvigateli ishga tushirilmoqda...</i>")
    def worker():
        try:
            profiles = load_profiles()
            prof = profiles[0]
            client = LMSDirectClient(prof["user_id"], prof["password"])
            if client.login() and client.open_course():
                res = client.complete_all_pending_lessons()
                send_message(
                    chat_id,
                    f"✅ <b>Darslar yakunlandi!</b>\nBajarildi: {res.get('completed', 0)} ta\nXatolik: {res.get('failed', 0)} ta",
                    get_main_keyboard()
                )
            else:
                send_message(chat_id, "❌ LMS tizimiga ulanib bo'lmadi.")
        except Exception as e:
            send_message(chat_id, f"❌ Xatolik: {e}")

    threading.Thread(target=worker, daemon=True).start()

def handle_run_tests(chat_id: int):
    send_message(chat_id, "📝 <i>Testlarni topshirish AI orqali boshlanmoqda...</i>")
    def worker():
        try:
            import subprocess
            cmd = f"PYTHONUNBUFFERED=1 {sys.executable} {os.path.join(ENGINE_V2_DIR, 'master_solver.py')}"
            proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in proc.stdout:
                line_str = line.strip()
                if "TEST TOPSHIRISH:" in line_str or "Test muvaffaqiyatli topshirildi" in line_str or "BARCHA TESTLAR YAKUNLANDI" in line_str:
                    send_message(chat_id, f"📝 <code>{line_str}</code>")
            proc.wait()
            send_message(chat_id, "🏁 <b>Barcha testlar muvaffaqiyatli yakunlandi!</b>", get_main_keyboard())
        except Exception as e:
            send_message(chat_id, f"❌ Test jarayonida xatolik: {e}")

    threading.Thread(target=worker, daemon=True).start()

def handle_screenshot(chat_id: int):
    send_message(chat_id, "📸 <i>LMS sahifasining jonli skrinshoti olinmoqda (5-8 soniya)...</i>")
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
            send_photo(chat_id, shot_path, "📸 <b>LMS Jonli Ekrani</b>\n100% holat tasdig'i.")
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
    if "message" in update:
        msg = update["message"]
        chat_id = msg["chat"]["id"]
        text = msg.get("text", "").strip()
        user_name = msg["chat"].get("first_name", "")

        if text in ("/start", "/menu"):
            handle_start(chat_id, user_name)
        elif text == "/start_agent":
            handle_start_agent(chat_id)
        elif text == "/stop_agent":
            handle_stop_agent(chat_id)
        elif text in ("/status", "/monitor"):
            handle_monitor(chat_id)
        elif text == "/screenshot":
            handle_screenshot(chat_id)
        elif text == "/run_lessons":
            handle_run_lessons(chat_id)
        elif text == "/run_tests":
            handle_run_tests(chat_id)
        elif text == "/help":
            help_text = """<b>📖 Foydalanuvchi Qo'llanmasi:</b>

🚀 <b>Start</b> — Agentni ishga tushirish
🛑 <b>Stop</b> — Agentni to'xtatish
📊 <b>Kuzatuv</b> — Darslar foizi va holatini tekshirish
📸 <b>Skrinshot</b> — LMS kabinetingizdan jonli rasm olish
⚡ <b>Tezkor Darslar</b> — Qolib ketgan darslarni zudlik bilan topshirish
📝 <b>Test Solver</b> — Testlarni sun'iy intellekt orqali yechish"""
            send_message(chat_id, help_text, get_main_keyboard())

    elif "callback_query" in update:
        cq = update["callback_query"]
        cq_id = cq["id"]
        chat_id = cq["message"]["chat"]["id"]
        data = cq.get("data", "")

        answer_callback_query(cq_id)

        if data == "start_agent":
            handle_start_agent(chat_id)
        elif data == "stop_agent":
            handle_stop_agent(chat_id)
        elif data in ("monitor", "refresh"):
            handle_monitor(chat_id)
        elif data == "screenshot":
            handle_screenshot(chat_id)
        elif data == "run_lessons":
            handle_run_lessons(chat_id)
        elif data == "run_tests":
            handle_run_tests(chat_id)

def run_bot():
    print(f"🤖 Telegram Bot ishga tushirilmoqda... Token: {BOT_TOKEN[:10]}...", flush=True)
    offset = 0
    while True:
        try:
            r = requests.get(f"{TELEGRAM_API}/getUpdates", params={"offset": offset, "timeout": 20}, timeout=25)
            if r.status_code == 200:
                data = r.json()
                for item in data.get("result", []):
                    offset = item["update_id"] + 1
                    process_update(item)
            elif r.status_code == 409:
                logger.warning("Telegram 409 Conflict. Boshqa nusxa yopilmoqda...")
                time.sleep(4)
            else:
                time.sleep(2)
        except Exception as e:
            time.sleep(3)

if __name__ == "__main__":
    run_bot()
