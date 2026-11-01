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

from playwright.sync_api import sync_playwright, Page, BrowserContext, Browser, Frame, Dialog
from google import genai

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
    "gemini-3.8-flash",
    "gemini-2.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.5-flash",
    "gemini-flash-latest",
]

class AgentRunner:
    def __init__(self):
        self.thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
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

    def log(self, level: str, message: str):
        with self.logs_lock:
            self.log_counter += 1
            entry = {
                "id": self.log_counter,
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "level": level.upper(),
                "message": message
            }
            self.logs.append(entry)
            print(f"[{entry['timestamp']}] [{entry['level']}] {entry['message']}", flush=True)

    def get_logs(self, since_id: int = 0) -> List[Dict[str, Any]]:
        with self.logs_lock:
            return [l for l in self.logs if l["id"] > since_id]

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

    def stop(self):
        if not (self.thread and self.thread.is_alive()):
            self.state = "STOPPED"
            self.log("INFO", "Agent allaqachon to'xtatilgan.")
            return True

        self.log("INFO", "🛑 Agentni to'xtatish so'rovi yuborildi...")
        self.stop_event.set()
        self.state = "STOPPING"
        self.thread.join(timeout=8.0)
        self.state = "STOPPED"
        self.current_lesson = None
        self.log("INFO", "Agent to'liq to'xtatildi.")
        return True

    # ------------------------------------------------------------------------
    # AI QUESTION SOLVER & TASK PARSER
    # ------------------------------------------------------------------------
    def _solve_quiz_with_ai(self, gemini_client, model_name: str, question_text: str, choices: List[Dict[str, Any]], custom_prompt: str) -> int:
        if not choices:
            return 0

        choices_text = "\n".join([f"{i+1}. {c['text']}" for i, c in enumerate(choices)])
        prompt = f"""Siz yapon tili bo'yicha N3 darajadagi professional imtihon topshiruvchi ekpertsiz.
Foydalanuvchi ko'rsatmasi: {custom_prompt or "Eng to'g'ri va aniq javobni tanla"}

--- SAVOL VA MATN ---
{question_text}

--- VARIANTLAR ---
{choices_text}

Qaysi variant to'g'ri javob?
FAQAT VA FAQAT quyidagi JSON formatida javob bering:
{{"correct_choice_number": <variant raqami 1 dan {len(choices)} gacha>}}
"""
        models_to_try = [model_name] + [m for m in GEMINI_MODELS if m != model_name]
        for m in models_to_try:
            try:
                res = gemini_client.models.generate_content(model=m, contents=prompt)
                raw = res.text.strip().replace("```json", "").replace("```", "").strip()
                data = json.loads(raw)
                num = int(data.get("correct_choice_number", 1))
                idx = num - 1
                if 0 <= idx < len(choices):
                    self.log("INFO", f"🧠 [AI {m}]: Variant #{num} tanlandi -> '{choices[idx]['text']}'")
                    return idx
            except Exception:
                continue

        self.log("WARN", "AI javob berolmadi, standart 1-variant tanlandi.")
        return 0

    # ------------------------------------------------------------------------
    # LMS AUTOMATION CORE
    # ------------------------------------------------------------------------
    def _worker_loop(self, target_profile_id: Optional[str]):
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
                matched = [p for p in profiles if p["id"] == target_profile_id]
                profiles_to_run = matched if matched else [profiles[0]]
            else:
                active_p = [p for p in profiles if p.get("active", True)]
                profiles_to_run = active_p[:1] if active_p else [profiles[0]]

        if not profiles_to_run:
            self.log("ERROR", "Hech qanday faol profil topilmadi!")
            self.state = "STOPPED"
            return

        self.log("INFO", f"📋 Ishlanadigan profillar: {[p['name'] + ' (' + p['user_id'] + ')' for p in profiles_to_run]}")

        with sync_playwright() as playwright:
            headless = settings.get("headless", True)
            browser: Browser = playwright.chromium.launch(
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

            try:
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
                        self.log("INFO", f"👤 Talaba profiliga o'tildi: {profile['name']} ({profile['user_id']})")
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
                self.log("ERROR", f"Agent siklida kutilmagan xatolik: {e}")
                self.state = "ERROR"
            finally:
                try:
                    browser.close()
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

                course_card = page.locator(f'text="{course_name}"').first
                if not course_card.is_visible():
                    course_card = page.locator('.card:has-text("N3"), a:has-text("N3")').first

                if not course_card.is_visible():
                    self.log("ERROR", f"Kurs kartasi topilmadi: {course_name}")
                    return False

                course_card.click()
                page.wait_for_load_state("load", timeout=20000)
                page.wait_for_timeout(1500)
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

    def _expand_chapters(self, page: Page):
        try:
            buttons = page.locator('li[id*="liChapter"] button.accordion-button.collapsed').all()
            for btn in buttons:
                try:
                    btn.click()
                    page.wait_for_timeout(150)
                except Exception:
                    pass
            page.wait_for_timeout(500)
        except Exception:
            pass

    def _scan_units(self, page: Page, user_id: str) -> List[Dict[str, Any]]:
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
                    
                    results.push({
                        chapter: chTitle,
                        title: title,
                        unitId: u.id,
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
            if u["isFinished"] or key in completed_set or u["title"] in completed_set:
                continue
            pending.append(u)

        self.total_completed_count = len(units_data) - len(pending)
        self.remaining_count = len(pending)
        self.log("INFO", f"📊 Jami darslar: {len(units_data)} ta | Bajarilgan: {self.total_completed_count} | Qolgan: {len(pending)}")
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
            return

        for idx, unit in enumerate(pending):
            if self.stop_event.is_set():
                break

            self.current_chapter = unit["chapter"]
            self.current_lesson = unit["title"]
            self.current_progress_pct = int(((idx) / len(pending)) * 100)
            self.log("INFO", f"\n[{idx+1}/{len(pending)}] Dars boshlandi: [{unit['chapter']}] {unit['title']}")

            success = self._run_unit(page, profile["user_id"], unit, gemini_client, model_name, speed, doc_time, custom_prompt)
            if success:
                save_completed_task(profile["user_id"], f"{unit['chapter']}::{unit['title']}")
                time.sleep(2)
            else:
                self.log("WARN", f"Dars bajarilmadi yoki xatolik yuz berdi: {unit['title']}")

        self.current_progress_pct = 100
        self.current_lesson = None

    def _run_unit(self, page: Page, user_id: str, unit: Dict[str, Any], gemini_client, model_name: str, speed: float, doc_time: int, custom_prompt: str) -> bool:
        try:
            self._expand_chapters(page)
            link = page.locator(f"#{unit['linkId']}").first if unit.get("linkId") else None
            if not link or not link.is_visible():
                link = page.locator(f'li[id*="liUnitListGroupItem"]:not(.finished) a[id*="lbnUnitName"]:has-text("{unit["title"]}")').first

            if not link or not link.is_visible():
                self.log("WARN", f"Havola topilmadi: {unit['title']}")
                return False

            link.click()
            page.wait_for_timeout(2000)
            self.capture_screenshot(page)

            start_btn = page.locator('button:has-text("開始する"), a:has-text("開始する"), [id*="hplStart"]').first
            if start_btn.is_visible():
                start_btn.click()

            page.wait_for_load_state("load", timeout=20000)
            page.wait_for_timeout(2500)
            self.capture_screenshot(page)

            curr_url = page.url
            if "test2.aspx" in curr_url or "Test" in unit["title"] or "テスト" in unit["title"] or "Quiz" in unit["title"]:
                res = self._handle_quiz(page, unit, gemini_client, model_name, custom_prompt)
            else:
                res = self._handle_video_or_doc(page, unit, speed, doc_time)

            if "/home/course/default.aspx" not in page.url:
                page.goto(f"{BASE_URL}/home/default.aspx", wait_until="load")
                page.wait_for_timeout(1500)
                self._navigate_to_course(page, self.active_profile)

            return res
        except Exception as e:
            self.log("ERROR", f"Dars bajarishda xatolik: {e}")
            return False

    def _handle_video_or_doc(self, page: Page, unit: Dict[str, Any], speed: float, doc_time: int) -> bool:
        self.state = "WATCHING_VIDEO"
        self.log("INFO", f"🎬 Dars ochildi: '{unit['title']}'...")
        page.wait_for_timeout(2000)

        contents_frame = page.frame(name="contents")
        ctrl_frame = page.frame(name="ctrl")
        target_frames = [contents_frame, page.main_frame] if contents_frame else [page.main_frame]
        active_video_frame = None

        for fr in target_frames:
            if fr and fr.evaluate('() => !!document.querySelector("video")'):
                active_video_frame = fr
                break

        if active_video_frame:
            video_meta = active_video_frame.evaluate('''() => {
                const v = document.querySelector("video");
                return v ? { duration: v.duration || 0, currentTime: v.currentTime || 0 } : null;
            }''')
            duration = video_meta.get("duration", 0) if video_meta else 0
            dur_str = time.strftime('%M:%S', time.gmtime(duration)) if duration > 0 else "Noma'lum"
            self.log("INFO", f"📹 Video darsi: Davomiyligi {dur_str} (Tezlik: {speed}x)")

            active_video_frame.evaluate(f'''() => {{
                const v = document.querySelector("video");
                if (v) {{
                    v.playbackRate = {speed};
                    v.muted = true;
                    v.play();
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
            self.log("INFO", f"📖 Slayd/Matn o'rganilmoqda ({doc_time} soniya kutish)...")
            waited = 0
            while waited < doc_time and not self.stop_event.is_set():
                time.sleep(5)
                waited += 5
                self.log("INFO", f"⌛ O'rganish: {waited}/{doc_time}s")
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
        self.log("INFO", f"📝 Test darsi AI bilan yechilmoqda: '{unit['title']}'...")
        page.wait_for_timeout(2000)

        for step in range(1, 30):
            if self.stop_event.is_set():
                return False

            if "test2.aspx" not in page.url or page.locator('text=受講結果, text=テスト結果').count() > 0:
                self.log("INFO", "🎉 Test to'liq yakunlandi!")
                break

            choices = page.evaluate('''() => {
                const radios = Array.from(document.querySelectorAll('#divSingleSelection label, label.answer-box'));
                return radios.map((lbl, idx) => ({ index: idx, id: lbl.id, text: lbl.innerText.trim() })).filter(c => c.text);
            }''')

            if not choices:
                next_b = page.locator('#ctl00_cplPageContent_lbnNext, a:has-text("次へ")').first
                finish_b = page.locator('#ctl00_cplPageContent_lbnFinish, a:has-text("終了"), button:has-text("終了")').first
                if next_b.is_visible():
                    next_b.click()
                    page.wait_for_load_state("load", timeout=15000)
                    page.wait_for_timeout(1500)
                    continue
                elif finish_b.is_visible():
                    finish_b.click()
                    page.wait_for_load_state("load", timeout=15000)
                    page.wait_for_timeout(1500)
                    continue
                else:
                    break

            q_text = page.inner_text("body")
            self.capture_screenshot(page)

            best_idx = self._solve_quiz_with_ai(gemini_client, model_name, q_text, choices, custom_prompt)
            page.locator(f"#{choices[best_idx]['id']}").click()
            page.wait_for_timeout(600)

            grading = page.locator('#ctl00_cplPageContent_lbnGrading, a:has-text("採点")').first
            if grading.is_visible():
                grading.click()
                page.wait_for_load_state("load", timeout=15000)
                page.wait_for_timeout(1500)
                self.capture_screenshot(page)

            next_b = page.locator('#ctl00_cplPageContent_lbnNext, a:has-text("次へ")').first
            finish_b = page.locator('#ctl00_cplPageContent_lbnFinish, a:has-text("終了"), button:has-text("終了")').first

            if next_b.is_visible():
                next_b.click()
                page.wait_for_load_state("load", timeout=15000)
                page.wait_for_timeout(1500)
            elif finish_b.is_visible():
                finish_b.click()
                page.wait_for_load_state("load", timeout=15000)
                page.wait_for_timeout(1500)

        if "/home/course/default.aspx" not in page.url:
            close_b = page.locator('a:has-text("閉じる"), button:has-text("閉じる"), a:has-text("戻る")').first
            if close_b.is_visible():
                close_b.click()
                page.wait_for_load_state("load", timeout=15000)
                page.wait_for_timeout(1500)

        self.log("INFO", f"✅ Test muvaffaqiyatli topshirildi: '{unit['title']}'")
        return True


# Global runner instance
agent_runner = AgentRunner()
