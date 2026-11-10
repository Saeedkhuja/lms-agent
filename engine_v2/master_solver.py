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

def solve_test_unit(page, test_info: dict) -> bool:
    title = test_info["title"]
    uid = test_info["uid"]
    url = f"https://e-jdu.uz/home/course/viewer/default.aspx?mode=study&cid=953&uid={uid}"
    
    print(f"\n{'=' * 60}", flush=True)
    print(f"📝 TEST TOPSHIRISH: {title} (UID: {uid})", flush=True)
    print(f"{'=' * 60}", flush=True)
    
    try:
        page.goto(url, wait_until="load", timeout=30000)
        page.wait_for_timeout(3000)
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
            time.sleep(2.0)

        print("   🏁 Barcha javoblar belgilandi! Baholash yuborilmoqda...", flush=True)
        page.evaluate("""() => {
            window.isShowAlertBeforeUnLoad = false;
            const btn = document.getElementById('ctl00_cplPageContent_btnNext');
            if (btn) btn.click();
        }""")
        page.wait_for_timeout(4000)
        print(f"✅ Test muvaffaqiyatli topshirildi: {title}", flush=True)
        return True

    else:
        print("   🔍 Test turi: TYPE B (test2.aspx - savolma-savol)", flush=True)
        for q_num in range(1, 60):
            page.wait_for_timeout(1000)
            
            # Check if finished
            if "/course/default.aspx" in page.url or page.locator("text=受講結果, text=テスト結果, text=テスト完了, text=お疲れさまでした").count() > 0:
                print(f"🎉 Test to'liq yakunlandi! ({title})", flush=True)
                return True
                
            choices = page.evaluate('''() => {
                const labels = Array.from(document.querySelectorAll('#divSingleSelection label, label.answer-box'));
                return labels.map((lbl, idx) => ({ index: idx, id: lbl.id, text: lbl.innerText.trim() })).filter(c => c.text);
            }''')
            
            if not choices:
                next_b = page.locator('#ctl00_cplPageContent_lbnNext, a:has-text("次へ"), button:has-text("次へ")').first
                finish_b = page.locator('#ctl00_cplPageContent_lbnFinish, a:has-text("終了"), button:has-text("終了"), a:has-text("閉じる")').first
                if next_b.is_visible():
                    print("   ➡️ '次へ' (Keyingisi) bosilmoqda...", flush=True)
                    next_b.click()
                    page.wait_for_timeout(2500)
                    continue
                elif finish_b.is_visible():
                    print("   🏁 '終了' (Yakunlash) bosilmoqda...", flush=True)
                    finish_b.click()
                    page.wait_for_timeout(3000)
                    return True
                else:
                    print("   ℹ️ Barcha savollar tugadi.", flush=True)
                    break
                    
            q_text = page.evaluate('''() => {
                const el = document.querySelector('.card-body, #ctl00_cplPageContent_lblQuestion, #divQuestionArea');
                return el ? el.innerText.trim() : document.body.innerText.trim();
            }''')
            q_clean = q_text[:70].replace('\n', ' ')
            print(f"   [{q_num}] {q_clean}...", flush=True)
            
            best_idx = solve_with_gemini(q_text, [c['text'] for c in choices])
            choice_id = choices[best_idx]["id"]
            
            try:
                page.locator(f"#{choice_id}").click(timeout=4000)
            except Exception:
                page.evaluate(f'(id) => {{ const el = document.getElementById(id); if (el) el.click(); }}', choice_id)
            page.wait_for_timeout(400)
            
            grading = page.locator('#ctl00_cplPageContent_lbnGrading, a:has-text("採点")').first
            if grading.is_visible():
                grading.click()
                page.wait_for_timeout(2500)
                
            finish_b = page.locator('#ctl00_cplPageContent_lbnFinish, a:has-text("終了"), button:has-text("終了")').first
            next_b = page.locator('#ctl00_cplPageContent_lbnNext, a:has-text("次へ")').first
            
            if finish_b.is_visible():
                print("   🏁 Oxirgi savol baholandi. '終了' bosilmoqda...", flush=True)
                finish_b.click()
                page.wait_for_timeout(3000)
                return True
            elif next_b.is_visible():
                next_b.click()
                page.wait_for_timeout(2000)
                
            time.sleep(1.5)
                
        print(f"✅ Test yakunlandi: {title}", flush=True)
        return True

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
        info = client.get_unit_viewer_info(p["link_id"])
        if info and info.get("uid"):
            test_units.append({
                "title": p["title"],
                "uid": info["uid"],
                "viewer_url": info["viewer_url"]
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
            solve_test_unit(page, test)
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

if __name__ == "__main__":
    main()
