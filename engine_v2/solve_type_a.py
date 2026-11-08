from playwright.sync_api import sync_playwright
import requests
import hashlib
import sqlite3
import json
import time
import re

import dotenv
dotenv.load_dotenv()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
DB_PATH = "/home/saeed/Downloads/lms_v2/question_cache.db"

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
            (q_hash, question, json.dumps(choices, ensure_ascii=False), ans_idx, ans_text)
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
        print(f"   ⚡ [CACHE] #{cached + 1} ({choices[cached][:25]})", flush=True)
        return cached

    choices_str = "\n".join([f"{i+1}. {c}" for i, c in enumerate(choices)])
    prompt = f"""Siz yapon tili bo'yicha JLPT N3 darajasidagi professional mutaxassis va imtihon tahlilchisisiz.
Quyidagi savol va berilgan javob variantlarini tahlil qiling:

【SAVOL】:
{q_text}

【JAVOB VARIANTLARI】:
{choices_str}

Talab:
Faqat va faqat to'g'ri deb hisoblangan variant raqamini (1, 2, 3 yoki 4) yagona son sifatida yozing. Hech qanday izoh yozmang.
Javob: 2"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {"contents": [{"parts": [{"text": prompt}]}]}

    for attempt in range(4):
        try:
            r = requests.post(url, json=payload, timeout=12)
            if r.status_code == 200:
                text = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                digits = re.findall(r"\d+", text)
                if digits:
                    val = int(digits[0])
                    if 1 <= val <= len(choices):
                        best_idx = val - 1
                        ans_text = choices[best_idx]
                        print(f"   🤖 [AI] #{val} ({ans_text[:25]})", flush=True)
                        save_answer_to_cache(q_hash, q_norm, choices, best_idx, ans_text)
                        return best_idx
            elif r.status_code == 429:
                wait_sec = 22 + attempt * 10
                print(f"   ⏳ [Rate limit 429] {wait_sec}s kutilmoqda...", flush=True)
                time.sleep(wait_sec)
                continue
            else:
                time.sleep(4)
        except Exception as e:
            time.sleep(4)
    return 0

def solve_multi_question_test(page, uid: str, title: str):
    url = f"https://e-jdu.uz/home/course/viewer/default.aspx?mode=study&cid=953&uid={uid}"
    print(f"\n=======================================================", flush=True)
    print(f"📝 TEST TYPE A (Hammasi bir sahifada): {title} (UID: {uid})", flush=True)
    print(f"=======================================================", flush=True)
    
    page.goto(url, wait_until="load", timeout=30000)
    page.wait_for_timeout(3000)
    
    # Extract all question blocks
    extract_js = """
    () => {
        const groups = {};
        const radios = Array.from(document.querySelectorAll('input[type="radio"]'));
        radios.forEach(r => {
            if (!groups[r.name]) {
                groups[r.name] = {
                    name: r.name,
                    radios: []
                };
            }
            groups[r.name].radios.push({ id: r.id, value: r.value });
        });
        
        // Find question texts for each group
        const result = [];
        const groupKeys = Object.keys(groups);
        
        groupKeys.forEach((gname, idx) => {
            const firstRadio = document.getElementById(groups[gname].radios[0].id);
            let text = "";
            let curr = firstRadio ? firstRadio.closest('tr, .row, .card-body, .card, div') : null;
            if (curr) {
                let prev = curr.previousElementSibling || curr.parentElement.previousElementSibling;
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
    }
    """
    q_list = page.evaluate(extract_js)
    print(f"📋 Jami savollar soni: {len(q_list)} ta", flush=True)
    
    for q in q_list:
        print(f"\n[{q['index']}/{len(q_list)}] Savol: {q['text'][:80].replace(chr(10), ' ')}...", flush=True)
        # Default choices 1, 2, 3, 4
        choices = ["1", "2", "3", "4"]
        best_idx = solve_with_gemini(q['text'], choices)
        target_radio_id = q['radios'][best_idx]['id']
        
        page.check(f"#{target_radio_id}")
        time.sleep(3.5) # Pace to stay within rate limit
        
    print("\n🏁 Barcha savollarga javob belgilandi! 採点 (Baholash) bosilmoqda...", flush=True)
    page.screenshot(path=f"/home/saeed/Downloads/lms_v2/test_{uid}_before_grading.png")
    
    grading = page.locator('#ctl00_cplPageContent_lbnGrading, a:has-text("採点")').first
    if grading.is_visible():
        grading.click()
        page.wait_for_timeout(3500)
        
    finish_b = page.locator('#ctl00_cplPageContent_lbnFinish, a:has-text("終了"), button:has-text("終了"), a:has-text("閉じる")').first
    if finish_b.is_visible():
        finish_b.click()
        page.wait_for_timeout(3000)
        
    page.screenshot(path=f"/home/saeed/Downloads/lms_v2/test_{uid}_result.png")
    print(f"✅ Test muvaffaqiyatli topshirildi: {title}", flush=True)

if __name__ == "__main__":
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("https://e-jdu.uz/default.aspx")
        page.locator('input[name*="txtUserID"]').first.fill("jdu-226516")
        page.locator('input[name*="txtPassword"]').first.fill("55ugtk")
        page.locator('button:has-text("ログイン"), input[value*="ログイン"]').first.click()
        page.wait_for_load_state("load")
        page.wait_for_timeout(2000)
        
        solve_multi_question_test(page, "14108", "2-dars Test")
        browser.close()
