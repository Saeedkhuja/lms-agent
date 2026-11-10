// e-JDU LMS — Autonomous AI Multi-Student Platform Controller
// Color Theme: #02070A (Dark), #0297DE (Cyan), #FC734D (Coral)

// State
let currentView = 'admin'; // 'admin' | 'cabin'
let currentCabinStudentId = null;
let currentProfiles = [];
let lastLogId = 0;
let cabinLastLogId = 0;
let allLogs = [];
let cabinLogs = [];
let activeLogFilter = 'ALL';
let pollingTimer = null;
let historyLastCount = -1;

// ---------------------------------------------------------------------------
// INITIALIZATION & ROUTING
// ---------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
  handleHashRoute();
  window.addEventListener("hashchange", handleHashRoute);

  loadProfiles().then(() => {
    if (!currentCabinStudentId && currentProfiles.length > 0) {
      currentCabinStudentId = currentProfiles[0].id;
    }
    loadSettings();
    startPolling();
  });
});

function handleHashRoute() {
  const hash = window.location.hash;
  if (hash.startsWith("#/cabin/") || hash.startsWith("#/student/")) {
    const parts = hash.split("/");
    const studentId = parts[2];
    switchMainView('cabin', studentId);
  } else {
    switchMainView('admin');
  }
}

function switchMainView(viewName, studentId = null) {
  currentView = viewName;
  const viewAdmin = document.getElementById("viewAdmin");
  const viewCabin = document.getElementById("viewStudentCabin");
  const navBtnAdmin = document.getElementById("navBtnAdmin");
  const navBtnCabin = document.getElementById("navBtnCabin");

  if (viewName === 'admin') {
    if (viewAdmin) viewAdmin.classList.remove("hidden");
    if (viewCabin) viewCabin.classList.add("hidden");
    if (navBtnAdmin) {
      navBtnAdmin.className = "px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all bg-[#0297DE] text-white shadow-md";
    }
    if (navBtnCabin) {
      navBtnCabin.className = "px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all text-[#8FAEC0] hover:text-white";
    }
    if (window.location.hash !== "#/admin") {
      history.replaceState(null, null, "#/admin");
    }
  } else {
    if (viewAdmin) viewAdmin.classList.add("hidden");
    if (viewCabin) viewCabin.classList.remove("hidden");
    if (navBtnAdmin) {
      navBtnAdmin.className = "px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all text-[#8FAEC0] hover:text-white";
    }
    if (navBtnCabin) {
      navBtnCabin.className = "px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all bg-[#0297DE] text-white shadow-md";
    }

    const targetId = studentId || currentCabinStudentId || (currentProfiles[0] ? currentProfiles[0].id : null);
    if (targetId) {
      selectCabinStudent(targetId);
      if (window.location.hash !== `#/cabin/${targetId}`) {
        history.replaceState(null, null, `#/cabin/${targetId}`);
      }
    }
  }
}

function openStudentCabin(studentId) {
  const targetId = studentId || currentCabinStudentId || (currentProfiles[0] ? currentProfiles[0].id : null);
  switchMainView('cabin', targetId);
}

// ---------------------------------------------------------------------------
// POLLING CONTROLLER
// ---------------------------------------------------------------------------
function startPolling() {
  if (pollingTimer) clearInterval(pollingTimer);
  pollOnce();
  pollingTimer = setInterval(pollOnce, 2000);
}

function pollOnce() {
  updateAdminStatus();
  updateAdminLogs();
  if (currentView === 'cabin' && currentCabinStudentId) {
    updateCabinData();
  }
}

// ---------------------------------------------------------------------------
// ADMIN VIEW: STATUS & KPI
// ---------------------------------------------------------------------------
async function updateAdminStatus() {
  try {
    const res = await fetch("/api/status");
    if (!res.ok) return;
    const data = await res.json();

    const state = data.state || "STOPPED";
    const isRunning = data.is_running;

    // Platform status badge in navbar
    const statusDot = document.getElementById("platformStatusDot");
    const statusText = document.getElementById("platformStatusText");
    const statusBadge = document.getElementById("platformStatusBadge");
    const btnGlobalStart = document.getElementById("btnGlobalStart");
    const btnGlobalStop = document.getElementById("btnGlobalStop");

    if (statusText) statusText.innerText = state;

    if (isRunning) {
      if (statusDot) statusDot.className = "w-2.5 h-2.5 rounded-full bg-[#05D686] animate-pulse";
      if (statusBadge) statusBadge.className = "badge-green flex items-center space-x-2 py-1 px-3.5 shadow-md";
      if (btnGlobalStart) {
        btnGlobalStart.disabled = true;
        btnGlobalStart.classList.add("opacity-50", "cursor-not-allowed");
      }
      if (btnGlobalStop) {
        btnGlobalStop.disabled = false;
        btnGlobalStop.classList.remove("opacity-50", "cursor-not-allowed");
      }
    } else if (state === "STANDBY") {
      if (statusDot) statusDot.className = "w-2.5 h-2.5 rounded-full bg-[#FC734D]";
      if (statusBadge) statusBadge.className = "badge-coral flex items-center space-x-2 py-1 px-3.5 shadow-md";
      if (btnGlobalStart) {
        btnGlobalStart.disabled = false;
        btnGlobalStart.classList.remove("opacity-50", "cursor-not-allowed");
      }
      if (btnGlobalStop) {
        btnGlobalStop.disabled = true;
        btnGlobalStop.classList.add("opacity-50", "cursor-not-allowed");
      }
    } else {
      if (statusDot) statusDot.className = "w-2.5 h-2.5 rounded-full bg-[#0297DE]";
      if (statusBadge) statusBadge.className = "badge-cyan flex items-center space-x-2 py-1 px-3.5 shadow-md";
      if (btnGlobalStart) {
        btnGlobalStart.disabled = false;
        btnGlobalStart.classList.remove("opacity-50", "cursor-not-allowed");
      }
      if (btnGlobalStop) {
        btnGlobalStop.disabled = true;
        btnGlobalStop.classList.add("opacity-50", "cursor-not-allowed");
      }
    }

    // Admin KPI Cards
    safeSetText("statTotalStudents", currentProfiles.length);
    safeSetText("statActiveAgents", isRunning ? state : "STANDBY");

    const activeProfile = data.active_profile;
    safeSetText("statActiveStudentName", activeProfile ? `${activeProfile.name} (${activeProfile.user_id})` : "Kutish rejimida");
    safeSetText("statAdminCompleted", data.total_completed || 0);
    safeSetText("statCurrentLessonAdmin", data.current_lesson || "Kutilmoqda...");
    safeSetText("statCurrentChapterAdmin", data.current_chapter || "-");

  } catch (err) {
    console.error("Admin status poll error:", err);
  }
}

// ---------------------------------------------------------------------------
// ADMIN VIEW: LOGS & FILTERING
// ---------------------------------------------------------------------------
async function updateAdminLogs() {
  try {
    const res = await fetch(`/api/logs?since_id=${lastLogId}`);
    if (!res.ok) return;
    const data = await res.json();
    const newLogs = data.logs || [];
    if (newLogs.length === 0) return;

    newLogs.forEach(l => {
      lastLogId = Math.max(lastLogId, l.id);
      allLogs.push(l);
    });

    renderAdminLogs();
  } catch (err) {
    console.error("Admin logs error:", err);
  }
}

function setLogFilter(filterName) {
  activeLogFilter = filterName;

  const filters = ['ALL', 'AI', 'INFO', 'WARN', 'ERROR'];
  filters.forEach(f => {
    const btn = document.getElementById(`filterBtn${f}`);
    if (!btn) return;
    if (f === filterName) {
      btn.className = "flex-1 py-1 rounded-lg text-center font-medium bg-[#0297DE] text-white shadow";
    } else {
      btn.className = "flex-1 py-1 rounded-lg text-center font-medium text-[#8FAEC0] hover:text-white";
    }
  });

  renderAdminLogs();
}

function renderAdminLogs() {
  const consoleEl = document.getElementById("logConsole");
  if (!consoleEl) return;

  const filtered = allLogs.filter(l => {
    if (activeLogFilter === 'ALL') return true;
    if (activeLogFilter === 'AI') {
      const msg = l.message.toLowerCase();
      return msg.includes('ai') || msg.includes('gemini') || msg.includes('savol') || msg.includes('javob') || msg.includes('test') || msg.includes('tahlil') || msg.includes('fikrlash');
    }
    return l.level === activeLogFilter;
  });

  consoleEl.innerHTML = "";
  if (filtered.length === 0) {
    consoleEl.innerHTML = `<div class="text-[#4A697D]">Ushbu filtr bo'yicha hozircha loglar yo'q.</div>`;
    return;
  }

  filtered.forEach(l => {
    const row = document.createElement("div");
    row.className = "flex items-start space-x-2 text-xs leading-relaxed border-b border-white/[0.03] pb-1";

    let levelBadge = "log-info";
    if (l.level === "WARN") levelBadge = "log-warn";
    else if (l.level === "ERROR") levelBadge = "log-error";
    else if (l.message.includes("AI") || l.message.includes("Gemini") || l.message.includes("Savol")) levelBadge = "log-ai";

    row.innerHTML = `
      <span class="text-[#4A697D] font-mono text-[11px] shrink-0 select-none">[${escapeHtml(l.timestamp)}]</span>
      <span class="${levelBadge} font-mono text-[10px] uppercase font-bold shrink-0">[${escapeHtml(l.level)}]</span>
      <span class="text-[#cce4f2] break-words flex-1">${escapeHtml(l.message)}</span>
    `;
    consoleEl.appendChild(row);
  });

  const chkScroll = document.getElementById("chkAutoScroll");
  if (chkScroll && chkScroll.checked) {
    consoleEl.scrollTop = consoleEl.scrollHeight;
  }
}

function clearLogs() {
  allLogs = [];
  lastLogId = 0;
  const consoleEl = document.getElementById("logConsole");
  if (consoleEl) {
    consoleEl.innerHTML = `<div class="text-[#4A697D]">Loglar tozalandi. Yangi xabarlar kutilmoqda...</div>`;
  }
}

// ---------------------------------------------------------------------------
// ADMIN VIEW: STUDENTS LIST (PROFILES)
// ---------------------------------------------------------------------------
async function loadProfiles() {
  try {
    const res = await fetch("/api/profiles");
    if (!res.ok) return;
    const data = await res.json();
    currentProfiles = data.profiles || [];

    renderAdminStudents();
    populateCabinStudentSelect();

    safeSetText("statTotalStudents", currentProfiles.length);
    safeSetText("badgeStudentCount", `${currentProfiles.length} ta`);
  } catch (err) {
    console.error("Load profiles error:", err);
  }
}

function renderAdminStudents() {
  const fullContainer = document.getElementById("fullStudentsList");
  if (!fullContainer) return;

  // 1. Calculate aggregate stats across all students for Overview Tab
  const totalCompleted = currentProfiles.reduce((acc, p) => acc + (p.completed_count || 199), 0);
  safeSetText("statTotalStudents", currentProfiles.length);
  safeSetText("statTotalCompleted", totalCompleted);
  safeSetText("badgeStudentCount", `${currentProfiles.length} ta`);

  if (currentProfiles.length === 0) {
    fullContainer.innerHTML = `
      <div class="panel p-8 text-center text-slate-400 space-y-3">
        <i class="bi bi-people text-4xl text-blue-400"></i>
        <p class="text-sm">Hozircha birorta ham talaba qo'shilmagan.</p>
        <button onclick="openAddProfileModal()" class="text-xs py-2 px-4 rounded-lg bg-blue-600 hover:bg-blue-500 text-white font-medium mx-auto flex items-center space-x-1 shadow">
          <i class="bi bi-plus-lg mr-1"></i> Birinchi talabani qo'shish
        </button>
      </div>
    `;
    return;
  }

  fullContainer.innerHTML = "";
  currentProfiles.forEach(p => {
    const card = document.createElement("div");
    card.className = "card-elevated p-4 sm:p-5 space-y-4 hover:border-blue-500/40 transition-all";

    const initial = (p.name || "U").charAt(0).toUpperCase();
    const completed = p.completed_count || 199;
    const total = 206;
    const pct = Math.min(100, Math.round((completed / total) * 100));

    card.innerHTML = `
      <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div class="flex items-center space-x-3.5">
          <div class="w-12 h-12 rounded-xl bg-gradient-to-tr from-blue-600 to-indigo-600 flex items-center justify-center font-bold text-white text-lg shadow-md border border-white/20 shrink-0">
            ${escapeHtml(initial)}
          </div>
          <div class="min-w-0">
            <div class="flex items-center space-x-2">
              <h3 class="font-bold text-sm text-white truncate">${escapeHtml(p.name)}</h3>
              ${pct === 100 ? 
                '<span class="text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">100% BAJARILGAN</span>' : 
                '<span class="text-[10px] font-bold px-2 py-0.5 rounded-full bg-blue-500/15 text-blue-400 border border-blue-500/30">JARAYONDA</span>'
              }
            </div>
            <div class="text-[11px] text-slate-400 font-mono flex flex-wrap items-center gap-x-2.5 gap-y-1 mt-1">
              <span>Login: <strong class="text-blue-400">${escapeHtml(p.user_id)}</strong></span>
              <span class="text-slate-600">•</span>
              <span class="flex items-center space-x-1">
                <span>Parol:</span>
                <span id="pwd_${p.id}" class="text-slate-300">••••••</span>
                <button type="button" onclick="togglePasswordVisibility('${p.id}', '${escapeHtml(p.password)}')" class="text-slate-500 hover:text-slate-300 text-xs ml-0.5">
                  <i id="eye_${p.id}" class="bi bi-eye"></i>
                </button>
              </span>
              <span class="text-slate-600">•</span>
              <span class="text-slate-300 truncate">${escapeHtml(p.course || "N3 (2026秋セメスター)")}</span>
            </div>
          </div>
        </div>

        <!-- Student Action Buttons -->
        <div class="flex items-center space-x-2 self-end sm:self-auto shrink-0">
          <button onclick="openStudentDetail('${escapeHtml(p.id)}')" class="px-3 py-1.5 rounded-lg bg-blue-600/20 hover:bg-blue-600 text-blue-300 hover:text-white text-xs font-semibold border border-blue-500/30 flex items-center space-x-1 transition-all">
            <i class="bi bi-person-badge"></i>
            <span>Barcha Ma'lumotlar</span>
          </button>
          <button onclick="startSingleStudent('${escapeHtml(p.id)}')" title="Agentni ishga tushirish" class="p-2 rounded-lg bg-emerald-600/20 hover:bg-emerald-600 text-emerald-400 hover:text-white text-xs border border-emerald-500/20">
            <i class="bi bi-play-fill text-sm"></i>
          </button>
          <button onclick="editProfile('${escapeHtml(p.id)}')" title="Tahrirlash" class="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white text-xs border border-white/10">
            <i class="bi bi-pencil"></i>
          </button>
          <button onclick="deleteProfile('${escapeHtml(p.id)}')" title="O'chirish" class="p-2 rounded-lg bg-rose-600/20 hover:bg-rose-600 text-rose-400 hover:text-white text-xs border border-rose-500/20">
            <i class="bi bi-trash"></i>
          </button>
        </div>
      </div>

      <!-- Progress Track -->
      <div class="space-y-1.5 pt-2 border-t border-white/[0.04]">
        <div class="flex items-center justify-between text-xs">
          <span class="text-slate-400">Kurs o'zlashtirish progressi:</span>
          <span class="font-bold ${pct === 100 ? 'text-emerald-400' : 'text-blue-400'}">${completed} / ${total} (${pct}%)</span>
        </div>
        <div class="w-full bg-slate-900 rounded-full h-2 overflow-hidden">
          <div class="h-2 rounded-full transition-all duration-500 ${pct === 100 ? 'bg-gradient-to-r from-emerald-500 to-teal-400' : 'bg-gradient-to-r from-blue-500 to-cyan-400'}" style="width: ${pct}%"></div>
        </div>
      </div>
    `;
    fullContainer.appendChild(card);
  });
}

// ---------------------------------------------------------------------------
// DEDICATED STUDENT DETAIL MODAL (PAGE) CONTROLLER
// ---------------------------------------------------------------------------
let currentDetailStudentId = null;
let currentDetailPasswordVisible = false;

async function openStudentDetail(profId) {
  const p = currentProfiles.find(x => x.id === profId);
  if (!p) return;

  currentDetailStudentId = profId;
  currentDetailPasswordVisible = false;

  const initial = (p.name || "U").charAt(0).toUpperCase();
  safeSetText("detailAvatar", initial);
  safeSetText("detailName", p.name || "Talaba");
  safeSetText("detailCourse", p.course || "N3 (2026秋セメスター)");
  safeSetText("detailUserId", p.user_id || "");
  safeSetText("detailPasswordMasked", "••••••");

  const eye = document.getElementById("detailEyeIcon");
  if (eye) eye.className = "bi bi-eye";

  const total = 206;
  const completed = p.completed_count || 199;
  const pct = Math.min(100, Math.round((completed / total) * 100));

  safeSetText("detailProgressPct", `${pct}%`);
  safeSetText("detailProgressRatio", `${completed} / ${total} dars`);
  const bar = document.getElementById("detailProgressBar");
  if (bar) bar.style.width = `${pct}%`;

  safeSetText("detailProgressStatus", pct === 100 ? "Barcha dars va testlar topshirilgan" : "O'zlashtirish jarayonida");

  // Load history list
  const listEl = document.getElementById("detailHistoryList");
  if (listEl) {
    listEl.innerHTML = '<div class="text-slate-500 text-center py-4">Tarix yuklanmoqda...</div>';
  }

  const modal = document.getElementById("studentDetailModal");
  if (modal) modal.classList.remove("hidden");

  try {
    const res = await fetch(`/api/students/${p.id}/history`);
    if (res.ok) {
      const data = await res.json();
      const history = data.history || [];
      safeSetText("detailHistoryCount", `${history.length} ta topshirilgan`);
      if (listEl) {
        if (history.length === 0) {
          listEl.innerHTML = '<div class="text-slate-500 text-center py-4">Hozircha topshirilgan vazifalar yo\'q.</div>';
        } else {
          listEl.innerHTML = history.map((item, i) => `
            <div class="flex items-center justify-between p-2 rounded-lg bg-slate-900/60 border border-white/[0.04] text-[11px]">
              <span class="text-slate-300 truncate max-w-[80%]">✅ ${escapeHtml(item)}</span>
              <span class="text-emerald-400 font-mono text-[10px]">#${i + 1}</span>
            </div>
          `).join("");
        }
      }
    }
  } catch (e) {
    if (listEl) listEl.innerHTML = '<div class="text-rose-400 text-center py-2">Tarixni yuklashda xatolik yuz berdi.</div>';
  }
}

function closeStudentDetailModal() {
  const modal = document.getElementById("studentDetailModal");
  if (modal) modal.classList.add("hidden");
}

function toggleDetailPasswordVisibility() {
  if (!currentDetailStudentId) return;
  const p = currentProfiles.find(x => x.id === currentDetailStudentId);
  if (!p) return;

  const span = document.getElementById("detailPasswordMasked");
  const eye = document.getElementById("detailEyeIcon");
  currentDetailPasswordVisible = !currentDetailPasswordVisible;

  if (currentDetailPasswordVisible) {
    if (span) span.innerText = p.password;
    if (eye) eye.className = "bi bi-eye-slash text-blue-400";
  } else {
    if (span) span.innerText = "••••••";
    if (eye) eye.className = "bi bi-eye";
  }
}

function copyDetailUserId() {
  if (!currentDetailStudentId) return;
  const p = currentProfiles.find(x => x.id === currentDetailStudentId);
  if (p && p.user_id) {
    navigator.clipboard.writeText(p.user_id);
    alert(`Login nusxalandi: ${p.user_id}`);
  }
}

function copyDetailPassword() {
  if (!currentDetailStudentId) return;
  const p = currentProfiles.find(x => x.id === currentDetailStudentId);
  if (p && p.password) {
    navigator.clipboard.writeText(p.password);
    alert("Parol nusxalandi!");
  }
}

function startCurrentDetailStudent() {
  if (currentDetailStudentId) {
    startSingleStudent(currentDetailStudentId);
  }
}

function stopCurrentDetailStudent() {
  if (currentDetailStudentId) {
    stopGlobalAgent();
  }
}

function editCurrentDetailStudent() {
  if (currentDetailStudentId) {
    closeStudentDetailModal();
    editProfile(currentDetailStudentId);
  }
}

function deleteCurrentDetailStudent() {
  if (currentDetailStudentId) {
    closeStudentDetailModal();
    deleteProfile(currentDetailStudentId);
  }
}

function togglePasswordVisibility(profId, actualPwd) {
  const span = document.getElementById(`pwd_${profId}`);
  const eye = document.getElementById(`eye_${profId}`);
  if (!span) return;
  if (span.innerText === "••••••") {
    span.innerText = actualPwd;
    if (eye) eye.className = "bi bi-eye-slash text-blue-400";
  } else {
    span.innerText = "••••••";
    if (eye) eye.className = "bi bi-eye";
  }
}

function populateCabinStudentSelect() {
  const select = document.getElementById("cabinStudentSelect");
  if (!select) return;

  select.innerHTML = "";
  currentProfiles.forEach(p => {
    const opt = document.createElement("option");
    opt.value = p.id;
    opt.innerText = `${p.name} (${p.user_id})`;
    if (p.id === currentCabinStudentId) {
      opt.selected = true;
    }
    select.appendChild(opt);
  });
}

function selectCabinStudent(studentId) {
  currentCabinStudentId = studentId;
  const select = document.getElementById("cabinStudentSelect");
  if (select) select.value = studentId;
  cabinLastLogId = 0;
  cabinLogs = [];
  historyLastCount = -1;
  updateCabinData();
}

// ---------------------------------------------------------------------------
// STUDENT INDIVIDUAL CABIN LOGIC
// ---------------------------------------------------------------------------
async function updateCabinData() {
  if (!currentCabinStudentId) return;

  // 1. Fetch Student Status & Telemetry
  try {
    const res = await fetch(`/api/students/${currentCabinStudentId}/status`);
    if (res.ok) {
      const data = await res.json();
      renderCabinStatus(data);
    }
  } catch (err) {
    console.error("Cabin status fetch error:", err);
  }

  // 2. Fetch Student Specific Logs
  try {
    const resLogs = await fetch(`/api/students/${currentCabinStudentId}/logs?since_id=${cabinLastLogId}`);
    if (resLogs.ok) {
      const logData = await resLogs.json();
      const newCabinLogs = logData.logs || [];
      if (newCabinLogs.length > 0) {
        newCabinLogs.forEach(l => {
          cabinLastLogId = Math.max(cabinLastLogId, l.id);
          cabinLogs.push(l);
        });
        renderCabinLogs();
      }
    }
  } catch (err) {
    console.error("Cabin logs fetch error:", err);
  }

  // 3. Fetch Completed Lessons History
  try {
    const resHist = await fetch(`/api/students/${currentCabinStudentId}/history`);
    if (resHist.ok) {
      const histData = await resHist.json();
      if (histData.total_completed !== historyLastCount) {
        historyLastCount = histData.total_completed;
        renderCabinHistory(histData);
      }
    }
  } catch (err) {
    console.error("Cabin history fetch error:", err);
  }
}

function renderCabinStatus(data) {
  const p = data.profile || {};
  const isRunning = data.is_running;
  const state = data.agent_state || "STOPPED";

  // Avatar & Header
  const avatarEl = document.getElementById("cabinStudentAvatar");
  if (avatarEl) avatarEl.innerText = (p.name || "U").charAt(0).toUpperCase();

  safeSetText("cabinStudentName", p.name || "-");
  safeSetText("cabinStudentUserId", p.user_id || "-");
  safeSetText("cabinStudentCourse", p.course || "N3 (2026秋セメスター)");

  const badgeEl = document.getElementById("cabinStatusBadge");
  if (badgeEl) {
    badgeEl.innerText = isRunning ? state : (data.total_completed > 0 ? "STANDBY" : "STANDBY");
    badgeEl.className = isRunning ? "badge-green text-xs" : "badge-cyan text-xs";
  }

  // Action Buttons
  const btnStart = document.getElementById("btnCabinStart");
  const btnStop = document.getElementById("btnCabinStop");

  if (isRunning) {
    if (btnStart) {
      btnStart.disabled = true;
      btnStart.classList.add("opacity-50", "cursor-not-allowed");
    }
    if (btnStop) {
      btnStop.disabled = false;
      btnStop.classList.remove("opacity-50", "cursor-not-allowed");
    }
  } else {
    if (btnStart) {
      btnStart.disabled = false;
      btnStart.classList.remove("opacity-50", "cursor-not-allowed");
    }
    if (btnStop) {
      btnStop.disabled = true;
      btnStop.classList.add("opacity-50", "cursor-not-allowed");
    }
  }

  // Telemetry Cards
  safeSetText("cabinCurrentLesson", data.current_lesson || "Kutilmoqda...");
  safeSetText("cabinCurrentChapter", data.current_chapter || "-");
  safeSetText("cabinCompletedCount", data.total_completed || 0);
  safeSetText("cabinTotalUnits", `${data.total_units || 0} ta`);

  const pct = data.current_progress_pct || 0;
  safeSetText("cabinProgressPct", `${pct}%`);

  const pBar = document.getElementById("cabinProgressBar");
  if (pBar) pBar.style.width = `${pct}%`;

  safeSetText("cabinCurrentActivity", data.current_activity || "Kutish holatida");
  safeSetText("cabinLastMinute", data.last_minute || "-");
  safeSetText("cabinLastUpdated", data.last_updated || "Bir necha soniya oldin");
}

function renderCabinLogs() {
  const consoleEl = document.getElementById("cabinLogConsole");
  if (!consoleEl) return;

  if (cabinLogs.length === 0) {
    consoleEl.innerHTML = `<div class="text-[#4A697D]">Ushbu talaba uchun yangi loglar kutilmoqda...</div>`;
    return;
  }

  consoleEl.innerHTML = "";
  cabinLogs.forEach(l => {
    const row = document.createElement("div");
    row.className = "flex items-start space-x-2 text-xs leading-relaxed border-b border-white/[0.03] pb-1";

    let levelBadge = "log-info";
    if (l.level === "WARN") levelBadge = "log-warn";
    else if (l.level === "ERROR") levelBadge = "log-error";
    else if (l.message.includes("AI") || l.message.includes("Gemini") || l.message.includes("Savol")) levelBadge = "log-ai";

    row.innerHTML = `
      <span class="text-[#4A697D] font-mono text-[11px] shrink-0 select-none">[${escapeHtml(l.timestamp)}]</span>
      <span class="${levelBadge} font-mono text-[10px] uppercase font-bold shrink-0">[${escapeHtml(l.level)}]</span>
      <span class="text-[#cce4f2] break-words flex-1">${escapeHtml(l.message)}</span>
    `;
    consoleEl.appendChild(row);
  });

  consoleEl.scrollTop = consoleEl.scrollHeight;
}

function renderCabinHistory(histData) {
  const container = document.getElementById("cabinHistoryList");
  const badge = document.getElementById("cabinHistoryBadge");
  if (!container) return;

  const items = histData.history || [];
  if (badge) badge.innerText = `${items.length} ta`;

  if (items.length === 0) {
    container.innerHTML = `<div class="text-xs text-[#8FAEC0] text-center p-6">Bajarilgan darslar topilmadi.</div>`;
    return;
  }

  container.innerHTML = "";
  items.forEach((item, idx) => {
    const row = document.createElement("div");
    row.className = "bg-[#030a0f] p-3 rounded-xl border border-[rgba(2,151,222,0.15)] flex items-center justify-between text-xs hover:border-[#0297DE]/40 transition";

    const rawName = typeof item === 'string' ? item : (item.name || `Dars #${idx + 1}`);
    let displayChapter = "";
    let displayTitle = rawName;
    if (rawName.includes("::")) {
      const parts = rawName.split("::");
      displayChapter = parts[0].trim();
      displayTitle = parts.slice(1).join("::").trim();
    }

    let typeIcon = "bi-journal-check text-[#05D686]";
    let typeBadge = "badge-green";
    const nameLower = displayTitle.toLowerCase();
    if (nameLower.includes("test") || nameLower.includes("quiz") || (typeof item === 'object' && item.score !== undefined)) {
      typeIcon = "bi-patch-question-fill text-[#FC734D]";
      typeBadge = "badge-coral";
    } else if (nameLower.includes("video") || nameLower.includes("suhbat") || nameLower.includes("会話")) {
      typeIcon = "bi-play-circle-fill text-[#0297DE]";
      typeBadge = "badge-cyan";
    }

    row.innerHTML = `
      <div class="flex items-center space-x-2.5 min-w-0">
        <i class="bi ${typeIcon} text-base shrink-0"></i>
        <div class="min-w-0">
          <div class="font-semibold text-white truncate">${escapeHtml(displayTitle)}</div>
          <div class="text-[10px] text-[#8FAEC0] font-mono mt-0.5 truncate">
            ${displayChapter ? `<span class="text-[#0297DE] font-semibold">${escapeHtml(displayChapter)}</span> • ` : ''}
            ${escapeHtml((typeof item === 'object' && item.timestamp) ? item.timestamp : 'Bajarilgan')}
          </div>
        </div>
      </div>
      <div class="shrink-0 text-right ml-2">
        <span class="${typeBadge} text-[9px] py-0.5 px-2">
          ${(typeof item === 'object' && item.score) ? escapeHtml(item.score) : 'YAKUNLANDI'}
        </span>
      </div>
    `;
    container.appendChild(row);
  });
}

// ---------------------------------------------------------------------------
// AGENT START / STOP ACTIONS
// ---------------------------------------------------------------------------
async function startGlobalAgent() {
  try {
    const res = await fetch("/api/agent/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({})
    });
    const data = await res.json();
    if (!res.ok) {
      alert("Xatolik: " + (data.detail || "Agentni ishga tushirib bo'lmadi"));
    } else {
      updateAdminStatus();
    }
  } catch (err) {
    alert("Serverga ulanishda xatolik yuz berdi.");
  }
}

async function stopGlobalAgent() {
  try {
    await fetch("/api/agent/stop", { method: "POST" });
    updateAdminStatus();
  } catch (err) {
    alert("To'xtatish so'rovida xatolik yuz berdi.");
  }
}

async function startCabinStudent() {
  if (!currentCabinStudentId) return;
  try {
    const res = await fetch(`/api/students/${currentCabinStudentId}/start`, { method: "POST" });
    const data = await res.json();
    if (!res.ok) {
      alert("Xatolik: " + (data.detail || "Talaba uchun agentni boshlab bo'lmadi"));
    } else {
      updateCabinData();
      updateAdminStatus();
    }
  } catch (err) {
    alert("Serverga ulanish xatosi.");
  }
}

async function stopCabinStudent() {
  if (!currentCabinStudentId) return;
  try {
    await fetch(`/api/students/${currentCabinStudentId}/stop`, { method: "POST" });
    updateCabinData();
    updateAdminStatus();
  } catch (err) {
    alert("To'xtatishda xatolik.");
  }
}

async function startSingleStudent(profId) {
  try {
    const res = await fetch(`/api/students/${profId}/start`, { method: "POST" });
    const data = await res.json();
    if (!res.ok) {
      alert("Xatolik: " + (data.detail || "Talaba uchun agentni boshlab bo'lmadi"));
    } else {
      updateAdminStatus();
      openStudentCabin(profId);
    }
  } catch (err) {
    alert("Serverga ulanish xatosi.");
  }
}

// ---------------------------------------------------------------------------
// PROFILE MODAL (ADD / EDIT / DELETE)
// ---------------------------------------------------------------------------
function openAddProfileModal() {
  document.getElementById("modalTitle").innerHTML = '<i class="bi bi-person-plus mr-2 text-[#0297DE]"></i> Yangi Talaba Qo\'shish';
  document.getElementById("editProfileId").value = "";
  document.getElementById("profName").value = "";
  document.getElementById("profUserId").value = "";
  document.getElementById("profPassword").value = "";
  document.getElementById("profCourse").value = "N3 (2026秋セメスター)";
  document.getElementById("profNotes").value = "";
  document.getElementById("profActive").checked = true;

  const modal = document.getElementById("profileModal");
  if (modal) modal.classList.remove("hidden");
}

function editProfile(profId) {
  const p = currentProfiles.find(x => x.id === profId);
  if (!p) return;

  document.getElementById("modalTitle").innerHTML = '<i class="bi bi-pencil mr-2 text-[#0297DE]"></i> Profilni Tahrirlash';
  document.getElementById("editProfileId").value = p.id;
  document.getElementById("profName").value = p.name;
  document.getElementById("profUserId").value = p.user_id;
  document.getElementById("profPassword").value = p.password;
  document.getElementById("profCourse").value = p.course || "N3 (2026秋セメスター)";
  document.getElementById("profNotes").value = p.notes || "";
  document.getElementById("profActive").checked = p.active !== false;

  const modal = document.getElementById("profileModal");
  if (modal) modal.classList.remove("hidden");
}

function closeProfileModal() {
  const modal = document.getElementById("profileModal");
  if (modal) modal.classList.add("hidden");
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
      res = await fetch(`/api/profiles/${profId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
    } else {
      res = await fetch("/api/profiles", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
    }

    if (!res.ok) {
      alert("Saqlashda xatolik yuz berdi");
    } else {
      closeProfileModal();
      await loadProfiles();
    }
  } catch (err) {
    alert("Serverga ulanish xatosi");
  }
}

async function deleteProfile(profId) {
  if (!confirm("Haqiqatan ham ushbu talaba profilini o'chirmoqchimisiz?")) return;
  try {
    const res = await fetch(`/api/profiles/${profId}`, { method: "DELETE" });
    if (res.ok) {
      if (currentCabinStudentId === profId) {
        currentCabinStudentId = null;
      }
      await loadProfiles();
    }
  } catch (e) {
    alert("O'chirishda xatolik");
  }
}

// ---------------------------------------------------------------------------
// SETTINGS MODAL
// ---------------------------------------------------------------------------
function openSettingsModal() {
  const modal = document.getElementById("settingsModal");
  if (modal) modal.classList.remove("hidden");
}

function closeSettingsModal() {
  const modal = document.getElementById("settingsModal");
  if (modal) modal.classList.add("hidden");
}

async function loadSettings() {
  try {
    const res = await fetch("/api/settings");
    if (!res.ok) return;
    const s = await res.json();

    const speedEl = document.getElementById("inputSpeed");
    if (speedEl) {
      speedEl.value = s.speed || 2.0;
      safeSetText("valSpeed", `${s.speed || 2.0}x`);
    }

    const docEl = document.getElementById("inputDocTime");
    if (docEl) {
      docEl.value = s.doc_time || 5;
      safeSetText("valDocTime", `${s.doc_time || 5} sek`);
    }

    const modelEl = document.getElementById("selectModel");
    if (modelEl) modelEl.value = s.gemini_model || "gemini-3.5-flash-lite";

    const apiKeyEl = document.getElementById("inputApiKey");
    if (apiKeyEl) apiKeyEl.value = s.gemini_api_key || "";

    const headEl = document.getElementById("chkHeadless");
    if (headEl) headEl.checked = s.headless !== false;

    const batchEl = document.getElementById("chkBatchMode");
    if (batchEl) batchEl.checked = s.batch_mode === true;

  } catch (err) {
    console.error("Settings load error:", err);
  }
}

async function saveSystemSettings() {
  const speedEl = document.getElementById("inputSpeed");
  const docEl = document.getElementById("inputDocTime");
  const modelEl = document.getElementById("selectModel");
  const apiKeyEl = document.getElementById("inputApiKey");
  const headEl = document.getElementById("chkHeadless");
  const batchEl = document.getElementById("chkBatchMode");

  const payload = {
    speed: speedEl ? parseFloat(speedEl.value) : 2.0,
    doc_time: docEl ? parseInt(docEl.value) : 5,
    check_interval: 15,
    gemini_model: modelEl ? modelEl.value : "gemini-3.5-flash-lite",
    gemini_api_key: apiKeyEl ? apiKeyEl.value.trim() : "",
    headless: headEl ? headEl.checked : true,
    batch_mode: batchEl ? batchEl.checked : false,
    custom_instructions: ""
  };

  try {
    const res = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    if (res.ok) {
      closeSettingsModal();
      alert("Sozlamalar muvaffaqiyatli saqlandi!");
      loadSettings();
    } else {
      const errData = await res.json().catch(() => ({}));
      alert(`Sozlamalarni saqlashda xatolik: ${errData.detail || "Noma'lum xatolik"}`);
    }
  } catch (err) {
    alert("Serverga ulanish xatosi: " + err.message);
  }
}

window.saveSettings = saveSystemSettings;
window.saveSystemSettings = saveSystemSettings;

function toggleApiKeyVisibility() {
  const input = document.getElementById("inputApiKey");
  const icon = document.getElementById("eyeIcon");
  if (!input) return;
  if (input.type === "password") {
    input.type = "text";
    if (icon) icon.className = "bi bi-eye-slash";
  } else {
    input.type = "password";
    if (icon) icon.className = "bi bi-eye";
  }
}

// ---------------------------------------------------------------------------
// GITHUB ACTIONS MODAL
// ---------------------------------------------------------------------------
function openGithubModal() {
  const modal = document.getElementById("githubModal");
  if (modal) modal.classList.remove("hidden");
}

function closeGithubModal() {
  const modal = document.getElementById("githubModal");
  if (modal) modal.classList.add("hidden");
}

// ---------------------------------------------------------------------------
// SUPERSONIC ENGINE ACTIONS
// ---------------------------------------------------------------------------
async function triggerEngineLessons() {
  if (!confirm("Barcha qolib ketgan video va o'qish darslarini bir necha soniyada topshirishni xohlaysizmi?")) return;
  try {
    const res = await fetch("/api/engine/run-lessons", { method: "POST" });
    if (res.ok) {
      alert("⚡ Tezkor darslar dvigateli ishga tushirildi! Loglarni kuzatib boring.");
    } else {
      alert("Xatolik yuz berdi.");
    }
  } catch (err) {
    alert("Serverga ulanishda xatolik.");
  }
}

async function triggerEngineTests() {
  if (!confirm("Barcha testlarni AI (Gemini) va SQLite keshi orqali topshirishni boshlaysizmi?")) return;
  try {
    const res = await fetch("/api/engine/run-tests", { method: "POST" });
    if (res.ok) {
      alert("📝 AI Test Solver ishga tushirildi! Konsolda savollarni ko'rishingiz mumkin.");
    } else {
      alert("Xatolik yuz berdi.");
    }
  } catch (err) {
    alert("Serverga ulanishda xatolik.");
  }
}

async function openScreenshotModal() {
  const modal = document.getElementById("screenshotModal");
  const img = document.getElementById("lmsScreenshotImg");
  const loading = document.getElementById("screenshotLoading");
  if (modal) modal.classList.remove("hidden");
  if (loading) loading.classList.remove("hidden");
  if (img) img.classList.add("hidden");

  try {
    const res = await fetch("/api/screenshot");
    const data = await res.json();
    if (data.screenshot && img) {
      img.src = `data:image/png;base64,${data.screenshot}`;
      img.classList.remove("hidden");
    } else {
      if (img) {
        img.src = `/static/final_proof.png?t=${Date.now()}`;
        img.classList.remove("hidden");
      }
    }
  } catch (err) {
    console.error("Screenshot error:", err);
  } finally {
    if (loading) loading.classList.add("hidden");
  }
}

function closeScreenshotModal() {
  const modal = document.getElementById("screenshotModal");
  if (modal) modal.classList.add("hidden");
}

// ---------------------------------------------------------------------------
// UTILITIES
// ---------------------------------------------------------------------------
function safeSetText(id, text) {
  const el = document.getElementById(id);
  if (el) el.innerText = text !== undefined && text !== null ? text : "";
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

