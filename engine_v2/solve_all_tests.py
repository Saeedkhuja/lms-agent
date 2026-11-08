#!/usr/bin/env python3
"""
=============================================================================
e-JDU LMS Autonomous Test Solver (Direct HTTP Gemini + SQLite Cache)
=============================================================================
Uses direct HTTP requests to Gemini 3.5 Flash with local SQLite question caching
and automatic 429 rate limit backoff to solve all 11 test units flawlessly.
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

import dotenv
dotenv.load_dotenv()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
DB_PATH = "/home/saeed/Downloads/lms_v2/question_cache.db"

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
            (q_hash, question, json.dumps([c['text'] for c in choices], ensure_ascii=False), ans_idx, ans_text)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass

def solve_with_gemini(q_text: str, choices: list) -> int:
    q_norm = re.sub(r'\s+', ' ', q_text).strip()
    q_hash = hashlib.sha256(q_norm.encode('utf-8')).hexdigest()
    
    # 1. Check local SQLite cache first
    cached = get_cached_answer(q_hash)
    if cached is not None and 0 <= cached < len(choices):
        print(f"      ⚡ [CACHE] Keshdan olindi: #{cached + 1} ({choices[cached]['text'][:30]})", flush=True)
        return cached

    choices_str = "\n".join([f"{i+1}. {c['text']}" for i, c in enumerate(choices)])
    prompt = f"""Siz yapon tili bo'yicha JLPT N3 darajasidagi professional mutaxassis va imtihon tahlilchisisiz.
Quyidagi savol va javob variantlarini diqqat bilan tahlil qiling:

【SAVOL】:
{q_text}

【JAVOB VARIANTLARI】:
{choices_str}

Qat'iy talablar:
- Faqat va faqat to'g'ri deb hisoblangan variant raqamini (1, 2, 3 yoki 4) yagona son sifatida qaytaring.
- Hech qanday izoh, so'z yoki ortiqcha belgi yozmang.
Javob namunasi: 2"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {"contents": [{"parts": [{"text": prompt}]}]}

    for attempt in range(5):
        try:
            r = requests.post(url, json=payload, timeout=12)
            if r.status_code == 200:
                data = r.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                digits = re.findall(r"\d+", text)
                if digits:
                    val = int(digits[0])
                    if 1 <= val <= len(choices):
                        best_idx = val - 1
                        ans_text = choices[best_idx]['text']
                        print(f"      🤖 [AI] Tanlandi: #{val} ({ans_text[:30]})", flush=True)
                        save_answer_to_cache(q_hash, q_norm, choices, best_idx, ans_text)
                        return best_idx
            elif r.status_code == 429:
                wait_sec = 25 + attempt * 10
                print(f"      ⏳ [Rate limit 429] {wait_sec} soniya kutilmoqda (urinish #{attempt+1})...", flush=True)
                time.sleep(wait_sec)
                continue
            else:
                print(f"      ⚠️ Status {r.status_code}: {r.text[:150]}", flush=True)
                time.sleep(5)
        except Exception as e:
            print(f"      ⚠️ So'rov xatoligi: {e}", flush=True)
            time.sleep(5)
    return 0

PENDING_TESTS = [
    {"title": "1-dars Test", "uid": "14008"},
    {"title": "2-dars Test", "uid": "14108"},
    {"title": "3-dars Test", "uid": "14243"},
    {"title": "文法(Grammatika)1Test (Ch21)", "uid": "14456"},
    {"title": "文法(Grammatika)2Test (Ch21)", "uid": "14454"},
    {"title": "文法(Grammatika)3Test (Ch21)", "uid": "14452"},
    {"title": "文法(Grammatika)9Test (Ch23)", "uid": "14471"},
    {"title": "4-dars Test (Ch24)", "uid": "14480"},
    {"title": "文法(Grammatika)1Test (Ch30)", "uid": "14532"},
    {"title": "文法(Grammatika)2Test (Ch30)", "uid": "14530"},
    {"title": "文法(Grammatika)3Test (Ch30)", "uid": "14528"},
]

def solve_single_test(page, test_info: dict) -> bool:
    title = test_info["title"]
    uid = test_info["uid"]
    url = f"https://e-jdu.uz/home/course/viewer/default.aspx?mode=study&cid=953&uid={uid}"
    
    print(f"\n=======================================================", flush=True)
    print(f"📝 TEST BOSHLANDI: {title} (UID: {uid})", flush=True)
    print(f"=======================================================", flush=True)
    
    try:
        page.goto(url, wait_until="load", timeout=30000)
        page.wait_for_timeout(2500)
    except Exception as e:
        print(f"❌ Test sahifasini ochishda xatolik: {e}", flush=True)
        return False
        
    for q_num in range(1, 45):
        page.wait_for_timeout(800)
        
        # Check if test finished
        if page.locator("text=受講結果, text=テスト結果, text=テスト完了, text=お疲れさまでした").count() > 0:
            print(f"🎉 Test to'liq yakunlandi! ({title})", flush=True)
            return True
            
        choices = page.evaluate('''() => {
            const radios = Array.from(document.querySelectorAll('#divSingleSelection label, label.answer-box'));
            return radios.map((lbl, idx) => ({ index: idx, id: lbl.id, text: lbl.innerText.trim() })).filter(c => c.text);
        }''')
        
        if not choices:
            finish_b = page.locator('#ctl00_cplPageContent_lbnFinish, a:has-text("終了"), button:has-text("終了")').first
            next_b = page.locator('#ctl00_cplPageContent_lbnNext, a:has-text("次へ")').first
            if finish_b.is_visible():
                print("   🏁 '終了' (Yakunlash) bosilmoqda...", flush=True)
                finish_b.click()
                page.wait_for_timeout(2500)
                return True
            elif next_b.is_visible():
                print("   ➡️ '次へ' bosilmoqda...", flush=True)
                next_b.click()
                page.wait_for_timeout(1500)
                continue
            else:
                print("   ℹ️ Savollar tugadi yoki natijalar sahifasi.", flush=True)
                break
                
        q_text = page.evaluate('''() => {
            const el = document.querySelector('.card-body, #divQuestionArea, #divQuestion');
            return el ? el.innerText.trim() : document.body.innerText.trim();
        }''')
        q_clean = q_text[:100].replace('\n', ' ')
        print(f"   [{q_num}] Savol: {q_clean}...", flush=True)
        
        best_idx = solve_with_gemini(q_text, choices)
        choice_id = choices[best_idx]["id"]
        
        # Click choice
        try:
            page.click(f"#{choice_id}", timeout=5000)
        except Exception:
            page.evaluate(f'(id) => {{ const el = document.getElementById(id); if (el) el.click(); }}', choice_id)
        page.wait_for_timeout(400)
        
        # Click grading (採点)
        grading = page.locator('#ctl00_cplPageContent_lbnGrading, a:has-text("採点")').first
        if grading.is_visible():
            grading.click()
            page.wait_for_timeout(1800)
            
        # Click Next or Finish
        finish_b = page.locator('#ctl00_cplPageContent_lbnFinish, a:has-text("終了"), button:has-text("終了")').first
        next_b = page.locator('#ctl00_cplPageContent_lbnNext, a:has-text("次へ")').first
        
        if finish_b.is_visible():
            print("   🏁 Test oxiriga yetildi. '終了' bosilmoqda...", flush=True)
            finish_b.click()
            page.wait_for_timeout(2500)
            return True
        elif next_b.is_visible():
            next_b.click()
            page.wait_for_timeout(1500)
            
        # Pacing between questions to respect API rate limits
        time.sleep(5.0)
            
    print(f"✅ Test yakunlandi: {title}", flush=True)
    return True

def main():
    init_db()
    print("=" * 60, flush=True)
    print("🚀 e-JDU BARCHA TESTLARNI AVTOMATIK YECHISH BOSHLANDI", flush=True)
    print(f"📋 Qolgan testlar soni: {len(PENDING_TESTS)} ta", flush=True)
    print("=" * 60, flush=True)
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        page = context.new_page()
        
        # 1. Login
        print("🔑 Tizimga kirilmoqda: jdu-226516...", flush=True)
        page.goto("https://e-jdu.uz/default.aspx", wait_until="load", timeout=30000)
        page.locator('input[name*="txtUserID"]').first.fill("jdu-226516")
        page.locator('input[name*="txtPassword"]').first.fill("55ugtk")
        page.locator('button:has-text("ログイン"), input[value*="ログイン"]').first.click()
        page.wait_for_load_state("load")
        page.wait_for_timeout(2000)
        
        if "/home/" not in page.url:
            print("❌ Login amalga oshmadi. URL:", page.url, flush=True)
            browser.close()
            return
            
        print("✅ Tizimga muvaffaqiyatli kirildi!", flush=True)
        
        # 2. Solve each test
        success_count = 0
        for i, test in enumerate(PENDING_TESTS, 1):
            print(f"\n[{i}/{len(PENDING_TESTS)}] Test topshirilmoqda: {test['title']}...", flush=True)
            ok = solve_single_test(page, test)
            if ok:
                success_count += 1
            time.sleep(3)
            
        print("\n" + "=" * 60, flush=True)
        print(f"🏁 BARCHA TESTLAR YAKUNLANDI: {success_count}/{len(PENDING_TESTS)} ta muvaffaqiyatli!", flush=True)
        print("=" * 60, flush=True)
        browser.close()

if __name__ == "__main__":
    main()
