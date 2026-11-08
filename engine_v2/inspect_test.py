from playwright.sync_api import sync_playwright
import json

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto("https://e-jdu.uz/default.aspx")
    page.locator('input[name*="txtUserID"]').first.fill("jdu-226516")
    page.locator('input[name*="txtPassword"]').first.fill("55ugtk")
    page.locator('button:has-text("ログイン"), input[value*="ログイン"]').first.click()
    page.wait_for_load_state("load")
    page.wait_for_timeout(2000)
    
    page.goto("https://e-jdu.uz/home/course/viewer/default.aspx?mode=study&cid=953&uid=14108")
    page.wait_for_timeout(3000)
    
    js = """
    () => {
        const radios = Array.from(document.querySelectorAll('input[type="radio"]'));
        const labels = Array.from(document.querySelectorAll('label'));
        const groups = {};
        radios.forEach(r => {
            groups[r.name] = (groups[r.name] || 0) + 1;
        });
        return {
            radios_count: radios.length,
            groups_count: Object.keys(groups).length,
            sample_radios: radios.slice(0, 8).map(r => ({ name: r.name, value: r.value, id: r.id })),
            sample_labels: labels.slice(0, 8).map(l => ({ id: l.id, text: l.innerText.trim(), for: l.htmlFor }))
        };
    }
    """
    res = page.evaluate(js)
    print(json.dumps(res, indent=2))
    browser.close()
