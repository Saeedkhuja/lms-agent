import requests
import re
import urllib.parse
from typing import Dict, List, Any, Optional

BASE_URL = "https://e-jdu.uz"

class LMSDirectClient:
    def __init__(self, user_id: str, password: str, course_name: str = "N3 (2026秋セメスター)"):
        self.user_id = user_id
        self.password = password
        self.course_name = course_name
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8,uz;q=0.7",
        })
        self.course_url = None
        self.course_id = 953

    def _extract_asp_tokens(self, html: str) -> Dict[str, str]:
        tokens = {}
        for field in ["__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION"]:
            m = re.search(rf'id=[\"\x27]{field}[\"\x27]\s+value=[\"\x27]([^\"]*)[\"\x27]', html)
            tokens[field] = m.group(1) if m else ""
        return tokens

    def login(self) -> bool:
        print(f"🔑 [HTTP] Tizimga kirilmoqda: {self.user_id}...")
        # 1. GET default.aspx to extract ASP tokens
        res = self.session.get(f"{BASE_URL}/default.aspx", timeout=15)
        if res.status_code != 200:
            print("❌ Login sahifasini ochib bo'lmadi:", res.status_code)
            return False

        tokens = self._extract_asp_tokens(res.text)

        # 2. POST login credentials
        payload = {
            "__LASTFOCUS": "",
            "__VIEWSTATE": tokens.get("__VIEWSTATE", ""),
            "__VIEWSTATEGENERATOR": tokens.get("__VIEWSTATEGENERATOR", ""),
            "__EVENTTARGET": "",
            "__EVENTARGUMENT": "",
            "__EVENTVALIDATION": tokens.get("__EVENTVALIDATION", ""),
            "ctl00$cplPageContent$txtUserID": self.user_id,
            "ctl00$cplPageContent$txtPassword": self.password,
            "ctl00$cplPageContent$hdnFaceCameraDevice": ""
        }

        headers = {
            "Origin": BASE_URL,
            "Referer": f"{BASE_URL}/default.aspx",
            "Content-Type": "application/x-www-form-urlencoded"
        }

        res_post = self.session.post(
            f"{BASE_URL}/default.aspx",
            data=payload,
            headers=headers,
            timeout=20,
            allow_redirects=True
        )

        # Check by accessing home page
        r_home = self.session.get(f"{BASE_URL}/home/default.aspx", timeout=15)
        if r_home.status_code == 200 and ("course" in r_home.text or "cid=953" in r_home.text or "KD_USER" in self.session.cookies):
            print("✅ [HTTP] Muvaffaqiyatli kirildi! Session ID:", self.session.cookies.get("ASP.NET_SessionId", "")[:10] + "...")
            return True

        print("❌ Login amalga oshmadi. URL:", res_post.url)
        return False

    def open_course(self) -> bool:
        print(f"📚 [HTTP] Kurs ochilmoqda: {self.course_name} (CID: {self.course_id})...")
        res = self.session.get(f"{BASE_URL}/home/default.aspx", timeout=15)
        if res.status_code != 200:
            print("❌ Asosiy sahifa ochilmadi")
            return False

        course_href = None
        for m in re.finditer(r'href=[\"\x27](/home/course/default\.aspx\?k=[^\"\x27]+)[\"\x27]', res.text):
            start = m.start()
            after = res.text[start: start + 700]
            if str(self.course_id) in after or self.course_name in after or "N3" in after:
                course_href = m.group(1).replace("&amp;", "&")
                break

        if not course_href:
            print("❌ Kurs havolasi topilmadi")
            return False

        res_course = self.session.get(f"{BASE_URL}{course_href}", timeout=15)

        # Check if inner module needs clicking
        if "liChapter" not in res_course.text:
            m_inner = re.search(r'href=[\"\x27](/home/course/default\.aspx\?k=[^\"\x27]+)[\"\x27]', res_course.text)
            if m_inner:
                course_href = m_inner.group(1).replace("&amp;", "&")
                res_course = self.session.get(f"{BASE_URL}{course_href}", timeout=15)

        self.course_url = f"{BASE_URL}{course_href}"
        print(f"✅ Kurs ochildi! URL: {self.course_url[:65]}...")
        return True

    def scan_units(self) -> List[Dict[str, Any]]:
        print("🔍 [HTTP] Barcha darslar skaner qilinmoqda...")
        res = self.session.get(self.course_url, timeout=15)
        
        pattern = r'<li[^>]+id=[\"\x27]([^\"]*liUnitListGroupItem[^\"]*)[\"\x27]([^>]*)>(.*?)</li>'
        items = re.findall(pattern, res.text, re.DOTALL)

        units = []
        for li_id, li_attrs, li_content in items:
            m_link = re.search(r'id=[\"\x27]([^\"]*lbnUnitName[^\"]*)[\"\x27][^>]*>(.*?)</a>', li_content)
            title = m_link.group(2).strip() if m_link else "Unknown"
            
            # Find uid
            m_uid = re.search(r'uid=(\d+)', li_content)
            uid = m_uid.group(1) if m_uid else None

            is_finished = any(cls in li_attrs for cls in ["finished", "complete", "passed"])
            m_prog = re.search(r'data-kd-progress=[\"\x27](\d+)[\"\x27]', li_content)
            prog = m_prog.group(1) if m_prog else "0"

            units.append({
                "title": title,
                "li_id": li_id,
                "link_id": m_link.group(1) if m_link else None,
                "is_finished": is_finished or prog == "100",
                "progress": prog,
                "uid": uid
            })

        finished_count = sum(1 for u in units if u["is_finished"])
        print(f"📊 [HTTP] Jami darslar: {len(units)} | Bajarilgan: {finished_count} | Qolgan: {len(units)-finished_count}")
        return units

    def get_unit_viewer_info(self, link_id: str) -> Optional[Dict[str, str]]:
        """Trigger unit postback and extract viewer URL and uid in 0.1s"""
        res_course = self.session.get(self.course_url, timeout=15)
        tokens = self._extract_asp_tokens(res_course.text)
        
        # Extract form action
        m_action = re.search(r'<form[^>]+action=[\"\x27]([^\"]+)[\"\x27]', res_course.text)
        action = m_action.group(1).replace("&amp;", "&") if m_action else None
        if action and not action.startswith("http"):
            action = urllib.parse.urljoin(self.course_url, action)

        target = link_id.replace("_", "$")
        payload = {
            "ctl00$MyScriptManager": "ctl00$MyScriptManager|" + target,
            "__EVENTTARGET": target,
            "__VIEWSTATE": tokens.get("__VIEWSTATE", ""),
            "__VIEWSTATEGENERATOR": tokens.get("__VIEWSTATEGENERATOR", ""),
            "__EVENTVALIDATION": tokens.get("__EVENTVALIDATION", ""),
            "ctl00$cplPageContent$20302$dkcChapterUnit$hdnIsMobile": "false",
            "__ASYNCPOST": "true"
        }

        headers = {
            "Referer": self.course_url,
            "Origin": BASE_URL,
            "X-MicrosoftAjax": "Delta=true",
            "Content-Type": "application/x-www-form-urlencoded"
        }

        res_post = self.session.post(action or self.course_url, data=payload, headers=headers, timeout=15)
        
        # Extract viewer link and uid
        m_viewer = re.search(r'viewer/default\.aspx\?[^\x22\x27\s]+', res_post.text)

        if m_viewer:
            v_href = m_viewer.group(0).replace("&amp;", "&")
            m_uid = re.search(r'uid=(\d+)', v_href)
            uid = m_uid.group(1) if m_uid else None
            return {"viewer_url": f"{BASE_URL}/home/course/{v_href}", "uid": uid}

        return None

    def complete_unit(self, uid: str, study_sec: int = 45, is_vp: bool = True) -> bool:
        """Mark a video or reading unit complete in 0.1s via direct logging.aspx POST"""
        url = f"{BASE_URL}/home/course/viewer/logging.aspx"
        payload = {
            "uid": str(uid),
            "cid": str(self.course_id),
            "study_sec": str(study_sec),
            "is_finished": "1",
            "rate": "100",
            "score": "0",
            "max_score": "0",
            "item_count": "0",
            "is_suspend": "0",
            "last_bind_id": "0",
            "last_page_no": "0",
            "page_no": "0",
            "slide_no": "0",
            "vp_resume_time": "0",
            "vp_video_time": "0",
            "is_vp_finish": "1" if is_vp else "0",
            "has_vp": "1" if is_vp else "0",
            "face_during_learning_error": "",
            "face_during_learning_id": ""
        }

        headers = {
            "Referer": f"{BASE_URL}/home/course/viewer/foot.aspx?mode=study&cid={self.course_id}&uid={uid}",
            "Origin": BASE_URL,
            "Content-Type": "application/x-www-form-urlencoded"
        }

        res = self.session.post(url, data=payload, headers=headers, timeout=10)
        return res.status_code == 200 or res.status_code == 302

if __name__ == "__main__":
    client = LMSDirectClient("jdu-226516", "55ugtk")
    if client.login():
        if client.open_course():
            units = client.scan_units()
            pending = [u for u in units if not u["is_finished"]]
            print(f"\nTopilgan darslar soni: {len(units)}, Qolgan: {len(pending)}")
            for p in pending[:5]:
                print(" -> Qolgan:", p["title"], "ID:", p["link_id"])
