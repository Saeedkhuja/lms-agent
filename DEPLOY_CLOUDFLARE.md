# 🌐 e-JDU LMS AI Agent Veb Dashboard - Cloudflare Qo'llanmasi

Ushbu loyiha orqali siz **e-jdu.uz LMS** tizimidagi dars va testlarni sun'iy intellekt (Gemini 2.5/3.8 Flash) yordamida avtonom yechuvchi robotni zamonaviy veb-dashboard orqali boshqarishingiz mumkin.

---

## ⚡ 1-USUL: Cloudflare Workers Static Assets (Wrangler orqali)

Siz avval ishlatgan xuddi o'sha Wrangler buyrug'i orqali veb-saytni to'g'ridan-to'g'ri Cloudflare tarmog'iga deploy qilishingiz mumkin:

```bash
cd /home/saeed/Downloads/lms_agent_web
npx wrangler@latest deploy --name docsdmeduz-el-docs-5f49c759-67a4-4570-ba41-e --assets ./static --compatibility-date 2026-10-25
```

Yoki to'liq yo'l bilan:
```bash
npx wrangler@latest deploy --name docsdmeduz-el-docs-5f49c759-67a4-4570-ba41-e --assets /home/saeed/Downloads/lms_agent_web/static --compatibility-date 2026-10-25
```

Ushbu buyruq saytni avtomatik ravishda Cloudflare Edge tarmog'iga joylaydi:
👉 **https://docsdmeduz-el-docs-5f49c759-67a4-4570-ba41-e.saidislomxojaxonov77.workers.dev**

### 💡 Saytni kompyuterdagi Agent bilan bog'lash:
Veb-sayt Cloudflare'da ishlaganda, kompyuteringizdagi Playwright agenti bilan bog'lanishi uchun:
1. Kompyuteringizda agentni yoqing:
   ```bash
   cd /home/saeed/Downloads/lms_agent_web
   ./start.sh
   ```
2. Cloudflare saytingizga kiring (`https://docsdmeduz-...workers.dev`) va yuqoridagi **"Server"** tugmasini bosing.
3. U yerga agent ishlayotgan manzilni (masalan, Cloudflare Tunnel bergan HTTPS havolasini yoki server IP manzilini) kiriting va "Saqlash" tugmasini bosing. Bo'ldi, sayt agent bilan jonli bog'lanadi!

---

## ⚡ 2-USUL: Cloudflare Tunnel (Agent backend + Frontend bittada)

Playwright brauzeri (Chromium) to'liq ishlashi va barcha darslarni avtonom bajarishi uchun dastur serverda/kompyuterda ishlaydi, **Cloudflare Tunnel (`cloudflared`)** esa uni dunyoga bepul HTTPS havolasi orqali xavfsiz ochib beradi.

### 1-qadam: Veb dashboardni ishga tushirish
```bash
cd /home/saeed/Downloads/lms_agent_web
./start.sh
```
Server `http://localhost:8000` manzilida ishlay boshlaydi.

### 2-qadam: Cloudflare Tunnel orqali dunyoga ulash
Yangi terminalda `cloudflared` ni o'rnating:

**Linux (Ubuntu/Zorin OS/Debian):**
```bash
curl -L --output cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared.deb
```

Endi tunnelni birgina buyruq bilan yoqing:
```bash
cloudflared tunnel --url http://localhost:8000
```

Terminalda sizga avtomatik bepul HTTPS havola beriladi:
```text
https://your-random-subdomain.trycloudflare.com
```
Ushbu havola orqali istalgan joydan (hatto telefoningizdan) to'g'ridan-to'g'ri veb dashboardga kirib, agentni boshqarishingiz mumkin!

---

## 🚀 3-USUL: O'z shaxsiy domeningiz orqali Cloudflare Tunnel (Doimiy 24/7)

Agar sizda Cloudflare'da domeningiz bo'lsa (masalan: `agent.mysite.com`):

1. Cloudflare hisobingizga kiring:
   ```bash
   cloudflared tunnel login
   ```

2. Yangi tunnel yarating:
   ```bash
   cloudflared tunnel create lms-agent
   ```

3. `~/.cloudflared/config.yml` fayliga quyidagini yozing:
   ```yaml
   tunnel: <TUNNEL_ID>
   credentials-file: /home/user/.cloudflared/<TUNNEL_ID>.json

   ingress:
     - hostname: agent.mysite.com
       service: http://localhost:8000
     - service: http_status:404
   ```

4. DNS ga ulab, xizmat sifatida fon rejimida yoqing:
   ```bash
   cloudflared tunnel route dns lms-agent agent.mysite.com
   sudo cloudflared service install
   sudo systemctl start cloudflared
   ```

---

## 🐳 4-USUL: Docker & Docker Compose orqali serverda ishga tushirish

```bash
cd /home/saeed/Downloads/lms_agent_web
docker compose up -d --build
```
Konteyner fon rejimida 8000-portda ishga tushadi.
