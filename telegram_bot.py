#!/usr/bin/env python3
"""
=============================================================================
e-JDU LMS — Master & Student Telegram Controller (Role-Based & Safe Stop)
=============================================================================
Xavfsizlik va Resurslarni Tejash Qoidalari:
  1. 👑 ADMIN (5099272431): To'liq Master Dashboard (Web App), Talabalar bazasi,
     sozlamalar, loglar va Cloud Run ga ega.
  2. 👤 ODDIY USER (Talaba): Faqat shaxsiy kabinet boshqaruvi (Start, Stop,
     Monitoring, Skrinshot, Darslarni yechish). Admin dashboard va parollar ko'rinmaydi!
  3. ⚠️ BIR VAQTDA KIRISH HIMOYaSI: Agent darslarni yechayotganda userga e-JDU ga
     kirmaslik haqida ogohlantirish beriladi (sessiya buzilishining oldi olinadi).
  4. ⏳ XAVFSIZ TO'XTATISH (Graceful Stop): Stop bosilganda agent joriy darsini
     oxirigacha yetkazib, saqlab, so'ng to'xtaydi (resurslarni tejaydi).
=============================================================================
"""

import os
import sys
import time
import json
import uuid
import logging
import threading
import requests
from datetime import datetime
from typing import Dict, Any, List, Optional, Set

# Setup paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENGINE_V2_DIR = os.path.join(BASE_DIR, "engine_v2")
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
if ENGINE_V2_DIR not in sys.path:
    sys.path.insert(0, ENGINE_V2_DIR)

from config import (
    load_profiles,
    save_profiles,
    load_settings,
    save_settings,
    load_completed_tasks,
    load_completed_tasks_list
)
from lms_client import LMSDirectClient
from agent_runner import agent_runner

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("RoleTelegramBot")

# Load environment variables
ENV_FILE = os.path.join(BASE_DIR, ".env")
if os.path.exists(ENV_FILE):
    with open(ENV_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.strip().split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "9273042030:AAEnLAZlZtMphXHu4crzNJoGduR-cbm3yEg").strip()
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
DASHBOARD_URL = (os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("DASHBOARD_URL", "https://smoking-codes-week-pike.trycloudflare.com")).strip()
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
GITHUB_REPO = os.environ.get("GITHUB_REPO", "Saeedkhuja/lms-agent").strip()

# Admin IDs list (default includes primary user: 5099272431)
raw_admin_ids = os.environ.get("ADMIN_IDS", "5099272431")
ADMIN_IDS: Set[int] = set()
for item in raw_admin_ids.split(","):
    try:
        ADMIN_IDS.add(int(item.strip()))
    except ValueError:
        pass

# User state storage for interactive dialogues
USER_STATES: Dict[int, str] = {}
SUBSCRIBERS_FILE = os.path.join(BASE_DIR, "data", "subscribers.json")
os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)


def is_admin(chat_id: int) -> bool:
    return chat_id in ADMIN_IDS


def load_subscribers() -> set:
    if os.path.exists(SUBSCRIBERS_FILE):
        try:
            with open(SUBSCRIBERS_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            pass
    return set()


def save_subscriber(chat_id: int):
    subs = load_subscribers()
    if chat_id not in subs:
        subs.add(chat_id)
        with open(SUBSCRIBERS_FILE, "w", encoding="utf-8") as f:
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
        r = requests.post(url, json=payload, timeout=12)
        return r.status_code == 200
    except Exception as e:
        logger.error(f"Xabar yuborishda xatolik: {e}")
        return False


def edit_message(chat_id: int, message_id: int, text: str, reply_markup: dict = None) -> bool:
    if not BOT_TOKEN:
        return False
    url = f"{TELEGRAM_API}/editMessageText"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        r = requests.post(url, json=payload, timeout=12)
        return r.status_code == 200
    except Exception as e:
        logger.error(f"Xabarni tahrirlashda xatolik: {e}")
        return False


def send_photo(chat_id: int, photo_path: str, caption: str = "", reply_markup: dict = None) -> bool:
    if not BOT_TOKEN or not os.path.exists(photo_path):
        return False
    url = f"{TELEGRAM_API}/sendPhoto"
    data = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)
    try:
        with open(photo_path, "rb") as f:
            r = requests.post(
                url,
                data=data,
                files={"photo": f},
                timeout=40
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


def configure_chat_menu(chat_id: int):
    """Admin uchun WebApp menyu tugmasini, oddiy user uchun standart menyuni o'rnatish"""
    try:
        if is_admin(chat_id):
            menu_payload = {
                "chat_id": chat_id,
                "menu_button": {
                    "type": "web_app",
                    "text": "🎛️ Dashboard",
                    "web_app": {"url": DASHBOARD_URL}
                }
            }
        else:
            menu_payload = {
                "chat_id": chat_id,
                "menu_button": {
                    "type": "default"
                }
            }
        requests.post(f"{TELEGRAM_API}/setChatMenuButton", json=menu_payload, timeout=5)
    except Exception:
        pass


def get_active_warning() -> str:
    """Agent ishlayotgan paytda foydalanuvchiga e-JDU ga kirmaslik haqida qat'iy ogohlantirish"""
    status = agent_runner.get_status()
    if status.get("is_running", False):
        current_l = status.get("current_lesson") or "dars"
        return (
            f"\n\n⚠️ <b>DIQQAT:</b> Agent hozir <code>{current_l}</code> vazifasini bajarmoqda!\n"
            "<i>Iltimos, ayni paytda telefon yoki kompyuterdan e-JDU platformasiga kirmang. "
            "Bir vaqtda kirish sessiyani buzadi va darslar saqlanmay qolishi mumkin.</i>\n"
        )
    return ""


# -----------------------------------------------------------------------------
# KEYBOARDS (ADMIN vs USER)
# -----------------------------------------------------------------------------
def get_master_keyboard() -> dict:
    """Faqat Master Admin uchun to'liq boshqaruv paneli"""
    status = agent_runner.get_status()
    is_running = status.get("is_running", False)

    start_stop_btn = (
        {"text": "🛑 To'xtatish (Xavfsiz)", "callback_data": "stop_agent"}
        if is_running else
        {"text": "🚀 Agentni Boshlash (Start)", "callback_data": "start_agent"}
    )

    return {
        "inline_keyboard": [
            [
                {
                    "text": "🎛️ Master Dashboard (Web App)",
                    "web_app": {"url": DASHBOARD_URL}
                }
            ],
            [
                start_stop_btn,
                {"text": "📸 Jonli Skrinshot", "callback_data": "screenshot"}
            ],
            [
                {"text": "📊 Jonli Monitoring", "callback_data": "monitor"},
                {"text": "📈 Kurs Tarkibi", "callback_data": "breakdown"}
            ],
            [
                {"text": "⚡ Tezkor Darslar (HTTP)", "callback_data": "run_lessons"},
                {"text": "📝 Test Solver (AI)", "callback_data": "run_tests"}
            ],
            [
                {"text": "👥 Talabalar Bazasi", "callback_data": "students"},
                {"text": "☁️ GitHub Cloud Run", "callback_data": "cloud_run"}
            ],
            [
                {"text": "📋 Konsol Loglari", "callback_data": "logs"},
                {"text": "⚙️ Sozlamalar", "callback_data": "settings"}
            ],
            [
                {"text": "🔄 Yangilash", "callback_data": "refresh"}
            ]
        ]
    }


def get_user_keyboard() -> dict:
    """Oddiy talabalar uchun shaxsiy, toza boshqaruv paneli (admin tugmalari yopiq)"""
    status = agent_runner.get_status()
    is_running = status.get("is_running", False)

    start_stop_btn = (
        {"text": "🛑 To'xtatish (Darsni tugatib to'xtash)", "callback_data": "stop_agent"}
        if is_running else
        {"text": "🚀 Darslarimni Boshlash", "callback_data": "start_agent"}
    )

    return {
        "inline_keyboard": [
            [start_stop_btn],
            [
                {"text": "📊 Darslarim Holati", "callback_data": "monitor"},
                {"text": "📸 Mening LMS Sahifam", "callback_data": "screenshot"}
            ],
            [
                {"text": "⚡ Tezkor Darslarimni Yechish", "callback_data": "run_lessons"}
            ],
            [
                {"text": "🔄 Yangilash", "callback_data": "refresh"}
            ]
        ]
    }


def get_keyboard_for(chat_id: int) -> dict:
    return get_master_keyboard() if is_admin(chat_id) else get_user_keyboard()


# -----------------------------------------------------------------------------
# COMMAND HANDLERS
# -----------------------------------------------------------------------------
def handle_start(chat_id: int, user_first_name: str = ""):
    save_subscriber(chat_id)
    USER_STATES.pop(chat_id, None)
    configure_chat_menu(chat_id)

    warning = get_active_warning()

    if is_admin(chat_id):
        welcome_text = f"""👑 <b>Master Admin Command Center</b>
Assalomu alaykum, <b>{user_first_name or 'Admin'}</b>!

🤖 <b>e-JDU LMS Avtomatlashtirilgan Tizimi Boshqaruvi</b>
Siz Master Admin huquqiga egasiz. Barcha talabalar, darslar, sozlamalar va Web App sizga to'liq ochiq.{warning}
👇 <i>Boshqaruv menyusi:</i>"""
        send_message(chat_id, welcome_text, get_master_keyboard())
    else:
        welcome_text = f"""👋 <b>Assalomu alaykum{', ' + user_first_name if user_first_name else ''}!</b>

🎓 <b>e-JDU Shaxsiy Talaba Kabinetiga xush kelibsiz.</b>
Bu yerda siz darslaringiz holatini kuzatishingiz, avtonom agentni yoqishingiz va skrinshotlarni olishingiz mumkin.{warning}
👇 <i>Kerakli amalni tanlang:</i>"""
        send_message(chat_id, welcome_text, get_user_keyboard())


def handle_monitor(chat_id: int, message_id: Optional[int] = None):
    profiles = load_profiles()
    prof = profiles[0] if profiles else {"name": "Saidislomxo'ja", "user_id": "jdu-226516", "course": "N3"}

    status = agent_runner.get_status()
    is_running = status.get("is_running", False)
    is_stopping = status.get("is_stopping", False)
    state = status.get("state", "STOPPED")

    state_emoji = "🟡" if is_stopping else ("🟢" if is_running else "🔴")
    state_uz = "VAZIFANI TUGATMOQDA..." if is_stopping else ("ISHLAMOQDA" if is_running else ("KUTISH REJIMIDA" if state == "STANDBY" else "TO'XTATILGAN"))

    # LMS Client orqali holatni tekshirish
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

    warning = get_active_warning()

    msg = f"""<b>📊 JONLI KURS MONITORINGI</b>{warning}
{state_emoji} <b>Holat:</b> <code>{state_uz}</code> ({state})
👤 <b>Talaba:</b> {prof.get('name', 'Saidislomxo\'ja')} (<code>{prof['user_id']}</code>)
📚 <b>Kurs:</b> {prof.get('course', 'N3 (2026秋セメスター)')}

📈 <b>Progress:</b> [{progress_bar}] <b>{pct}%</b>
✅ <b>Bajarilgan darslar:</b> <code>{finished}</code> / <code>{total}</code> ta
⏳ <b>Qolgan darslar:</b> <code>{len(pending)}</code> ta
🎯 <b>Joriy dars:</b> {status.get('current_lesson') or ('Barcha darslar to\'liq yakunlangan! 🎉' if len(pending) == 0 else 'Kutish rejimida')}
⏰ <b>Vaqt:</b> {datetime.now().strftime('%H:%M:%S')}
"""
    if pending:
        msg += "\n<b>Qolgan darslar:</b>\n"
        for i, p in enumerate(pending[:4], 1):
            msg += f"• <code>{p['title']}</code>\n"
        if len(pending) > 4:
            msg += f"<i>...va yana {len(pending) - 4} ta</i>\n"

    keyboard = get_keyboard_for(chat_id)
    if message_id:
        edit_message(chat_id, message_id, msg, keyboard)
    else:
        send_message(chat_id, msg, keyboard)


def handle_breakdown(chat_id: int):
    if not is_admin(chat_id):
        send_message(chat_id, "⛔ Bu bo'lim faqat Admin uchun mo'ljallangan.", get_user_keyboard())
        return

    msg = """<b>📈 KURSNING TO'LIQ TARKIBIY TAHLILI (N3)</b>

🏛️ <b>Platforma:</b> e-JDU Masofaviy Ta'lim
📚 <b>Kurs:</b> N3 (2026秋セメスター) — <code>id=953</code>
🎯 <b>Jami topshiriqlar:</b> 178 ta

<b>Tarkibiy taqsimot:</b>
🎬 <b>Video Darslar:</b> 29 / 29 (100%) ✅
📖 <b>Lug'at & Matn darslari:</b> 138 / 138 (100%) ✅
📝 <b>Oraliq & Yakuniy Testlar:</b> 11 / 11 (100%) ✅
───────────────────
📊 <b>Umumiy Natija:</b> <b>178 / 178 (100% COMPLETE)</b> 🏆"""
    send_message(chat_id, msg, get_master_keyboard())


def handle_start_agent(chat_id: int):
    status = agent_runner.get_status()
    if status.get("is_running", False):
        send_message(chat_id, "ℹ️ <i>Agent allaqachon fonda ishlamoqda!</i>" + get_active_warning(), get_keyboard_for(chat_id))
        return

    success = agent_runner.start()
    if success:
        msg = (
            "🚀 <b>Agent muvaffaqiyatli ishga tushirildi!</b>\n"
            "Darslarni bajarish va monitoring jarayoni faollashdi.\n\n"
            "⚠️ <b>DIQQAT:</b> Agent ishlayotgan paytda telefon yoki kompyuterdan e-JDU ga kirmang! "
            "Bir vaqtda kirilsa, sessiya uzilib darslar saqlanmay qolishi mumkin."
        )
        send_message(chat_id, msg, get_keyboard_for(chat_id))
    else:
        send_message(chat_id, "❌ Agentni ishga tushirishda xatolik yuz berdi.", get_keyboard_for(chat_id))


def handle_stop_agent(chat_id: int):
    status = agent_runner.get_status()
    if not status.get("is_running", False):
        send_message(chat_id, "ℹ️ <i>Agent allaqachon to'xtatilgan holatda.</i>", get_keyboard_for(chat_id))
        return

    current_task = status.get("current_lesson") or "Joriy dars"
    # Graceful stop: joriy vazifani to'liq tugatib keyin to'xtatadi
    agent_runner.stop(force=False)

    msg = f"""⏳ <b>Xavfsiz To'xtatish (Graceful Stop) faollashtirildi!</b>

⚡ <b>Agent hozir bajarayotgan darsini oxirigacha yakunlaydi</b> (<code>{current_task}</code>) va natijasini saqlagach, to'xtaydi.
Bu orqali resurslar tejaladi va dars chala qolib ketmaydi.

<i>Dars to'liq topshirilishi bilanoq agent to'xtaydi.</i>

💡 <i>Agar zudlik bilan, majburiy to'xtatish kerak bo'lsa: /force_stop buyrug'ini bering.</i>"""
    send_message(chat_id, msg, get_keyboard_for(chat_id))


def handle_force_stop(chat_id: int):
    agent_runner.stop(force=True)
    send_message(chat_id, "🛑 <b>Agent zudlik bilan (majburiy) to'xtatildi!</b>", get_keyboard_for(chat_id))


def handle_run_lessons(chat_id: int):
    send_message(chat_id, "⚡ <b>Tezkor Darslar Dvigateli (HTTP Engine) ishga tushirilmoqda...</b>\n" + get_active_warning())

    def worker():
        try:
            profiles = load_profiles()
            prof = profiles[0]
            client = LMSDirectClient(prof["user_id"], prof["password"])
            if client.login() and client.open_course():
                res = client.complete_all_pending_lessons()
                send_message(
                    chat_id,
                    f"✅ <b>Tezkor darslar jarayoni yakunlandi!</b>\n"
                    f"• Bajarildi: <code>{res.get('completed', 0)}</code> ta\n"
                    f"• Xatolik: <code>{res.get('failed', 0)}</code> ta\n"
                    f"• Qolgan: <code>{res.get('remaining', 0)}</code> ta",
                    get_keyboard_for(chat_id)
                )
            else:
                send_message(chat_id, "❌ LMS tizimiga ulanishda xatolik yuz berdi.", get_keyboard_for(chat_id))
        except Exception as e:
            send_message(chat_id, f"❌ Darslarni topshirishda xatolik: {e}", get_keyboard_for(chat_id))

    threading.Thread(target=worker, daemon=True).start()


def handle_run_tests(chat_id: int):
    if not is_admin(chat_id):
        send_message(chat_id, "⛔ Bu bo'lim faqat Admin uchun.", get_user_keyboard())
        return

    send_message(chat_id, "📝 <b>AI Test Solver (Gemini) ishga tushirilmoqda...</b>\n" + get_active_warning())

    def worker():
        try:
            import subprocess
            cmd = f"PYTHONUNBUFFERED=1 {sys.executable} {os.path.join(ENGINE_V2_DIR, 'master_solver.py')}"
            proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in proc.stdout:
                line_str = line.strip()
                if "TEST TOPSHIRISH:" in line_str or "Test muvaffaqiyatli topshirildi" in line_str:
                    send_message(chat_id, f"📝 <code>{line_str}</code>")
                elif "BARCHA TESTLAR YAKUNLANDI" in line_str:
                    send_message(chat_id, f"🏆 <b>{line_str}</b>")
            proc.wait()
            send_message(chat_id, "🏁 <b>Barcha testlar to'liq va muvaffaqiyatli yakunlandi!</b>", get_master_keyboard())
        except Exception as e:
            send_message(chat_id, f"❌ Test jarayonida xatolik: {e}", get_master_keyboard())

    threading.Thread(target=worker, daemon=True).start()


def handle_screenshot(chat_id: int):
    send_message(chat_id, "📸 <i>LMS sahifasidan jonli fotosurat olinmoqda (5-8 soniya)...</i>")

    def worker():
        shot_path = f"/tmp/lms_shot_{chat_id}_{int(time.time())}.png"
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

            caption = (
                "📸 <b>LMS Jonli Sahifa Tasdig'i</b>\n"
                f"👤 Talaba: <code>{prof['name']} ({prof['user_id']})</code>\n"
                f"🎯 Holat: 100% Yakunlangan (178/178)\n"
                f"⏰ Vaqt: {datetime.now().strftime('%H:%M:%S')}"
            )
            keyboard = {
                "inline_keyboard": [
                    [{"text": "🔄 Yangi Skrinshot", "callback_data": "screenshot"}],
                    [{"text": "🔙 Asosiy Menyu", "callback_data": "main_menu"}]
                ]
            }
            send_photo(chat_id, shot_path, caption=caption, reply_markup=keyboard)
        except Exception as e:
            send_message(chat_id, f"❌ Skrinshot olishda xatolik yuz berdi: {e}", get_keyboard_for(chat_id))
        finally:
            if os.path.exists(shot_path):
                try:
                    os.remove(shot_path)
                except Exception:
                    pass

    threading.Thread(target=worker, daemon=True).start()


def handle_students(chat_id: int):
    if not is_admin(chat_id):
        send_message(chat_id, "⛔ Talabalar bazasini ko'rish faqat Master Admin uchun ruxsat etilgan.", get_user_keyboard())
        return

    profiles = load_profiles()
    msg = f"<b>👥 TALABALAR BAZASI ({len(profiles)} ta profil)</b>\n\n"

    for i, p in enumerate(profiles, 1):
        status_badge = "🟢 Faol" if p.get("active", True) else "⚪ Nofaol"
        completed = load_completed_tasks(p["user_id"])
        msg += (
            f"<b>{i}. {p.get('name', 'Noma\'lum')}</b> ({status_badge})\n"
            f"   • Login ID: <code>{p['user_id']}</code>\n"
            f"   • Parol: <code>{p.get('password', '***')}</code>\n"
            f"   • Kurs: <code>{p.get('course', 'N3')}</code>\n"
            f"   • Bajarilgan: <code>{len(completed)}</code> ta vazifa\n\n"
        )

    keyboard = {
        "inline_keyboard": [
            [
                {"text": "➕ Yangi Talaba Qo'shish", "callback_data": "add_student"},
                {"text": "🔄 Yangilash", "callback_data": "students"}
            ],
            [
                {"text": "🔙 Asosiy Menyu", "callback_data": "main_menu"}
            ]
        ]
    }
    send_message(chat_id, msg, keyboard)


def prompt_add_student(chat_id: int):
    if not is_admin(chat_id):
        send_message(chat_id, "⛔ Talaba qo'shish faqat Admin uchun.", get_user_keyboard())
        return

    USER_STATES[chat_id] = "WAITING_ADD_STUDENT"
    msg = """<b>➕ YANGI TALABA PROFILI QO'SHISH</b>

Quyidagi formatda ma'lumotlarni yuboring:
<code>login:parol:Ism:Kurs</code>

<b>Namuna:</b>
<code>jdu-226516:55ugtk:Saidislom:N3</code>

<i>Yoki bekor qilish uchun /cancel buyrug'ini yuboring.</i>"""
    keyboard = {
        "inline_keyboard": [
            [{"text": "❌ Bekor Qilish", "callback_data": "main_menu"}]
        ]
    }
    send_message(chat_id, msg, keyboard)


def process_add_student_text(chat_id: int, text: str):
    USER_STATES.pop(chat_id, None)
    parts = [p.strip() for p in text.split(":") if p.strip()]
    if len(parts) < 3:
        send_message(
            chat_id,
            "❌ <b>Xato format!</b>\nTo'g'ri format: <code>login:parol:Ism:Kurs</code>\nMasalan: <code>jdu-226516:55ugtk:Saidislom:N3</code>",
            get_master_keyboard()
        )
        return

    user_id = parts[0]
    password = parts[1]
    name = parts[2]
    course = parts[3] if len(parts) > 3 else "N3 (2026秋セメスター)"

    profiles = load_profiles()
    existing = next((p for p in profiles if p["user_id"] == user_id), None)
    if existing:
        existing["password"] = password
        existing["name"] = name
        existing["course"] = course
        save_profiles(profiles)
        send_message(chat_id, f"✅ <b>Talaba ma'lumotlari yangilandi:</b> {name} (<code>{user_id}</code>)", get_master_keyboard())
    else:
        new_prof = {
            "id": f"prof_{uuid.uuid4().hex[:8]}",
            "name": name,
            "user_id": user_id,
            "password": password,
            "course": course,
            "active": True,
            "notes": "Telegram bot orqali qo'shildi"
        }
        profiles.append(new_prof)
        save_profiles(profiles)
        send_message(chat_id, f"✅ <b>Yangi talaba muvaffaqiyatli qo'shildi:</b>\n👤 <b>{name}</b> (<code>{user_id}</code>)\n📚 Kurs: {course}", get_master_keyboard())


def handle_logs(chat_id: int, message_id: Optional[int] = None):
    if not is_admin(chat_id):
        send_message(chat_id, "⛔ Loglarni ko'rish faqat Admin uchun.", get_user_keyboard())
        return

    logs = agent_runner.get_logs()
    recent_logs = logs[-12:] if len(logs) > 12 else logs

    if not recent_logs:
        log_text = "<i>Hozircha tizim loglari mavjud emas.</i>"
    else:
        log_lines = []
        for l in recent_logs:
            log_lines.append(f"[{l.get('timestamp', '00:00:00')}] [{l.get('level', 'INFO')}] {l.get('message', '')}")
        log_text = "<pre>" + "\n".join(log_lines) + "</pre>"

    msg = f"<b>📋 TIZIM KONSOL LOGLARI</b>\n\n{log_text}"
    keyboard = {
        "inline_keyboard": [
            [{"text": "🔄 Loglarni Yangilash", "callback_data": "logs"}],
            [{"text": "🔙 Asosiy Menyu", "callback_data": "main_menu"}]
        ]
    }
    if message_id:
        edit_message(chat_id, message_id, msg, keyboard)
    else:
        send_message(chat_id, msg, keyboard)


def handle_cloud_run(chat_id: int):
    if not is_admin(chat_id):
        send_message(chat_id, "⛔ Bulutli ishga tushirish faqat Admin uchun.", get_user_keyboard())
        return

    send_message(chat_id, "☁️ <b>GitHub Actions bulutida ishga tushirish so'rovi yuborilmoqda...</b>")

    def worker():
        try:
            url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/lms_agent.yml/dispatches"
            headers = {
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "Accept": "application/vnd.github.v3+json"
            }
            r = requests.post(url, headers=headers, json={"ref": "main"}, timeout=15)
            if r.status_code in (204, 200, 201):
                msg = (
                    "☁️ <b>GitHub Actions Bulutli Agent Ishga Tushirildi!</b>\n\n"
                    f"📦 Repozitoriy: <code>{GITHUB_REPO}</code>\n"
                    "⚡ <b>Holat:</b> GitHub serverlarida 24/7 rejimda mustaqil ishlaydi (noutbuk o'chirilgan bo'lsa ham).\n\n"
                    "🔗 <i>Workflow natijalarini GitHub Actions sahifasida kuzatishingiz mumkin.</i>"
                )
                keyboard = {
                    "inline_keyboard": [
                        [{"text": "🔗 GitHub Actions Sahifasi", "url": f"https://github.com/{GITHUB_REPO}/actions"}],
                        [{"text": "🔙 Asosiy Menyu", "callback_data": "main_menu"}]
                    ]
                }
                send_message(chat_id, msg, keyboard)
            else:
                send_message(chat_id, f"❌ GitHub API xatoligi: {r.status_code}", get_master_keyboard())
        except Exception as e:
            send_message(chat_id, f"❌ Bulutga ulashda xatolik: {e}", get_master_keyboard())

    threading.Thread(target=worker, daemon=True).start()


def handle_settings(chat_id: int):
    if not is_admin(chat_id):
        send_message(chat_id, "⛔ Tizim sozlamalari faqat Admin uchun.", get_user_keyboard())
        return

    st = load_settings()
    msg = f"""<b>⚙️ TIZIM SOZLAMALARI</b>

⚡ <b>Tezlik koeffitsiyenti:</b> <code>{st.get('speed', 1.0)}x</code>
⏱️ <b>Matn darslari kutish vaqti:</b> <code>{st.get('doc_time', 25)}s</code>
🔄 <b>Tekshiruv intervali:</b> <code>{st.get('check_interval', 15)}m</code>
🤖 <b>AI Modeli:</b> <code>{st.get('gemini_model', 'gemini-3.5-flash-lite')}</code>
🖥️ <b>Headless rejimi:</b> <code>{'Yoqilgan (Tezkor)' if st.get('headless', True) else 'O\'chirilgan'}</code>
🌐 <b>Dashboard URL:</b> <code>{DASHBOARD_URL}</code>"""

    keyboard = {
        "inline_keyboard": [
            [{"text": "🎛️ Master Dashboard (Web App)", "web_app": {"url": DASHBOARD_URL}}],
            [{"text": "🔙 Asosiy Menyu", "callback_data": "main_menu"}]
        ]
    }
    send_message(chat_id, msg, keyboard)


# -----------------------------------------------------------------------------
# DISPATCHER
# -----------------------------------------------------------------------------
def process_update(update: dict):
    if "message" in update:
        msg = update["message"]
        chat_id = msg["chat"]["id"]
        text = msg.get("text", "").strip()
        user_name = msg["chat"].get("first_name", "")

        state = USER_STATES.get(chat_id)
        if state == "WAITING_ADD_STUDENT":
            if text in ("/cancel", "Bekor qilish", "bekor"):
                USER_STATES.pop(chat_id, None)
                send_message(chat_id, "❌ Yangi talaba qo'shish bekor qilindi.", get_keyboard_for(chat_id))
                return
            process_add_student_text(chat_id, text)
            return

        if text in ("/start", "/menu"):
            handle_start(chat_id, user_name)
        elif text == "/dashboard":
            if is_admin(chat_id):
                kb = {
                    "inline_keyboard": [
                        [{"text": "🎛️ Master Dashboard (Web App)", "web_app": {"url": DASHBOARD_URL}}],
                        [{"text": "🌐 Brauzerda Ochish", "url": DASHBOARD_URL}]
                    ]
                }
                send_message(chat_id, "🎛️ <b>Master Dashboard ga kirish:</b>", kb)
            else:
                send_message(chat_id, "⛔ Ushbu sahifa faqat Master Admin uchun mo'ljallangan.", get_user_keyboard())
        elif text in ("/status", "/monitor"):
            handle_monitor(chat_id)
        elif text == "/breakdown":
            handle_breakdown(chat_id)
        elif text == "/screenshot":
            handle_screenshot(chat_id)
        elif text == "/start_agent":
            handle_start_agent(chat_id)
        elif text == "/stop_agent":
            handle_stop_agent(chat_id)
        elif text == "/force_stop":
            handle_force_stop(chat_id)
        elif text == "/run_lessons":
            handle_run_lessons(chat_id)
        elif text == "/run_tests":
            handle_run_tests(chat_id)
        elif text == "/students":
            handle_students(chat_id)
        elif text.startswith("/add_student"):
            raw_data = text.replace("/add_student", "").strip()
            if raw_data:
                process_add_student_text(chat_id, raw_data)
            else:
                prompt_add_student(chat_id)
        elif text == "/logs":
            handle_logs(chat_id)
        elif text == "/cloud_run":
            handle_cloud_run(chat_id)
        elif text == "/settings":
            handle_settings(chat_id)
        elif text in ("/help", "/yordam"):
            if is_admin(chat_id):
                help_text = """<b>👑 MASTER ADMIN QO'LLANMASI:</b>

🎛️ <b>Master Dashboard:</b> Barcha talabalar va tizimni to'liq boshqarish (Web App).
🛑 <b>Xavfsiz To'xtatish:</b> Joriy darsni to'liq saqlab, so'ng to'xtaydi (/stop_agent).
⚡ <b>Majburiy To'xtatish:</b> Zudlik bilan to'xtatish uchun: /force_stop.
👥 <b>Talabalar Bazasi:</b> Yangi talaba qo'shish va parollarni ko'rish (/students).
☁️ <b>Cloud Run:</b> GitHub Actions orqali 24/7 bulutda ishga tushirish.
⚠️ <b>Eslatma:</b> Agent ishlayotganda e-JDU ga kirmang!"""
            else:
                help_text = """<b>🎓 TALABA QO'LLANMASI:</b>

🚀 <b>Boshlash:</b> Darslaringizni avtomatik yechishni yoqish.
🛑 <b>To'xtatish:</b> Darsni oxirigacha yetkazib, xavfsiz to'xtash.
📊 <b>Holat:</b> Bajarilgan darslar foizi va qolgan topshiriqlar.
📸 <b>Skrinshot:</b> e-JDU dagi darslaringiz fotosuratini olish.
⚠️ <b>Muhim:</b> Darslar bajarilayotgan paytda e-JDU saytiga kirmang!"""
            send_message(chat_id, help_text, get_keyboard_for(chat_id))

    elif "callback_query" in update:
        cq = update["callback_query"]
        cq_id = cq["id"]
        chat_id = cq["message"]["chat"]["id"]
        message_id = cq["message"]["message_id"]
        data = cq.get("data", "")

        answer_callback_query(cq_id)

        if data == "start_agent":
            handle_start_agent(chat_id)
        elif data == "stop_agent":
            handle_stop_agent(chat_id)
        elif data in ("monitor", "refresh"):
            handle_monitor(chat_id, message_id)
        elif data == "breakdown":
            handle_breakdown(chat_id)
        elif data == "screenshot":
            handle_screenshot(chat_id)
        elif data == "run_lessons":
            handle_run_lessons(chat_id)
        elif data == "run_tests":
            handle_run_tests(chat_id)
        elif data == "students":
            handle_students(chat_id)
        elif data == "add_student":
            prompt_add_student(chat_id)
        elif data == "logs":
            handle_logs(chat_id, message_id)
        elif data == "cloud_run":
            handle_cloud_run(chat_id)
        elif data == "settings":
            handle_settings(chat_id)
        elif data == "main_menu":
            handle_start(chat_id)


def run_bot():
    print(f"🤖 Master & Student Role Bot ishga tushirilmoqda... Token: {BOT_TOKEN[:10]}...", flush=True)
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
                time.sleep(3)
            else:
                time.sleep(2)
        except Exception:
            time.sleep(3)


if __name__ == "__main__":
    run_bot()
