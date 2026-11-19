const $ = s => document.querySelector(s);
let SESSION = "";
let SUBS = [];
let EDIT_ID = null;
let PROFILE_ID = null;

function toast(msg, kind) {
  const t = document.createElement("div");
  t.className = "toast " + (kind || "");
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 3500);
}

async function api(url, body) {
  const opts = { headers: {"Content-Type": "application/json", "X-Admin-Session": SESSION} };
  if (body !== undefined) { opts.method = "POST"; opts.body = JSON.stringify(body); }
  const res = await fetch(url, opts);
  return res.json();
}

// ─── Admin login ───
$("#admin-login-btn").onclick = async () => {
  const pw = $("#admin-pw").value.trim();
  if (!pw) return;
  const d = await api("/admin/api/login", {password: pw});
  if (d.ok) {
    if (d.is_subscriber || (d.redirect && d.redirect !== "/admin")) {
      $("#admin-msg").textContent = "✔ مرحباً بك " + (d.name || "") + "! جاري نقلك إلى لوحة حسابك...";
      $("#admin-msg").style.color = "#22c55e";
      setTimeout(() => { window.location.href = d.redirect || "/"; }, 500);
      return;
    }
    SESSION = d.session;
    $("#login-overlay").hidden = true;
    $("#main-ui").hidden = false;
    $("#admin-pw-badge").textContent = "Admin Mode";
    loadAll();
  } else {
    $("#admin-msg").textContent = "❌ كلمة المرور أو التوكن غير صحيح (Wrong password / Invalid token)";
    $("#admin-msg").style.color = "#ef4444";
  }
};
$("#admin-pw").onkeydown = e => { if (e.key === "Enter") $("#admin-login-btn").click(); };

// ─── Load data ───
async function loadAll() {
  try {
    const [d, cfg] = await Promise.all([
      api("/admin/api/subscribers"),
      api("/admin/api/config/credentials")
    ]);
    SUBS = d.subscribers || [];
    renderStats();
    renderList();
    if (cfg && cfg.ok) {
      if ($("#cfg-admin-token")) $("#cfg-admin-token").value = cfg.admin_token || "";
      if ($("#cfg-admin-password")) $("#cfg-admin-password").value = cfg.admin_password || "";
    }
  } catch (err) {
    console.error("loadAll error:", err);
  }
}

function renderStats() {
  const active = SUBS.filter(s => s.is_active).length;
  const expired = SUBS.filter(s => s.is_expired).length;
  const disabled = SUBS.filter(s => s.manually_disabled).length;
  $("#stats").innerHTML = `
    <div class="stat-card"><div class="label">TOTAL</div><div class="value">${SUBS.length}</div></div>
    <div class="stat-card"><div class="label">ACTIVE</div><div class="value green">${active}</div></div>
    <div class="stat-card"><div class="label">EXPIRED</div><div class="value red">${expired}</div></div>
    <div class="stat-card"><div class="label">DISABLED</div><div class="value amber">${disabled}</div></div>`;
}

function fmtDate(ts) {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleDateString("en-GB", {day:"2-digit",month:"short",year:"numeric"});
}
function fmtAgo(ts) {
  if (!ts) return "never";
  const m = Math.round((Date.now()/1000 - ts) / 60);
  if (m < 60) return m + " min ago";
  if (m < 1440) return Math.round(m/60) + " h ago";
  return Math.round(m/1440) + " d ago";
}

function renderList() {
  if (!SUBS.length) { $("#sub-list").innerHTML = '<div class="empty-state">No subscribers yet — create one above.</div>'; return; }
  $("#sub-list").innerHTML = SUBS.map((s, i) => {
    const st = s.manually_disabled ? "disabled" : s.is_expired ? "expired" : "active";
    const stLabel = s.manually_disabled ? "DISABLED" : s.is_expired ? "EXPIRED" : "ACTIVE";
    const days = s.days_left !== null ? (s.days_left <= 0 ? "0 days" : s.days_left + " d left") : "∞ unlimited";
    const daysCls = s.days_left !== null && s.days_left <= 3 ? (s.days_left <= 0 ? "gone" : "warn") : "";
    const maxAcc = s.max_accounts || 1;
    const curAcc = s.accounts_count !== undefined ? s.accounts_count : 0;
    return `<div class="sub-row">
      <span class="num">#${s.id}</span>
      <div class="name">${esc(s.name)}<small>Created: ${fmtDate(s.created_at)} · Last login: ${fmtAgo(s.last_login)} · Logins: ${s.login_count}</small></div>
      <div class="token-cell" title="Click to copy" data-token="${esc(s.token)}">${s.token.slice(0,8)}…${s.token.slice(-6)}</div>
      <div class="status ${st}">${stLabel}</div>
      <div class="days ${daysCls}">${days}</div>
      <div class="acc-limit-box" title="الحد الأقصى لحسابات المشترك (الحالي / المسموح) — عدّل الرقم واضغط Enter للحفظ" style="display:flex; align-items:center; gap:6px; background:rgba(168,85,247,0.1); border:1px solid rgba(168,85,247,0.3); border-radius:8px; padding:3px 8px;">
        <span style="font-size:12px;">🎮</span>
        <input type="number" min="1" max="99" value="${maxAcc}" data-acc-limit="${s.id}" style="width:38px; padding:2px 4px; border-radius:6px; border:1px solid rgba(255,255,255,0.15); background:#14141d; color:#fff; font-size:12px; font-weight:800; text-align:center;">
        <small style="font-size:10px; color:${curAcc >= maxAcc ? '#ef4444' : '#22c55e'}; font-weight:800;">(${curAcc}/${maxAcc})</small>
      </div>
      <div class="actions">
        <button class="btn btn-green btn-sm" data-viewas="${s.id}" style="font-weight:900; background:linear-gradient(135deg, #22c55e, #16a34a); color:#000; font-size:11px; padding:7px 14px;" title="ادخل حساب المشترك لتصفح ومتابعة وإدارة حسابات اللعبة">👤 ادخل حسابه</button>
        <button class="btn btn-primary btn-sm" data-profile="${s.id}">ℹ DETAILS</button>
        <button class="btn btn-ghost btn-sm" data-tokens="${s.id}" style="border-color:rgba(168,85,247,0.5); color:#c084fc; font-weight:800;" title="عرض سجل توكنات حسابات اللعبة للمشترك لآخر 24 ساعة">📜 سجل التوكنات</button>
        <button class="btn btn-ghost btn-sm" data-edit="${s.id}">✎ EDIT</button>
        <button class="btn btn-ghost btn-sm" data-copy="${s.id}">⧉ TOKEN</button>
        <button class="btn btn-ghost btn-sm" data-reset="${s.id}">🔄 NEW TOKEN</button>
        <button class="btn btn-ghost btn-sm" data-toggle="${s.id}" data-active="${s.is_active?1:0}">${s.is_active||s.is_expired ? "⏸ DISABLE" : "▶ ENABLE"}</button>
        <button class="btn btn-red btn-sm" data-del="${s.id}">✕</button>
      </div>
    </div>`;
  }).join("");
  wireList();
}

function esc(s) { return String(s||"").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }

function wireList() {
  document.querySelectorAll("[data-token]").forEach(el => el.onclick = () => { navigator.clipboard.writeText(el.dataset.token); toast("✔ Token copied!", "ok"); });
  document.querySelectorAll("[data-copy]").forEach(b => b.onclick = () => { const s = SUBS.find(x => x.id == b.dataset.copy); if (s) { navigator.clipboard.writeText(s.token); toast("✔ Full token copied!", "ok"); } });
  document.querySelectorAll("[data-edit]").forEach(b => b.onclick = () => openEdit(+b.dataset.edit));
  document.querySelectorAll("[data-profile]").forEach(b => b.onclick = () => openProfile(+b.dataset.profile));
  document.querySelectorAll("[data-tokens]").forEach(b => b.onclick = () => openTokensModal(+b.dataset.tokens));
  document.querySelectorAll("[data-viewas]").forEach(b => b.onclick = () => {
    window.location.href = "/admin/api/subscribers/" + b.dataset.viewas + "/view-as";
  });
  document.querySelectorAll("[data-reset]").forEach(b => b.onclick = async () => {
    if (!confirm("Generate a new token? The old one will stop working.")) return;
    const d = await api("/admin/api/subscribers/" + b.dataset.reset + "/reset-token", {});
    if (d.new_token) { toast("✔ New token: " + d.new_token.slice(0,12) + "…", "ok"); navigator.clipboard.writeText(d.new_token); loadAll(); }
  });
  document.querySelectorAll("[data-toggle]").forEach(b => b.onclick = async () => {
    const active = b.dataset.active === "1";
    await api("/admin/api/subscribers/" + b.dataset.toggle + "/update", {is_active: !active});
    toast(active ? "⏸ Disabled" : "▶ Enabled", "ok"); loadAll();
  });
  document.querySelectorAll("[data-del]").forEach(b => b.onclick = async () => {
    if (!confirm("Delete this subscriber permanently?")) return;
    await api("/admin/api/subscribers/" + b.dataset.del + "/delete", {});
    toast("✔ Deleted", "ok"); loadAll();
  });
  document.querySelectorAll("[data-acc-limit]").forEach(inp => {
    inp.onchange = async () => {
      const id = inp.dataset.accLimit;
      const val = Math.max(1, parseInt(inp.value) || 1);
      inp.value = val;
      await api("/admin/api/subscribers/" + id + "/update", {max_accounts: val});
      toast("✔ تم تحديث الحد الأقصى للحسابات إلى " + val, "ok");
      loadAll();
    };
    inp.onkeydown = (e) => {
      if (e.key === "Enter") inp.blur();
    };
  });
}

// ─── Profile Modal ───
function openProfile(id) {
  const s = SUBS.find(x => x.id === id);
  if (!s) return;
  PROFILE_ID = id;
  const st = s.manually_disabled ? "disabled" : s.is_expired ? "expired" : "active";
  const stColors = {active: "#22c55e", expired: "#ef4444", disabled: "#8b8b9a"};
  const stLabels = {active: "● ACTIVE", expired: "● EXPIRED", disabled: "● DISABLED"};
  $("#prf-avatar").textContent = s.name[0].toUpperCase();
  $("#prf-name").textContent = s.name;
  $("#prf-id").textContent = "#" + s.id;
  const badge = $("#prf-status-badge");
  badge.textContent = stLabels[st];
  badge.style.color = stColors[st];
  $("#prf-created").textContent = fmtDate(s.created_at);
  $("#prf-expires").textContent = s.expires_at ? fmtDate(s.expires_at) : "∞ Unlimited";
  const daysEl = $("#prf-days");
  if (s.days_left === null) { daysEl.textContent = "∞"; daysEl.style.color = "#a855f7"; }
  else if (s.days_left <= 0) { daysEl.textContent = "EXPIRED"; daysEl.style.color = "#ef4444"; }
  else if (s.days_left <= 3) { daysEl.textContent = s.days_left + " d"; daysEl.style.color = "#f59e0b"; }
  else { daysEl.textContent = s.days_left + " d"; daysEl.style.color = "#e8e8ef"; }
  $("#prf-lastlogin").textContent = fmtAgo(s.last_login);
  const curAcc = s.accounts_count !== undefined ? s.accounts_count : 0;
  const maxAcc = s.max_accounts || 1;
  const prfMax = $("#prf-maxaccs");
  if (prfMax) {
    prfMax.textContent = `${curAcc} / ${maxAcc} (${curAcc >= maxAcc ? 'مكتمل' : (maxAcc - curAcc) + ' متاح'})`;
    prfMax.style.color = curAcc >= maxAcc ? '#ef4444' : '#22c55e';
  }
  $("#prf-notes").textContent = s.notes || "—";
  const tokenBox = $("#prf-token");
  tokenBox.textContent = s.token;
  tokenBox.onclick = () => { navigator.clipboard.writeText(s.token); toast("✔ Token copied!", "ok"); };
  const toggleBtn = $("#prf-btn-toggle");
  const isDisabled = s.manually_disabled;
  toggleBtn.textContent = isDisabled ? "▶ ENABLE" : "⏸ DISABLE";
  $("#profile-modal").hidden = false;
}

// Profile modal button handlers
$("#prf-btn-close").onclick = () => { $("#profile-modal").hidden = true; };
$("#prf-btn-viewas").onclick = () => {
  window.location.href = "/admin/api/subscribers/" + PROFILE_ID + "/view-as";
};
const btnPrfTokens = $("#prf-btn-tokens");
if (btnPrfTokens) btnPrfTokens.onclick = () => {
  if (PROFILE_ID) {
    $("#profile-modal").hidden = true;
    openTokensModal(PROFILE_ID);
  }
};
$("#prf-btn-copy-token").onclick = () => {
  const s = SUBS.find(x => x.id === PROFILE_ID);
  if (s) { navigator.clipboard.writeText(s.token); toast("✔ Token copied!", "ok"); }
};
$("#prf-btn-edit").onclick = () => { $("#profile-modal").hidden = true; openEdit(PROFILE_ID); };
$("#prf-btn-reset-token").onclick = async () => {
  if (!confirm("Generate a new token? The old one will stop working.")) return;
  const d = await api("/admin/api/subscribers/" + PROFILE_ID + "/reset-token", {});
  if (d.new_token) {
    toast("✔ New token generated & copied!", "ok");
    navigator.clipboard.writeText(d.new_token);
    $("#profile-modal").hidden = true;
    loadAll();
  }
};
$("#prf-btn-toggle").onclick = async () => {
  const s = SUBS.find(x => x.id === PROFILE_ID);
  if (!s) return;
  const wasDisabled = s.manually_disabled;
  await api("/admin/api/subscribers/" + PROFILE_ID + "/update", {is_active: wasDisabled});
  toast(wasDisabled ? "▶ Enabled" : "⏸ Disabled", "ok");
  $("#profile-modal").hidden = true;
  loadAll();
};
$("#prf-btn-delete").onclick = async () => {
  const s = SUBS.find(x => x.id === PROFILE_ID);
  if (!confirm("Delete " + (s ? s.name : "this subscriber") + " permanently?")) return;
  await api("/admin/api/subscribers/" + PROFILE_ID + "/delete", {});
  toast("✔ Deleted", "ok");
  $("#profile-modal").hidden = true;
  loadAll();
};

// ─── Create ───
$("#btn-create").onclick = async () => {
  const name = $("#c-name").value.trim();
  const days = parseInt($("#c-days").value) || 0;
  const maxAcc = parseInt($("#c-max-accs")?.value) || 1;
  const notes = $("#c-notes").value.trim();
  if (!name) { toast("Enter a name!", "bad"); return; }
  const d = await api("/admin/api/subscribers/create", {name, days: days || null, notes, max_accounts: maxAcc});
  if (d.token) {
    const disp = $("#new-token-display");
    disp.hidden = false;
    disp.textContent = "✔ TOKEN FOR " + name.toUpperCase() + ": " + d.token;
    disp.onclick = () => { navigator.clipboard.writeText(d.token); toast("✔ Token copied!", "ok"); };
    navigator.clipboard.writeText(d.token);
    toast("✔ Created! Token copied to clipboard.", "ok");
    $("#c-name").value = ""; $("#c-notes").value = "";
    if ($("#c-max-accs")) $("#c-max-accs").value = 1;
    loadAll();
  }
};

// ─── Edit ───
function openEdit(id) {
  const s = SUBS.find(x => x.id === id);
  if (!s) return;
  EDIT_ID = id;
  $("#edit-title").textContent = "EDIT — " + s.name;
  $("#e-name").value = s.name;
  if ($("#e-max-accs")) $("#e-max-accs").value = s.max_accounts || 1;
  $("#e-days").value = 0;
  $("#e-set-days").value = "";
  $("#e-notes").value = s.notes || "";
  $("#edit-modal").hidden = false;
}
$("#btn-save-edit").onclick = async () => {
  const maxAcc = parseInt($("#e-max-accs")?.value) || 1;
  const body = {
    name: $("#e-name").value.trim(),
    notes: $("#e-notes").value.trim(),
    max_accounts: maxAcc
  };
  const addDays = parseInt($("#e-days").value) || 0;
  const setDays = $("#e-set-days").value.trim();
  if (addDays > 0) {
    await api("/admin/api/subscribers/" + EDIT_ID + "/extend", {days: addDays});
  }
  if (setDays !== "") {
    body.days = parseInt(setDays) || 0;
  }
  await api("/admin/api/subscribers/" + EDIT_ID + "/update", body);
  $("#edit-modal").hidden = true;
  toast("✔ Updated!", "ok");
  loadAll();
};

// ─── Navigation Buttons ───
const btnDash = $("#btn-dashboard");
if (btnDash) btnDash.onclick = () => { location.href = "/"; };
const btnCancelEdit = $("#btn-cancel-edit");
if (btnCancelEdit) btnCancelEdit.onclick = () => { $("#edit-modal").hidden = true; };

// ─── Admin Credentials Reset ───
const btnSaveAdminPw = $("#btn-save-admin-password");
if (btnSaveAdminPw) {
  btnSaveAdminPw.onclick = async () => {
    const pw = ($("#cfg-admin-password").value || "").trim();
    if (!pw) { toast("كلمة المرور لا يمكن أن تكون فارغة!", "bad"); return; }
    btnSaveAdminPw.disabled = true;
    try {
      const d = await api("/admin/api/config/credentials", {admin_password: pw});
      if (d.ok) {
        toast("✔ تم حفظ وتحديث كلمة مرور الأدمن الموحدة بنجاح!", "ok");
        if ($("#admin-pw-badge")) $("#admin-pw-badge").textContent = "Admin Mode";
      } else {
        toast("فشل تحديث كلمة المرور", "bad");
      }
    } catch (e) {
      toast("خطأ في الاتصال", "bad");
    }
    btnSaveAdminPw.disabled = false;
  };
}

// ─── Misc ───
$("#btn-refresh").onclick = loadAll;
$("#btn-logout").onclick = () => { location.href = "/auth/logout"; };

// ─── Game Tokens Log Modal (سجل توكنات المشترك لآخر 24 ساعة) ───
let TOKENS_SUB_ID = null;

function fmtDateTime(ts) {
  if (!ts) return "—";
  try {
    return new Date(ts * 1000).toLocaleString("ar-EG", {
      month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: true
    });
  } catch (e) {
    return fmtDate(ts);
  }
}

async function openTokensModal(subId) {
  TOKENS_SUB_ID = subId;
  const s = SUBS.find(x => x.id === subId);
  const name = s ? s.name : "#" + subId;
  const tTitle = $("#toklog-title");
  if (tTitle) tTitle.textContent = "سجل توكنات حسابات اللعبة — " + name;
  const tSub = $("#toklog-subtitle");
  if (tSub) tSub.textContent = "سجل التوكنات لآخر 24 ساعة للمشترك (" + name + ")";
  const modal = $("#tokens-modal");
  if (modal) modal.hidden = false;
  await loadTokensLog(subId);
}

async function loadTokensLog(subId) {
  const container = $("#toklog-content");
  const countEl = $("#toklog-count");
  const clearBtn = $("#btn-clear-tokens-log");
  if (!container) return;
  container.innerHTML = '<div style="text-align:center; padding:30px; color:var(--muted); font-size:13px;">جاري جلب سجل التوكنات...</div>';
  try {
    const res = await api("/admin/api/subscribers/" + subId + "/game-tokens");
    if (!res || !res.ok) {
      container.innerHTML = '<div class="empty-state" style="color:var(--red);">❌ تعذر تحميل سجل التوكنات</div>';
      return;
    }
    const tokens = res.tokens || [];
    if (countEl) countEl.textContent = tokens.length + " توكن مسجل (خلال آخر 24 ساعة)";
    if (clearBtn) {
      clearBtn.style.display = tokens.length > 0 ? "inline-block" : "none";
    }

    if (!tokens.length) {
      container.innerHTML = `
        <div class="empty-state" style="padding:36px 16px; text-align:center; background:rgba(255,255,255,0.015); border-radius:12px; border:1px dashed var(--line);">
          <div style="font-size:32px; margin-bottom:10px;">📭</div>
          <div style="font-weight:800; font-size:14px; color:var(--text); margin-bottom:6px;">لا توجد أي توكنات مسجلة لهذا المشترك في آخر 24 ساعة</div>
          <div style="color:var(--muted); font-size:12px; line-height:1.6; max-width:460px; margin:0 auto;">
            يتم تسجيل توكنات حسابات اللعبة هنا تلقائياً بمجرد قيام المشترك بتشغيل برنامج <strong>CMSync</strong> والربط باللعبة، أو عند إضافة حسابه من اللوحة، ويتم مسح كل توكن تلقائياً بعد مرور 24 ساعة.
          </div>
        </div>`;
      return;
    }

    container.innerHTML = tokens.map(t => {
      const hoursLeft = t.hours_left_in_log !== undefined ? t.hours_left_in_log : 24.0;
      const gameExp = t.is_game_expired;
      const isUrgent = hoursLeft <= 3.0;
      return `
        <div style="background:var(--panel-2); border:1px solid ${isUrgent ? 'rgba(239,68,68,0.4)' : 'var(--line)'}; border-radius:12px; padding:14px; margin-bottom:12px; transition:border-color .2s;">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; flex-wrap:wrap; gap:8px;">
            <div style="display:flex; align-items:center; gap:8px;">
              <span style="font-size:13px; font-weight:900; background:rgba(168,85,247,0.18); color:#c084fc; border:1px solid rgba(168,85,247,0.3); border-radius:6px; padding:3px 10px; font-family:monospace;">
                🎮 ${esc(t.account_name)}
              </span>
              <span style="font-size:10px; font-weight:800; background:rgba(255,255,255,0.06); padding:2px 8px; border-radius:6px; color:var(--muted); text-transform:uppercase;">
                ${esc(t.source || 'auto')}
              </span>
            </div>
            <div style="font-size:11px; font-weight:800; color:${isUrgent ? '#ef4444' : '#f59e0b'}; background:${isUrgent ? 'rgba(239,68,68,0.12)' : 'rgba(245,158,11,0.1)'}; padding:3px 8px; border-radius:6px;" title="يتم حذف التوكن تلقائياً من السجل بعد مرور 24 ساعة">
              ⏳ متبقي على الحذف: ${hoursLeft} ساعة
            </div>
          </div>

          <div style="display:flex; justify-content:space-between; align-items:center; font-size:11px; color:var(--muted); margin-bottom:8px; flex-wrap:wrap; gap:6px;">
            <span>تاريخ الإضافة: <strong style="color:var(--text);">${fmtDateTime(t.added_at)}</strong> <small style="color:var(--muted);">(${fmtAgo(t.added_at)})</small></span>
            <span>حالة صلاحية اللعبة: <strong style="color:${gameExp ? 'var(--red)' : 'var(--green)'}; font-weight:800;">${gameExp ? '🔴 منتهي (Expired)' : '🟢 صالح (Valid)'}</strong></span>
          </div>

          <div style="position:relative; display:flex; align-items:center; gap:8px; margin-top:8px;">
            <div style="flex:1; background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:8px 12px; font-family:ui-monospace, Consolas, monospace; font-size:11px; color:#a7f3d0; word-break:break-all; user-select:all; max-height:64px; overflow-y:auto; line-height:1.4;">
              ${esc(t.token)}
            </div>
            <button class="btn btn-primary btn-sm" style="flex-shrink:0; height:100%; padding:10px 14px; font-weight:800; display:flex; align-items:center; gap:4px;" data-copy-tok="${esc(t.token)}">
              📋 نسخ التوكن
            </button>
          </div>
        </div>`;
    }).join("");

    container.querySelectorAll("[data-copy-tok]").forEach(btn => {
      btn.onclick = () => {
        navigator.clipboard.writeText(btn.dataset.copyTok);
        toast("✔ تم نسخ توكن اللعبة إلى الحافظة بنجاح!", "ok");
      };
    });
  } catch (err) {
    console.error("loadTokensLog error:", err);
    container.innerHTML = '<div class="empty-state" style="color:var(--red);">❌ حدث خطأ أثناء الاتصال بالسيرفر</div>';
  }
}

// Wire Tokens Modal Buttons
const btnCloseTokModal = $("#btn-close-tokens-modal");
if (btnCloseTokModal) btnCloseTokModal.onclick = () => { $("#tokens-modal").hidden = true; };

const btnRefreshTokLog = $("#btn-refresh-tokens-log");
if (btnRefreshTokLog) btnRefreshTokLog.onclick = () => {
  if (TOKENS_SUB_ID) loadTokensLog(TOKENS_SUB_ID);
};

const btnClearTokLog = $("#btn-clear-tokens-log");
if (btnClearTokLog) btnClearTokLog.onclick = async () => {
  if (!TOKENS_SUB_ID) return;
  if (!confirm("هل أنت متأكد من رغبتك في مسح سجل توكنات هذا المشترك بالكامل يدوياً؟")) return;
  try {
    const res = await api("/admin/api/subscribers/" + TOKENS_SUB_ID + "/game-tokens/clear", {});
    if (res && res.ok) {
      toast("✔ تم مسح سجل التوكنات بنجاح", "ok");
      loadTokensLog(TOKENS_SUB_ID);
    } else {
      toast("تعذر مسح السجل", "bad");
    }
  } catch (e) {
    toast("خطأ في الاتصال", "bad");
  }
};

// ─── Auto-check existing admin session ───
(async function initSession() {
  try {
    const d = await api("/admin/api/session-check");
    if (d.ok && d.session) {
      SESSION = d.session;
      $("#login-overlay").hidden = true;
      $("#main-ui").hidden = false;
      $("#admin-pw-badge").textContent = d.is_local ? "Local Direct Mode (Port 8001)" : "Admin Mode";
      loadAll();
    }
  } catch (e) {}
})();
