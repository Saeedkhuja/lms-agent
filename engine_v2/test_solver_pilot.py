import os
import sys
import time
import re
from playwright.sync_api import sync_playwright
GEMINI_API_KEY = None
if os.path.exists("/home/saeed/Downloads/lms_agent_web/.env"):
    with open("/home/saeed/Downloads/lms_agent_web/.env") as f:
        for line in f:
            if line.startswith("GEMINI_API_KEY="):
                GEMINI_API_KEY = line.strip().split("=", 1)[1]

from google import genai
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

def solve_with_gemini(q_text, choices):
    if not gemini_client:
        return 0
    choices_str = "\n".join([f"{i+1}. {c['text']}" for i, c in enumerate(choices)])
    prompt = f"""Siz yapon tili bo'yicha JLPT N3 darajasidagi professional mutaxassis va repetitorsiz.
Quyidagi savol va berilgan javob variantlarini diqqat bilan o'rganib chiqing:

【SAVOL】:
{q_text}

【JAVOB VARIANTLARI】:
{choices_str}

Talablar:
- Faqat va faqat to'g'ri javob variantining raqamini (1, 2, 3 yoki 4) yagona son sifatida yozing.
- Hech qanday tushuntirish, so'z yoki ortiqcha belgi yozmang.
Misol: 2"""

    for model in ["gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-1.5-flash"]:
        try:
            resp = gemini_client.models.generate_content(
                model=model,
                contents=prompt
            )
            ans = resp.text.strip()
            digits = re.findall(r"\d+", ans)
            if digits:
                val = int(digits[0])
                if 1 <= val <= len(choices):
                    print(f"🤖 [AI] Model {model} tanladi: {val} ({choices[val-1]['text']})")
                    return val - 1
        except Exception as e:
            print(f"⚠️ Model {model} xatolik: {e}")
            continue
    return 0

def solve_pilot():
    target_uid = "14456" # 文法(Grammatika)1Test (kamroq savolli gramatika testi)
    url = f"https://e-jdu.uz/home/course/viewer/default.aspx?mode=study&cid=953&uid={target_uid}"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        page = context.new_page()
        
        # 1. Login
        print("🔑 Login qilinmoqda...")
        page.goto("https://e-jdu.uz/default.aspx", wait_until="load")
        page.locator('input[name*="txtUserID"]').first.fill("jdu-226516")
        page.locator('input[name*="txtPassword"]').first.fill("55ugtk")
        page.locator('button:has-text("ログイン"), input[value*="ログイン"]').first.click()
        page.wait_for_load_state("load")
        page.wait_for_timeout(2000)
        print("✅ Login qilindi, URL:", page.url)
        
        # 2. Open quiz directly
        print(f"📝 Test ochilmoqda: {url}")
        page.goto(url, wait_until="load")
        page.wait_for_timeout(2500)
        print("Test sahifasi yuklandi, URL:", page.url)
        
        for step in range(1, 40):
            print(f"\n--- [SAVOL #{step}] ---")
            page.wait_for_timeout(1000)
            
            # Check if finished
            if page.locator("text=受講結果, text=テスト結果, text=テスト完了").count() > 0:
                print("🎉 Test to'liq yakunlandi!")
                break
                
            choices = page.evaluate('''() => {
                const radios = Array.from(document.querySelectorAll('#divSingleSelection label, label.answer-box'));
                return radios.map((lbl, idx) => ({ index: idx, id: lbl.id, text: lbl.innerText.trim() })).filter(c => c.text);
            }''')
            
            if not choices:
                next_b = page.locator('#ctl00_cplPageContent_lbnNext, a:has-text("次へ")').first
                finish_b = page.locator('#ctl00_cplPageContent_lbnFinish, a:has-text("終了"), button:has-text("終了")').first
                if next_b.is_visible():
                    print("➡️ '次へ' (Keyingisi) bosilmoqda...")
                    next_b.click()
                    page.wait_for_load_state("load")
                    continue
                elif finish_b.is_visible():
                    print("🏁 '終了' (Yakunlash) bosilmoqda...")
                    finish_b.click()
                    page.wait_for_load_state("load")
                    break
                else:
                    print("Choices ham, nav ham topilmadi. Sahifa sarlavhasi:", page.title())
                    break
                    
            q_text = page.evaluate('''() => {
                const el = document.querySelector('.card-body, #divQuestionArea, #divQuestion');
                return el ? el.innerText.trim() : document.body.innerText.trim();
            }''')
            print("Savol:", q_text[:120].replace("\n", " "))
            print(f"Variantlar ({len(choices)} ta):", [c['text'] for c in choices])
            
            best_idx = solve_with_gemini(q_text, choices)
            choice_id = choices[best_idx]['id']
            print(f"🖱 Variant tanlanmoqda: #{choice_id}")
            page.click(f"#{choice_id}")
            page.wait_for_timeout(500)
            
            grading = page.locator('#ctl00_cplPageContent_lbnGrading, a:has-text("採点")').first
            if grading.is_visible():
                print("📝 '採点' (Baholash) bosilmoqda...")
                grading.click()
                page.wait_for_load_state("load")
                page.wait_for_timeout(1000)
                
            next_b = page.locator('#ctl00_cplPageContent_lbnNext, a:has-text("次へ")').first
            finish_b = page.locator('#ctl00_cplPageContent_lbnFinish, a:has-text("終了"), button:has-text("終了")').first
            if next_b.is_visible():
                print("➡️ '次へ' bosilmoqda...")
                next_b.click()
                page.wait_for_load_state("load")
            elif finish_b.is_visible():
                print("🏁 '終了' bosilmoqda...")
                finish_b.click()
                page.wait_for_load_state("load")
                break
                
        print("\nTest jarayoni tugadi. Natija skrinshoti saqlanmoqda...")
        page.screenshot(path="/home/saeed/Downloads/lms_v2/test_result_pilot.png")
        browser.close()

if __name__ == "__main__":
    solve_pilot()
