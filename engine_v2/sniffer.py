import json
import time
import os
from playwright.sync_api import sync_playwright

OUTPUT_FILE = "/home/saeed/Downloads/lms_v2/network_log.json"
BASE_URL = "https://e-jdu.uz"

captured_events = []

def record_event(event_type, data):
    # Filter out noisy static assets (images, css, fonts)
    url = data.get("url", "")
    if any(ext in url.lower() for ext in [".png", ".jpg", ".jpeg", ".gif", ".css", ".woff", ".woff2", ".ico", ".svg"]):
        return
    captured_events.append({
        "time": time.time(),
        "type": event_type,
        **data
    })
    print(f"[{event_type}] {data.get('method', '')} {url[:90]}")

def run_sniffer():
    print("🚀 LMS Network Sniffer boshlanmoqda...")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        def on_request(request):
            post_data = None
            try:
                post_data = request.post_data
            except Exception:
                pass
            record_event("REQUEST", {
                "url": request.url,
                "method": request.method,
                "headers": dict(request.headers),
                "post_data": post_data
            })

        def on_response(response):
            # Capture responses for .aspx, API, and JSON calls
            url = response.url
            if any(ext in url.lower() for ext in [".aspx", "/api/", ".asmx", ".ashx", "/service/"]):
                body_sample = None
                try:
                    text = response.text()
                    body_sample = text[:1500] if text else None
                except Exception:
                    pass
                record_event("RESPONSE", {
                    "url": response.url,
                    "status": response.status,
                    "headers": dict(response.headers),
                    "body_sample": body_sample
                })

        page.on("request", on_request)
        page.on("response", on_response)

        # 1. Login flow
        print("\n--- 1. Login sahifasi ---")
        page.goto(f"{BASE_URL}/default.aspx", wait_until="load", timeout=30000)
        page.wait_for_timeout(1500)
        
        user_input = page.locator('input[name*="txtUserID"]').first
        pass_input = page.locator('input[name*="txtPassword"]').first
        user_input.fill("jdu-226516")
        pass_input.fill("55ugtk")
        
        print("Login tugmasi bosilmoqda...")
        page.locator('button:has-text("ログイン"), input[value*="ログイン"]').first.click()
        page.wait_for_load_state("load", timeout=20000)
        page.wait_for_timeout(2000)

        # Capture cookies
        cookies = context.cookies()
        print(f"✅ Tizimga kirildi! Olingan cookie'lar soni: {len(cookies)}")
        record_event("COOKIES", {"cookies": cookies})

        # 2. Course navigation
        print("\n--- 2. Kurs sahifasi ochilmoqda ---")
        course_card = page.locator('text="N3 (2026秋セメスター)"').first
        if not course_card.is_visible():
            course_card = page.locator('.card:has-text("N3"), a:has-text("N3")').first
        course_card.click()
        page.wait_for_load_state("load", timeout=20000)
        page.wait_for_timeout(2000)

        # Inner module click if needed
        if page.locator('li[id*="liChapter"]').count() == 0:
            inner_mod = page.locator('.list-group-item:has-text("N3")').first
            if inner_mod.is_visible():
                print("Inner module bosilmoqda...")
                inner_mod.click()
                page.wait_for_load_state("load", timeout=20000)
                page.wait_for_timeout(2000)

        # 3. Expand chapters and inspect pending unit
        print("\n--- 3. Boblar ochilmoqda ---")
        page.evaluate('''() => {
            document.querySelectorAll('li[id*="liChapter"] button.accordion-button.collapsed').forEach(b => b.click());
        }''')
        page.wait_for_timeout(2500)

        # Find 5章③::文法(Grammatika)9 or any pending link
        print("\n--- 4. Darsga kirish so'rovini ushlash ---")
        test_link = page.locator('a:has-text("文法(Grammatika)9")').first
        if not test_link.is_visible():
            test_link = page.locator('a[id*="lbnUnitName"]').first

        if test_link.is_visible():
            link_text = test_link.inner_text().strip()
            print(f"Dars havolasi bosilmoqda: '{link_text}'...")
            test_link.click(force=True)
            page.wait_for_timeout(4000)

        browser.close()

    # Save to file
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(captured_events, f, indent=2, ensure_ascii=False)
    print(f"\n✅ Tahlil yakunlandi! Jami {len(captured_events)} ta asosiy tarmoq hodisalari saqlandi: {OUTPUT_FILE}")

if __name__ == "__main__":
    run_sniffer()
