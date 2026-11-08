#!/usr/bin/env python3
"""
=============================================================================
e-JDU LMS Autonomous AI Agent - GitHub Actions 24/7 Auto-Runner
=============================================================================
Designed for running on GitHub Actions Public Repositories (6-hour limit).
Gracefully saves progress, logs to Step Summary, and auto-chains runs.
=============================================================================
"""

import os
import sys
import time
import argparse
from datetime import datetime

from config import load_profiles, load_settings, load_completed_tasks, BASE_DIR
from agent_runner import AgentRunner

def write_step_summary(content: str):
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path and os.path.exists(os.path.dirname(summary_path)):
        try:
            with open(summary_path, "a", encoding="utf-8") as f:
                f.write(content + "\n")
        except Exception:
            pass

def main():
    parser = argparse.ArgumentParser(description="GitHub Actions LMS Agent Runner")
    parser.add_argument("--max-hours", type=float, default=5.3, help="Max execution hours before graceful auto-stop (default 5.3)")
    parser.add_argument("--profile-id", type=str, default=None, help="Target specific student profile ID")
    args = parser.parse_args()

    max_seconds = int(args.max_hours * 3600)
    start_time = time.time()

    print("=" * 60)
    print("🚀 GITHUB ACTIONS LMS AGENT ISHGA TUSHIRILMOQDA")
    print(f"⏰ Maksimal ish vaqti: {args.max_hours} soat ({max_seconds} sek)")
    print(f"📅 Boshlangan vaqt: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    write_step_summary(f"## 🤖 e-JDU LMS Agent — GitHub Actions Run\n- **Boshlangan vaqt:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n- **Maksimal limit:** {args.max_hours} soat\n")

    settings = load_settings()
    profiles = load_profiles()
    active_profiles = [p for p in profiles if p.get("active", True)]

    if args.profile_id:
        active_profiles = [p for p in active_profiles if p["id"] == args.profile_id]

    if not active_profiles:
        print("❌ Hech qanday faol talaba profili topilmadi!")
        write_step_summary("❌ **Xatolik:** Hech qanday faol talaba profili topilmadi.")
        sys.exit(0)

    print(f"📋 Faol talabalar ro'yxati ({len(active_profiles)} ta):")
    for p in active_profiles:
        completed = load_completed_tasks(p["user_id"])
        print(f"  • {p['name']} ({p['user_id']}) - {len(completed)} ta dars avval bajarilgan")

    runner = AgentRunner()

    # Start runner in background thread
    runner.start(profile_id=args.profile_id)

    # Monitor loop
    try:
        while True:
            elapsed = time.time() - start_time
            if elapsed >= max_seconds:
                print("\n" + "=" * 60)
                print(f"⏳ 6-soatlik GitHub Actions limitiga yetilmoqda ({args.max_hours} soat o'tdi).")
                print("🛑 Jarayon xavfsiz to'xtatilmoqda va keyingi run zanjiriga uzatilmoqda...")
                print("=" * 60)
                runner.stop()
                break

            if runner.state == "STOPPED":
                print("\n🏁 Agent barcha topshiriqlarni yakunladi yoki to'xtadi.")
                break

            # Heartbeat log every 60 seconds
            status = runner.get_status()
            current_lesson = status.get("current_lesson") or "Kutilmoqda"
            pct = status.get("current_progress_pct", 0)
            completed = status.get("total_completed", 0)
            remaining = status.get("remaining", 0)
            m, s = divmod(int(elapsed), 60)
            h, m = divmod(m, 60)
            print(f"[{h:02d}:{m:02d}:{s:02d}] Holat: {status['state']} | Dars: {current_lesson} | Bajarilgan: {completed} | Qolgan: {remaining} ({pct}%)", flush=True)

            time.sleep(60)
    except KeyboardInterrupt:
        print("\nTo'xtatish signali qabul qilindi...")
        runner.stop()

    total_elapsed = int(time.time() - start_time)
    th, tm = divmod(total_elapsed // 60, 60)
    print("\n" + "=" * 60)
    print("📊 SEANSI YAKUNIY HISOBOTI:")
    print(f"⏱ Jami ishlangan vaqt: {th} soat {tm} daqiqa")
    for p in active_profiles:
        completed = load_completed_tasks(p["user_id"])
        print(f"✅ {p['name']} ({p['user_id']}): Jami {len(completed)} ta dars bajarilgan")
    print("=" * 60)

    summary_content = f"""
### 📊 Natijalar:
- **Jami ishlagan vaqt:** {th} soat {tm} daqiqa
- **Bajarilgan darslar:**
"""
    for p in active_profiles:
        c = load_completed_tasks(p["user_id"])
        summary_content += f"  - **{p['name']}** (`{p['user_id']}`): {len(c)} ta dars yakunlangan\n"
    write_step_summary(summary_content)

    print("✅ Skript yakunlandi.")
    sys.exit(0)

if __name__ == "__main__":
    main()
