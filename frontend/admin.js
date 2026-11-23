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
    const lim = s.account_limit;
    return `<div class="sub-row">
      <span class="num">#${s.id}</span>
      <div class="name">${esc(s.name)}<small>Created: ${fmtDate(s.created_at)} · Last login: ${fmtAgo(s.last_login)} · Logins: ${s.login_count}</small></div>
      <div class="token-cell" title="Click to copy" data-token="${esc(s.token)}">${s.token.slice(0,8)}…${s.token.slice(-6)}</div>
      <div class="status ${st}">${stLabel}</div>
      <div class="days ${daysCls}">${days}</div>
      <div class="limit-cell">
        <label for="lim-${s.id}">ACCTS</label>
        <input id="lim-${s.id}" data-limit="${s.id}" type="number" min="0" step="1"
               value="${lim === null || lim === undefined ? "" : lim}"
               placeholder="no limit" title="أقصى عدد حسابات يقدر يضيفها — فاضي = من غير حد">
        <button class="btn btn-ghost btn-sm" data-limitsave="${s.id}" title="حفظ الحد — ومنه بيتقفل زرار الإضافة عنده لما يوصل">SAVE</button>
      </div>
      <div class="actions">
        <button class="btn btn-green btn-sm" data-openas="${s.id}" style="font-weight:900;" title="Login as subscriber with full session & inventory access">👤 OPEN AS SUBSCRIBER</button>
        <button class="btn btn-primary btn-sm" data-profile="${s.id}">ℹ DETAILS</button>
        <button class="btn btn-ghost btn-sm" data-toklog="${s.id}">🔑 TOKEN LOG${s.token_log_count ? ` (${s.token_log_count})` : ''}</button>
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

// حد الحسابات للمشترك: فاضي = من غير حد، 0 = ممنوع يضيف أي حساب
async function saveLimit(btn) {
  const id = btn.dataset.limitsave;
  const input = document.querySelector(`[data-limit="${id}"]`);
  const raw = (input.value || "").trim();
  if (raw !== "" && !/^\d+$/.test(raw)) { toast("Limit must be a whole number (or empty for no limit).", "bad"); return; }
  btn.disabled = true;
  try {
    const d = await api("/admin/api/subscribers/" + id + "/update", {account_limit: raw === "" ? null : parseInt(raw, 10)});
    if (d && d.id) {
      toast(raw === "" ? "✔ No account limit" : "✔ Limit set to " + raw + " account(s)", "ok");
      loadAll();
      return;
    }
    toast("Could not save the limit", "bad");
  } catch (e) {
    toast("Could not save the limit", "bad");
  }
  btn.disabled = false;
}

function esc(s) { return String(s||"").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }

function wireList() {
  document.querySelectorAll("[data-token]").forEach(el => el.onclick = () => { navigator.clipboard.writeText(el.dataset.token); toast("✔ Token copied!", "ok"); });
  document.querySelectorAll("[data-copy]").forEach(b => b.onclick = () => { const s = SUBS.find(x => x.id == b.dataset.copy); if (s) { navigator.clipboard.writeText(s.token); toast("✔ Full token copied!", "ok"); } });
  document.querySelectorAll("[data-toklog]").forEach(b => b.onclick = () => openTokenLog(+b.dataset.toklog));
  document.querySelectorAll("[data-openas]").forEach(b => b.onclick = () => {
    const s = SUBS.find(x => x.id == b.dataset.openas);
    const url = s ? ("/?as_subscriber=" + encodeURIComponent(s.name)) : ("/admin/api/subscribers/" + b.dataset.openas + "/view-as");
    window.open(url, "_blank");
  });
  document.querySelectorAll("[data-limitsave]").forEach(b => b.onclick = () => saveLimit(b));
  document.querySelectorAll("[data-limit]").forEach(el => el.onkeydown = e => {
    if (e.key === "Enter") { const b = document.querySelector(`[data-limitsave="${el.dataset.limit}"]`); if (b) saveLimit(b); }
  });
  document.querySelectorAll("[data-edit]").forEach(b => b.onclick = () => openEdit(+b.dataset.edit));
  document.querySelectorAll("[data-profile]").forEach(b => b.onclick = () => openProfile(+b.dataset.profile));
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
  $("#prf-logincount").textContent = s.login_count;
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
  if (!PROFILE_ID) return;
  const s = SUBS.find(x => x.id === PROFILE_ID);
  const url = s ? ("/?as_subscriber=" + encodeURIComponent(s.name)) : ("/admin/api/subscribers/" + PROFILE_ID + "/view-as");
  window.open(url, "_blank");
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

// ─── Token log (24h) ───
let TOK_ID = null;
let TOK_TIMER = null;

async function openTokenLog(id) {
  const s = SUBS.find(x => x.id === id);
  if (!s) return;
  TOK_ID = id;
  $("#tok-title").textContent = "TOKEN LOG — " + s.name;
  $("#tok-modal").hidden = false;
  await loadTokenLog();
  clearInterval(TOK_TIMER);
  // السطر اللي عدّى عليه 24 ساعة لازم يختفي لوحده والعيّنة مفتوحة
  TOK_TIMER = setInterval(loadTokenLog, 60000);
}

async function loadTokenLog() {
  if (TOK_ID === null) return;
  try {
    const d = await api("/admin/api/subscribers/" + TOK_ID + "/token-log");
    const list = $("#tok-list");
    const tokens = d.tokens || [];
    $("#tok-sub").textContent = tokens.length
      ? `${tokens.length} token(s) in the last ${d.hours} h — each line disappears ${d.hours} h after the token was first added.`
      : `No tokens in the last ${d.hours} h. When ${esc(d.name || "this subscriber")} adds a game token it shows here for 24 h.`;
    if (!tokens.length) { list.innerHTML = '<div class="empty-state">Nothing in the log right now.</div>'; return; }
    list.innerHTML = '<div class="tok-head"><span>ACCOUNT</span><span>TOKEN</span><span>LEFT</span><span>ADDED</span></div>' +
      tokens.map(t => `<div class="tok-row">
        <div class="acc">${esc(t.account_name)}<small>${esc(t.account === t.account_name ? "" : t.account)}</small></div>
        <div class="tok" title="Click to copy" data-copytoken="${esc(t.token)}">${esc(t.token.slice(0, 12))}…${esc(t.token.slice(-8))}</div>
        <div class="left">${t.hours_left} h<small>of 24</small></div>
        <div style="font-size:11px;color:var(--muted);font-variant-numeric:tabular-nums;">${esc(t.added_text)}</div>
      </div>`).join("");
    list.querySelectorAll("[data-copytoken]").forEach(el => el.onclick = () => {
      navigator.clipboard.writeText(el.dataset.copytoken); toast("✔ Token copied!", "ok");
    });
  } catch (e) {
    $("#tok-list").innerHTML = '<div class="empty-state">Could not load the log.</div>';
  }
}

function closeTokenLog() {
  $("#tok-modal").hidden = true;
  TOK_ID = null;
  clearInterval(TOK_TIMER);
}
$("#btn-tok-close").onclick = closeTokenLog;
$("#tok-modal").onclick = e => { if (e.target === $("#tok-modal")) closeTokenLog(); };

// ─── Create ───
$("#btn-create").onclick = async () => {
  const name = $("#c-name").value.trim();
  const days = parseInt($("#c-days").value) || 0;
  const notes = $("#c-notes").value.trim();
  const limRaw = ($("#c-limit").value || "").trim();
  if (!name) { toast("Enter a name!", "bad"); return; }
  if (limRaw !== "" && !/^\d+$/.test(limRaw)) { toast("Accounts limit must be a whole number (or empty for no limit).", "bad"); return; }
  const d = await api("/admin/api/subscribers/create", {name, days: days || null, notes,
    account_limit: limRaw === "" ? null : parseInt(limRaw, 10)});
  if (d.token) {
    const disp = $("#new-token-display");
    disp.hidden = false;
    disp.textContent = "✔ TOKEN FOR " + name.toUpperCase() + ": " + d.token;
    disp.onclick = () => { navigator.clipboard.writeText(d.token); toast("✔ Token copied!", "ok"); };
    navigator.clipboard.writeText(d.token);
    toast("✔ Created! Token copied to clipboard.", "ok");
    $("#c-name").value = ""; $("#c-notes").value = ""; $("#c-limit").value = "";
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
  $("#e-days").value = 0;
  $("#e-set-days").value = "";
  $("#e-notes").value = s.notes || "";
  $("#e-limit").value = (s.account_limit === null || s.account_limit === undefined) ? "" : s.account_limit;
  $("#edit-modal").hidden = false;
}
$("#btn-save-edit").onclick = async () => {
  const body = { name: $("#e-name").value.trim(), notes: $("#e-notes").value.trim() };
  const addDays = parseInt($("#e-days").value) || 0;
  const setDays = $("#e-set-days").value.trim();
  const limRaw = ($("#e-limit").value || "").trim();
  if (limRaw !== "" && !/^\d+$/.test(limRaw)) { toast("Accounts limit must be a whole number (or empty for no limit).", "bad"); return; }
  body.account_limit = limRaw === "" ? null : parseInt(limRaw, 10);
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
const btnSaveAdminTok = $("#btn-save-admin-token");
if (btnSaveAdminTok) {
  btnSaveAdminTok.onclick = async () => {
    const tok = ($("#cfg-admin-token").value || "").trim();
    if (!tok) { toast("Admin password cannot be empty!", "bad"); return; }
    btnSaveAdminTok.disabled = true;
    try {
      const d = await api("/admin/api/config/credentials", {admin_token: tok});
      if (d.ok) {
        toast("✔ Admin password updated!", "ok");
      } else {
        toast("Failed to update password", "bad");
      }
    } catch (e) {
      toast("Error updating password", "bad");
    }
    btnSaveAdminTok.disabled = false;
  };
}

const btnGenAdminTok = $("#btn-gen-admin-token");
if (btnGenAdminTok) {
  btnGenAdminTok.onclick = () => {
    const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!@#$%*-_=+";
    const pick = s => s[Math.floor(Math.random() * s.length)];
    let parts = [
      pick("ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
      pick("abcdefghijklmnopqrstuvwxyz"),
      pick("0123456789"),
      pick("!@#$%*-_=+")
    ];
    for (let i = 0; i < 46; i++) parts.push(pick(chars));
    for (let i = parts.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [parts[i], parts[j]] = [parts[j], parts[i]];
    }
    $("#cfg-admin-token").value = parts.join("");
    toast("🎲 50-char token generated (click SAVE to apply)", "ok");
  };
}

// ─── Item icon catalog ───
function catStamp(sec) {
  if (!sec) return "never synced";
  return new Date(sec * 1000).toLocaleString();
}

async function loadCatalog() {
  const stat = $("#cat-stat");
  if (!stat) return;
  try {
    const d = await api("/admin/api/catalog");
    stat.textContent = d.ok
      ? `${d.total.toLocaleString()} items · ${d.with_icon.toLocaleString()} icons stored locally · ${d.manual.toLocaleString()} manual definitions · last sync ${catStamp(d.synced_at)}`
      : "Catalog status unavailable";
  } catch (e) {
    stat.textContent = "Catalog status unavailable";
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const btn = $("#btn-cat-sync");
  if (btn) btn.onclick = async () => {
    const msg = $("#cat-msg");
    btn.disabled = true;
    btn.textContent = "⟳ SYNCING…";
    msg.textContent = "Reading the source catalog and downloading any new icons…";
    msg.style.color = "var(--muted)";
    try {
      const d = await api("/admin/api/catalog/sync", {});
      if (d.ok) {
        msg.textContent = `✔ ${d.added} new item(s) added · ${d.images} new icon(s) downloaded · ${d.total.toLocaleString()} items in the local catalog (${d.icons.toLocaleString()} with icons)`;
        msg.style.color = "var(--green)";
        toast(`✔ Catalog synced — ${d.added} new item(s), ${d.images} new icon(s)`, "ok");
      } else {
        msg.textContent = "✕ " + (d.detail || "The sync failed");
        msg.style.color = "var(--red)";
      }
    } catch (e) {
      msg.textContent = "✕ " + e.message;
      msg.style.color = "var(--red)";
    }
    btn.disabled = false;
    btn.textContent = "⟳ SYNC ARCTRACKER CATALOG";
    loadCatalog();
  };
  loadCatalog();
});

// ─── Misc ───
$("#btn-refresh").onclick = () => { loadAll(); loadCatalog(); };
$("#btn-logout").onclick = (e) => {
  if (e) e.preventDefault();
  try { localStorage.clear(); } catch (_) {}
  try { sessionStorage.clear(); } catch (_) {}
  const cookiesToClear = [
    "cm_subscriber_token", "cm_admin_session", "cm_admin_token",
    "cm_admin_saved", "cm_viewing_subscriber", "cm_test_sub", "cm_test_name"
  ];
  cookiesToClear.forEach((name) => {
    document.cookie = `${name}=; path=/; max-age=0; expires=Thu, 01 Jan 1970 00:00:00 GMT`;
  });
  window.location.replace("/auth/logout");
};

// ─── Auto-check existing admin session ───
(async function initSession() {
  try {
    const d = await api("/admin/api/session-check");
    if (d.ok && d.session) {
      SESSION = d.session;
      const badge = $("#admin-pw-badge");
      if (badge) badge.textContent = d.is_local ? "Local Direct Mode (Port 8001)" : "Admin Mode";
      loadAll();
      loadCatalog();
    } else {
      location.href = "/login";
    }
  } catch (e) {
    location.href = "/login";
  }
})();
