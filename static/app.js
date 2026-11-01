// LMS Autonomous AI Agent Frontend Controller

let lastLogId = 0;
let pollingInterval = null;
let currentProfiles = [];
let selectedProfileId = "";

// Backend API URL Configuration (supports Cloudflare deployment connecting to local/remote agent)
let API_BASE = localStorage.getItem("lms_agent_api_base") || "";

function getApiUrl(path) {
  if (!API_BASE) {
    return path;
  }
  return `${API_BASE.replace(/\/+$/, "")}${path}`;
}

function openServerConfigModal() {
  document.getElementById("customBackendUrlInput").value = API_BASE;
  const modal = document.getElementById("serverModal");
  modal.classList.remove("hidden");
  modal.classList.add("flex");
}

function closeServerConfigModal() {
  const modal = document.getElementById("serverModal");
  modal.classList.add("hidden");
  modal.classList.remove("flex");
}

function saveServerConfigModal() {
  const val = document.getElementById("customBackendUrlInput").value.trim();
  API_BASE = val;
  if (val) {
    localStorage.setItem("lms_agent_api_base", val);
  } else {
    localStorage.removeItem("lms_agent_api_base");
  }
  closeServerConfigModal();
  updateServerStatusLabel();
  lastLogId = 0;
  loadProfiles();
  loadSettings();
  updateStatus();
  updateLogs();
  updateScreenshot();
}

function updateServerStatusLabel() {
  const lbl = document.getElementById("serverStatusLabel");
  const dot = document.getElementById("serverStatusDot");
  if (lbl) {
    if (API_BASE) {
      lbl.innerText = "Tunnel / VPS";
      lbl.className = "hidden md:inline text-indigo-400 font-semibold";
      if (dot) dot.className = "w-2 h-2 rounded-full bg-indigo-400";
    } else {
      const isLocal = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";
      lbl.innerText = isLocal ? "Lokal" : "Server Ulanmagan";
      lbl.className = isLocal ? "hidden md:inline text-slate-300" : "hidden md:inline text-amber-400 font-medium";
      if (dot) dot.className = isLocal ? "w-2 h-2 rounded-full bg-slate-400" : "w-2 h-2 rounded-full bg-amber-400";
    }
  }
}

// Initialize Dashboard
document.addEventListener("DOMContentLoaded", () => {
  updateServerStatusLabel();
  
  // If running on Cloudflare/external domain and no API_BASE is configured, open modal or alert
  const isLocal = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";
  if (!isLocal && !API_BASE) {
    const banner = document.getElementById("remoteBanner");
    if (banner) banner.classList.remove("hidden");
  }

  loadProfiles();
  loadSettings();
  startPolling();
});

// ---------------------------------------------------------------------------
// POLLING & REALTIME DATA
// ---------------------------------------------------------------------------
function startPolling() {
  if (pollingInterval) clearInterval(pollingInterval);
  updateStatus();
  updateLogs();
  updateScreenshot();

  pollingInterval = setInterval(() => {
    updateStatus();
    updateLogs();
    updateScreenshot();
  }, 1800);
}

async function updateStatus() {
  try {
    const res = await fetch(getApiUrl("/api/status"));
    if (!res.ok) return;
    const data = await res.json();

    // 1. Update Status Badge
    const badge = document.getElementById("statusBadge");
    const dot = document.getElementById("statusDot");
    const text = document.getElementById("statusText");
    const btnStart = document.getElementById("btnStart");
    const btnStop = document.getElementById("btnStop");

    const state = data.state || "STOPPED";
    text.innerText = state;

    if (state === "RUNNING" || state === "WATCHING_VIDEO" || state === "SOLVING_QUIZ") {
      dot.className = "w-2.5 h-2.5 rounded-full bg-emerald-400 pulsing-green";
      badge.className = "flex items-center space-x-2 px-3 py-1.5 rounded-lg bg-emerald-950/40 border border-emerald-500/40 text-xs";
      text.className = "font-bold text-emerald-400 uppercase tracking-wider";
      btnStart.disabled = true;
      btnStart.classList.add("opacity-50", "cursor-not-allowed");
      btnStop.disabled = false;
      btnStop.classList.remove("opacity-50", "cursor-not-allowed");
    } else if (state === "STANDBY") {
      dot.className = "w-2.5 h-2.5 rounded-full bg-amber-400";
      badge.className = "flex items-center space-x-2 px-3 py-1.5 rounded-lg bg-amber-950/40 border border-amber-500/40 text-xs";
      text.className = "font-bold text-amber-400 uppercase tracking-wider";
      btnStart.disabled = true;
      btnStart.classList.add("opacity-50", "cursor-not-allowed");
      btnStop.disabled = false;
      btnStop.classList.remove("opacity-50", "cursor-not-allowed");
    } else {
      dot.className = "w-2.5 h-2.5 rounded-full bg-slate-400";
      badge.className = "flex items-center space-x-2 px-3 py-1.5 rounded-lg bg-slate-800/80 border border-slate-700/60 text-xs";
      text.className = "font-semibold text-slate-300 uppercase tracking-wider";
      btnStart.disabled = false;
      btnStart.classList.remove("opacity-50", "cursor-not-allowed");
      btnStop.disabled = true;
      btnStop.classList.add("opacity-50", "cursor-not-allowed");
    }

    // 2. Update Stats
    const student = data.active_profile;
    document.getElementById("statStudent").innerText = student ? student.name : "-";
    document.getElementById("statUserId").innerText = student ? student.user_id : "-";
    document.getElementById("statLesson").innerText = data.current_lesson || "Yo'q";
    document.getElementById("statChapter").innerText = data.current_chapter || "-";
    document.getElementById("statCompleted").innerText = data.total_completed || 0;
    document.getElementById("statRemaining").innerText = data.remaining || 0;

    // Uptime formatting
    const upSec = data.uptime_seconds || 0;
    const hours = Math.floor(upSec / 3600);
    const mins = Math.floor((upSec % 3600) / 60);
    const secs = upSec % 60;
    document.getElementById("statUptime").innerText = `${pad(hours)}:${pad(mins)}:${pad(secs)}`;

    // Progress bar
    const pct = data.current_progress_pct || 0;
    document.getElementById("progressBar").style.width = `${pct}%`;
    document.getElementById("progressPercentText").innerText = `${pct}%`;

    // Active Activity text
    let activityText = "Kutish holatida";
    if (state === "WATCHING_VIDEO") activityText = "Video dars tomosha qilinmoqda...";
    else if (state === "SOLVING_QUIZ") activityText = "Test savollari AI bilan yechilmoqda...";
    else if (state === "STANDBY") activityText = "Barcha darslar yakunlangan, navbatdagi tekshiruv kutilmoqda";
    else if (state === "RUNNING") activityText = "LMS sahifalarida harakatlanilmoqda...";
    document.getElementById("currentActivityText").innerText = activityText;

  } catch (err) {
    console.error("Status update error:", err);
  }
}

async function updateLogs() {
  try {
    const res = await fetch(getApiUrl(`/api/logs?since_id=${lastLogId}`));
    if (!res.ok) return;
    const data = await res.json();
    const logs = data.logs || [];
    if (logs.length === 0) return;

    const consoleEl = document.getElementById("logConsole");
    if (lastLogId === 0) {
      consoleEl.innerHTML = "";
    }

    logs.forEach(l => {
      lastLogId = Math.max(lastLogId, l.id);
      const row = document.createElement("div");
      row.className = "flex items-start space-x-2 leading-relaxed";

      let colorClass = "text-slate-300";
      if (l.level === "INFO") colorClass = "log-info";
      else if (l.level === "WARN") colorClass = "log-warn";
      else if (l.level === "ERROR") colorClass = "log-error";

      row.innerHTML = `
        <span class="text-slate-500 select-none">[${l.timestamp}]</span>
        <span class="${colorClass} font-semibold">[${l.level}]</span>
        <span class="text-slate-200">${escapeHtml(l.message)}</span>
      `;
      consoleEl.appendChild(row);
    });

    if (document.getElementById("chkAutoScroll").checked) {
      consoleEl.scrollTop = consoleEl.scrollHeight;
    }
  } catch (err) {
    console.error("Log update error:", err);
  }
}

async function updateScreenshot() {
  try {
    const res = await fetch(getApiUrl("/api/screenshot"));
    if (!res.ok) return;
    const data = await res.json();

    const img = document.getElementById("liveScreen");
    const placeholder = document.getElementById("screenPlaceholder");

    if (data.screenshot) {
      img.src = `data:image/jpeg;base64,${data.screenshot}`;
      img.classList.remove("hidden");
      placeholder.classList.add("hidden");
    } else {
      img.classList.add("hidden");
      placeholder.classList.remove("hidden");
    }
  } catch (err) {
    console.error("Screenshot update error:", err);
  }
}

// ---------------------------------------------------------------------------
// AGENT CONTROLS
// ---------------------------------------------------------------------------
async function startAgent() {
  const profileId = selectedProfileId || document.getElementById("quickProfileSelect").value || null;
  const customTask = document.getElementById("customTaskInput").value.trim() || null;

  try {
    const res = await fetch(getApiUrl("/api/agent/start"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        profile_id: profileId,
        custom_task: customTask
      })
    });
    const data = await res.json();
    if (!res.ok) {
      alert("Xatolik: " + (data.detail || "Agentni ishga tushirib bo'lmadi"));
    } else {
      updateStatus();
    }
  } catch (e) {
    alert("Serverga ulanishda xatolik yuz berdi. Backend ishlayotganini tekshiring.");
  }
}

async function stopAgent() {
  try {
    await fetch(getApiUrl("/api/agent/stop"), { method: "POST" });
    updateStatus();
  } catch (e) {
    alert("To'xtatish so'rovida xatolik.");
  }
}

function clearLogs() {
  document.getElementById("logConsole").innerHTML = "";
  lastLogId = 0;
}

function toggleFullscreen() {
  const container = document.getElementById("screenContainer");
  if (!document.fullscreenElement) {
    container.requestFullscreen().catch(err => alert("Fullscreen xatoligi: " + err.message));
  } else {
    document.exitFullscreen();
  }
}

// ---------------------------------------------------------------------------
// TABS SWITCHER
// ---------------------------------------------------------------------------
function switchTab(tabName) {
  const tabs = ["profiles", "ai_task", "settings"];
  tabs.forEach(t => {
    const panel = document.getElementById(`tab${capitalize(t)}`);
    const btn = document.getElementById(`tabBtn${capitalize(t)}`);
    if (t === tabName) {
      panel.classList.remove("hidden");
      btn.className = "flex-1 py-2 rounded-xl text-center transition-all bg-indigo-600 text-white shadow-md font-semibold";
    } else {
      panel.classList.add("hidden");
      btn.className = "flex-1 py-2 rounded-xl text-center transition-all text-slate-400 hover:text-white";
    }
  });
}

function capitalize(s) {
  if (s === "ai_task") return "AiTask";
  return s.charAt(0).toUpperCase() + s.slice(1);
}

// ---------------------------------------------------------------------------
// PROFILES MANAGEMENT
// ---------------------------------------------------------------------------
async function loadProfiles() {
  try {
    const res = await fetch(getApiUrl("/api/profiles"));
    if (!res.ok) return;
    const data = await res.json();
    currentProfiles = data.profiles || [];

    const listEl = document.getElementById("profilesList");
    const quickSelect = document.getElementById("quickProfileSelect");
    listEl.innerHTML = "";
    quickSelect.innerHTML = '<option value="">Barcha faol profillar...</option>';

    currentProfiles.forEach(p => {
      // Add to quick select dropdown
      const opt = document.createElement("option");
      opt.value = p.id;
      opt.innerText = `${p.name} (${p.user_id})`;
      quickSelect.appendChild(opt);

      // Render Profile Card
      const card = document.createElement("div");
      card.className = "bg-slate-800/60 border border-white/5 rounded-xl p-3 flex items-center justify-between hover:border-indigo-500/30 transition group";
      card.innerHTML = `
        <div class="flex items-center space-x-3 truncate">
          <div class="w-9 h-9 rounded-xl bg-gradient-to-tr from-indigo-600 to-purple-600 flex items-center justify-center font-bold text-white text-xs">
            ${p.name.charAt(0).toUpperCase()}
          </div>
          <div class="truncate">
            <div class="flex items-center space-x-2">
              <span class="font-bold text-xs text-white">${escapeHtml(p.name)}</span>
              ${p.active ? '<span class="text-[9px] px-1.5 py-0.2 rounded bg-emerald-500/20 text-emerald-300 font-semibold">FAOL</span>' : '<span class="text-[9px] px-1.5 py-0.2 rounded bg-slate-700 text-slate-400">NOFAOL</span>'}
            </div>
            <div class="text-[11px] text-slate-400 font-mono flex items-center space-x-2">
              <span>${p.user_id}</span>
              <span class="text-slate-600">•</span>
              <span class="text-emerald-400">${p.completed_count || 0} ta bajarilgan</span>
            </div>
          </div>
        </div>
        <div class="flex items-center space-x-1.5">
          <button onclick="editProfile('${p.id}')" title="Tahrirlash" class="p-1.5 rounded-lg bg-slate-700/50 hover:bg-slate-700 text-slate-300 text-xs">
            <i class="bi bi-pencil"></i>
          </button>
          <button onclick="deleteProfile('${p.id}')" title="O'chirish" class="p-1.5 rounded-lg bg-rose-950/40 hover:bg-rose-900 text-rose-400 text-xs">
            <i class="bi bi-trash"></i>
          </button>
        </div>
      `;
      listEl.appendChild(card);
    });
  } catch (err) {
    console.error("Profiles load error:", err);
  }
}

function switchProfile(profId) {
  selectedProfileId = profId;
}

function openAddProfileModal() {
  document.getElementById("modalTitle").innerHTML = '<i class="bi bi-person-plus mr-2 text-indigo-400"></i> Yangi Talaba Qo\'shish';
  document.getElementById("editProfileId").value = "";
  document.getElementById("profName").value = "";
  document.getElementById("profUserId").value = "";
  document.getElementById("profPassword").value = "";
  document.getElementById("profCourse").value = "N3 (2026秋セメスター)";
  document.getElementById("profNotes").value = "";
  document.getElementById("profActive").checked = true;
  document.getElementById("profileModal").classList.remove("hidden");
}

function editProfile(profId) {
  const p = currentProfiles.find(x => x.id === profId);
  if (!p) return;
  document.getElementById("modalTitle").innerHTML = '<i class="bi bi-pencil mr-2 text-indigo-400"></i> Profilni Tahrirlash';
  document.getElementById("editProfileId").value = p.id;
  document.getElementById("profName").value = p.name;
  document.getElementById("profUserId").value = p.user_id;
  document.getElementById("profPassword").value = p.password;
  document.getElementById("profCourse").value = p.course || "N3 (2026秋セメスター)";
  document.getElementById("profNotes").value = p.notes || "";
  document.getElementById("profActive").checked = p.active !== false;
  document.getElementById("profileModal").classList.remove("hidden");
}

function closeProfileModal() {
  document.getElementById("profileModal").classList.add("hidden");
}

async function saveProfile() {
  const profId = document.getElementById("editProfileId").value;
  const payload = {
    name: document.getElementById("profName").value.trim(),
    user_id: document.getElementById("profUserId").value.trim(),
    password: document.getElementById("profPassword").value.trim(),
    course: document.getElementById("profCourse").value.trim(),
    notes: document.getElementById("profNotes").value.trim(),
    active: document.getElementById("profActive").checked
  };

  if (!payload.name || !payload.user_id || !payload.password) {
    alert("Iltimos, ism, login va parolni kiriting!");
    return;
  }

  try {
    let res;
    if (profId) {
      res = await fetch(getApiUrl(`/api/profiles/${profId}`), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
    } else {
      res = await fetch(getApiUrl("/api/profiles"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
    }

    if (!res.ok) {
      alert("Saqlashda xatolik yuz berdi");
    } else {
      closeProfileModal();
      loadProfiles();
    }
  } catch (err) {
    alert("Serverga ulanish xatosi");
  }
}

async function deleteProfile(profId) {
  if (!confirm("Haqiqatan ham ushbu talaba profilini o'chirmoqchimisiz?")) return;
  try {
    const res = await fetch(getApiUrl(`/api/profiles/${profId}`), { method: "DELETE" });
    if (res.ok) {
      loadProfiles();
    }
  } catch (e) {
    alert("O'chirishda xatolik");
  }
}

// ---------------------------------------------------------------------------
// SETTINGS
// ---------------------------------------------------------------------------
async function loadSettings() {
  try {
    const res = await fetch(getApiUrl("/api/settings"));
    if (!res.ok) return;
    const s = await res.json();

    document.getElementById("inputSpeed").value = s.speed || 1.0;
    document.getElementById("valSpeed").innerText = (s.speed || 1.0) + "x";

    document.getElementById("inputDocTime").value = s.doc_time || 25;
    document.getElementById("valDocTime").innerText = (s.doc_time || 25) + " sek";

    document.getElementById("inputInterval").value = s.check_interval || 15;
    document.getElementById("valInterval").innerText = (s.check_interval || 15) + " daqiqa";

    document.getElementById("selectModel").value = s.gemini_model || "gemini-3.8-flash";
    document.getElementById("inputApiKey").value = s.gemini_api_key || "";
    document.getElementById("chkHeadless").checked = s.headless !== false;
    document.getElementById("chkBatchMode").checked = s.batch_mode === true;
    document.getElementById("customTaskInput").value = s.custom_instructions || "";
  } catch (err) {
    console.error("Settings load error:", err);
  }
}

async function saveSystemSettings() {
  const payload = {
    speed: parseFloat(document.getElementById("inputSpeed").value),
    doc_time: parseInt(document.getElementById("inputDocTime").value),
    check_interval: parseInt(document.getElementById("inputInterval").value),
    gemini_model: document.getElementById("selectModel").value,
    gemini_api_key: document.getElementById("inputApiKey").value.trim(),
    headless: document.getElementById("chkHeadless").checked,
    batch_mode: document.getElementById("chkBatchMode").checked,
    custom_instructions: document.getElementById("customTaskInput").value.trim()
  };

  try {
    const res = await fetch(getApiUrl("/api/settings"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    if (res.ok) {
      alert("Sozlamalar muvaffaqiyatli saqlandi!");
    } else {
      alert("Sozlamalarni saqlashda xatolik.");
    }
  } catch (err) {
    alert("Serverga ulanish xatosi.");
  }
}

function toggleApiKeyVisibility() {
  const input = document.getElementById("inputApiKey");
  const icon = document.getElementById("eyeIcon");
  if (input.type === "password") {
    input.type = "text";
    icon.className = "bi bi-eye-slash";
  } else {
    input.type = "password";
    icon.className = "bi bi-eye";
  }
}

// ---------------------------------------------------------------------------
// AI DIRECTIVES
// ---------------------------------------------------------------------------
function setPromptTemplate(text) {
  document.getElementById("customTaskInput").value = text;
}

async function submitCustomTask() {
  const task = document.getElementById("customTaskInput").value.trim();
  if (!task) {
    alert("Iltimos, buyruq matnini kiriting!");
    return;
  }

  try {
    const res = await fetch(getApiUrl("/api/custom-task"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task })
    });
    if (res.ok) {
      alert("Yangi AI buyruq agentga muvaffaqiyatli yuklandi!");
    }
  } catch (err) {
    alert("Buyruqni yuborishda xatolik.");
  }
}

function pad(num) {
  return num < 10 ? "0" + num : num;
}

function escapeHtml(str) {
  if (!str) return "";
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
