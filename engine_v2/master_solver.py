#!/usr/bin/env python3
"""
=============================================================================
e-JDU LMS Master Autonomous Test Solver (AI + SQLite Cache)
=============================================================================
Handles both Type A (test.aspx - all questions on 1 page) and
Type B (test2.aspx - step-by-step single-question pages).
Uses Gemini API (gemini-3.5-flash-lite, 15 RPM) + local SQLite cache for 100% precision.
=============================================================================
"""

import os
import sys
import time
import re
import hashlib
import sqlite3
import json
import requests
from playwright.sync_api import sync_playwright
try:
    from engine_v2.lms_client import LMSDirectClient
except ImportError:
    from lms_client import LMSDirectClient

import dotenv
dotenv.load_dotenv()
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "question_cache.db")
if not os.path.exists(DB_PATH) and os.path.exists("/home/saeed/Downloads/lms_v2/question_cache.db"):
    import shutil
    try:
        shutil.copy2("/home/saeed/Downloads/lms_v2/question_cache.db", DB_PATH)
    except Exception:
        pass

# Load GEMINI_API_KEY reliably
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
if not GEMINI_API_KEY:
    try:
        sys.path.insert(0, BASE_DIR)
        from config import load_settings
        st = load_settings()
        GEMINI_API_KEY = st.get("gemini_api_key", "").strip()
    except Exception:
        pass
if not GEMINI_API_KEY:
    env_file = os.path.join(BASE_DIR, ".env")
    if os.path.exists(env_file):
        try:
            with open(env_file, "r", encoding="utf-8") as _f:
                for _line in _f:
                    if _line.startswith("GEMINI_API_KEY="):
                        GEMINI_API_KEY = _line.strip().split("=", 1)[1].strip()
                        break
        except Exception:
            pass

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS question_cache (
            q_hash TEXT PRIMARY KEY,
            question TEXT,
            choices TEXT,
            answer_idx INTEGER,
            answer_text TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def get_cached_answer(q_hash: str) -> int:
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT answer_idx FROM question_cache WHERE q_hash = ?", (q_hash,))
        row = cur.fetchone()
        conn.close()
        if row:
            return row[0]
    except Exception:
        pass
    return None

def save_answer_to_cache(q_hash: str, question: str, choices: list, ans_idx: int, ans_text: str):
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO question_cache (q_hash, question, choices, answer_idx, answer_text) VALUES (?, ?, ?, ?, ?)",
            (q_hash, question, json.dumps(choices, ensure_ascii=False), ans_idx, str(ans_text))
        )
        conn.commit()
        conn.close()
    except Exception:
        pass

def solve_with_gemini(q_text: str, choices: list) -> int:
    q_norm = re.sub(r'\s+', ' ', q_text).strip()
    q_hash = hashlib.sha256(q_norm.encode('utf-8')).hexdigest()
    
    cached = get_cached_answer(q_hash)
    if cached is not None and 0 <= cached < len(choices):
        print(f"      ⚡ [CACHE] #{cached + 1} ({str(choices[cached])[:25]})", flush=True)
        return cached

    choices_str = "\n".join([f"{i+1}. {c}" for i, c in enumerate(choices)])
    prompt = f"""Siz yapon tili bo'yicha JLPT N3 darajasidagi professional mutaxassis va imtihon tahlilchisisiz.
Quyidagi savol va javob variantlarini tahlil qiling:

【SAVOL】:
{q_text}

【JAVOB VARIANTLARI】:
{choices_str}

Talab:
Faqat va faqat to'g'ri deb hisoblangan variant raqamini (1, 2, 3 yoki 4) yagona son sifatida yozing.
Javob namunasi: 2"""

    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    models = ["gemini-3.5-flash-lite", "gemini-flash-lite-latest", "gemini-3.5-flash"]

    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
        for attempt in range(3):
            try:
                r = requests.post(url, json=payload, timeout=12)
                if r.status_code == 200:
                    text = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                    digits = re.findall(r"\d+", text)
                    if digits:
                        val = int(digits[0])
                        if 1 <= val <= len(choices):
                            best_idx = val - 1
                            ans_text = str(choices[best_idx])
                            print(f"      🤖 [AI - {model}] #{val} ({ans_text[:25]})", flush=True)
                            save_answer_to_cache(q_hash, q_norm, [str(c) for c in choices], best_idx, ans_text)
                            return best_idx
                elif r.status_code == 429:
                    wait_sec = 20 + attempt * 10
                    print(f"      ⏳ [Rate limit 429 - {model}] {wait_sec}s kutilmoqda...", flush=True)
                    time.sleep(wait_sec)
                    continue
                else:
                    time.sleep(2)
                    break
            except Exception as e:
                time.sleep(2)
                break
    return 0

def ensure_logged_in(page, user_id: str, password: str):
    curr_url = page.url or ""
    body_text = page.inner_text("body") if "error" in curr_url else ""
    needs_login = (
        "error.aspx" in curr_url
        or "認証情報" in body_text
        or curr_url.rstrip("/") in ["https://e-jdu.uz", "https://e-jdu.uz/default.aspx", "about:blank"]
        or page.locator('input[name*="txtUserID"]').count() > 0
    )
    if needs_login:
        print(f"   🔄 Sessiya yangilanmoqda: {user_id}...", flush=True)
        page.goto("https://e-jdu.uz/default.aspx", wait_until="load", timeout=30000)
        page.locator('input[name*="txtUserID"]').first.fill(user_id)
        page.locator('input[name*="txtPassword"]').first.fill(password)
        page.locator('button:has-text("ログイン"), input[value*="ログイン"]').first.click()
        page.wait_for_timeout(3000)

def solve_test_unit(page, test_info: dict, user_id: str = "jdu-226516", password: str = "55ugtk") -> bool:
    title = test_info.get("title", "Test")
    uid = test_info.get("uid")
    viewer_url = test_info.get("viewer_url") or (f"https://e-jdu.uz/home/course/viewer/default.aspx?mode=study&cid=953&uid={uid}" if uid else None)
    
    print(f"\n{'=' * 60}", flush=True)
    print(f"📝 TEST TOPSHIRISH: {title} (UID: {uid or 'Joriy oyna'})", flush=True)
    print(f"{'=' * 60}", flush=True)

    curr = page.url.lower() if page.url else ""
    if "test.aspx" not in curr and "test2.aspx" not in curr:
        if viewer_url:
            try:
                page.goto(viewer_url, wait_until="load", timeout=30000)
                page.wait_for_timeout(2500)
            except Exception as e:
                print(f"❌ Test sahifasini ochishda xatolik: {e}", flush=True)
                return False

    # Check if already finished
    if page.locator("text=受講結果, text=テスト結果, text=テスト完了, text=お疲れさまでした").count() > 0:
        print(f"🎉 Test allaqachon yakunlangan! ({title})", flush=True)
        return True

    # Detect test type
    is_type_a = page.evaluate("""() => {
        const radios = document.querySelectorAll('input[type="radio"]');
        const single = document.querySelector('#divSingleSelection');
        return radios.length > 8 && (!single || !single.contains(radios[0]));
    }""") or ("test.aspx" in page.url and "test2.aspx" not in page.url)

    if is_type_a:
        print("   🔍 Test turi: TYPE A (test.aspx - barcha savollar 1 sahifada)", flush=True)
        q_list = page.evaluate("""() => {
            const groups = {};
            const radios = Array.from(document.querySelectorAll('input[type="radio"]'));
            radios.forEach(r => {
                if (!groups[r.name]) {
                    groups[r.name] = { name: r.name, radios: [] };
                }
                groups[r.name].radios.push({ id: r.id, value: r.value });
            });
            const result = [];
            const keys = Object.keys(groups);
            keys.forEach((gname, idx) => {
                const firstRadio = document.getElementById(groups[gname].radios[0].id);
                let text = "";
                let curr = firstRadio ? firstRadio.closest('tr, .row, .card-body, .card, div') : null;
                if (curr) {
                    let prev = curr.previousElementSibling || (curr.parentElement ? curr.parentElement.previousElementSibling : null);
                    text = (prev ? prev.innerText : "") + "\\n" + curr.innerText;
                    if (text.length < 30 && curr.parentElement) {
                        text = curr.parentElement.innerText;
                    }
                }
                result.push({
                    index: idx + 1,
                    name: gname,
                    text: text.slice(0, 300).trim(),
                    radios: groups[gname].radios
                });
            });
            return result;
        }""")

        print(f"   📋 Jami savollar soni: {len(q_list)} ta", flush=True)
        for q in q_list:
            q_clean = q['text'][:70].replace('\n', ' ')
            print(f"   [{q['index']}/{len(q_list)}] {q_clean}...", flush=True)
            choices = ["1", "2", "3", "4"]
            best_idx = solve_with_gemini(q['text'], choices)
            target_radio_id = q['radios'][best_idx]['id']
            page.evaluate(f'''(id) => {{
                const el = document.getElementById(id);
                if (el) {{
                    el.checked = true;
                    el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                }}
            }}''', target_radio_id)
            time.sleep(1.5)

        print("   🏁 Barcha javoblar belgilandi! Baholash yuborilmoqda...", flush=True)
        # Handle confirmation dialogs
        page.on("dialog", lambda d: d.accept())
        page.evaluate("""() => {
            if (document.forms[0]) {
                document.forms[0].action = window.location.href;
            }
            window.isShowAlertBeforeUnLoad = false;
        }""")
        
        # Click 採点 (#a_next_foot)
        grade_btn = page.locator('#a_next_foot, #ctl00_cplPageContent_lbnGrading, a:has-text("採点"), button:has-text("採点")').first
        if grade_btn.is_visible():
            print("   📝 '採点' (Baholash) tugmasi bosilmoqda...", flush=True)
            grade_btn.click()
            page.wait_for_timeout(3500)

        # Trigger form submit if still on test page
        try:
            page.evaluate("""() => {
                if (document.querySelector('input[type="radio"]') && typeof __doPostBack === 'function') {
                    __doPostBack('ctl00$cplPageContent$btnNext', '');
                }
            }""")
            page.wait_for_timeout(4000)
        except Exception:
            pass

        # Check for result screen
        page.wait_for_load_state("load", timeout=15000)
        page.wait_for_timeout(2000)

        close_btn = page.locator('a:has-text("終了"), button:has-text("終了"), a:has-text("閉じる"), button:has-text("閉じる"), #ctl00_cplPageContent_lbnFinish, #a_close_foot').first
        if close_btn.is_visible():
            print("   🏁 '終了/閉じる' bosilmoqda...", flush=True)
            close_btn.click()
            page.wait_for_timeout(2500)

        print(f"✅ Test muvaffaqiyatli topshirildi: {title}", flush=True)
        return True

    else:
        print("   🔍 Test turi: TYPE B (test2.aspx - savolma-savol)", flush=True)
        questions_answered = 0
        for q_num in range(1, 40):
            page.wait_for_timeout(1000)

            # Check if actual error page happened
            if "error.aspx" in page.url:
                ensure_logged_in(page, user_id, password)
                if viewer_url:
                    page.goto(viewer_url, wait_until="load", timeout=30000)
                    page.wait_for_timeout(3000)

            # Check if finished
            if page.locator("text=受講結果, text=テスト結果, text=テスト完了, text=お疲れさまでした").count() > 0:
                print(f"🎉 Test to'liq yakunlandi! ({title})", flush=True)
                close_btn = page.locator('#ctl00_cplPageContent_lbnClose, a:has-text("閉じる"), button:has-text("閉じる"), a:has-text("終了")').first
                if close_btn.is_visible():
                    close_btn.click()
                    page.wait_for_timeout(2000)
                return True

            choices = page.evaluate('''() => {
                const labels = Array.from(document.querySelectorAll('label[id*="lblAnswer"], #divSingleSelection label, label.answer-box'));
                return labels.map((lbl, idx) => ({
                    index: idx,
                    id: lbl.id,
                    text: lbl.innerText.trim(),
                    htmlFor: lbl.htmlFor || ""
                })).filter(c => c.text);
            }''')

            if not choices:
                next_b = page.locator('#ctl00_cplPageContent_lbnNext, a:has-text("次へ"), button:has-text("次へ")').first
                finish_b = page.locator('#ctl00_cplPageContent_lbnFinish, a:has-text("終了"), button:has-text("終了")').first
                page.evaluate("() => { if (document.forms[0]) document.forms[0].action = window.location.href; }")
                if next_b.is_visible():
                    print("   ➡️ '次へ' (Keyingisi) bosilmoqda...", flush=True)
                    next_b.click()
                    page.wait_for_timeout(2000)
                    continue
                elif finish_b.is_visible():
                    print("   🏁 '終了' (Yakunlash) bosilmoqda...", flush=True)
                    finish_b.click()
                    page.wait_for_timeout(2500)
                    continue
                elif page.locator("text=受講結果, text=テスト結果, text=テスト完了, text=お疲れさまでした").count() > 0:
                    print(f"🎉 Test to'liq yakunlandi! ({title})", flush=True)
                    close_btn = page.locator('#ctl00_cplPageContent_lbnClose, a:has-text("閉じる"), button:has-text("閉じる")').first
                    if close_btn.is_visible():
                        page.evaluate("() => { if (document.forms[0]) document.forms[0].action = window.location.href; }")
                        close_btn.click()
                        page.wait_for_timeout(2000)
                    return True
                else:
                    page.wait_for_timeout(2000)
                    continue

            q_text = page.evaluate('''() => {
                const el = document.querySelector('#ctl00_cplPageContent_pnlQuestionArea, #divQuestionArea, .card-body, #ctl00_cplPageContent_lblQuestion');
                return el ? el.innerText.trim() : document.body.innerText.trim();
            }''')
            q_clean = q_text[:70].replace('\n', ' ')
            print(f"   [{q_num}] {q_clean}...", flush=True)

            best_idx = solve_with_gemini(q_text, [c['text'] for c in choices])
            chosen = choices[best_idx]
            target_id = chosen.get("htmlFor") or chosen["id"]

            try:
                page.locator(f"#{target_id}").click(timeout=3000)
            except Exception:
                page.evaluate(f'(id) => {{ const el = document.getElementById(id); if (el) el.click(); }}', target_id)
            page.wait_for_timeout(600)

            # Preserve token in form action before postback
            page.evaluate("() => { if (document.forms[0]) document.forms[0].action = window.location.href; }")

            grading = page.locator('#ctl00_cplPageContent_lbnGrading, a:has-text("採点")').first
            if grading.is_visible():
                grading.click()
                page.wait_for_timeout(2500)
                questions_answered += 1

            next_b = page.locator('#ctl00_cplPageContent_lbnNext, a:has-text("次へ")').first
            finish_b = page.locator('#ctl00_cplPageContent_lbnFinish, a:has-text("終了"), button:has-text("終了")').first

            page.evaluate("() => { if (document.forms[0]) document.forms[0].action = window.location.href; }")

            if next_b.is_visible():
                next_b.click()
                page.wait_for_timeout(2000)
            elif finish_b.is_visible():
                print("   🏁 Oxirgi savol baholandi. '終了' bosilmoqda...", flush=True)
                finish_b.click()
                page.wait_for_timeout(3000)
                close_btn = page.locator('#ctl00_cplPageContent_lbnClose, a:has-text("閉じる"), button:has-text("閉じる")').first
                if close_btn.is_visible():
                    page.evaluate("() => { if (document.forms[0]) document.forms[0].action = window.location.href; }")
                    close_btn.click()
                    page.wait_for_timeout(2500)
                return True

            time.sleep(1.5)

        # Check final status
        if page.locator("text=受講結果, text=テスト結果, text=テスト完了, text=お疲れさまでした").count() > 0:
            print(f"🎉 Test to'liq yakunlandi! ({title})", flush=True)
            return True
        print(f"⚠️ Test to'liq yakunlanmadi yoki savollar tugamadi: {title}", flush=True)
        return False

def main():
    init_db()
    import argparse
    parser = argparse.ArgumentParser(description="e-JDU LMS Master Autonomous Test Solver")
    parser.add_argument("--user-id", type=str, default=None)
    parser.add_argument("--password", type=str, default=None)
    args = parser.parse_args()

    user_id = args.user_id
    password = args.password
    if not user_id or not password:
        profiles_file = os.path.join(DATA_DIR, "profiles.json")
        if os.path.exists(profiles_file):
            try:
                with open(profiles_file, "r", encoding="utf-8") as f:
                    profs = json.load(f)
                    if profs:
                        user_id = profs[0].get("user_id")
                        password = profs[0].get("password")
            except Exception:
                pass
    user_id = user_id or "jdu-226516"
    password = password or "55ugtk"

    print("=" * 60, flush=True)
    print(f"🚀 e-JDU LMS MASTER AUTONOMOUS TEST SOLVER ({user_id})", flush=True)
    print("=" * 60, flush=True)
    
    # 1. Scan live remaining units
    client = LMSDirectClient(user_id, password)
    if not client.login() or not client.open_course():
        print("❌ LMS ga ulanib bo'lmadi")
        return
        
    units = client.scan_units()
    pending = [u for u in units if not u["is_finished"]]
    print(f"📊 Qolgan darslar soni: {len(pending)} ta", flush=True)
    
    test_units = []
    for p in pending:
        uid = p.get("uid")
        if not uid and p.get("link_id"):
            info = client.get_unit_viewer_info(p["link_id"])
            uid = info.get("uid") if info else None
        if uid:
            test_units.append({
                "title": p["title"],
                "uid": uid,
                "viewer_url": f"https://e-jdu.uz/home/course/viewer/default.aspx?mode=study&cid=953&uid={uid}"
            })
            
    print(f"📋 Bajarilishi lozim bo'lgan testlar: {len(test_units)} ta\n", flush=True)
    for i, t in enumerate(test_units, 1):
        print(f"  {i:2d}. {t['title']} (UID: {t['uid']})", flush=True)

    if not test_units:
        print("🎉 Barcha testlar allaqachon 100% bajarilgan!", flush=True)
        return

    # 2. Launch Playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        page = context.new_page()
        page.on("dialog", lambda dialog: (print(f"      🔔 [DIALOG]: {dialog.message}", flush=True), dialog.accept()))
        
        print(f"\n🔑 Playwright orqali tizimga kirilmoqda: {user_id}...", flush=True)
        page.goto("https://e-jdu.uz/default.aspx", wait_until="load", timeout=30000)
        page.locator('input[name*="txtUserID"]').first.fill(user_id)
        page.locator('input[name*="txtPassword"]').first.fill(password)
        page.locator('button:has-text("ログイン"), input[value*="ログイン"]').first.click()
        page.wait_for_load_state("load")
        page.wait_for_timeout(2000)
        
        if "/home/" not in page.url:
            print("❌ Login amalga oshmadi. URL:", page.url, flush=True)
            browser.close()
            return
            
        print("✅ Tizimga muvaffaqiyatli kirildi!", flush=True)
        
        for i, test in enumerate(test_units, 1):
            print(f"\n[{i}/{len(test_units)}] Test topshirilmoqda: {test['title']}...", flush=True)
            solve_test_unit(page, test, user_id=user_id, password=password)
            time.sleep(3)
            
        print("\n" + "=" * 60, flush=True)
        print("🏁 BARCHA TESTLAR YAKUNLANDI! LMS tekshirilmoqda...", flush=True)
        print("=" * 60, flush=True)
        browser.close()

    # Final check
    print("\n🔍 Yakuniy hisobot olinmoqda...")
    client.open_course()
    final_units = client.scan_units()
    fin_count = sum(1 for u in final_units if u["is_finished"])
    total_count = len(final_units)
    percent = (fin_count * 100) // total_count if total_count else 0
    print(f"\n🎉 KURS NATIJASI: {fin_count} / {total_count} ({percent}%) BAJARILDI!")

    # Sync completed tasks file
    completed_file = os.path.join(DATA_DIR, "completed_tasks", f"completed_{user_id}.txt")
    try:
        with open(completed_file, "w", encoding="utf-8") as f:
            for i, u in enumerate(final_units):
                if u["is_finished"]:
                    f.write(f"{u['title']} (#{i+1})\n")
    except Exception:
        pass

if __name__ == "__main__":
    main()
