import os
import sys
import time
import json
import logging
import threading
import base64
from typing import Dict, List, Any, Optional
from datetime import datetime
from collections import deque

try:
    from playwright.sync_api import sync_playwright, Page, BrowserContext, Browser, Frame, Dialog
    HAS_PLAYWRIGHT = True
except Exception:
    sync_playwright = None
    Page = Any
    BrowserContext = Any
    Browser = Any
    Frame = Any
    Dialog = Any
    HAS_PLAYWRIGHT = False

try:
    from google import genai
    HAS_GENAI = True
except Exception:
    genai = None
    HAS_GENAI = False

from config import (
    load_settings,
    load_profiles,
    load_completed_tasks,
    save_completed_task,
    BASE_DIR
)

BASE_URL = "https://e-jdu.uz"

# Fallback models in priority order
GEMINI_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.8-flash",
    "gemini-3.5-flash",
    "gemini-flash-latest",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
]

class AgentRunner:
    def __init__(self):
        self.thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.graceful_stop_requested = False
        self.state = "STOPPED"  # STOPPED, RUNNING, WATCHING_VIDEO, SOLVING_QUIZ, STANDBY, ERROR
        self.active_profile: Optional[Dict[str, Any]] = None
        self.current_lesson: Optional[str] = None
        self.current_chapter: Optional[str] = None
        self.current_progress_pct: int = 0
        self.total_completed_count: int = 0
        self.remaining_count: int = 0
        self.latest_screenshot_b64: Optional[str] = None
        self.start_time: Optional[float] = None
        
        self.logs_lock = threading.Lock()
        self.logs = deque(maxlen=2000)
        self.log_counter = 0

        self.custom_task_prompt: Optional[str] = None
        self.students_telemetry: Dict[str, Dict[str, Any]] = {}

    def log(self, level: str, message: str, profile_id: Optional[str] = None, user_id: Optional[str] = None):
        with self.logs_lock:
            self.log_counter += 1
            prof_id = profile_id or (self.active_profile.get("id") if self.active_profile else None)
            u_id = user_id or (self.active_profile.get("user_id") if self.active_profile else None)
            entry = {
                "id": self.log_counter,
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "level": level.upper(),
                "message": message,
                "profile_id": prof_id,
                "user_id": u_id
            }
            self.logs.append(entry)
            prefix = f"[{u_id}] " if u_id else ""
            print(f"[{entry['timestamp']}] [{entry['level']}] {prefix}{entry['message']}", flush=True)

    def get_logs(self, since_id: int = 0, profile_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self.logs_lock:
            if profile_id:
                return [l for l in self.logs if l["id"] > since_id and (l.get("profile_id") == profile_id or not l.get("profile_id"))]
            return [l for l in self.logs if l["id"] > since_id]

    def update_student_telemetry(self, profile_id: str, data: Dict[str, Any]):
        if profile_id not in self.students_telemetry:
            self.students_telemetry[profile_id] = {}
        self.students_telemetry[profile_id].update(data)
        self.students_telemetry[profile_id]["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.students_telemetry[profile_id]["last_minute"] = datetime.now().strftime("%H:%M")

    def get_student_status(self, profile_id: str) -> Dict[str, Any]:
        profiles = load_profiles()
        prof = next((p for p in profiles if p["id"] == profile_id), None)
        if not prof:
            return {"error": "Talaba topilmadi"}

        telemetry = self.students_telemetry.get(profile_id, {})
        completed = load_completed_tasks(prof["user_id"])
        is_active = (self.active_profile and self.active_profile.get("id") == profile_id and self.state not in ("STOPPED", "ERROR"))

        completed_count = len(completed)
        remaining = self.remaining_count if is_active else telemetry.get("remaining", 0)
        total_units = telemetry.get("total_units", completed_count + remaining)
        pct = int((completed_count / total_units * 100)) if total_units > 0 else (self.current_progress_pct if is_active else 0)

        return {
            "profile": prof,
            "is_running": is_active,
            "agent_state": self.state if is_active else ("STANDBY" if completed_count > 0 else "STOPPED"),
            "current_chapter": self.current_chapter if is_active else telemetry.get("current_chapter", "-"),
            "current_lesson": self.current_lesson if is_active else telemetry.get("current_lesson", "-"),
            "current_progress_pct": pct,
            "total_completed": completed_count,
            "remaining": remaining,
            "total_units": total_units,
            "current_activity": telemetry.get("current_activity", "Kutish holatida" if not is_active else "Ishlamoqda..."),
            "last_updated": telemetry.get("last_updated", "-"),
            "last_minute": telemetry.get("last_minute", datetime.now().strftime("%H:%M")),
            "uptime_seconds": int(time.time() - self.start_time) if is_active and self.start_time else 0
        }

    def capture_screenshot(self, page: Optional[Page]):
        if not page:
            return
        try:
            shot_bytes = page.screenshot(type="jpeg", quality=65)
            self.latest_screenshot_b64 = base64.b64encode(shot_bytes).decode("utf-8")
        except Exception:
            pass

    def get_status(self) -> Dict[str, Any]:
        uptime_sec = int(time.time() - self.start_time) if self.start_time and self.state != "STOPPED" else 0
        return {
            "state": self.state,
            "is_running": self.state not in ("STOPPED", "ERROR"),
            "is_stopping": self.graceful_stop_requested,
            "active_profile": self.active_profile,
            "current_lesson": self.current_lesson,
            "current_chapter": self.current_chapter,
            "current_progress_pct": self.current_progress_pct,
            "total_completed": self.total_completed_count,
            "remaining": self.remaining_count,
            "uptime_seconds": uptime_sec,
            "custom_task": self.custom_task_prompt,
            "has_screenshot": self.latest_screenshot_b64 is not None
        }

    def start(self, profile_id: Optional[str] = None, custom_task: Optional[str] = None):
        if self.thread and self.thread.is_alive():
            self.log("WARN", "Agent allaqachon ishlab turibdi!")
            return False

        self.stop_event.clear()
        self.graceful_stop_requested = False
        self.state = "RUNNING"
        self.start_time = time.time()
        self.custom_task_prompt = custom_task

        self.thread = threading.Thread(
            target=self._worker_loop,
            args=(profile_id,),
            daemon=True
        )
        self.thread.start()
        self.log("INFO", "🚀 Agent fon jarayoni muvaffaqiyatli ishga tushirildi.")
        return True

    def stop(self, force: bool = False):
        if not (self.thread and self.thread.is_alive()):
            self.state = "STOPPED"
            self.graceful_stop_requested = False
            self.log("INFO", "Agent allaqachon to'xtatilgan.")
            return True

        if force or self.state in ("STANDBY", "STOPPED"):
            self.log("INFO", "🛑 Agent zudlik bilan to'xtatildi.")
            self.stop_event.set()
            self.state = "STOPPED"
            self.graceful_stop_requested = False
            self.current_lesson = None
            return True

        self.log("INFO", "⏳ [GRACEFUL STOP] Xavfsiz to'xtatish so'rovi qabul qilindi. Agent hozirgi darsini oxirigacha yakunlab, so'ng to'xtaydi (resurslar tejaladi)...")
        self.graceful_stop_requested = True
        self.state = "FINISHING_TASK"
        return True

    # ------------------------------------------------------------------------
    # AI QUESTION SOLVER & TASK PARSER
    # ------------------------------------------------------------------------
    def _solve_quiz_with_ai(self, gemini_client, model_name: str, question_text: str, choices: List[Dict[str, Any]], custom_prompt: str, image_bytes: Optional[bytes] = None) -> int:
        if not choices:
            return 0

        choices_text = "\n".join([f"{i+1}. {c['text']}" for i, c in enumerate(choices)])
        prompt = f"""Siz yapon tili bo'yicha JLPT N3 darajasidagi professional repetitor va imtihon tahlilchisisiz.
Foydalanuvchi ko'rsatmasi: {custom_prompt or "Eng to'g'ri, xatosiz va aniq javobni tanla"}

--- SAVOL / MATN ---
{question_text}

--- VARIANTLAR ---
{choices_text}

SAVOLNI CHUQUR TAHLIL QILISH VA FIKRLASH TALABLARI:
1. Savoldagi qavs ichidagi 【...】 yoki chiziq tortilgan so'zning o'qilishi (reading/furigana), ma'nosi yoki grammatik yuklamasini aniqlang.
2. Har bir variantni grammatik qoidalar (yuklamalar, fe'l shakllari, jumlalar bog'lanishi) bo'yicha bosqichma-bosqich tahlil qiling (Chain of Thought).
3. Eng to'g'ri bo'lgan yagona variant raqamini tanlang.

FAQAT quyidagi JSON formatida javob bering:
{{
  "fikrlash": "Qaysi grammatika yoki o'qilish qoidasi asosida bu variant tanlangani haqida 1-2 jumlalik tahlil",
  "correct_choice_number": <1 dan {len(choices)} gacha son>
}}
"""
        # Ensure Gemini client is available
        if not gemini_client:
            try:
                s = load_settings()
                key = os.environ.get("GEMINI_API_KEY") or s.get("gemini_api_key")
                gemini_client = genai.Client(api_key=key)
            except Exception as e:
                self.log("ERROR", f"❌ Gemini Client yaratib bo'lmadi: {e}")

        models_to_try = [model_name] + [m for m in GEMINI_MODELS if m != model_name]
        last_error = None
        for m in models_to_try:
            try:
                contents = []
                if image_bytes:
                    try:
                        from google.genai import types
                        img_part = types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
                        contents.append(img_part)
                    except Exception:
                        pass
                contents.append(prompt)

                res = gemini_client.models.generate_content(model=m, contents=contents)
                raw = res.text.strip().replace("```json", "").replace("```", "").strip()
                data = json.loads(raw)
                num = int(data.get("correct_choice_number", 1))
                fikr = data.get("fikrlash", "")
                idx = num - 1
                if 0 <= idx < len(choices):
                    if fikr:
                        self.log("INFO", f"🧠 [AI Fikrlash]: {fikr}")
                    self.log("INFO", f"🎯 [AI Tanlovi]: #{num} -> '{choices[idx]['text']}'")
                    return idx
            except Exception as e:
                last_error = e
                continue

        if last_error:
            err_str = str(last_error)
            if "UNAUTHENTICATED" in err_str or "API key not valid" in err_str or "401" in err_str:
                self.log("ERROR", "❌ [DIQQAT] Gemini API kalit yaroqsiz! Dashboard 'Sozlamalar' bo'limida aistudio.google.com dan olingan haqiqiy API kalitni kiriting!")
            else:
                self.log("WARN", f"AI javob berolmadi ({last_error.__class__.__name__}). Standart 1-variant tanlandi.")
        else:
            self.log("WARN", "AI javob berolmadi, standart 1-variant tanlandi.")
        return 0

    # ------------------------------------------------------------------------
    # LMS AUTOMATION CORE
    # ------------------------------------------------------------------------
    def _worker_loop(self, target_profile_id: Optional[str]):
        browser = None
        playwright_ctx = None
        try:
            self.log("INFO", "⚙️ Sozlamalar va profillar yuklanmoqda...")
            settings = load_settings()
            profiles = load_profiles()

            # Initialize Gemini Client
            gemini_client = None
            api_key = settings.get("gemini_api_key", "").strip()
            if api_key:
                try:
                    gemini_client = genai.Client(api_key=api_key)
                except Exception as e:
                    self.log("WARN", f"Gemini API ulashda xatolik: {e}")

            # Choose profile(s)
            profiles_to_run = []
            if settings.get("batch_mode", False):
                profiles_to_run = [p for p in profiles if p.get("active", True)]
            else:
                if target_profile_id:
                    matched = [p for p in profiles if p.get("id") == target_profile_id]
                    profiles_to_run = matched if matched else [profiles[0]]
                else:
                    active_p = [p for p in profiles if p.get("active", True)]
                    profiles_to_run = active_p[:1] if active_p else [profiles[0]]

            if not profiles_to_run:
                self.log("ERROR", "Hech qanday faol profil topilmadi!")
                self.state = "STOPPED"
                return

            self.log("INFO", f"📋 Ishlanadigan profillar: {[p.get('name', 'Talaba') + ' (' + p.get('user_id', '') + ')' for p in profiles_to_run]}")

            self.log("INFO", "🌐 Brauzer (Playwright Chromium) ishga tushirilmoqda...")
            playwright_ctx = sync_playwright().start()
            headless = settings.get("headless", True)
            browser = playwright_ctx.chromium.launch(
                headless=headless,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-extensions",
                    "--no-zygote",
                    "--disable-blink-features=AutomationControlled"
                ]
            )
            context: BrowserContext = browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
            page: Page = context.new_page()

            # Dialog auto-accept handler
            def handle_dialog(dialog: Dialog):
                self.log("INFO", f"🔔 Alert/Popup: [{dialog.type}] '{dialog.message}' -> OK qilindi")
                try:
                    dialog.accept()
                except Exception:
                    pass
            page.on("dialog", handle_dialog)

            while not self.stop_event.is_set():
                # Refresh settings periodically
                settings = load_settings()
                speed = float(settings.get("speed", 1.0))
                doc_time = int(settings.get("doc_time", 25))
                check_interval_min = int(settings.get("check_interval", 15))
                selected_model = settings.get("gemini_model", "gemini-3.8-flash")
                custom_prompt = self.custom_task_prompt or settings.get("custom_instructions", "")

                for profile in profiles_to_run:
                    if self.stop_event.is_set():
                        break

                    self.active_profile = profile
                    self.log("INFO", f"\n=======================================================")
                    self.log("INFO", f"👤 Talaba profiliga o'tildi: {profile.get('name', '')} ({profile.get('user_id', '')})")
                    self.log("INFO", f"=======================================================")

                    # Run profile session
                    self._process_profile(page, profile, settings, gemini_client, selected_model, speed, doc_time, custom_prompt)

                if self.stop_event.is_set():
                    break

                # Standby wait before checking for new lessons
                self.state = "STANDBY"
                self.log("INFO", f"⏳ Barcha joriy darslar yakunlandi. Yangi darslar {check_interval_min} daqiqadan so'ng tekshiriladi...")
                
                sleep_remaining = check_interval_min * 60
                while sleep_remaining > 0 and not self.stop_event.is_set():
                    time.sleep(min(3, sleep_remaining))
                    sleep_remaining -= 3

        except Exception as e:
            import traceback
            self.log("ERROR", f"Agent jarayonida xatolik: {e}")
            self.log("ERROR", traceback.format_exc().strip())
            self.state = "ERROR"
        finally:
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass
            if playwright_ctx:
                try:
                    playwright_ctx.stop()
                except Exception:
                    pass
            self.state = "STOPPED"
            self.active_profile = None
            self.current_lesson = None
            self.log("INFO", "Agent seansi yakunlandi.")

    def _login(self, page: Page, profile: Dict[str, Any]) -> bool:
        user_id = profile["user_id"]
        password = profile["password"]
        for attempt in range(3):
            if self.stop_event.is_set():
                return False
            try:
                curr_url = page.url or ""
                needs_login = (
                    "error.aspx" in curr_url
                    or curr_url.rstrip("/") in [BASE_URL, f"{BASE_URL}/default.aspx", "about:blank"]
                    or page.locator('input[name*="txtUserID"]').count() > 0
                )
                if not needs_login and "/home/" in curr_url:
                    return True

                self.log("INFO", f"🔑 Tizimga kirilmoqda: {user_id}...")
                page.goto(BASE_URL, timeout=30000, wait_until="load")
                page.wait_for_timeout(1500)
                self.capture_screenshot(page)

                user_input = page.locator('input[name*="txtUserID"]').first
                pass_input = page.locator('input[name*="txtPassword"]').first

                if user_input.is_visible():
                    user_input.fill(user_id)
                    pass_input.fill(password)
                    page.locator('button:has-text("ログイン"), input[value*="ログイン"]').first.click()
                    page.wait_for_load_state("load", timeout=20000)
                    page.wait_for_timeout(2000)
                    self.capture_screenshot(page)

                if "/home/" in page.url:
                    self.log("INFO", f"✅ Tizimga muvaffaqiyatli kirildi! ({profile['name']})")
                    return True
            except Exception as ex:
                self.log("WARN", f"Kirishda xatolik (#{attempt+1}): {ex}")
                time.sleep(3)
        return False

    def _navigate_to_course(self, page: Page, profile: Dict[str, Any]) -> bool:
        course_name = profile.get("course", "N3 (2026秋セメスター)")
        try:
            if "/home/course/default.aspx" not in page.url or "k=" not in page.url:
                page.goto(f"{BASE_URL}/home/default.aspx", timeout=30000, wait_until="load")
                page.wait_for_timeout(1500)

                found = page.evaluate('''() => {
                    const links = Array.from(document.querySelectorAll('a[href*="/home/course/default.aspx"]'));
                    const n3 = links.find(a => {
                        const txt = (a.innerText || "") + " " + (a.closest('.card, .list-group-item, li, div')?.innerText || "");
                        return txt.includes("N3") || a.href.includes("953") || txt.includes("953");
                    }) || links[0];
                    if (n3) { n3.click(); return true; }
                    return false;
                }''')
                if not found:
                    self.log("ERROR", f"Kurs kartasi topilmadi: {course_name}")
                    return False

                page.wait_for_load_state("load", timeout=20000)
                page.wait_for_timeout(2500)
                self.capture_screenshot(page)

            if page.locator('li[id*="liChapter"]').count() == 0:
                inner_mod = page.locator('.list-group-item:has-text("N3")').first
                if inner_mod.is_visible():
                    inner_mod.click()
                    page.wait_for_load_state("load", timeout=20000)
                    page.wait_for_timeout(1500)
                    self.capture_screenshot(page)

            return page.locator('li[id*="liChapter"]').count() > 0
        except Exception as e:
            self.log("ERROR", f"Kurs navigatsiyasida xatolik: {e}")
            return False

    def _dismiss_all_modals(self, page: Page):
        """KnowledgeDeliver LMS dagi dialog, popup va modallarni (#test-log-detail, #unitProp) to'liq yopish."""
        try:
            # 1. Click modal close buttons
            for sel in [
                '#test-log-detail button',
                '#test-log-detail .btn-close',
                '#unitProp button',
                '#unitProp .btn-close',
                '.modal.show button.btn-close',
                '.modal.show [data-bs-dismiss="modal"]',
                'button:has-text("閉じる")',
                'a:has-text("閉じる")',
                'button:has-text("OK")'
            ]:
                try:
                    for b in page.locator(sel).all():
                        if b.is_visible(timeout=150):
                            b.click(timeout=400)
                            page.wait_for_timeout(100)
                except Exception:
                    pass

            # 2. Force remove modal overlays via DOM evaluation
            page.evaluate('''() => {
                const modals = document.querySelectorAll('.modal.show, #test-log-detail, #unitProp, .modal');
                modals.forEach(m => {
                    m.classList.remove('show');
                    m.style.display = 'none';
                    m.setAttribute('aria-hidden', 'true');
                });
                document.querySelectorAll('.modal-backdrop, .offcanvas-backdrop').forEach(b => b.remove());
                document.body.classList.remove('modal-open');
                document.body.style.overflow = '';
                document.body.style.paddingRight = '';
            }''')
        except Exception:
            pass

    def _expand_chapters(self, page: Page):
        self._dismiss_all_modals(page)
        try:
            page.evaluate('''() => {
                document.querySelectorAll('li[id*="liChapter"] button.accordion-button.collapsed').forEach(b => b.click());
            }''')
            page.wait_for_timeout(2000)
        except Exception:
            pass
        self._dismiss_all_modals(page)

    def _scan_units(self, page: Page, user_id: str) -> List[Dict[str, Any]]:
        self._dismiss_all_modals(page)
        self._expand_chapters(page)
        completed_set = load_completed_tasks(user_id)

        units_data = page.evaluate('''() => {
            const results = [];
            const chapters = document.querySelectorAll('li[id*="liChapter"]');
            chapters.forEach(ch => {
                const btn = ch.querySelector('button.accordion-button, button');
                const chTitle = btn ? btn.innerText.trim().replace(/\\s+/g, ' ') : 'Chapter';
                const unitItems = ch.querySelectorAll('li[id*="liUnitListGroupItem"]');
                unitItems.forEach(u => {
                    const link = u.querySelector('a[id*="lbnUnitName"]');
                    const title = link ? link.innerText.trim() : u.innerText.trim();
                    const isFinished = u.classList.contains('finished') || 
                                       u.classList.contains('complete') || 
                                       u.classList.contains('passed');
                    const pie = u.querySelector('.pie-list');
                    const progress = pie ? pie.getAttribute('data-kd-progress') : '0';
                    const hasCheck = !!u.querySelector('.bi-check, .bi-check-circle, .bi-check-circle-fill, .bi-check2');
                    const uidMatch = (u.outerHTML || '').match(/uid=(\d+)/);
                    
                    results.push({
                        chapter: chTitle,
                        title: title,
                        unitId: u.id,
                        uid: uidMatch ? uidMatch[1] : null,
                        linkId: link ? link.id : null,
                        isFinished: isFinished || progress === '100' || hasCheck
                    });
                });
            });
            return results;
        }''')

        pending = []
        for u in units_data:
            key = f"{u['chapter']}::{u['title']}"
            if u["isFinished"] or key in completed_set:
                continue
            pending.append(u)

        self.total_completed_count = len(units_data) - len(pending)
        self.remaining_count = len(pending)
        self.log("INFO", f"📊 Jami darslar: {len(units_data)} ta | Bajarilgan: {self.total_completed_count} | Qolgan: {len(pending)}")
        
        if self.active_profile:
            self.update_student_telemetry(self.active_profile["id"], {
                "total_units": len(units_data),
                "completed_count": self.total_completed_count,
                "remaining": len(pending),
                "progress_pct": int((self.total_completed_count / len(units_data) * 100)) if len(units_data) > 0 else 0
            })

        return pending

    def _process_profile(self, page: Page, profile: Dict[str, Any], settings: Dict[str, Any], gemini_client, model_name: str, speed: float, doc_time: int, custom_prompt: str):
        if not self._login(page, profile):
            self.log("ERROR", f"Profilga kirib bo'lmadi: {profile['name']}")
            return

        if not self._navigate_to_course(page, profile):
            self.log("ERROR", f"Kursga kirib bo'lmadi: {profile['course']}")
            return

        pending = self._scan_units(page, profile["user_id"])
        if not pending:
            self.log("INFO", f"🎉 {profile['name']} uchun barcha darslar to'liq bajarilgan!")
            self.update_student_telemetry(profile["id"], {
                "current_activity": "Barcha darslar yakunlandi! 🎉",
                "current_lesson": "Yakunlangan",
                "current_chapter": "Tugallandi"
            })
            return

        for idx, unit in enumerate(pending):
            if self.stop_event.is_set():
                break

            self.current_chapter = unit["chapter"]
            self.current_lesson = unit["title"]
            self.current_progress_pct = int(((idx) / len(pending)) * 100)
            self.log("INFO", f"\n[{idx+1}/{len(pending)}] Dars boshlandi: [{unit['chapter']}] {unit['title']}")

            self.update_student_telemetry(profile["id"], {
                "current_chapter": unit["chapter"],
                "current_lesson": unit["title"],
                "current_activity": f"Bajarilmoqda: {unit['title']}",
                "remaining": len(pending) - idx,
                "progress_pct": int(((idx) / len(pending)) * 100)
            })

            success = self._run_unit(page, profile["user_id"], unit, gemini_client, model_name, speed, doc_time, custom_prompt)
            if success:
                save_completed_task(profile["user_id"], f"{unit['chapter']}::{unit['title']}")
                time.sleep(1.5)
                self.update_student_telemetry(profile["id"], {
                    "completed_count": self.total_completed_count + idx + 1,
                    "remaining": len(pending) - idx - 1,
                    "current_activity": f"✅ Yakunlandi: {unit['title']}"
                })
            else:
                self.log("WARN", f"Dars bajarilmadi yoki xatolik yuz berdi: {unit['title']}")

            if self.graceful_stop_requested:
                self.log("INFO", f"✅ [GRACEFUL STOP] Joriy vazifa '{unit['title']}' oxirigacha yakunlandi va saqlandi! Agent xavfsiz to'xtatildi.")
                self.state = "STOPPED"
                self.graceful_stop_requested = False
                self.stop_event.set()
                break

        self.current_progress_pct = 100
        self.current_lesson = None

    def _run_unit(self, page: Page, user_id: str, unit: Dict[str, Any], gemini_client, model_name: str, speed: float, doc_time: int, custom_prompt: str) -> bool:
        self._dismiss_all_modals(page)
        
        for attempt in range(1, 3):
            try:
                self._expand_chapters(page)
                self._dismiss_all_modals(page)

                link = page.locator(f"#{unit['linkId']}").first if unit.get("linkId") else None
                if not link or not link.is_visible():
                    link = page.locator(f'li[id*="liUnitListGroupItem"]:not(.finished) a[id*="lbnUnitName"]:has-text("{unit["title"]}")').first

                if not link or not link.is_visible():
                    self.log("WARN", f"Havola topilmadi (urinish #{attempt}): {unit['title']}")
                    if attempt == 1:
                        self._navigate_to_course(page, self.active_profile)
                        continue
                    return False

                # Ensure nothing intercepts pointer events
                self._dismiss_all_modals(page)
                clicked = False
                try:
                    link.click(timeout=6000, force=True)
                    clicked = True
                except Exception:
                    self.log("WARN", f"Oddiy click qilinmadi, JS orqali bosilmoqda: {unit['title']}")
                    self._dismiss_all_modals(page)
                    if unit.get("linkId"):
                        page.evaluate('(id) => { const el = document.getElementById(id); if (el) { el.click(); } }', unit['linkId'])
                        clicked = True

                page.wait_for_timeout(2000)
                # Dismiss lingering modals before starting
                self._dismiss_all_modals(page)
                self.capture_screenshot(page)

                start_btn = page.locator('button:has-text("開始する"), a:has-text("開始する"), [id*="hplStart"]').first
                target_page = page
                if start_btn.is_visible():
                    initial_count = len(page.context.pages)
                    start_btn.click()
                    page.wait_for_timeout(3000)
                    if len(page.context.pages) > initial_count:
                        target_page = page.context.pages[-1]
                        target_page.bring_to_front()

                target_page.wait_for_load_state("load", timeout=20000)
                page.wait_for_timeout(2000)
                self.capture_screenshot(target_page)

                curr_url = target_page.url
                if "test" in curr_url.lower() or "Test" in unit["title"] or "テスト" in unit["title"] or "Quiz" in unit["title"]:
                    res = self._handle_quiz(target_page, unit, gemini_client, model_name, custom_prompt)
                else:
                    res = self._handle_video_or_doc(target_page, unit, speed, doc_time)

                if target_page != page:
                    try:
                        target_page.close()
                    except Exception:
                        pass

                self._dismiss_all_modals(page)

                if "/home/course/default.aspx" not in page.url:
                    page.goto(f"{BASE_URL}/home/course/default.aspx", wait_until="load")
                    page.wait_for_timeout(1500)
                    self._navigate_to_course(page, self.active_profile)
                    self._dismiss_all_modals(page)

                return res
            except Exception as e:
                self.log("ERROR", f"Dars bajarishda xatolik (urinish #{attempt}): {e}")
                self._dismiss_all_modals(page)
                if attempt == 1:
                    try:
                        page.goto(f"{BASE_URL}/home/course/default.aspx", wait_until="load")
                        page.wait_for_timeout(1500)
                        self._navigate_to_course(page, self.active_profile)
                    except Exception:
                        pass
                    continue
                return False
        return False

    def _handle_video_or_doc(self, page: Page, unit: Dict[str, Any], speed: float, doc_time: int) -> bool:
        self.state = "WATCHING_VIDEO"
        self.log("INFO", f"🎬 Dars ochildi: '{unit['title']}'...")
        page.wait_for_timeout(2000)

        contents_frame = page.frame(name="contents")
        ctrl_frame = page.frame(name="ctrl")
        active_video_frame = None

        # Search for video across all frames with up to 4 retries (8 seconds)
        for _ in range(4):
            candidate_frames = [contents_frame, page.main_frame] if contents_frame else []
            for f in page.frames:
                if f not in candidate_frames:
                    candidate_frames.append(f)

            for fr in candidate_frames:
                try:
                    if fr and fr.evaluate('() => !!document.querySelector("video")'):
                        active_video_frame = fr
                        break
                except Exception:
                    pass
            if active_video_frame:
                break
            page.wait_for_timeout(2000)

        if active_video_frame:
            # Wait for video duration to load
            for _ in range(5):
                video_meta = active_video_frame.evaluate('''() => {
                    const v = document.querySelector("video");
                    return v ? { duration: v.duration || 0, currentTime: v.currentTime || 0 } : null;
                }''')
                duration = video_meta.get("duration", 0) if video_meta else 0
                if duration and duration > 0:
                    break
                page.wait_for_timeout(1000)

            dur_str = time.strftime('%M:%S', time.gmtime(duration)) if duration > 0 else "Noma'lum"
            self.log("INFO", f"📹 Video darsi: Davomiyligi {dur_str} (Tezlik: {speed}x)")

            active_video_frame.evaluate(f'''() => {{
                const v = document.querySelector("video");
                if (v) {{
                    v.playbackRate = {speed};
                    v.muted = true;
                    v.play().catch(() => {{}});
                }}
            }}''')

            start_t = time.time()
            max_wait = (duration / max(0.5, speed)) + 30 if duration > 0 else 300
            last_logged = -10

            while time.time() - start_t < max_wait and not self.stop_event.is_set():
                status = active_video_frame.evaluate('''() => {
                    const v = document.querySelector("video");
                    return v ? { ended: v.ended, currentTime: v.currentTime || 0, duration: v.duration || 0, paused: v.paused } : { ended: true };
                }''')
                curr_t = status.get("currentTime", 0)
                dur_t = status.get("duration", duration) or duration
                is_ended = status.get("ended", False)

                if dur_t > 0:
                    pct = int((curr_t / dur_t) * 100)
                    if pct >= last_logged + 15:
                        self.log("INFO", f"⏳ [Video]: {time.strftime('%M:%S', time.gmtime(curr_t))} / {dur_str} ({pct}%)")
                        last_logged = pct
                        self.capture_screenshot(page)

                if is_ended or (dur_t > 0 and curr_t >= dur_t - 0.5):
                    self.log("INFO", "🏁 Video oxiriga yetdi!")
                    time.sleep(2)
                    break
                time.sleep(3)
        else:
            is_video_lesson = any(k in unit['title'] for k in ["動画", "ビデオ", "Lecture", "会話", "文法"])
            effective_time = max(90, int(480 / max(0.5, speed))) if is_video_lesson else doc_time
            if is_video_lesson:
                self.log("INFO", f"📹 Video darsi (Standart rejim): Davomiyligi 2x tezlik nisbatida {effective_time}s kutilmoqda...")
            else:
                self.log("INFO", f"📖 Slayd/Matn darsi o'rganilmoqda ({effective_time} soniya kutish)...")
            waited = 0
            while waited < effective_time and not self.stop_event.is_set():
                time.sleep(5)
                waited += 5
                if waited % 15 == 0 or waited >= effective_time:
                    self.log("INFO", f"⌛ O'rganish jarayoni: {waited}/{effective_time}s")
                    self.capture_screenshot(page)

        # Click finish
        clicked = False
        if ctrl_frame:
            try:
                clicked = ctrl_frame.evaluate('''() => {
                    const b = document.getElementById("a_next") || Array.from(document.querySelectorAll("a, button")).find(el => (el.innerText || "").includes("終了"));
                    if (b) { b.classList.remove("disabled"); b.click(); return true; }
                    return false;
                }''')
            except Exception:
                pass

        if not clicked:
            btn = page.locator('#a_next, button:has-text("終了"), a:has-text("終了")').first
            if btn.is_visible():
                btn.click()

        page.wait_for_load_state("load", timeout=15000)
        page.wait_for_timeout(2500)
        self.capture_screenshot(page)
        self.log("INFO", f"✅ Dars yakunlandi: '{unit['title']}'")
        return True

    def _handle_quiz(self, page: Page, unit: Dict[str, Any], gemini_client, model_name: str, custom_prompt: str) -> bool:
        self.state = "SOLVING_QUIZ"
        self.log("INFO", f"📝 Test darsi AI (Gemini) bilan yechilmoqda: '{unit['title']}'...")
        try:
            from engine_v2.master_solver import solve_test_unit
            u_id = self.active_profile.get("user_id", "jdu-226516") if self.active_profile else "jdu-226516"
            pwd = self.active_profile.get("password", "55ugtk") if self.active_profile else "55ugtk"
            ok = solve_test_unit(page, unit, user_id=u_id, password=pwd)
            self._dismiss_all_modals(page)
            if ok:
                self.log("INFO", f"✅ Test muvaffaqiyatli topshirildi: '{unit['title']}'")
            else:
                self.log("WARN", f"⚠️ Test to'liq topshirilmadi: '{unit['title']}'")
            return ok
        except Exception as e:
            self.log("ERROR", f"Test topshirishda xatolik: {e}")
            return False


# Global runner instance
agent_runner = AgentRunner()
