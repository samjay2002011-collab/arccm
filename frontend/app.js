/* لوحة إدارة المخزن — مباشرة على بوابة Embark Pioneer: أعمدة + سحب/إفلات + كليك يمين + تفاصيل + محرك إجراءات.
   كل إجراء يمر على /api/actions/*: لو الكتابة مقفولة بيرجع preview للطلب فقط. */

const state = {
  account: "", view: "inventory", sections: {}, writes: null, status: null,
  selected: new Set(), lastPicked: null, stacked: false, queries: {}, searchFocus: null, searchSel: null, drag: null,
  dupes: null, dupesFor: "", dupeFilter: false,
  tomain: null, tomainFor: "", tomainFilter: false, tomainMains: [], tomainIsMain: false,
  transferGroups: null, transferFor: "", transferTarget: "",
  accounts: [], profile: null, capacity: { used: 0, limit: null }, level: null, wallet: {},
  menuOpen: false, filters: null, loadout: null, locations: null, loadoutSel: "", loPopOpen: false, sortBy: "category",
  /* المعاينة: قالب محفوظ مختار، والشبكة بتتلبى بشكله قبل ما يتنفذ. loFillMode =
     المسار اللي عايز بيه القطع الناقصة (تصنيع ولا شراء). */
  loPreview: null, loFillMode: localStorage.getItem("fahmy.loFillMode") || "craft",
  clipboard: null, moveSeq: 0, moveQueue: [], moveBusy: false, sectionsGen: 0,
  queue: { items: [], count: 0, route_alive: false }, queueOpen: false,
  /* قفل اللوحة بعد ↑ UPDATE — مفيش حركة ولا إضافة لحد ما يعمل CANCEL. */
  frozen: false,
  newItems: {}, patchCandidates: [],
  /* قطع الباتش الجديد اللي مالهاش اسم ولا أيقونة في الفهارس: بتبان "?" وبتزعق
     اللوحة. مخفية افتراضيًا — الزرار اللي في راس الستاش بيظهرها وقت ما ينزل جديد. */
  showUnknown: localStorage.getItem("fahmy.showUnknown") === "1",
  history: [],
  augmentSpecs: null,
  /* صفوف الحسابات التانية اللي اتسحبت وقت البحث — عشان كارت التفاصيل يفتح على
     بلاطة أجنبية (قراءة بس؛ النقل لسه على قطع الحساب النشط). */
  foreign: {},
  syncing: new Set(), syncFlash: new Set(), stashPending: 0,
};
try { state.clipboard = JSON.parse(localStorage.getItem("fahmy.attach.clipboard") || "null"); } catch { state.clipboard = null; }

/* الحساب اللي بيتحكم فيه التاب ده — sessionStorage بياعتبر كل تاب وحدة مستقلة،
   فالتبويب التاني (أو إعادة تحميل الصفحة) ما يسرقش اختيار التاب الأول. */
const TAB_ACCOUNT_KEY = "fahmy.tab.account";
const tabAccount = () => { try { return sessionStorage.getItem(TAB_ACCOUNT_KEY) || ""; } catch { return ""; } };
const rememberTabAccount = (name) => { try { sessionStorage.setItem(TAB_ACCOUNT_KEY, name || ""); } catch { /* وضع خاص */ } };
state.account = tabAccount();

const $ = (s) => document.querySelector(s);
let searchTimer = null;
let ctxOpenTimer = 0;
let ctxOpenItem = null;
const FINE_POINTER = !!(window.matchMedia && window.matchMedia("(hover: hover) and (pointer: fine)").matches);
const ROMAN = { 1: "I", 2: "II", 3: "III", 4: "IV", 5: "V" };
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const asset = (f) => (f ? `/assets/items/${String(f).split("/").map(encodeURIComponent).join("/")}` : "");
const num = (n) => (n === null || n === undefined ? "—" : Number(n).toLocaleString("en-US"));
const numSpaced = (n) => (n === null || n === undefined ? "—" : Number(n).toLocaleString("en-US").replace(/,/g, " "));
const RARITY_ORDER = ["Common", "Uncommon", "Rare", "Epic", "Legendary", "Amplified"];
const SORT_MODES = [["category", "CATEGORY"], ["rarity", "RARITY"], ["name", "NAME"], ["value", "VALUE"]];
const CATEGORY_RANK = {
  Augments: 1, Shields: 2, Weapons: 3, "Weapon Mods": 3, Ammunition: 4,
  "Quick Use": 4, Trinkets: 5, "Crafting Materials": 5, Research: 6,
  Keys: 7, Furniture: 7, Misc: 7,
  Blueprints: 8, Designs: 8, Stencils: 8,
};
// الأسلحة والمودات نفس الفئة العرض، بس المودات لازم تفضل ورا كل سلاح
const CATEGORY_SUBRANK = { "Weapon Mods": 1, Blueprints: 1, Designs: 2, Stencils: 3 };
const PLANT_TYPES = new Set(["nature", "flora", "organic", "plant"]);

const STAT_FILTER = {
  coins: "brightness(0) invert(1)",
  cred: "invert(58%) sepia(93%) saturate(345%) hue-rotate(182deg) brightness(101%) contrast(97%)",
  tokens: "invert(25%) sepia(34%) saturate(1487%) hue-rotate(345deg) brightness(97%) contrast(92%)",
};
const STEAM_PATH = "M4.102 21.033C6.211 22.881 8.977 24 12 24c3.026 0 5.789-1.119 7.902-2.967 1.877-1.912-4.316-8.709-7.902-11.417-3.582 2.708-9.779 9.505-7.898 11.417zm11.16-14.406c2.5 2.961 7.484 10.313 6.076 12.912C23.002 17.48 24 14.861 24 12.004c0-3.34-1.365-6.362-3.57-8.536 0 0-.027-.022-.082-.042-.063-.022-.152-.045-.281-.045-.592 0-1.985.434-4.805 3.246zM3.654 3.426c-.057.02-.082.041-.086.042C1.365 5.642 0 8.664 0 12.004c0 2.854.998 5.473 2.661 7.533-1.401-2.605 3.579-9.951 6.08-12.91-2.82-2.813-4.216-3.245-4.806-3.245-.131 0-.223.021-.281.046v-.002zM12 3.551S9.055 1.828 6.755 1.746c-.903-.033-1.454.295-1.521.339C7.379.646 9.659 0 11.984 0H12c2.334 0 4.605.646 6.766 2.085-.068-.046-.615-.372-1.52-.339C14.946 1.828 12 3.545 12 3.545v.006z";
const ICO = {
  copy: `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>`,
  refresh: `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 3v6h-6"/></svg>`,
  edit: `<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>`,
  trash: `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M6 6l1 14h10l1-14"/></svg>`,
  check: `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"><path d="m4 12 5 5L20 6"/></svg>`,
  calendar: `<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.9"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/></svg>`,
  clock: `<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.9"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>`,
  wrench: `<svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94z"/></svg>`,
};
const KIND_ICON = {
  design: `<svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20 20 4"/><path d="M14 4h6v6"/></svg>`,
  stencil: `<svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" stroke-width="1.9"><rect x="4" y="4" width="16" height="16" rx="3"/><rect x="9" y="9" width="6" height="6" rx="1"/></svg>`,
};

function platSvg(platform) {
  const p = (platform || "steam").toLowerCase();
  if (p === "steam") return `<svg viewBox="0 0 24 24" fill="currentColor"><path d="${STEAM_PATH}"/></svg>`;
  if (p === "epic") return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M4 3h16v18l-4-2.6L12 21l-4-2.6L4 21z"/><path d="M9 7v7l3 1.6 3-1.6V7"/></svg>`;
  if (p === "xbox") return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="9"/><path d="M6 6c3 2.4 8.4 8.6 10.6 12M18 6c-2.3 1.9-7.6 7.8-10.2 12"/></svg>`;
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 12h10"/></svg>`;
}
const PLAT_NAME = { steam: "Steam", epic: "Epic Games", xbox: "Xbox", manual: "Manual" };

// بوابة Pioneer الرسمية ما بتعرفش اسم اللاعب: الحساب الجديد بيجي باسم مشتق من الـ SteamID.
// نعرّف التسمية المشتق عشان نبينها وتحفز علي التسمية الحقيقية مرة واحدة (الاسم بيتحفظ في دفتر الأسماء).
const DERIVED_NAME = /^(RAIDER|ACCOUNT|PIONEER)[\s_]*[0-9]+$/i;
const isUnnamed = (a) => DERIVED_NAME.test(String((a && (a.display_name || a.name)) || ""));

const SLOT_META = {
  augment: { label: "AUGMENT" }, shield: { label: "SHIELD" },
  gun_1: { label: "WEAPON 1" }, gun_2: { label: "WEAPON 2" },
  quick_use: { label: "QUICK USE" }, safe_pocket: { label: "SAFE POCKET" },
  augmented_slots: { label: "AUGMENTED" },
};
const ESSENTIAL_SLOTS = ["augment", "shield", "gun_1", "gun_2"];
const FIREARM_TYPES = ["weapon", "smg", "assault rifle", "battle rifle", "shotgun", "sniper rifle",
  "hand cannon", "lmg", "pistol", "special"];

async function fetchJson(url, opts) {
  const res = await fetch(url, opts);
  if (res.status === 401) {
    if (window.location.pathname !== "/login" && !window.location.pathname.startsWith("/login")) {
      window.location.href = "/login";
    }
    return {};
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `${url} -> HTTP ${res.status}`);
  return body;
}

// نفس الطلب الشغال دلوقتي بيتشارك مع اللي يجي وراه — boot والـ views كانت بتكرره
const inflight = new Map();
function json(url, opts) {
  if (opts && opts.method) return fetchJson(url, opts);
  const running = inflight.get(url);
  if (running) return running;
  const pending = fetchJson(url, opts).finally(() => inflight.delete(url));
  inflight.set(url, pending);
  return pending;
}
/* قفل ↑ UPDATE بيقفل أي كتابة على البوابة من أي مكان في الموقع — حتى زرار
   SCRAPPY في الهيدر أو مودال مفتوح قبل القفل. القراءة (sync/plan) واللمسة
   نفسها بيفضلوا شغالين. */
const FROZEN_OK_POSTS = ["/api/actions/sync", "/api/actions/plan", "/api/actions/touch"];
function frozenWriteGuard(url) {
  if (!state.frozen) return false;
  const path = String(url || "").split("?")[0];
  if (!path.startsWith("/api/actions/") || FROZEN_OK_POSTS.includes(path)) return false;
  frozenBlock("This move");
  return true;
}
const post = (url, body) => (frozenWriteGuard(url)
  ? Promise.resolve({ executed: false, error: "frozen", detail: "Board is locked after UPDATE — press CANCEL." })
  : json(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) }));
const del = (url, body) => json(url, { method: "DELETE", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
const patch = (url, body) => json(url, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });

function ageText(minutes) {
  if (minutes === null || minutes === undefined) return "never";
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${Math.round(minutes)} min ago`;
  return `${(minutes / 60).toFixed(1)} h ago`;
}
function toast(msg, kind) {
  const t = document.createElement("div");
  t.className = "toast " + (kind || "");
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 4200);
}
function tokenText(st) {
  if (!st?.token?.present) return "missing";
  const h = st.token.expires_in_hours;
  return h === null ? "no expiry" : h <= 0 ? "EXPIRED" : `${h.toFixed(0)} h left`;
}

/* ------------------------------------------------------------------ data */
async function loadStatus() {
  const st = await json("/api/status");
  state.status = st;
  const online = st.mode === "online";
  const dot = $("#conn-dot");
  if (dot) dot.className = "dot" + (online ? "" : " off");
  const banner = $("#mode-banner");
  /* البوابة ساقطة وفي نسخة محفوظة: مفيش لافتة — النجمة الحمرا جنب الحساب بتقول إن
     التوكن خلص، وده كفاية عنده. اللافتة بتفضل بس لما مفيش نسخة أصلاً (مفيش حاجة تعرضه). */
  if (online || st.mode === "offline_cached") banner.hidden = true;
  else {
    banner.hidden = false;
    banner.textContent = "⚠ No saved snapshot yet — run SYNCHRONIZE; the Embark Pioneer gateway is reachable.";
  }
  $("#status-box").innerHTML = `
    <span class="k">mode</span><span class="v ${online ? "ok" : "warn"}">${esc(st.mode)}</span>
    <span class="k">last pull</span><span class="v">${ageText(st.last_attempt_age_minutes)}</span>
    <span class="k">accounts up</span><span class="v">${st.accounts_online ?? "—"}</span>
    <span class="k">icons cached</span><span class="v">${num(st.assets_local)}</span>
    <span class="k">token</span><span class="v ${st.token?.expires_in_hours > 24 ? "ok" : "warn"}">${esc(tokenText(st))}</span>
    ${Object.entries(st.accounts || {}).map(([a, v]) => `<span class="k">${esc(a)}</span><span class="v">${num(v.items)} items · ${ageText(v.age_minutes)}</span>`).join("")}`;

  agentLine();
}

/* ------------------------------------------------------------------ الحسابات + الهيدر */
async function loadAccounts() {
  const data = await json("/api/accounts");
  state.accounts = data.accounts || [];
  state.profile = data.profile || state.profile;
  state.capacity = data.capacity || { used: state.accounts.length, limit: null };
  // التاب بيحتفظ بحسابه طالعة لسه موجود؛ حساب السيرفر العام مجرد بداية للتابات الجديدة.
  const mine = (list) => list.find((a) => a.name === state.account);
  if (!mine(state.accounts)) {
    state.account = (data.active && (data.active !== "" ? data.active : "")) ||
      (state.accounts.find((a) => a.is_active) || state.accounts[0] || {}).name || state.account;
  }
  if (state.account) rememberTabAccount(state.account);
  renderAccountsPage();
  return data;
}

async function loadHeader() {
  const d = await json("/api/profile?account=" + encodeURIComponent(state.account || ""));
  state.profile = d.profile || state.profile;
  state.wallet = d.wallet || {};
  state.level = d.level || null;
  if (d.capacity) state.capacity = d.capacity;
  renderHeader();
}

function fmtWhen(iso) {
  if (!iso) return "—";
  const d = new Date(String(iso).length === 10 ? iso + "T00:00:00Z" : iso);
  if (isNaN(d.getTime())) return "—";
  return d.toLocaleString("en-US", { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: true });
}

function levelRing(level) {
  if (!level || !level.level) return "";
  const R = 20, C = 2 * Math.PI * R;
  const p = Math.max(0, Math.min(1, Number(level.progress) || 0));
  const tip = level.max_level
    ? `Level ${level.level} (MAX) · ${num(level.xp)} XP`
    : `Level ${level.level} · ${num(level.xp)} XP · ${num(Math.max(0, (level.next || 0) - (level.xp || 0)))} to level ${level.level + 1}`;
  return `<div class="level-ring" title="${esc(tip)}">
    <svg viewBox="0 0 48 48" width="48" height="48">
      <circle class="track" cx="24" cy="24" r="${R}" fill="none" stroke-width="3"/>
      <circle class="fill" cx="24" cy="24" r="${R}" fill="none" stroke-width="3"
              stroke-dasharray="${C.toFixed(2)}" stroke-dashoffset="${(C * (1 - p)).toFixed(2)}"/>
    </svg><span>${esc(level.level)}</span></div>`;
}

function tokenDot(a) {
  if (a.is_expired) return { cls: "bad", tip: "Token expired — needs renewal" };
  const h = a.token_hours_left;
  if (h !== null && h !== undefined && h <= 6) {
    return { cls: "warn", tip: `Token expires in about ${Math.max(0, Math.round(h))} h` };
  }
  return { cls: "ok", tip: "Token is valid" };
}

function renderHeader() {
  const wallet = state.wallet || {};
  const chips = ["coins", "tokens"].map((key) => {
    const s = wallet[key] || {};
    const icon = s.image
      ? `<img src="${asset(s.image)}" alt="" style="filter:${STAT_FILTER[key]}">`
      : `<span class="fallback" style="color:${esc(s.color || "#fff")}"></span>`;
    return `<div class="stat ${key}" title="${esc(s.title || key)}">${icon}<b>${numSpaced(s.value || 0)}</b></div>`;
  }).join("");
  $("#wallet").innerHTML = chips + levelRing(state.level);

  // الحسابات أزرار قدامه على طول — ضغطة واحدة تنقّل للتاني، والنقطة بتقول حالة التوكن
  const tabs = state.accounts.map((a) => {
    const d = tokenDot(a);
    return `<button class="acc-tab ${a.name === state.account ? "on" : ""}" data-pick="${esc(a.id)}"
             title="${esc(a.display_name)} — ${esc(d.tip)}">
        <span class="tok-dot ${d.cls}"></span><b>${a.is_main ? "★ " : ""}${esc(a.display_name)}</b>
        ${isUnnamed(a) ? `<small class="need-name" data-rename="${esc(a.id)}">✎</small>` : ""}
      </button>`;
  }).join("");
  $("#acc-switch").innerHTML = state.accounts.length
    ? `<div class="acc-tabs">${tabs}</div>`
    : `<div class="acc-tabs"><button class="acc-tab" data-manage="1"><b>NO ACCOUNT</b><small>ADD ONE</small></button></div>`;

  const rename = (node) => {
    node.onclick = (e) => { e.stopPropagation(); editAccount(node.dataset.rename); };
  };
  document.querySelectorAll("#acc-switch [data-pick]").forEach((button) => {
    button.oncontextmenu = (event) => {
      event.preventDefault();
      const account = state.accounts.find((row) => row.id === button.dataset.pick);
      if (!account) return;
      openModal(account.display_name, `<p class="note">${account.is_main ? "Remove this account from transfer destinations?" : "Mark this account as a main transfer destination?"}</p>`, async () => {
        await json(`/api/accounts/${encodeURIComponent(account.id)}/main`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ is_main: !account.is_main }) });
        state.transferGroups = null;
        state.tomain = null;
        await loadAccounts();
        renderHeader();
        renderInventory();
      }, account.is_main ? "REMOVE MAIN" : "MARK AS MAIN");
    };
  });
  document.querySelectorAll("#acc-switch [data-rename]").forEach(rename);
  document.querySelectorAll("#acc-switch [data-pick]").forEach((b) => b.onclick = () => {
    state.menuOpen = false;
    renderHeader();
    selectAccountById(b.dataset.pick);
  });
  const manageBtn = document.querySelector("[data-manage]");
  if (manageBtn) manageBtn.onclick = () => { state.menuOpen = false; renderHeader(); showView("accounts"); };
}

function acctRowHTML(a) {
  const plat = esc(a.platform || "manual");
  const hours = a.token_hours_left;
  const tokenWarn = a.is_expired
    ? `<span class="exp">token expired</span>`
    : (hours !== null && hours !== undefined && hours <= 6
        ? `<span class="exp">token ${Math.max(0, Math.round(hours))} h left</span>` : "");
  const syncedAt = a.updated_at || (a.last_sync ? new Date(a.last_sync * 1000).toISOString() : null) ||
    (a.last_success ? new Date(a.last_success * 1000).toISOString() : null);
  return `
  <div class="acct-row ${a.is_expired ? "expired" : ""}" data-id="${esc(a.id)}">
    <div class="plat-icon ${plat}">${platSvg(a.platform)}</div>
    <div class="acct-main">
      <div class="acct-title">
        <span class="acct-name">${esc(a.display_name)}</span>
        ${isUnnamed(a) ? `<span class="badge manual" title="The official gateway never returns player names — type it once and it stays saved for this account">Auto name ✎</span>` : ""}
        <span class="badge ${plat}">${esc(PLAT_NAME[a.platform] || a.platform || "Manual")}</span>
        ${a.name === state.account ? `<span class="badge active">IN THIS TAB</span>` : ""}
        ${a.is_active && a.name !== state.account ? `<span class="badge manual">DEFAULT</span>` : ""}
        ${a.is_expired ? `<span class="badge restricted">EXPIRED</span>` : ""}
        ${a.is_restricted ? `<span class="badge restricted">RESTRICTED</span>` : ""}
      </div>
      <div class="acct-meta">
        <span>${ICO.calendar} Added: ${esc(fmtWhen(a.added_at))}</span>
        <span>${ICO.clock} Updated: ${esc(fmtWhen(syncedAt))}</span>
        ${tokenWarn}
      </div>
    </div>
    <div class="acct-actions">
      ${a.name === state.account ? "" : `<button class="select-btn" data-select="${esc(a.id)}" title="Open this account in this tab">${ICO.check} USE IN THIS TAB</button>`}
      <button class="icon-btn" data-copy="${esc(a.id)}" title="Copy authorization token">${ICO.copy}</button>
      <button class="icon-btn" data-refresh="${esc(a.id)}" title="Refresh this account now">${ICO.refresh}</button>
      <button class="icon-btn" data-edit="${esc(a.id)}" title="Edit label / re-authorize">${ICO.edit}</button>
      <button class="icon-btn danger" data-del="${esc(a.id)}" title="Remove this account from the board (asks for confirmation)">${ICO.trash}</button>
    </div>
  </div>`;
}

const AGENT_NOTES = {
  "token unchanged": "Token unchanged",
  "token refreshed for existing account": "Account token refreshed",
  "registered automatically from the game": "New account registered from the game",
  "a newer token is already stored": "A newer token is already stored",
};

function agentDownload() {
  // نفس السطر بيتحط في كارت CMSync وفي لوحة CONNECTION — مصدر واحد، مكانين.
  const r = (state.status || {}).release || {};
  const html = !r.present
    ? `<span class="dl-meta">No CMSync build on this server yet.</span>`
    : `<a class="dl-link" href="/download/cmsync" download title="CMSync.exe — the local agent that registers your account automatically">⬇ Download CMSync</a>
       <span class="dl-meta">build ${esc(r.built_at_text || "")} · ${esc((r.size / 1048576).toFixed(1))} MB</span>
       <button class="ghost tiny dl-copy" type="button" title="Copy the download link to send to someone">⧉ copy link</button>`;
  document.querySelectorAll("[data-agent-dl]").forEach((el) => {
    el.innerHTML = html;
    const btn = el.querySelector(".dl-copy");
    if (btn) btn.onclick = async () => {
      const url = `${location.origin}/download/cmsync`;
      try {
        await navigator.clipboard.writeText(url);
        toast("Download link copied.");
      } catch {
        toast(`Copy failed — the link is ${url}`);
      }
    };
  });
}

function agentLine() {
  agentDownload();
  const el = $("#agent-line");
  if (!el) return;
  const a = (state.status || {}).agent || {};
  if (!a.account) return;
  const mins = Math.max(0, Math.round((Date.now() / 1000 - Number(a.at || 0)) / 60));
  const ago = mins < 60 ? `${num(mins)} min ago`
    : mins < 1440 ? `${num(Math.round(mins / 60))} h ago`
    : `${num(Math.round(mins / 1440))} day${Math.round(mins / 1440) === 1 ? "" : "s"} ago`;
  const left = a.exp ? Math.round((a.exp - Date.now() / 1000) / 3600) : null;
  const note = AGENT_NOTES[a.note] || a.note || "";
  el.innerHTML = `Last sent: <b>${esc(a.account)}</b>${note ? ` · ${esc(note)}` : ""} · ${ago}` +
    (left !== null ? ` · token valid for ${num(left)} h` : "");
}

function renderAccountsPage() {
  const host = $("#acct-rows");
  if (!host) return;
  const cap = state.capacity || { used: 0, limit: null };
  const capEl = $("#cap-value");
  if (capEl) {
    // مفيش حد حسابات خارجي — العدد المحلي بس.
    capEl.textContent = cap.limit ? `${num(cap.used)} / ${num(cap.limit)}` : num(cap.used);
    capEl.classList.toggle("full", !!cap.limit && cap.used >= cap.limit);
  }
  host.innerHTML = state.accounts.length
    ? state.accounts.map(acctRowHTML).join("")
    : `<div class="acct-empty" style="text-align: center; padding: 25px 15px; background: rgba(255,255,255,0.03); border: 1px dashed rgba(255,255,255,0.15); border-radius: 8px;">
        <p style="margin: 0 0 8px 0; color: #f3f4f6; font-size: 14px;">No linked accounts yet.</p>
        <p style="margin: 0 0 15px 0; color: #9ca3af; font-size: 12px;">Run CMSync on your PC to automatically sync your game account, or download it below:</p>
        <a href="/download/CMSync.exe" download style="display: inline-block; background: #9333ea; color: #ffffff; padding: 7px 18px; border-radius: 6px; text-decoration: none; font-size: 12px; font-weight: bold;">📥 Download CMSync.exe</a>
      </div>`;
  wireAccountRows();
  agentLine();
}

function wireAccountRows() {
  document.querySelectorAll("[data-select]").forEach((b) => b.onclick = async () => {
    b.disabled = true;
    try { await selectAccountById(b.dataset.select); toast("✔ Active account changed.", "ok"); }
    catch (e) { toast(e.message, "bad"); }
    b.disabled = false;
  });
  document.querySelectorAll("[data-copy]").forEach((b) => b.onclick = () => copyToken(b.dataset.copy, b));
  document.querySelectorAll("[data-refresh]").forEach((b) => b.onclick = () => refreshOne(b));
  document.querySelectorAll("[data-edit]").forEach((b) => b.onclick = () => editAccount(b.dataset.edit));
  document.querySelectorAll("[data-del]").forEach((b) => b.onclick = () => removeAccount(b.dataset.del));
}

function acctNote(text, kind) {
  const el = $("#acct-note");
  if (!el) return;
  el.textContent = text || "";
  el.className = "form-note " + (kind || "");
}

async function selectAccountById(id) {
  const modal = $("#modal");
  if (modal) modal.hidden = true;
  const picked = (state.accounts.find((a) => a.id === id) || {}).name || state.account;
  // الاختيار ده بتاع التاب ده بس — sessionStorage ما بيتشاركش مع التابات التانية.
  state.account = picked;
  if (state.recentMoves) state.recentMoves.clear();
  rememberTabAccount(picked);
  // اللوحة المقفولة بتاعة حساب واحد — التبديل لحساب تاني يفكّها عنده
  setFrozen(false, true);
  try { await post(`/api/accounts/${encodeURIComponent(id)}/select`); }
  catch (e) { toast(e.message, "bad"); return; }
  state.selected.clear();
  state.queries = {};
  state.transferGroups = null; state.transferFor = "";
  state.dupes = null; state.dupesFor = ""; state.dupeFilter = false;
  state.tomain = null; state.tomainFor = ""; state.tomainFilter = false;
  state.tomainMains = []; state.tomainIsMain = false;
  state.foreign = {};
  state.loadoutSel = "";
  state.loPreview = null;
  state.scrappy = null;
  syncScrappyPill();
  await Promise.all([refreshAll(), loadAccounts()]);
  if (state.view === "traders") loadTraders().catch((e) => toast("⛔ " + e.message, "bad"));
  if (state.view === "workshop") loadWorkshop().catch((e) => toast("⛔ " + e.message, "bad"));
  loadScrappy().catch(() => {});
}

async function copyToken(id, btn) {
  try {
    const d = await json(`/api/accounts/${encodeURIComponent(id)}/token`);
    if (!d.token) throw new Error("No stored token for this account.");
    const value = "Bearer " + d.token;
    let copied = false;
    try {
      if (navigator.clipboard?.writeText) { await navigator.clipboard.writeText(value); copied = true; }
    } catch { /* المتصفح ممكن يرفض لو الصفحة مش متفعّلة */ }
    if (!copied) {
      const ta = document.createElement("textarea");
      ta.value = value;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      try { copied = document.execCommand("copy"); } catch { copied = false; }
      ta.remove();
    }
    if (copied) {
      btn.classList.add("copied");
      setTimeout(() => btn.classList.remove("copied"), 1200);
      toast("✔ Token copied (Bearer …).", "ok");
      return;
    }
    openModal("COPY AUTHORIZATION TOKEN", `
      <p class="note">The browser blocked auto-copy (the page is not in focus). The token is selected below — press Ctrl+C.</p>
      <input id="copy-value" class="copy-input" readonly value="${esc(value)}">`, null);
    $("#copy-value").focus();
    $("#copy-value").select();
  } catch (e) { toast("Copy failed: " + e.message, "bad"); }
}

async function refreshOne(btn) {
  const id = btn.dataset.refresh;
  const rec = state.accounts.find((a) => a.id === id) || {};
  btn.disabled = true;
  btn.classList.add("spinning");
  try {
    const d = await post(`/api/accounts/${encodeURIComponent(id)}/refresh`);
    if (d.ok) {
      toast(`✔ ${d.account}: ${num(d.items)} items refreshed from Embark.`, "ok");
      await Promise.all([loadAccounts(), loadHeader(), loadStatus()]);
      if (rec.name === state.account) await Promise.all([loadSections(), loadLegend()]);
    } else toast("Refresh failed: " + (d.detail || d.error || "unknown"), "bad");
  } catch (e) { toast(e.message, "bad"); }
  btn.disabled = false;
  btn.classList.remove("spinning");
}

function editAccount(id) {
  const a = state.accounts.find((x) => x.id === id);
  if (!a) return;
  openModal(`EDIT ACCOUNT — ${a.display_name}`, `
    <div class="field"><label>Account name — as it appears in your in-game profile</label>
      <input id="edit-label" type="text" maxlength="64" value="${esc(a.label && !isUnnamed(a) ? a.label : "")}"
             placeholder="e.g. G14 #0847"></div>
    <p class="note" style="margin-top:8px">The official Pioneer gateway never exposes player names to any tool — this name is typed once and saved against the account identity (SteamID and Embark id), so the account keeps it even if it is re-registered or deleted and comes back.</p>
    <div class="field" style="margin-top:14px"><label>AUTHORIZATION TOKEN — leave empty to keep it unchanged</label>
      <div class="input-wrap"><span class="key-ico">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
          <circle cx="8" cy="15" r="4"/><path d="M10.85 12.15 19 4"/><path d="m18 5 2 2"/><path d="m15 8 2 2"/>
        </svg></span>
        <input id="edit-token" type="password" autocomplete="off" spellcheck="false" placeholder="Bearer eyJhbGciOiJIUz..."></div></div>
    <p class="note" style="margin-top:12px">Edits stay local in your own database; pulls and writes go straight to the Embark Pioneer gateway.</p>`,
    async () => {
      const label = ($("#edit-label").value || "").trim();
      const token = ($("#edit-token").value || "").trim();
      const body = { label };
      if (token) body.token = token;
      const out = await json(`/api/accounts/${encodeURIComponent(id)}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      state.accounts = state.accounts.map((x) => (x.id === id ? out.account : x));
      renderAccountsPage();
      toast("✔ Updated: " + out.account.display_name, "ok");
      await Promise.all([loadAccounts(), loadHeader(), loadStatus()]);
    }, "SAVE");
}

function removeAccount(id) {
  const a = state.accounts.find((x) => x.id === id);
  if (!a) return;
  // الحذف بيّمسح التوكن والمحزون كله من القاعدة، وبعدها اللوحة بترفض تسجّله
  // تاني من الذاكرة (مدرج في قائمة المحذوفين) — فدخلة واحدة على زرابيت الغلط
  // كانت كفيلة إنها تضيّع حساب كامل. الحذف بقى بخطوة تأكيد صريحة.
  openModal(`DELETE ACCOUNT — ${esc(a.display_name || a.name)}`, `
    <p class="note">Removed from this board: the stored token, all inventory rows, saved loadouts
    and pull snapshots of <b>${esc(a.name)}</b>. The in-game inventory itself is
    untouched — the board only remembers that this account was deleted on purpose, so it will not restore it from memory.</p>
    <p class="note" style="margin-top:10px">To take an account off the board temporarily,
    disable it (DISABLE) instead of deleting it.</p>`,
    async () => {
      const wasActive = a.name === state.account;
      const out = await json(`/api/accounts/${encodeURIComponent(id)}?unlink=0`, { method: "DELETE" });
      await Promise.all([loadAccounts(), loadHeader(), loadStatus()]);
      if (wasActive) await Promise.all([loadSections(), loadLegend()]);
      toast("✔ " + (out.note || "removed"), "ok");
    }, "DELETE FOR EVER", { confirmKind: "danger" });
}

async function addAccount() {
  const token = ($("#acct-token").value || "").trim();
  const label = ($("#acct-label").value || "").trim();
  if (!token) { acctNote("Paste an AUTHORIZATION TOKEN first.", "bad"); $("#acct-token").focus(); return; }
  const btn = $("#acct-add");
  btn.disabled = true;
  acctNote("Verifying the token and pulling account data from Embark…", "");
  try {
    const out = await post("/api/accounts/add", { token, label });
    const a = out.account || {};
    $("#acct-token").value = "";
    $("#acct-label").value = "";
    const pulled = out.pulled?.ok ? ` — ${num(out.pulled.items)} items pulled` : "";
    acctNote(`✔ Added ${a.display_name || a.name}${pulled} · ${out.note || ""}`, "ok");
    toast(`✔ ${a.display_name || "the account"} added.`, "ok");
    await Promise.all([loadAccounts(), loadHeader(), loadStatus()]);
    if (out.pulled?.ok) await Promise.all([loadSections(), loadLegend()]);
  } catch (e) {
    acctNote("⛔ " + e.message, "bad");
  }
  btn.disabled = false;
}

/* ------------------------------------------------------------------ حفظ الحركات الأخيرة لمنع ارتداد العناصر
   عند النقل (المخزن ⇄ الشنطة ⇄ اللود آوت)، الباكند ينفّذ النقلة على بوابة اللعبة
   فوراً لكن إعادة سحب السنابشوت من Embark تأخذ 3-4 ثوان في خيط خلفي.
   لو طلبت الواجهة loadSections قبل اكتمال السحب، السيرفر يعيد السنابشوت القديم
   فترتد القطعة لمكانها السابق مؤقتاً لحوالي 5 ثوان!
   هذه الدالة تحتفظ بمكان القطعة الجديد حتى يؤكد السيرفر في السنابشوت وصولها لمكانها. */
function reconcileSectionsWithRecentMoves(data) {
  if (!state.recentMoves || !state.recentMoves.size) return;
  const now = Date.now();
  // إهمال الحركات التي مر عليها أكثر من 12 ثانية كحد أقصى للأمان
  for (const [id, m] of state.recentMoves.entries()) {
    if (now - m.at > 12000) {
      state.recentMoves.delete(id);
    }
  }
  if (!state.recentMoves.size) return;

  const sections = data.sections || {};
  const loadout = data.loadout || {};

  for (const [id, m] of state.recentMoves.entries()) {
    let serverContainer = null;
    let foundRow = null;

    // البحث عن موقع القطعة في رد السيرفر
    for (const [cName, bucket] of Object.entries(sections)) {
      const idx = (bucket.slots || []).findIndex((s) => s && s.instance_id === id);
      if (idx !== -1) {
        serverContainer = cName;
        foundRow = bucket.slots[idx];
        break;
      }
    }
    if (!serverContainer && loadout.slots) {
      for (const [slotKey, list] of Object.entries(loadout.slots)) {
        const slotObj = (list || []).find((s) => s && s.item && s.item.instance_id === id);
        if (slotObj) {
          serverContainer = slotKey;
          foundRow = slotObj.item;
          break;
        }
      }
    }

    // إذا كان السيرفر وضع القطعة بالفعل في الحاوية المستهدفة الصحيحة:
    if (serverContainer === m.container) {
      state.recentMoves.delete(id);
      continue;
    }

    // إذا كان السيرفر أعاد القطعة في مكانها القديم (السيرفر لسه ما حدّثش):
    // نحذفها من الحاوية القديمة اللي السيرفر باعتها
    if (serverContainer) {
      if (sections[serverContainer] && sections[serverContainer].slots) {
        sections[serverContainer].slots = sections[serverContainer].slots.filter((s) => s && s.instance_id !== id);
      }
      if (loadout.slots && loadout.slots[serverContainer]) {
        for (const slot of loadout.slots[serverContainer]) {
          if (slot.item && slot.item.instance_id === id) slot.item = null;
        }
      }
    }

    // ونثبت القطعة في مكانها الجديد اللي المستخدم نقلها إليه
    const targetRow = foundRow || m.row;
    targetRow.container = m.container;
    targetRow.wrapper_id = m.wrapper || "";

    if (loadout.slots && loadout.slots[m.container]) {
      const emptySlot = loadout.slots[m.container].find((s) => !s.item);
      if (emptySlot) emptySlot.item = targetRow;
    } else {
      if (!sections[m.container]) {
        sections[m.container] = { container: m.container, capacity: null, slots: [] };
      }
      sections[m.container].slots = sections[m.container].slots || [];
      if (!sections[m.container].slots.some((s) => s && s.instance_id === id)) {
        sections[m.container].slots.push(targetRow);
      }
    }
  }
}

async function loadSections(forceUnknown = false) {
  const reqs = [json(`/api/sections?account=${encodeURIComponent(state.account)}`)];
  if (forceUnknown || !state.newItems || !Object.keys(state.newItems).length) {
    reqs.push(loadUnknown());
  }
  const [data] = await Promise.all(reqs);
  reconcileSectionsWithRecentMoves(data);
  state.sections = data.sections || {};
  state.transferGroups = null;
  setUnlocked(data.unlocked);
  state.writes = data.writes || state.writes;
  state.loadout = data.loadout || null;
  state.locations = data.locations || null;
  state.augmentSpecs = data.augments || state.augmentSpecs;
  state.sectionsGen += 1;
  renderInventory();
}

/* بنود الباتش الجديد ملهاش اسم في الفهارس العامة — بنقرا الـ asset ids المملوكة
   اللي من غير اسم من شجرة الحساب نفسها، فالقطعة بتظهر برقمها ونعرفها. */
async function loadUnknown() {
  try {
    const d = await json(`/api/assets/unknown?account=${encodeURIComponent(state.account)}`);
    const map = {};
    (d.in_inventory || []).forEach((r) => { map[String(r.asset_id)] = r; });
    state.newItems = map;
    state.patchCandidates = d.patch_candidates || [];
  } catch { state.newItems = {}; }
}

/* تسجيل اسم لـ asset id مجهول: مرة واحدة بس، وبعدها القطعة بترجع باسمها
   وأيقونتها وتصنيفها وملكيتها بالـ ID — بتتخزن في data/catalog/asset_index_local.csv. */
async function identifyAsset(assetId) {
  const cands = (state.patchCandidates || []).filter((c) => c && c.name);
  const ask = `In-game name for this item (asset id: ${assetId})` +
    (cands.length ? `\nLatest patch candidates: ${cands.map((c) => c.name).join(" | ")}` : "");
  const name = String(window.prompt(ask, cands.length === 1 ? cands[0].name : "") || "").trim();
  if (!name) return;
  try {
    await post("/api/assets/name", { asset_id: assetId, name });
    await post("/api/refresh", {});
    toast(`✔ ${name} ← ${assetId}`, "good");
    await loadSections();
  } catch (e) {
    toast("⛔ " + e.message, "bad");
  }
}

async function loadLegend() {
  try {
    const f = await json(`/api/filters?account=${state.account}`);
    state.filters = f || {};
    if (!f || !f.counts || !f.counts.rarities) {
      $("#legend-box").innerHTML = "";
      return;
    }
    $("#legend-box").innerHTML = RARITY_ORDER.filter((r) => f.counts.rarities[r])
      .map((r) => `<div><i class="sw" style="background:${rarityColor(r)}"></i>${r} <span class="count">${f.counts.rarities[r]}</span></div>`).join("");
  } catch (e) {
    console.warn("[legend]", e);
    $("#legend-box").innerHTML = "";
  }
}

function rarityColor(r) {
  return { Common: "#788091", Uncommon: "#4cc94f", Rare: "#0fa2e0", Epic: "#a44de0", Legendary: "#f5b800", Amplified: "#ff4d2e" }[r] || "#788091";
}

// كلاس الندرة بتاع الـ CSS (--arc-r / --arc-glow) — بيخلي أي أيقونة في أي لوحة
// تتلوّن بلون درجاتها زي البلاطات الأساسية.
function rarCls(r) {
  return "r-" + (RARITY_ORDER.find((x) => x.toLowerCase() === String(r || "").toLowerCase()) || "Common");
}

function badgeInk(r) {
  return { Common: "#ffffff", Uncommon: "#06170c", Rare: "#06131c", Epic: "#ffffff", Legendary: "#14161e", Amplified: "#ffffff" }[r] || "#ffffff";
}

async function loadLog() {
  const d = await json("/api/actions/log?limit=12&account=" + encodeURIComponent(state.account || ""));
  state.writes = d.writes || state.writes;
  $("#log-box").innerHTML = d.log.length ? d.log.map((row) => {
    const ok = row.status === "executed";
    return `<div class="log-row ${ok ? "ok" : "bad"}"><b>${esc(row.kind)}</b>
      <span>${esc(row.account)} · ${row.items} · ${new Date(row.ts * 1000).toLocaleTimeString("en-GB")}</span>
      <em>${esc(String(row.response || row.status).slice(0, 90))}</em></div>`;
  }).join("") : `<p class="note">No actions yet.</p>`;
}

/* ------------------------------------------------------------------ render */
/* التجميع على (الاسم اللي بيتعرض | الصحة | بصمة الملحقات). الاسم هو اللي المستخدم
   شايفه فعلاً وهو نفسه اللي كارت التفاصيل بيعرضه. */
function groupTiles(rows, stacked = state.stacked) {
  if (!stacked) return rows.map((r) => ({ ...r, ids: [r.instance_id], wrappers: [r.wrapper_id], qty: r.qty }));
  const map = new Map();
  for (const r of rows) {
    const dura = durabilityVisible(r) ? durabilityInfo(r) : null;
    const key = `${displayNameOf(r)}|${dura ? `${dura.current}/${dura.max}` : ""}|${attachmentSignature(r)}`;
    if (!map.has(key)) map.set(key, { ...r, ids: [], wrappers: [], qty: 0, instances: [] });
    const g = map.get(key);
    g.qty += r.qty || 0;
    g.ids.push(r.instance_id);
    g.wrappers.push(r.wrapper_id);
    g.instances.push(r);
  }
  return [...map.values()];
}

/* الاسم اللي بيظهر في البلاطة وفي كارت التفاصيل — مكان واحد عشان التجميع
   والعرض ما يختلفوش. */
function displayNameOf(row) {
  const base = String(row.display_name || row.name || "");
  const lvl = tierLabel(row);
  return lvl && !base.trim().toUpperCase().endsWith(" " + lvl.toUpperCase()) ? `${base} ${lvl}` : base;
}

function durabilitySortPct(t) {
  if (!durabilityVisible(t)) return -1;
  const info = durabilityInfo(t);
  const max = Number(info.max) || 0;
  if (!max) return -1;
  return (Number(info.current) || 0) / max;
}

function categoryRank(t) {
  const group = String(t.group || "");
  const kind = String(t.arctracker_type || t.type || "").trim().toLowerCase();
  if (group === "Crafting Materials" && PLANT_TYPES.has(kind)) return 6;
  return CATEGORY_RANK[group] || 7;
}

function baseItemName(t) {
  return String(t.display_name || t.name || "").toLowerCase().replace(/\s+(i{1,3}|iv|v)$/i, "");
}

function itemLevelRank(t) {
  const level = Number(t.level) || 0;
  if (level) return level;
  const quality = Number(t.quality_level) || 0;
  if (quality) return quality + 1;
  const suffix = String(t.display_name || t.name || "").trim().match(/\s+(i{1,3}|iv|v)$/i);
  return suffix ? ({ i: 1, ii: 2, iii: 3, iv: 4, v: 5 }[suffix[1].toLowerCase()] || 0) : 0;
}

function sortTiles(tiles) {
  const by = state.sortBy || "category";
  const nameOf = (t) => String(t.display_name || t.name || "").toLowerCase();
  const rank = (t) => {
    const i = RARITY_ORDER.indexOf(t.rarity);
    return i < 0 ? 99 : i;
  };
  const sameItem = (a, b) => durabilitySortPct(b) - durabilitySortPct(a)
    || (Number(b.qty) || 0) - (Number(a.qty) || 0);
  const byName = (a, b) => nameOf(a).localeCompare(nameOf(b)) || sameItem(a, b);
  const byCategory = (a, b) => {
    const ga = categoryRank(a), gb = categoryRank(b);
    if (ga !== gb) return ga - gb;
    const sa = CATEGORY_SUBRANK[a.group] || 0, sb = CATEGORY_SUBRANK[b.group] || 0;
    if (sa !== sb) return sa - sb;
    const ra = rank(a), rb = rank(b);
    if (ra !== rb) return rb - ra;
    const na = baseItemName(a), nb = baseItemName(b);
    if (na !== nb) return na.localeCompare(nb);
    const la = itemLevelRank(a), lb = itemLevelRank(b);
    if (la !== lb) return lb - la;
    return sameItem(a, b);
  };
  return [...tiles].sort((a, b) => {
    if (by === "rarity") return rank(a) - rank(b) || byName(a, b);
    if (by === "name") return byName(a, b);
    if (by === "value") return itemTotalValue(b, b.qty) - itemTotalValue(a, a.qty) || byName(a, b);
    return byCategory(a, b);
  });
}

function searchNeedle(q) {
  return String(q || "").trim().toLowerCase().replace(/[\u2018\u2019]/g, "'");
}
function matchesSearch(t, q) {
  const needle = searchNeedle(q);
  if (!needle) return true;
  const hay = `${t.display_name || ""} ${t.name || ""}`.toLowerCase().replace(/[\u2018\u2019]/g, "'");
  return hay.includes(needle);
}

/* --------------------------------------------------------------- QTY: كمية بالرقم
   الرقم بيتجمّع من رصّات الستاش + الأوفرستاش. لما ما يكونش في مجموع كامل بالظبط
   الموقع بيفصل الباقي من رصة أكبر على مسار التقسيم الرسمي (نفس اللي اللعبة بتعمله)،
   فالشنطة بتستلم الرقم بالضبط — ولو عدّى سقف الأكوم بيستلمه رصّتين (15 + 2). */
function assetKey(r) {
  return String(r.asset_id || r.name || "");
}

function qtyAmount() {
  const n = Math.floor(Number(state.queries.qty));
  return Number.isFinite(n) && n > 0 ? n : 0;
}

function healthRank(r) {
  // العناصر اللي مالهاش صحة (ذخيرة/خامات) بتاخد 1 عشان الترتيب مايّتاشهاش تحت السليمة.
  if (!durabilityVisible(r)) return 1;
  const info = durabilityInfo(r);
  const max = Number(info.max) || 0;
  if (!max) return 1;
  return Math.min(1, (Number(info.current) || 0) / max);
}

function pickStacks(items, want) {
  // الستاكات الأكبر من الرقم مش بتدخل الحساب: الخطة دي رصّات كاملة بس — اللي
  // عدّى الرقم بيتكمّل بالتقسيم في qtyPickFor. عند التعادل في الحجم بنرتّب بالصحة
  // (الكاملة أولاً ثم النازلة) لأن الـdp بيُفضّل الأقدم.
  const sorted = items.map((r) => ({ row: r, qty: Number(r.qty) || 0, health: healthRank(r) }))
    .filter((x) => x.qty > 0 && x.qty <= want)
    .sort((a, b) => b.qty - a.qty || b.health - a.health);
  // من نفس المقص حجمه مش محتاجين أكتر من floor(want/q) نسخة — الزيادة تنفخ الجدول وتضيع الستاكات الصغيرة
  const perQty = new Map();
  const list = [];
  for (const it of sorted) {
    const max = Math.floor(want / it.qty);
    const used = perQty.get(it.qty) || 0;
    if (used >= max) continue;
    perQty.set(it.qty, used + 1);
    list.push(it);
  }
  if (!list.length) return null;
  if (want > 4000) {
    // أرقام كبيرة: الدقة الكاملة متستاهلش مصاريف الذاكرة — بمرتين على أكبر الستاكات
    const taken = new Set();
    let left = want;
    for (let pass = 0; pass < 2 && left > 0; pass++) {
      for (const it of list) {
        if (taken.has(it.row.instance_id) || it.qty > left) continue;
        taken.add(it.row.instance_id); left -= it.qty;
        if (!left) break;
      }
    }
    const items = list.filter((x) => taken.has(x.row.instance_id)).map((x) => x.row);
    if (items.length) return { items, total: want - left, exact: left === 0, missing: left || 0 };
  }
  const BIG = 1e9;
  const rows = list.length;
  const dp = Array.from({ length: rows + 1 }, () => new Int32Array(want + 1).fill(BIG));
  const take = Array.from({ length: rows + 1 }, () => new Uint8Array(want + 1));
  dp[0][0] = 0;
  for (let i = 0; i < rows; i++) {
    const q = list[i].qty;
    const cur = dp[i]; const next = dp[i + 1];
    for (let s = 0; s <= want; s++) {
      if (cur[s] < next[s]) { next[s] = cur[s]; take[i + 1][s] = 0; }
      if (s >= q && cur[s - q] + 1 < next[s]) { next[s] = cur[s - q] + 1; take[i + 1][s] = 1; }
    }
  }
  const rebuild = (sum) => {
    const out = [];
    for (let i = rows; i > 0 && sum > 0; i--) {
      if (!take[i][sum]) continue;
      out.unshift(list[i - 1].row);
      sum -= list[i - 1].qty;
    }
    return sum === 0 ? out : null;
  };
  if (dp[rows][want] < BIG) {
    const got = rebuild(want);
    if (got) return { items: got, total: want, exact: true };
  }
  const over = items.map((r) => ({ row: r, qty: Number(r.qty) || 0 }))
    .filter((x) => x.qty > want).sort((a, b) => a.qty - b.qty)[0];
  let bestBelow = null;
  for (let s = want - 1; s > 0; s--) {
    if (dp[rows][s] >= BIG) continue;
    const got = rebuild(s);
    if (got) { bestBelow = { items: got, total: s, exact: false, missing: want - s }; break; }
  }
  if (bestBelow && (!over || (want - bestBelow.total) <= (over.qty - want))) return bestBelow;
  if (over) return { items: [over.row], total: over.qty, exact: false, extra: over.qty - want };
  return bestBelow;
}

/* رصة حقيقية = عنصر واحد بكمية > 1. القطع المستقلة (سلاح/شيلد/أوجمنت) كمية كل
   واحدة 1 ومتجمعة بصرياً بس، فالسحب الجزئي منها بياخد أول N قطعة من غير تقسيم. */
function isRealStack(r) {
  return (Number(r.qty) || 0) > 1;
}

function qtyPickFor(items, want) {
  const usable = items.filter((r) => (Number(r.qty) || 0) > 0);
  if (!usable.length) return null;
  // القطع المستقلة: كمية كل واحدة 1 ومفيش فيها حاجة تتقسم — أول N قطعة
  // (كاملة الصحة الأول) بتتاخد زي ما هي.
  const single = usable.filter((r) => isRealStack(r) === false)
    .sort((a, b) => healthRank(b) - healthRank(a));
  const stacksOnly = usable.filter(isRealStack);
  if (single.length) {
    const cap = Math.max(0, ...stacksOnly.map((r) => Number(r.stack_size) || 0));
    const takes = stacksOnly.length ? fillTakes(stacksOnly, want, cap) : null;
    const done = takes ? takes.reduce((s, t) => s + t.amount, 0) : 0;
    const picked = single.slice(0, Math.max(0, want - done));
    return { items: (takes ? takes.map((t) => t.row) : []).concat(picked),
             total: done + picked.length, exact: done + picked.length === want,
             takes: takes || [], splits: (takes || []).filter((t) => t.partial).length,
             pieces: picked.length };
  }
  const whole = pickStacks(usable, want);
  if (whole && whole.exact) return whole;
  /* الرقم مستحيل برصّات كاملة: فضّي اللي يدخل فيه من المخزن ونفصل الباقي من
     أقرب رصة أكبر — نفس خطة الباكند (actions.fill_takes)، والتنفيذ بيعيدها
     على الشجرة الحية فالرقم هنا للعرض بس. */
  const cap = Math.max(0, ...usable.map((r) => Number(r.stack_size) || 0));
  const takes = fillTakes(usable, want, cap);
  if (takes) {
    return { items: takes.map((t) => t.row), total: want, exact: true, takes,
             splits: takes.filter((t) => t.partial).length };
  }
  return whole || { items: usable.slice(0, 1), total: 0, exact: false, short: true };
}

/* نسخة العرض من خطة الباكند: رصّات كاملة الأول، والفاضل chunks ما بتعديش سقف الأكوم. */
function fillTakes(rows, want, cap) {
  const pool = rows.map((r) => ({ row: r, amount: Number(r.qty) || 0 }))
    .filter((s) => s.amount > 0 && s.row.instance_id)
    .sort((a, b) => b.amount - a.amount);
  let left = want;
  if (!pool.length || pool.reduce((s, x) => s + x.amount, 0) < left) return null;
  const takes = [];
  for (const s of pool) {
    if (left <= 0) break;
    if (s.amount <= left) {
      takes.push({ row: s.row, amount: s.amount, partial: false });
      left -= s.amount;
      s.amount = 0;
    }
  }
  while (left > 0) {
    const chunk = cap > 1 ? Math.min(left, cap) : left;
    const cands = pool.filter((s) => s.amount > chunk);
    if (!cands.length) return null;
    const s = cands.reduce((a, b) => (b.amount < a.amount ? b : a));
    takes.push({ row: s.row, amount: chunk, partial: true });
    s.amount -= chunk;
    left -= chunk;
  }
  return takes;
}

function markQtyPick(ids) {
  if (!state.qtyPick) state.qtyPick = new Set();
  ids.forEach((i) => state.qtyPick.add(i));
}

function qtyStripHTML(rows, poolRows, want) {
  if (!rows.length) {
    return `<div class="qty-strip"><div class="qty-head"><span>QTY ${num(want)}</span>
      <b>Type the item name in search first</b><i>or select a stack from the stash</i></div></div>`;
  }
  const byAsset = new Map();
  for (const r of poolRows) {
    const k = assetKey(r);
    if (!k) continue;
    if (!byAsset.has(k)) byAsset.set(k, []);
    byAsset.get(k).push(r);
  }
  const picks = [];
  for (const r of rows) {
    const k = assetKey(r);
    if (!k || byAsset.has(k) === false || picks.some((p) => p.asset === k)) continue;
    const items = byAsset.get(k) || [];
    const total = items.reduce((s, x) => s + (Number(x.qty) || 0), 0);
    const pick = qtyPickFor(items, want);
    if (pick) picks.push({ asset: k, items, total, pick });
  }
  picks.sort((a, b) => (b.pick.exact - a.pick.exact) || (b.total - a.total));
  const shown = picks.slice(0, 12);
  const head = `<div class="qty-head"><span>QTY ${num(want)}</span>
    <b>${shown.filter((p) => p.pick.exact).length} of ${picks.length} types give the exact amount</b>
    <i>Drag the card to the backpack — whatever cannot be made from whole stacks is split off a larger stack on the official split route</i></div>`;
  if (!shown.length) {
    return `<div class="qty-strip">${head}<p class="note">No type in the stash has stacks adding up to ${num(want)}.
      Type the item name in search first, or raise the number.</p></div>`;
  }
  return `<div class="qty-strip">${head}<div class="qty-cards">${shown.map(qtyCardHTML).join("")}</div></div>`;
}

function qtyCardHTML(entry) {
  const { pick } = entry;
  const first = pick.items[0] || entry.items[0];
  const ids = pick.items.map((r) => r.instance_id);
  const takes = pick.takes || [];
  const pieces = takes.length
    ? takes.map((t) => num(t.amount) + (t.partial ? " *" : "")).join(" + ")
    : pick.items.map((r) => num(Number(r.qty) || 0)).join(" + ") || "0";
  const note = pick.exact ? (pick.splits ? `splits off ${num(pick.splits)}` : "")
    : pick.missing ? `missing ${num(pick.missing)}`
    : pick.extra ? `extra ${num(pick.extra)}` : "all available is less";
  markQtyPick(ids);
  // أي بطاقة QTY بتسحب خطة كاملة من الباكند (الستاكات الكاملة لوحدها ما بتوصلش
  // للرقم، وخانة مشغولة في الشنطة كانت بتبلع الرصة كلها). البطاقة اللي ما بتحتاجش
  // تقسيم بتفضل بنفس الرقم، بس بتروح على نفس مسار التحقق.
  const fill = pick.exact && pick.total
    ? ` data-fill-asset="${esc(entry.asset)}" data-fill-amount="${Number(pick.total) || 0}"` : "";
  const tip = pick.exact && pick.splits
    ? `${esc(first.display_name || first.name)} — ${esc(pieces)} (* split off a larger stack)`
    : `${esc(first.display_name || first.name)} — ${esc(pieces)}`;
  return `<div class="qty-card ${pick.exact ? "exact" : "approx"}"${fill} title="${esc(tip)}">
    ${tileHTML({ ...first, qty: pick.total || first.qty, ids }, "stash")}
    <span class="qty-pieces">${pieces}</span>
    <span class="qty-note">${note}</span>
  </div>`;
}

/* التقسيم كتابة حقيقية على المنبع: بنسأله split ونردّ رده. مفيش استنى ولا مراقبة —
   الموقع نفسه هو اللي بيعمل الطلب، زي باقي المواقع بالظبط. */
async function runSplit(row, amount, targetWrapper) {
  const name = row.display_name || row.name || "";
  if (!writesLive()) { toast(writeBlockMsg(), "bad"); return; }
  const btns = document.querySelectorAll("[data-split-run]");
  btns.forEach((b) => { b.disabled = true; b.textContent = "… waiting for the gateway"; });
  let out = null;
  try {
    out = await post("/api/actions/split", {
      account: state.account, instance_id: row.instance_id,
      target_wrapper_id: targetWrapper || "", amount, confirmed: true,
    });
  } catch (e) {
    out = { executed: false, detail: String(e && e.message || e).slice(0, 200) };
  }
  btns.forEach((b) => { b.disabled = false; });
  $("#modal").hidden = true;
  if (out && out.executed) toast("✔ " + (out.detail || "Split done."), "ok");
  else toast("⛔ " + ((out && (out.detail || out.error)) || "The gateway did not answer."), "bad", 9000);
  try { await post("/api/refresh"); } catch { /* المنبع مش reachable — من الكاش */ }
  await loadSections();
  renderInventory();
}

function fieldFocus() {
  // بنمسك مكان المؤشر قبل ما innerHTML يرمي العقدة: من غيره أي رسم في الخلفية
  // (poll) كان بيحوّله لآخر النص أو بيشيله خالص وهو بيكتب.
  const el = document.activeElement;
  if (!el || !el.id || ["INPUT", "TEXTAREA"].indexOf(el.tagName) < 0) return null;
  let sel = null;
  try {
    if (el.selectionStart !== null && el.selectionStart !== undefined) {
      sel = [el.selectionStart, el.selectionEnd];
    }
  } catch { sel = null; }
  return { id: el.id, sel };
}

/* ------------------------------------------------- قطعك المكررة بنفس الـ id تحت الستاش
   فوق: نتائج بحثك في حسابك إنت كاملة. تحتها: قطعك إنت اللي نفس الـ instance id بتاعها
   موجود في حساب تاني عندك — دي اللي بتختفي لو اتنقلت، فالأمان إنها تتبيّع الأول.
   البلاطات حية (بِتاعتك): تتحدد وتسحب للشنطة وتبيعها، والشارة فوق كل بلاطة بتقول
   كل حساب تاني فيه كام قطعة من نفس الـ id. */
let xToken = 0;

/* الاسم المختصر لحساب التاب ده — نفس شكل _acc_short في الباكند (G22 من G22#7334). */
function myAccountLabel() {
  const a = (state.accounts || []).find((x) => x.name === state.account) || {};
  const text = String(a.display_name || a.label || a.name || state.account || "").trim();
  return text.split("#")[0].trim() || text;
}

/* كارت التفاصيل لبلاطة ميتة (حساب تاني): هوفر بس — بلا سحب ولا تحديد ولا كليك يمين. */
function wireForeignHover(host) {
  host.querySelectorAll(".tile.cat").forEach((t) => {
    if (!t.dataset.ids) return;
    t.onmouseenter = (e) => showCard(t, e);
    t.onmousemove = (e) => positionCard(e);
    t.onmouseleave = () => hideCard();
  });
}

/* أيقونة لكل حساب تاني: قطعك المكررة عنده بالذات + كام قطعة منه عنده.
   نفس الخانة ممكن تظهر في أكتر من أيقونة (لو id مكرر في حسابين) — التحديد Set
   فبيتنضّف تلقائياً، وده أدق: أيقونة G22 بتحدد الـ 17 اللي عند G22 بس. */
function xaccTilesByAccount(rows) {
  const buckets = new Map();
  for (const r of rows) {
    const dura = durabilityVisible(r) ? durabilityInfo(r) : null;
    const dk = dura ? `${dura.current}/${dura.max}` : "";
    for (const o of r.others || []) {
      const key = `${r.name}|${dk}|${o.label}`;
      const b = buckets.get(key) || { label: o.label, theirs: 0, rows: [] };
      b.rows.push(r);
      b.theirs += Number(o.qty) || 0;
      buckets.set(key, b);
    }
  }
  const list = [...buckets.values()].map((b) => ({
    label: b.label, theirs: b.theirs, tile: groupTiles(b.rows, true)[0],
  }));
  /* ترتيب مستقر: جوه نفس العنصر والصحة، الحسابات بالأبجدية — فالأيقونتين بتاعت
     Il Toro بيطلعوا جنب بعض (G18 ثم G22) بدل ما يتفرقوا. */
  list.sort((a, b) => a.label.toLowerCase().localeCompare(b.label.toLowerCase()));
  return sortTiles(list.map((x) => ({ ...x.tile, xaccLabel: x.label, xaccTheirs: x.theirs })));
}

async function fillCrossAccountResults(q) {
  const host = $("#xacc-results");
  if (!host || !String(q || "").trim()) return;
  const token = ++xToken;
  let out;
  try {
    out = await post("/api/item/cross", { account: state.account, q });
  } catch {
    if (token === xToken && document.contains(host)) host.hidden = true;
    return;
  }
  if (token !== xToken || !document.contains(host)) return;
  const rows = out.rows || [];
  /* مفيش تكرار بنفس الـ id — المنطقة تختفي كلها، حتى الفاصل المتقطع. */
  if (!rows.length) { host.hidden = true; return; }
  const tiles = xaccTilesByAccount(rows);
  const pieces = rows.reduce((a, r) => a + (Number(r.qty) || 1), 0);
  const accs = [...new Set(rows.flatMap((r) => (r.others || []).map((o) => o.label)))]
    .sort((a, b) => a.toLowerCase().localeCompare(b.toLowerCase()));
  host.innerHTML = `<p class="xacc-head">Your items (${esc(myAccountLabel())}) with the same id `
    + `also appear in another account: ${num(rows.length)} cells (${num(pieces)} pieces) · icon per account: `
    + `${esc(accs.join(", "))} · drag them to the backpack or sell them</p>`
    + tiles.map((t) => tileHTML(t, "stash")).join("");
  host.querySelectorAll(".tile").forEach((el, i) => {
    wireTile(el);
    const t = tiles[i];
    if (!t || !t.xaccLabel) return;
    const box = document.createElement("span");
    box.className = "xacc-chips";
    box.innerHTML = `<span class="xacc-chip">${esc(t.xaccLabel)} ×${num(t.xaccTheirs)}</span>`;
    el.appendChild(box);
  });
  updateSelCount();
}

/* ------------------------------------------------------- FIND ME: الكميات في كل حساب
   مقارنة باردة للنوع ده في حساباته التانية — سطر لكل حساب وبلاطة لكل (اسم + صحة)
   بكميتها، مكرر أو مش مكرر. البلاطات ميتة بس بتفتح كارت التفاصيل بالهوفر. */
let fmToken = 0;

/* بلاطة حساب تاني: ميتة (بلا drag ولا تحديد) بس ليها data-ids عشان كارت الهوفر.
   نفس أشكال tileHTML: البلوبرنت/الديزاين/الستينسل خلفيتهم بتختلف عن السلاح العادي. */
function findmeTileHTML(r) {
  const dura = durabilityVisible(r) ? durabilityInfo(r) : null;
  const lvl = tierLabel(r);
  const kind = itemKind(r);
  const special = kind === "design" || kind === "stencil";
  const tip = `${r.account_label} — ${r.display_name || r.name}`
    + `${dura ? ` · dur ${dura.current}/${dura.max}` : ""}`
    + ` · ${num(r.cells)} cells (${num(r.qty)} pieces)`;
  return `<div class="tile cat fm r-${esc(r.rarity)} ${kind === "blueprint" ? "bp" : ""} ${special ? kind : ""}" title="${esc(tip)}"
       data-ids="${esc((r.ids || [r.instance_id]).join(","))}" data-name="${esc(r.name)}"
       data-qty="${Number(r.qty) || 1}" data-kind="${esc(kind)}" data-type="${esc(r.arctracker_type || r.type || "")}">
    ${r.image ? `<img loading="lazy" src="${asset(r.image)}" alt="" onerror="this.style.visibility='hidden'">` : `<span class="ph">?</span>`}
    ${special ? `<span class="cat-strip">${KIND_ICON[kind]}<span>${kind.toUpperCase()}</span></span>` : ""}
    ${lvl ? `<span class="lvl">${lvl}</span>` : ""}
    ${dura ? `<span class="dura ${dura.warn ? "dura-" + dura.warn : ""}">${dura.current}/${dura.max}</span>` : ""}
    ${r.qty > 1 ? `<span class="qty">${num(r.qty)}</span>` : ""}
  </div>`;
}

function findmeGroupHTML(g) {
  return `<div class="fm-grp">
    <p class="fm-acc">${esc(g.account_label)}<span class="fm-count">${num(g.cells)} cells · ${num(g.pieces)} pieces</span></p>
    <div class="fm-row">${g.rows.map(findmeTileHTML).join("")}</div>
  </div>`;
}

async function fillFindMe(q) {
  const host = $("#findme");
  if (!host || !String(q || "").trim()) return;
  const token = ++fmToken;
  let out;
  try {
    out = await post("/api/item/findme", { account: state.account, q });
  } catch {
    if (token === fmToken && document.contains(host)) host.hidden = true;
    return;
  }
  if (token !== fmToken || !document.contains(host)) return;
  const groups = (out && out.groups) || [];
  /* مفيش أي حساب تاني فيه حاجة من البحث — القسم يختفي كله. */
  if (!groups.length) { host.hidden = true; return; }
  const more = out.total > out.shown ? ` · showing ${num(out.shown)} of ${num(out.total)}` : "";
  /* صفوف الحسابات التانية بتتسجّل عشان findRow تلقاها وكارت التفاصيل يفتح عليها. */
  groups.forEach((g) => g.rows.forEach((r) => (r.ids || [r.instance_id]).forEach((id) => {
    state.foreign[id] = r;
  })));
  host.innerHTML = `<p class="findme-head">FIND ME — «${esc(String(q).trim())}» `
    + `in each of your other accounts${more}</p>`
    + groups.map(findmeGroupHTML).join("");
  wireForeignHover(host);
}

/* --------------------------------------------------------------- قطع مكرر الـ id
   دي القطع بتاعتك إنت اللي نفس الـ instance id بتاعها موجود في حساب تاني — الخطرة
   على النقل (بتختفي). الباكند بيرجّع آيدز حسابك بس، فالفلتر ده بيصفّي مخزنك إنت
   وتقدر تحددها كلها وتسحبها للشنطة أو تبيعها. */
let dupeToken = 0;
function dupeMap() {
  return state.dupes && state.dupesFor === state.account ? state.dupes : null;
}
function dupeRows() {
  const map = dupeMap();
  if (!map) return [];
  const q = state.queries.inventory || "";
  return ["stash", "overflow"]
    .flatMap((k) => ((state.sections[k] || {}).slots || []))
    .filter((r) => r && r.instance_id && map[r.instance_id] && matchesSearch(r, q));
}
/* DUP id متصنف بالحساب: مجموعة بلاطات لكل حساب تاني، وفوقها اسم الحساب لوحده.
   البلاطة بتاعت الحساب المفتوح دايماً وبتفضل تتسحب وتتحدد، بس بتظهر تحت كل حساب
   بيشاركها نفس الـ id — لأن التكرار بيختلف من قطعة لتانية. */
function dupAccountGroups(rows, dmap) {
  const byAcc = new Map();
  for (const r of rows) {
    for (const acc of (dmap[r.instance_id] || [])) {
      if (!byAcc.has(acc)) byAcc.set(acc, []);
      byAcc.get(acc).push(r);
    }
  }
  return [...byAcc.entries()]
    .sort((a, b) => a[0].toLowerCase().localeCompare(b[0].toLowerCase()))
    .map(([acc, list]) => ({ acc, tiles: sortTiles(groupTiles(list, true)) }));
}

async function fillDupes() {
  if (dupeMap()) return;
  const token = ++dupeToken;
  const acc = state.account;
  let out;
  try {
    out = await post("/api/item/dupes", { account: acc });
  } catch { return; }
  if (token !== dupeToken || acc !== state.account) return;
  state.dupes = (out && out.map) || {};
  state.dupesFor = acc;
  if (state.view === "inventory" && $("#column-host")) renderInventory();
}

/* ---------------------------------------------------- TO MAIN: اللي ينفع يتنقل
   قطع الحساب الفرعي اللي نوعها مش موجود في الحسابات الأساسية — دي اللي ينفع
   يتسحب ويأخده الأساسي قبل ما الفرعي يتقفل. النقل يدوي: توكن الفرعي ما بيقدرش
   على الأساسي، فالفلتر بيعرض ويحدد بس. */
let toMainToken = 0;
function toMainMap() {
  return state.tomain && state.tomainFor === state.account ? state.tomain : null;
}
function toMainRows() {
  const map = toMainMap();
  if (!map) return [];
  const q = state.queries.inventory || "";
  return ["stash", "overflow"]
    .flatMap((k) => ((state.sections[k] || {}).slots || []))
    .filter((r) => r && r.instance_id && map[r.instance_id] && matchesSearch(r, q));
}
async function fillTomain() {
  if (toMainMap()) return;
  const token = ++toMainToken;
  const acc = state.account;
  let out;
  try {
    out = await post("/api/item/tomain", { account: acc });
  } catch { return; }
  if (token !== toMainToken || acc !== state.account) return;
  state.tomain = (out && out.map) || {};
  state.tomainFor = acc;
  state.tomainMains = (out && out.mains) || [];
  state.tomainIsMain = !!(out && out.is_main);
  if (state.view === "inventory" && $("#column-host")) renderInventory();
}

let transferRequest = 0;
let transferPending = "";
async function fillTransferCandidates() {
  const account = state.account;
  if (state.transferFor === account && state.transferGroups || transferPending === account) return;
  const request = ++transferRequest;
  transferPending = account;
  let out;
  try {
    out = await post("/api/item/transfer-candidates", { account });
  } finally {
    if (request === transferRequest) transferPending = "";
  }
  if (request !== transferRequest || account !== state.account) return;
  state.transferFor = account;
  state.transferGroups = out.groups || [];
  if (!state.transferGroups.some((group) => group.account === state.transferTarget)) {
    state.transferTarget = state.transferGroups[0]?.account || "";
  }
  renderInventory();
}

function transferGroup() {
  return state.transferFor === state.account
    ? (state.transferGroups || []).find((group) => group.account === state.transferTarget) : null;
}

function renderInventory() {
  const host = $("#column-host");
  if (!host) return;
  hideCard();
  state.qtyPick = new Set();
  const keep = fieldFocus();
  if (keep) { state.searchFocus = keep.id; state.searchSel = keep.sel; }
  const scrolled = {};
  host.querySelectorAll(".inv-body[data-scroll]").forEach((b) => { scrolled[b.dataset.scroll] = b.scrollTop; });
  host.innerHTML = [stashColumn(), backpackColumn(), loadoutColumn()].join("");
  fillCrossAccountResults(state.queries.inventory || "").catch(() => {});
  fillFindMe(state.queries.inventory || "").catch(() => {});
  fillDupes().catch(() => {});
  fillTomain().catch(() => {});
  fillTransferCandidates().catch(() => {});
  wireInventory();
  host.querySelectorAll(".inv-body[data-scroll]").forEach((b) => {
    if (scrolled[b.dataset.scroll]) b.scrollTop = scrolled[b.dataset.scroll];
  });
  updateSelCount();
  paintSync();
}
function renderColumns() { renderInventory(); }

function invColumn(key, cls, head, body, foot) {
  return `<section class="inv-col ${cls}" data-container="${esc(key)}">
    <div class="inv-head">${head}</div>
    <div class="inv-body" data-scroll="${esc(key)}" data-drop="${esc(key)}">${body}</div>
    ${foot || ""}
  </section>`;
}

function stashColumn() {
  const stash = state.sections.stash || { slots: [], capacity: 0 };
  const overflow = state.sections.overflow || { slots: [], capacity: 0 };
  const stashSlots = stash.slots || [];
  const ovfSlots = overflow.slots || [];
  const slots = [...stashSlots, ...ovfSlots];
  const capacity = (stash.capacity || 0) + (overflow.capacity || 0);
  const q = state.queries.inventory || "";
  const want = qtyAmount();
  const dmap = dupeMap();
  const target = transferGroup();
  const candidateIds = new Set(target?.ids || []);
  const onlyDupes = state.dupeFilter;
  /* فلتر "TO MAIN": قطع الحساب الفرعي اللي نوعها مش موجود في الأساسي — تتنقل قبل
     ما الفرعي يتقفل. الحساب الأساسي نفسه مفيش عند حاجة ياخدها، فالزرار بيختفي. */
  const tmap = toMainMap();
  const onlyMain = state.tomainFilter && !state.tomainIsMain;
  const tcount = tmap && !state.tomainIsMain ? slots.filter((r) => r && candidateIds.has(r.instance_id)).length : 0;
  const filtered = slots.filter((r) => matchesSearch(r, q) && (!onlyMain || candidateIds.has(r.instance_id)));
  /* البلاطة اللي ملهاش أيقونة بتترسم "?" — دي قطع الباتش الجديد اللي الفهارس لسه
     معرفاهاش. الزرار بيبدّل بينها وبين اللوحة النضيفة، والعداد بيقول كام واحدة.
     البحث بيكشفها دايمًا: اسم البلاطة نفسها "Item <asset id>" فلو كتب الرقم
     وهو مخفي عايز يلاقيها قدامه، مش صفحة فاضية. */
  const visible = (state.showUnknown || String(q).trim()) ? filtered : filtered.filter((r) => r.image);
  /* وقت البحث أو الفلتر التجميع إجباري: عايز قطع حسابك في صف واحد مجمّع ومرتب
     بالصحة، مش خمس بلاطات متطابقة. زر STACKED بيضل يتحكم في الوضع العادي. */
  const stackedNow = state.stacked || !!String(q).trim() || !!onlyDupes || !!onlyMain;
  const tiles = sortTiles(groupTiles(visible, stackedNow));
  const head = `<span class="bar purple"></span><h2>STASH</h2>
    <button class="ghost tiny toggle ${stackedNow ? "on" : ""}" data-act="stacked"
            title="${q || onlyDupes || onlyMain ? "Grouping is on — your items are merged and sorted by durability" : "Merge identical items into one tile"}">STACKED</button>
    <button class="ghost tiny toggle ${state.dupeFilter ? "on" : ""}" data-act="dupes"
            title="Repeated IDs grouped by account">DUP id</button>
    ${state.tomainIsMain ? "" : `<button class="ghost tiny toggle ${state.tomainFilter ? "on" : ""}" data-act="tomain"
            title="Pieces on this account whose item type is not on ${esc((state.tomainMains || []).join(" / ")) || "your main accounts"} — the ones worth carrying over before this account is emptied. Click to see only them and select them all at once; the move itself is in-game, your token here cannot write to another account.">TO MAIN${tmap ? " · " + num(tcount) : " · …"}</button>`}
    <button class="ghost tiny" id="btn-merge-all"
            title="Merges every pile in the account up to each type stack cap — stash and overflow together, run on the official gateway.">⇄ MERGE ALL</button>
    <div class="spacer"></div>
    <input class="inline-search inv-search" id="inv-search" data-search="inventory" type="search"
           placeholder="SEARCH INVENTORY..." value="${esc(q)}" autocomplete="off"
           title="Search STASH + OVERFLOW — press Esc twice to clear this and QTY">
    <input class="inline-search inv-qty" id="inv-qty" data-qty-input="1" type="text" inputmode="numeric"
           maxlength="6" placeholder="QTY" value="${esc(state.queries.qty || "")}" autocomplete="off"
           title="Type a number — it groups the stacks whose total equals that number, splits the rest off a larger stack when the number cannot be made exactly, then lets you drag them in one go">
    <span class="cap-box" title="STASH ${num(stashSlots.length)}/${num(stash.capacity || 0)} · OVERFLOW ${num(ovfSlots.length)}/${num(overflow.capacity || 0)}">${num(slots.length)}/${num(capacity)}</span>`;
  const pool = q ? visible : slots.filter((r) => state.selected.has(r.instance_id));
  const strip = want ? qtyStripHTML(pool, slots, want) : "";
  const xHost = q ? `<div class="xacc-results" id="xacc-results"><p class="note empty-col">…</p></div>` : "";
  const fmHost = q ? `<div class="findme" id="findme"><p class="note empty-col">…</p></div>` : "";
  const duplicateRows = slots.filter((r) => matchesSearch(r, q) && (state.showUnknown || String(q).trim() || r.image));
  const duplicateGroups = onlyDupes && dmap ? dupAccountGroups(duplicateRows, dmap) : [];
  const duplicatesHTML = onlyDupes ? (dmap ? duplicateGroups.map((group) => `<p class="dup-acc">ALSO IN ${esc(group.acc)}</p><div class="dup-row">${group.tiles.map((tile) => tileHTML(tile, "stash")).join("")}</div>`).join("") || `<p class="note empty-col">No repeated IDs in other accounts</p>` : `<p class="note empty-col">Loading repeated IDs...</p>`) : "";
  const transferHeading = onlyMain ? `<p class="dup-acc">${target ? `TO ${esc(target.label)} · IDs absent in saved snapshot · ${target.last_success ? esc(new Date(target.last_success * 1000).toLocaleString()) : "Target never synchronized — synchronize before transfer"}` : "Right-click an account name and mark a main destination"}</p>` : "";
  const renderedTiles = tiles.map((t) => tileHTML(t, "stash")).join("");
  const tilesHTML = onlyDupes ? duplicatesHTML : transferHeading + strip + (tiles.length ? (onlyMain ? `<div class="dup-row">${renderedTiles}</div>` : renderedTiles) : `<p class="note empty-col">${onlyMain ? "No suggestions for this destination" : "EMPTY"}</p>`);
  return invColumn("stash", "col-stash", head, tilesHTML + xHost + fmHost);
}

function slotCell(s, key, idx) {
  const item = s && s.item ? s.item : null;
  const wrapper = s?.wrapper_id || "";
  return `<div class="slot-cell ${item ? "filled" : ""} ${wrapper ? "" : "no-wrapper"}"
       title="${esc(wrapper ? "" : NO_WRAPPER_HINT)}"
       data-slot-cell="${esc(key)}" data-slot="${esc(key)}" data-slot-index="${idx}"
       data-wrapper="${esc(wrapper)}" ${wrapper ? "" : 'data-nowrapper="1"'}>
    ${item ? tileHTML(item, key, { slot: key }) : `<span class="slot-cross"></span>`}
    ${lockMark(wrapper)}
  </div>`;
}

/* الخانة بلا wrapper = قالب من مواصفات الأوجمنت لسه اللعبة ما بنيحه في حاوية الحساب.
   بتقفل أول ما تدخل ماتش، فبنبيّنها مقفولة بدل ما نسيبها ترفض السحبة في الصمت. */
const NO_WRAPPER_HINT = "This cell is not built yet in the game backpack — the equipped augment is larger than the container the game created for your account. The game rebuilds the backpack as soon as you enter a match, and after that this cell becomes usable.";
function lockMark(wrapper) {
  return wrapper ? "" : `<span class="slot-lock" aria-hidden="true">🔒</span>`;
}

function backpackColumn() {
  const lo = state.loadout || {};
  const capacity = lo.capacity?.backpack || 0;
  const slots = lo.slots?.backpack || [];
  const pv = pvLive();
  if (pv) {
    /* الشنطة بتتلبّى بشكل البروفيل: الخانات الفاضية خانات فعلية هتمل لما التنفيذ
       يمشي، فCLEAR/UNDO بتاع اللوحة الحيّة بيتخبوا في المعاينة ما دامت مش بتاعتها. */
    const cards = pvCardsIn("backpack");
    const cap = pvCapOf("backpack", capacity);
    const gaps = cards.filter((c) => c.status === "missing").length;
    const head = `<span class="bar blue"></span><h2>BACKPACK</h2>
      <span class="pv-who" title="Preview of «${esc(pv.loadout.name)}» — nothing has been moved yet">PREVIEW · ${esc(pv.loadout.name)}</span>
      <div class="spacer"></div>
      <span class="cap-box" title="${gaps ? num(gaps) + " backpack cells are missing from the profile — see the bar under LOADOUT." : "Every backpack cell in this profile is already on the account."}">${num(cards.length)} / ${num(cap)}${gaps ? ` <b class="cap-locked">${num(gaps)}✕</b>` : ""}</span>`;
    return invColumn("backpack", "col-backpack", head, pvBackpackBody());
  }
  const used = slots.filter((s) => s.item).length;
  /* الخانة اللي ليها wrapper_id واحدة بتاعت الحاوية الحقيقية اللي اللعبة عاملها على
     الحساب. الخانات الزايدة مجرد قالب من مواصفات الأوجمنت — اللعبة تبنيها أول ما
     تدخل ماتش، فالعدّاد بيربط السعة المبنية بس ويوري القالب المقفول جنبه. */
  const built = slots.filter((s) => s.wrapper_id).length;
  const template = Math.max(0, capacity - built);
  const shownCap = built || capacity;
  let cells = "";
  for (let i = 0; i < capacity; i++) cells += slotCell(slots.find((x) => x.slot_index === i) || null, "backpack", i);
  const loc = state.locations || {};
  const pointed = loc.pointed !== false;
  let capTip = pointed
    ? `Backpack capacity comes from the equipped container «${loc.loadout || "?"}» — that is the very container the game reads. The game rebuilds the backpack container as soon as you enter a match, so anything the site adds shows up in the next match.`
    : `⚠ The container the equipped slot points to «${loc.equipped_loadout || "?"}» is not the augment backpack «${loc.loadout || "?"}» — items go into the equipped container itself, and the site tries to point the slot at the augment backpack automatically.`;
  if (template) capTip += ` — the equipped augment declares ${capacity} cells, but the container on the account has only ${built} built. The ${template} locked cells unlock on their own as soon as you enter one match.`;
  const head = `<span class="bar blue"></span><h2>BACKPACK</h2><div class="spacer"></div>
    <button class="ghost tiny" id="bp-clear" title="CLEAR — return the backpack contents to the stash">CLEAR</button>
    <button class="ghost tiny" id="bp-clear-all" title="CLEAR ALL — whole loadout + backpack to the stash">CLEAR ALL</button>
    <button class="ghost tiny" data-undo-btn title="UNDO — step back one move at a time">UNDO</button>
    <span class="cap-box" title="${esc(capTip)}">${pointed ? "" : "⚠ "}${used} / ${shownCap}${template ? ` <b class="cap-locked">+${template}🔒</b>` : ""}</span>`;
  const body = `<div class="slot-grid bp-grid">${cells}</div>`;
  return invColumn("backpack", "col-backpack", head, body);
}

function bigSlot(key) {
  const slots = state.loadout?.slots?.[key] || [];
  const s = slots[0] || null;
  return `<div class="big-slot">
    <div class="slot-cell big ${s?.item ? "filled" : ""} ${s?.wrapper_id ? "" : "no-wrapper"}" data-slot-cell="loadout" data-slot="${key}"
         data-slot-index="0" data-wrapper="${esc(s?.wrapper_id || "")}" ${s?.wrapper_id ? "" : 'data-nowrapper="1"'}
         title="${esc(s?.wrapper_id ? "" : NO_WRAPPER_HINT)}">
      ${s?.item ? tileHTML(s.item, "loadout", { slot: key, equip: true }) : `<span class="slot-cross"></span>`}
      ${lockMark(s?.wrapper_id)}
    </div>
    <div class="slot-label">${SLOT_META[key].label}</div>
  </div>`;
}

function loadoutSection(key, cap) {
  if (!cap) return "";
  const slots = state.loadout?.slots?.[key] || [];
  const used = slots.filter((s) => s.item && s.slot_index < cap).length;
  let cells = "";
  let locked = 0;
  for (let i = 0; i < cap; i++) {
    const s = slots.find((x) => x.slot_index === i) || null;
    if (!s?.wrapper_id) locked++;
    cells += `<div class="slot-cell ${s?.item ? "filled" : ""} ${s?.wrapper_id ? "" : "no-wrapper"}" data-slot-cell="loadout" data-slot="${key}"
        data-slot-index="${i}" data-wrapper="${esc(s?.wrapper_id || "")}" ${s?.wrapper_id ? "" : 'data-nowrapper="1"'}
        title="${esc(s?.wrapper_id ? "" : NO_WRAPPER_HINT)}">
      ${s?.item ? tileHTML(s.item, "loadout", { slot: key, equip: true }) : `<span class="slot-cross"></span>`}
      ${lockMark(s?.wrapper_id)}</div>`;
  }
  return `<div class="lo-section">
    <div class="lo-sec-head"><span class="sec-dot"></span><span class="sec-label">${SLOT_META[key].label}</span>
      <div class="spacer"></div><span class="sec-count"
        title="${locked ? esc(NO_WRAPPER_HINT) : ""}">${used}/${cap}${locked ? " · " + locked + "🔒" : ""}</span></div>
    <div class="slot-row">${cells}</div>
  </div>`;
}

function loRowsHTML(list) {
  if (!list.length) return `<p class="note empty-col">No saved loadouts yet — press SAVE.</p>`;
  return list.map((l) => {
    const on = String(state.loadoutSel) === String(l.id);
    return `<div class="lo-row ${on ? "on" : ""}" data-lo="${l.id}"
        title="${esc(l.name)} — by ${esc(l.owner || "")}">
      <span class="lo-rname">${esc(l.name)}</span>
      <span class="lo-own">${esc(l.owner || "")}</span>
      <button class="lo-rename" data-lo-rename="${l.id}" title="Rename">✎</button>
      <button class="lo-del" data-lo-del="${l.id}" title="Delete loadout">✕</button>
    </div>`;
  }).join("");
}

/* ============================== معاينة البروفيل ==============================
   اختيار قالب من القائمة ما بينفذش حاجة: الشبكة نفسها بتتلبّى بشكل البروفيل
   أول — كل خانة بكارت وبحالتها (READY نفس القطعة / SUB نسخة تانية من نفس النوع /
   NO CELL الخانة مش مبنية / MISSING مش عندك). الناقصة بتاخد مسار من زرار المسار
   اللي في الشريط: ⚒ تصنيع أو 🛒 شراء — ولو المسار المختار مش متوفر للقطعة دي
   بتيبان بوسم تاني صريح، واللوحة قبل التنفيذ بتعدّد اللي هيتجيب بالمسار التاني.
   المعاينة كلها من الداتا المحلية وشجرة الحساب: مفيش ولا طلب كتابة واحد. */

const PV_TAG = { ready: "READY", substituted: "SUB", blocked: "NO CELL", missing: "MISSING", short: "SHORT" };
const PV_DROP_HINT = "Profile preview is on — the board shows the saved template, not your live inventory. Press APPLY or ✕ first.";

function pvLive() {
  const p = state.loPreview;
  if (!p) return null;
  return String(p.loadout?.id) === String(state.loadoutSel) && p.account === state.account ? p : null;
}
function pvCardsIn(key) {
  const p = pvLive();
  return p ? (p.cards || []).filter((c) => c.slot === key) : [];
}
/* السعة في المعاينة = سعة الحساب أو آخر خانة في البروفيل — عشان البروفيل اللي
   اتحفظ بأوجمنت أكبر ما يضيعش منه خانة. */
function pvCapOf(key, live) {
  const last = pvCardsIn(key).reduce((m, c) => Math.max(m, (Number(c.slot_index) || 0) + 1), 0);
  return Math.max(Number(live) || 0, last);
}
function pvMode() { return state.loFillMode === "buy" ? "buy" : "craft"; }
/* المسار الفعلي للبند: اللي اختاره، ولو مستحيل ياخد التاني اللي ممكن. */
function pvRoute(card) {
  const fill = card.fill || {};
  const want = pvMode();
  if (fill[want] && fill[want].possible) return want;
  const other = want === "buy" ? "craft" : "buy";
  if (fill[other] && fill[other].possible) return other;
  return "";
}
function pvCross(card) { const r = pvRoute(card); return !!r && r !== pvMode(); }

/* الخانة صاحبة بس بعدد أقل من المحفوظ: APPLY يسحب اللي في الستاش أولاً
   (نفس ⇄)، وبعده يصنّع أو يشتري الفاضل بس. */
function pvShortHint(card) {
  const have = Number(card.short_have) || 0;
  const need = Number(card.short_need) || Number(card.qty) || 0;
  const gap = Number(card.short_by) || Math.max(0, need - have);
  const pulled = Number(card.from_stash) || 0;
  const cap = Number(card.cap) || 0;
  const head = `${card.name} — the cell holds ${num(have)} of the ${num(need)} the profile saved (short ${num(gap)}).`;
  const ceiling = card.over_cap ? ` A stack of this holds ${num(cap)} at most, so the cell fills to ${num(cap)}.` : "";
  const pull = pulled > 0 ? ` APPLY pulls ${num(pulled)} from your stash into this cell.` : "";
  if (!card.fill) return `${head}${ceiling}${pull}`
    + (pulled ? "" : " You have none of this type in the stash — craft or buy the missing units first.");
  const route = pvRoute(card);
  if (!route) {
    return `${head}${ceiling}${pull} The rest cannot be crafted (${(card.fill.craft || {}).detail || "?"}) `
      + `and cannot be bought (${(card.fill.buy || {}).detail || "?"}).`;
  }
  const opt = card.fill[route] || {};
  const why = pvCross(card)
    ? ` — ${pvMode() === "craft" ? "crafting is not possible" : "buying is not possible"}, so it goes the other way`
    : "";
  return `${head}${ceiling}${pull} To get the other ${num(card.need_to_get)}: ${route === "craft"
    ? `craft ${num(opt.crafts)} run${Number(opt.crafts) > 1 ? "s" : ""} of ${num(opt.per_craft)} at ${opt.station_label || "the station"}`
    : `buy ${num(opt.buys)}× from ${opt.trader || "a trader"} for ${num(opt.total)} ${(opt.currency || {}).name || "Coins"}`}${why}`;
}

function pvHint(card) {
  if (card.status === "short") return pvShortHint(card);
  if (card.status === "ready") {
    return card.in_place ? `${card.name} — already sitting in this cell, nothing to move.`
                         : `${card.name} — the very piece the profile saved is on the account, ready to place.`;
  }
  if (card.status === "substituted") {
    return `${card.name} — a different copy of the same item will be used (it is in the ${(card.current || {}).container || "stash"}).`;
  }
  if (card.status === "blocked") return `${card.name} — ${card.detail || "that cell is not built in the account tree yet."}`;
  const fill = card.fill || {};
  const route = pvRoute(card);
  if (!route) {
    return `${card.name} ×${num(card.qty)} — cannot be crafted (${(fill.craft || {}).detail || "?"}) `
      + `and cannot be bought (${(fill.buy || {}).detail || "?"}).`;
  }
  const opt = fill[route] || {};
  const why = pvCross(card)
    ? ` — ${pvMode() === "craft" ? "crafting is not possible" : "buying is not possible"}, so it goes the other way`
    : "";
  return `${card.name} ×${num(card.qty)} — ${route === "craft"
    ? `craft ${num(opt.crafts)}× at ${opt.station_label || "the station"}`
    : `buy ${num(opt.buys)}× from ${opt.trader || "a trader"} for ${num(opt.total)} ${(opt.currency || {}).name || "Coins"}`}${why}`;
}

function pvTile(card) {
  const cls = String(card.status || "missing");
  const wantRoute = cls === "missing" || (cls === "short" && !!card.fill);
  const route = wantRoute ? pvRoute(card) : "";
  const cross = wantRoute && route && pvCross(card);
  const tag = cls === "short" ? `SHORT −${num(card.short_by)}`
    : (card.in_place ? "IN PLACE" : (PV_TAG[cls] || "MISSING"));
  return `<div class="tile cat pv r-${esc(card.rarity || "Common")} pv-${cls}${route ? " pv-via-" + route : ""}"
      data-pv="${esc(String(card.i ?? ""))}" title="${esc(pvHint(card))}">
    ${card.image ? `<img loading="lazy" src="${asset(card.image)}" alt="" onerror="this.style.visibility='hidden'">` : `<span class="ph">?</span>`}
    ${Number(card.qty) > 1 ? `<span class="qty">${num(card.qty)}</span>` : ""}
    <span class="pv-tag pv-tag-${cls}${card.in_place && cls !== "short" ? " pv-tag-in" : ""}">${tag}</span>
    ${route ? `<span class="pv-via${cross ? " cross" : ""}">${route === "craft" ? "⚒" : "🛒"}</span>` : ""}
  </div>`;
}

function pvCell(card, big) {
  return `<div class="slot-cell pv-cell ${big ? "big " : ""}${card ? "filled" : "pv-empty"}">${card ? pvTile(card) : `<span class="slot-cross"></span>`}</div>`;
}

function pvBigSlot(key) {
  const cards = pvCardsIn(key);
  const card = cards.find((c) => (Number(c.slot_index) || 0) === 0) || cards[0] || null;
  return `<div class="big-slot">${pvCell(card, true)}<div class="slot-label">${SLOT_META[key].label}</div></div>`;
}

function pvSection(key, liveCap) {
  const cap = pvCapOf(key, liveCap);
  if (!cap) return "";
  const cards = pvCardsIn(key);
  let cells = "";
  for (let i = 0; i < cap; i++) cells += pvCell(cards.find((c) => (Number(c.slot_index) || 0) === i) || null, false);
  const gaps = cards.filter((c) => c.status === "missing" || c.status === "blocked").length;
  return `<div class="lo-section">
    <div class="lo-sec-head"><span class="sec-dot"></span><span class="sec-label">${SLOT_META[key].label}</span>
      <div class="spacer"></div><span class="sec-count ${gaps ? "pv-warn" : ""}">${cards.length ? cards.length + " / " + cap : "empty"}</span></div>
    <div class="slot-row">${cells}</div>
  </div>`;
}

function pvLoadoutBody() {
  const cap = (state.loadout || {}).capacity || {};
  const big = ESSENTIAL_SLOTS.map((key) => pvBigSlot(key)).join("");
  const quick = pvSection("quick_use", cap.quick_use || 0);
  const augmented = (cap.augmented || 0) > 0 || pvCardsIn("augmented_slots").length
    ? pvSection("augmented_slots", cap.augmented || 0) : "";
  const safe = pvSection("safe_pocket", cap.safe_pocket || 0);
  return `<div class="big-grid">${big}</div>${quick}${augmented}${safe}`;
}

function pvBackpackBody() {
  const cap = pvCapOf("backpack", (state.loadout || {}).capacity?.backpack || 0);
  const cards = pvCardsIn("backpack");
  let cells = "";
  for (let i = 0; i < cap; i++) cells += pvCell(cards.find((c) => (Number(c.slot_index) || 0) === i) || null, false);
  return `<div class="slot-grid bp-grid">${cells}</div>`;
}

/* الشريط تحت: حالة البروفيل + الحساب بالمسار المختار + زرار المسار + APPLY.
   التكلفة بتتلم لكل عملة لوحدها عشان شراء بند بـ Tokens وبند بـ Coins ما يخلطش. */
function pvCosts(jobs) {
  const by = {};
  jobs.forEach((j) => {
    if (j.route !== "buy") return;
    const name = (j.opt.currency || {}).name || "Coins";
    by[name] = (by[name] || 0) + (Number(j.opt.total) || 0);
  });
  return by;
}

function pvBarHTML() {
  const p = pvLive();
  if (!p) return "";
  const s = p.summary || {};
  const jobs = pvJobs();
  const costs = pvCosts(jobs);
  const mode = pvMode();
  const blocked = (p.cards || []).filter((c) => c.status === "blocked").length;
  // الخانات اللي لسه محتاجة تصنيع/شراء بعد اللي هيتسحب من المخزن.
  const shortNeed = Number(s.short_needing) || 0;
  const topupUnits = Number(s.short_covered) || 0;
  const gaps = (s.missing || 0) + blocked + shortNeed;
  const craftN = jobs.filter((j) => j.route === "craft").length;
  const buyN = jobs.filter((j) => j.route === "buy").length;
  const unfill = (s.missing || 0) + shortNeed - jobs.length;
  const extras = Number(s.extras) || 0;
  const money = Object.keys(costs).map((k) => `${num(costs[k])} ${esc(k)}`).join(" + ");
  const bits = [`<b>${num(s.ready || 0)}</b> in place`];
  if (s.short) bits.push(`<b>${num(s.short)}</b> short on count${topupUnits ? ` (<b>${num(topupUnits)}</b> unit${topupUnits > 1 ? "s" : ""} pulled from your stash)` : ""}`);
  if (craftN) bits.push(`<b>${num(craftN)}</b> to craft`);
  if (buyN) bits.push(`<b>${num(buyN)}</b> to buy${mode === "craft" ? " <i>(no materials)</i>" : ""}`);
  if (money) bits.push(`<b>${money}</b>`);
  if (blocked) bits.push(`<b>${num(blocked)}</b> cell${blocked > 1 ? "s" : ""} not built`);
  if (unfill > 0) bits.push(`<b class="pv-bad">${num(unfill)}</b> unavailable`);
  if (extras) bits.push(`<b>${num(extras)}</b> extra item${extras > 1 ? "s go" : " goes"} back to the stash`);
  return `<div class="pv-bar ${gaps || extras ? "gaps" : "clean"}">
    <span class="pv-state">${gaps ? "ITEMS MISSING · " + num(gaps)
      : (extras ? "EXTRA IN YOUR KIT · " + num(extras) : "PROFILE READY")}</span>
    <span class="pv-bits">${bits.join(" · ")}</span>
    <div class="spacer"></div>
    <div class="pv-mode" title="How to get what the profile is missing — whole cells and missing units inside a cell: craft them from your stash materials, or buy them from your traders. A piece that cannot go the chosen way is marked on its card.">
      <button type="button" class="pv-m ${mode === "craft" ? "on" : ""}" data-pv-mode="craft">⚒ CRAFT</button>
      <button type="button" class="pv-m ${mode === "buy" ? "on" : ""}" data-pv-mode="buy">🛒 BUY</button>
    </div>
  </div>`;
}

/* بنود التعبئة: بند لكل خانة ناقصة (أو ناقصة عدد) ولها مسار ممكن. forced = مش المسار اللي اختاره. */
function pvJobs() {
  const p = pvLive();
  if (!p) return [];
  return (p.cards || [])
    .filter((c) => c.status === "missing" || (c.status === "short" && c.fill))
    .map((c) => ({ card: c, route: pvRoute(c), opt: (c.fill || {})[pvRoute(c)] || {} }))
    .filter((j) => j.route)
    .map((j) => Object.assign(j, { forced: j.route !== pvMode() }));
}

function loadoutColumn() {
  const lo = state.loadout || {};
  const cap = lo.capacity || {};
  const saved = lo.saved || [];
  const cur = saved.find((l) => String(state.loadoutSel) === String(l.id));
  const pv = pvLive();
  const head = `<span class="bar purple"></span><h2>LOADOUT</h2><div class="spacer"></div>
    <div class="lo-dd ${state.loPopOpen ? "open" : ""}" id="lo-dd">
      <button class="lo-select" id="lo-toggle" type="button"
              title="Saved loadouts — the same list in all your accounts">
        <span class="lo-cur">${esc(cur ? cur.name : "LOADOUT")}</span><span class="chev">▾</span></button>
      <div class="lo-pop" id="lo-pop" ${state.loPopOpen ? "" : "hidden"}>${loRowsHTML(saved)}</div>
    </div>
    <button class="ghost tiny" id="lo-save">SAVE</button>
    <button class="btn-load" id="lo-apply"
            title="${pv ? (Number((pv.summary || {}).short_covered) > 0
                            ? "Pull the short cells' units from your stash, fill the rest the chosen way, then place the profile"
                            : "Fill the missing cells the chosen way, then place the profile")
                        : "Place the selected profile — pick it from the list first"}">APPLY</button>
    <button class="ghost tiny" id="lo-reset" title="${pv ? "Cancel the preview — back to the live board" : "Back to the current state"}">✕</button>`;
  if (pv) {
    return invColumn("loadout", "col-loadout", head, pvLoadoutBody(), pvBarHTML());
  }
  const big = ESSENTIAL_SLOTS.map((key) => bigSlot(key)).join("");
  const quick = loadoutSection("quick_use", cap.quick_use || 0);
  const augmented = (cap.augmented || 0) > 0 ? loadoutSection("augmented_slots", cap.augmented) : "";
  const safe = loadoutSection("safe_pocket", cap.safe_pocket || 0);
  return invColumn("loadout", "col-loadout", head,
    `<div class="big-grid">${big}</div>${quick}${augmented}${safe}`);
}

function isWeapon(t) {
  return FIREARM_TYPES.includes(String(t.arctracker_type || t.type || "").trim().toLowerCase());
}

// البوابة المباشرة باتبعت level=0 للسلاح، فالدرجة (I..V) بتتقري من آخر الاسم
// ("Il Toro IV" -> IV) — نفس شكل اللعبة.
const TIER_IN_NAME = /\s(I|II|III|IV|V|VI|VII|VIII|IX|X)$/;
function tierLabel(t) {
  const lvl = Number(t.level) || 0;
  if (lvl > 0 && lvl < 5) return ROMAN[lvl] || "";
  const m = String(t.display_name || t.name || "").match(TIER_IN_NAME);
  return m ? m[1] : "";
}

function durabilityInfo(t) {
  // البوابة بتدي durability كنسبة من 1، فالسقف الحقيقي بيجي من durability_max
  // (130 لسلاح Tier IV مثلاً) ولولاها بنحسبها من جودة السلاح.
  let max = Number(t.durability_max) || Number(t.max_durability) || 0;
  if (max <= 1) max = isWeapon(t) ? 100 + (Number(t.quality_level) || 0) * 10 : 100;
  const raw = t.durability;
  if (raw === null || raw === undefined) {
    return { current: max, max, warn: null };
  }
  const md = Number(t.max_durability) || 1;
  let pct, current;
  if (Number(raw) > 1 && md <= 1) {
    current = Math.round(Number(raw));
    pct = Math.min(1, current / max);
  } else {
    pct = md > 0 ? Number(raw) / md : 0;
    current = Math.round(pct * max);
  }
  current = Math.max(0, Math.min(max, current));
  return { current, max, warn: current <= 0 ? "red" : pct < 0.5 ? "yellow" : null };
}

function durabilityVisible(t) {
  // السلاح/الدرع/الأوجمنت دايمًا ليه صحة: arctracker بغلّط ويرجّع has_durability=false
  // لأسلحة فعلية (Canto IV مثلاً وداتابيزه بتقول 35%)، فالنوع أسبق من الراية.
  const kind = String(t.arctracker_type || t.type || "").trim().toLowerCase();
  if (isWeapon(t) || kind === "augment" || kind === "shield") return true;
  if (typeof t.has_durability === "boolean") return t.has_durability;
  return t.show_durability === 1 || t.show_durability === true;
}

/* البوابة بتبعت خانات السلاح تحت attachments (اسمها التاريخي؛ مش modifiers ولا children)،
   وكل خانة {slot_name, is_empty, display_name, image_filename, rarity}. أي شكل تاني بنسيبه
   فاضي بدل ما نرمي استثناء. */
const ATT_LIST_KEYS = ["attachments", "modifiers", "children", "slots"];

function attachmentsOf(t) {
  if (!t) return [];
  let list = t.attachments;
  if (typeof list === "string") {
    try { list = JSON.parse(list); } catch { list = []; }
  }
  if (!Array.isArray(list)) {
    const alt = ATT_LIST_KEYS.map((key) => t[key]).find((v) => Array.isArray(v));
    list = alt || [];
  }
  return list.filter((a) => a && typeof a === "object");
}

/* الـ Stencil لون تجميلي مش مرفق مادي: البوابة بترفض فكّه، وخانته هي نفس خانة
   mod_slot فمش لازم تتحسب ضمن 4 خانات السلاح. */
const STENCIL_SLOT_ASSET_ID = "67839673";

function isStencil(a) {
  if (!a || typeof a !== "object") return false;
  if (a.is_stencil) return true;
  if (String(a.type || "").trim().toLowerCase() === "stencil") return true;
  const name = String(a.display_name || a.name || "").trim().toLowerCase();
  return name.includes("stencil") && String(a.slot_asset_id || "") === STENCIL_SLOT_ASSET_ID;
}

function modsOf(list) {
  return (list || []).filter((a) => !isStencil(a));
}

function stencilsOf(t) {
  return attachmentsOf(t).filter(isStencil);
}

/* بصمة الملحقات: سلاح عليه مودات ميتجمعش مع سلاح فاضي، ولا Compensator III
   مع Compensator II. الخانة الفاضية بتتسجل بـ slot_name لوحده (نداء واحد لسلاحين
   فاضيين — typeof null === "object" لو استخدمنا "||"). */
function attachmentSignature(t) {
  const list = modsOf(attachmentsOf(t));
  if (!list.length) return "";
  const stamp = stencilsOf(t).map((a) => a.asset_id ?? a.display_name ?? a.name ?? "?").sort().join(",");
  return list.map((a) => a.is_empty
    ? `${a.slot_name || a.slot_asset_id || "?"}=`
    : `${a.slot_name || a.slot_asset_id || "?"}=${a.asset_id ?? a.display_name ?? a.name ?? "?"}`
  ).sort().join("|") + (stamp ? `#${stamp}` : "");
}

/* في كارت STACKED الأسلحة كلها بنفس الملحقات بالظبط (ده شرط التجميع)، فالخانات
   اللي بتتعرض جوه الكارت هي خانات أي قطعة منهم — مش خانات قطعة واحدة بتتكلم باسم
   المجموعة كلها. */
function sharedAttachments(rows) {
  const list = rows || [];
  if (!list.length) return [];
  let best = modsOf(attachmentsOf(list[0]));
  for (const row of list.slice(1)) {
    const other = modsOf(attachmentsOf(row));
    if (other.length !== best.length) return [];
    for (let i = 0; i < best.length; i++) {
      const a = best[i];
      const b = other[i];
      if (String(a.slot_name || "") !== String(b.slot_name || "")) return [];
      if (!!a.is_empty !== !!b.is_empty) return [];
      if (!a.is_empty && String(a.asset_id ?? "") !== String(b.asset_id ?? "")) return [];
    }
    if (other.length > best.length) best = other;
  }
  return best;
}

/* Stencil مشترك لو كل قطع البلاطة شايلين نفس اللون — السطر بيتعرض مرة واحدة. */
function sharedStencils(rows) {
  const list = rows || [];
  if (!list.length) return [];
  const stamp = (row) => stencilsOf(row).map((a) => String(a.asset_id ?? a.display_name ?? a.name ?? "")).sort().join("|");
  const first = stamp(list[0]);
  return list.every((row) => stamp(row) === first) ? stencilsOf(list[0]) : [];
}

function itemTotalValue(t, amount) {
  const value = Number(t.value) || 0;
  const md = Number(t.max_durability) || 0;
  let unit = value;
  if (t.durability !== null && t.durability !== undefined && md > 0) {
    unit = value * (Number(t.durability) / md);
  }
  let total = unit * (Number(amount) || 1);
  for (const a of attachmentsOf(t)) total += Number(a.value) || 0;
  return Math.floor(total);
}

function itemKind(t) {
  const group = String(t.group || "");
  if (group === "Designs") return "design";
  if (group === "Stencils") return "stencil";
  if (group === "Blueprints") return "blueprint";
  const kind = String(t.arctracker_type || t.type || "").toLowerCase();
  if (kind === "design") return "design";
  if (kind === "stencil") return "stencil";
  if (kind === "blueprint" || / blueprint$/i.test(String(t.display_name || t.name || ""))) return "blueprint";
  return "";
}

/* البلوبرنتات المفعلة: البوابة الرسمية بتسجّل لكل مخطط اتفعّل عقدة اسمها
   "Unlock Craft <اسم العنصر>" في شجرة الحساب نفسه، والباك إند بيقرأها مع كل
   مزامنة وبيبعتهالنا في /api/sections. يعني العلامة دي مقروءة مش مستنتَجة،
   وبتاعة الحساب المفتوح بس — فلازم البلاطات اللي لحساب تاني تفضل من غيرھا. */
const UNLOCKED = { assets: new Set(), names: new Set() };

function setUnlocked(raw) {
  const u = raw || {};
  UNLOCKED.assets = new Set((u.assets || []).map(String));
  UNLOCKED.names = new Set(u.names || []);
}

function bpLearned(t) {
  // العلامة دي للمخطوطة نفسها (بلوبرنت / ديزاين / ستنسل) بس. إثبات التفعيل بيكون
  // عقدة اسمها وأصلها اسم القطعة المصنوعة، فبدون الحارس ده كان ✔ بيطلع على
  // الأوجمنت والذخيرة — أي قطعة عادية اتصنعت من المخطط.
  if (!itemKind(t)) return false;
  if (!UNLOCKED.assets.size && !UNLOCKED.names.size) return false;
  if (t.xaccLabel || t.account_label) return false;
  if (UNLOCKED.assets.has(String(t.asset_id ?? ""))) return true;
  const name = String(t.display_name || t.name || "").trim().toLowerCase().replace(/\s+/g, " ");
  if (!name) return false;
  // "Jupiter Blueprint" = المخطوطة الخام بتاعة Jupiter: تتعلّم بنفس العلامة.
  return UNLOCKED.names.has(name) || UNLOCKED.names.has(name.replace(/ blueprint$/, ""));
}

function tileHTML(t, container, opts = {}) {
  const lvl = tierLabel(t);
  const chosen = state.selected.has(t.instance_id) || (t.ids || []).some((i) => state.selected.has(i));
  const slot = opts.slot || "";
  const equip = !!opts.equip;
  const dura = durabilityVisible(t) ? durabilityInfo(t) : null;
  const broken = !!dura && dura.warn === "red";
  const kind = itemKind(t);
  const special = kind === "design" || kind === "stencil";
  const syncing = state.syncing.has(t.instance_id) || (t.ids || []).some((i) => state.syncing.has(i));
  const picked = !opts.slot && !!state.qtyPick
    && ((t.ids || [t.instance_id]).some((i) => state.qtyPick.has(i)) || state.qtyPick.has(t.instance_id));
  // قطع بتوصل من البوابة برقم من غير اسم ولا أيقونة: بعضها نزل بعد آخر نسخة من
  // الفهرس الرسمي، وبعضها بقايا عناصر اتغيّرت أو اتشالت (اللعبة نفسها بتعرضها
  // "ITEM <id>"). من غير التلميح ده البلاطة بتبان فاضية وهي قطعة حقيقية في حسابك.
  const unnamed = !t.image && /^Item\s-?\d+$/.test(String(t.name || "").trim());
  const learned = bpLearned(t);
  return `
  <div class="tile r-${esc(t.rarity)} ${chosen ? "sel selected" : ""} ${syncing ? "is-syncing" : ""} ${t.damaged ? "dmg" : ""} ${broken ? "broken" : ""} ${equip ? "eq" : ""} ${kind === "blueprint" ? "bp" : ""} ${special ? kind : ""} ${picked ? "qty-hit" : ""} ${learned ? "bpl" : ""}"
       draggable="true" data-id="${esc(t.instance_id)}" data-ids="${esc((t.ids || [t.instance_id]).join(","))}"
       data-wrapper="${esc(t.wrapper_id)}" data-container="${esc(container)}" data-slot="${esc(slot)}"
       data-qty="${Number(t.qty) || 1}" data-group="${esc(t.group || "")}" data-kind="${esc(kind)}"
       data-asset="${esc(t.asset_id ?? "")}" data-cap="${Number(t.stack_size) || 0}"
       data-name="${esc(t.name)}" data-type="${esc(t.arctracker_type || t.type || "")}"
       ${unnamed ? `title="Unknown item: the official gateway returns it as a number with no name and no icon, and the official index has no entry for it — so the game and the site both show it like this. It really is in your account — asset ${esc(t.asset_id || "")}"` : ""}>
    ${t.image ? `<img loading="lazy" src="${asset(t.image)}" alt="" onerror="this.style.visibility='hidden'">` : `<span class="ph">?</span>`}
    ${special ? `<span class="cat-strip">${KIND_ICON[kind]}<span>${kind.toUpperCase()}</span></span>` : ""}
    ${lvl ? `<span class="lvl">${lvl}</span>` : ""}
    ${dura ? `<span class="dura ${dura.warn ? "dura-" + dura.warn : ""}">${dura.current}/${dura.max}</span>` : ""}
    ${t.qty > 1 ? `<span class="qty">${num(t.qty)}</span>` : ""}
    ${learned ? `<span class="bpl-check" title="Blueprint activated on this account">✔</span>` : ""}
    ${!equip && dura && dura.warn ? `<span class="warn warn-${dura.warn}">⚠</span>` : ""}
    ${chosen ? `<span class="sel-check" aria-hidden="true">✓</span>` : ""}
    <span class="sync-veil" aria-hidden="true"><span class="sync-ring"></span></span>
  </div>`;
}

function writesLive() {
  const w = state.writes || {};
  if (w.write_paused) return false;
  if (w.armed) return true;
  return w.move_mode === "direct_gateway" && !!w.move_armed;
}

function writeBlockMsg() {
  const w = state.writes || {};
  if (w.gateway_route_down) {
    return "⛔ Embark has the inventory write route off their gateway right now — " +
      "moves fail for every tool and account. Reads and syncing are fine, and this site " +
      "re-checks the route on its own.";
  }
  return w.write_paused
    ? "🧊 Writes are frozen — someone is playing this account right now. Say 009 when you are done."
    : "🔒 Writes are paused — say 009 to open them.";
}

/* مسارات الكتابة اللي بتفشل لسبب خارجي بتتلخص في سطر واحد: الباركاند بيقول
   الحقيقة كاملة، بس هو مش حاجة يعملها حاجة في الواجهة. */
function failText(reason, detail) {
  if (reason === "gateway_route_down") {
    return "⛔ Embark has the write route off their gateway — no tool can move items right now. " +
      "Reads are fine, and this site re-checks every minute.";
  }
  return "⛔ " + (detail || reason || "blocked");
}

/* ------------------------------------------------------------------ wiring */
function slotAccepts(slot, type, group, row) {
  const kind = String(type || "").toLowerCase();
  const firearm = FIREARM_TYPES.some((k) => kind.includes(k));
  if (slot === "gun_1" || slot === "gun_2") return firearm && !(row && row.is_blueprint);
  if (slot === "augment") return kind === "augment";
  if (slot === "shield") return kind === "shield";
  if (slot === "quick_use") return group === "Quick Use";
  return true;
}

/* ------------------------------------------------------------------ DnD rules */
/* مفيش أي فحص لنوع العنصر مقابل نوع الخانة — أي عنصر يدخل أي خانة. */
function emptyBackpackSlots(exclude = "") {
  return (state.loadout?.slots?.backpack || [])
    .filter((s) => !s.item && s.wrapper_id && s.wrapper_id !== exclude);
}

// خانتا السلاح نفس الوظيفة: سحبة سلاحين تنزل في الاتنين مع بعض
const SLOT_GROUP = { gun_1: ["gun_1", "gun_2"], gun_2: ["gun_2", "gun_1"] };
// سعة الأوجمنت بتيجي من الباب ده في lo.capacity
const CAP_KEY = { augmented_slots: "augmented" };
function slotGroupOf(slot) { return SLOT_GROUP[slot] || [slot]; }

function emptyLoadoutCells(slot, startWrapper = "") {
  const cells = [];
  const cap = state.loadout?.capacity || {};
  for (const key of slotGroupOf(slot)) {
    const list = [...(state.loadout?.slots?.[key] || [])]
      .sort((a, b) => (Number(a.slot_index) || 0) - (Number(b.slot_index) || 0));
    const limit = ESSENTIAL_SLOTS.includes(key) ? 1 : (Number(cap[CAP_KEY[key] || key]) || list.length);
    for (const s of list) {
      if (!s.item && s.wrapper_id && Number(s.slot_index) < limit) cells.push({ slotKey: key, entry: s });
    }
  }
  if (startWrapper) {
    const at = cells.findIndex((c) => c.entry.wrapper_id === startWrapper);
    if (at > 0) cells.unshift(...cells.splice(at, 1));
  }
  return cells;
}

function slotDropCheck(slot, wrapper, filled, d) {
  if (!d || !(d.ids || []).length) return { ok: false, reason: "" };
  if ((d.container === "loadout" || d.container === "backpack") && d.wrapper && wrapper && d.wrapper === wrapper)
    return { ok: false, reason: "", self: true };
  if (d.ids.length !== 1) {
    const free = slot === "backpack" ? emptyBackpackSlots(wrapper) : emptyLoadoutCells(slot, wrapper);
    if (free.length) return { ok: true, batch: true, free: free.length };
    return { ok: false, reason: slot === "backpack" ? "Backpack is full — no free cell." : "No free cell in this section." };
  }
  if (!wrapper) return { ok: false, neutral: true, reason: "This cell is not activated on the game account yet — play one match so the container gets built, then SYNC." };
  return { ok: true, swap: !!filled };
}

function dropCheck(cell, d) {
  if (!cell) return { ok: false, reason: "" };
  if (pvLive()) return { ok: false, reason: PV_DROP_HINT };
  const wrapper = cell.dataset.wrapper || "";
  const filled = cell.classList.contains("filled");
  if (cell.dataset.slotCell === "loadout") return slotDropCheck(cell.dataset.slot, wrapper, filled, d);
  if (cell.dataset.slotCell === "backpack") {
    if (!wrapper) return { ok: false, reason: "This cell is not activated on the game account yet — open the game once so the backpack expands, then SYNC." };
    return slotDropCheck("backpack", wrapper, filled, d);
  }
  return { ok: false, reason: "" };
}

function bodyDropCheck(body, d) {
  const key = body?.dataset?.scroll;
  if (!d || !(d.ids || []).length) return { ok: false, reason: "" };
  if (pvLive() && (key === "backpack" || key === "loadout")) return { ok: false, reason: PV_DROP_HINT };
  if (key === "stash") {
    if (!dropIds(d, "stash", "", "").length) return { ok: false, self: true };
    return { ok: true };
  }
  if (key === "backpack") {
    if (!dropIds(d, "backpack", "", "").length) return { ok: false, self: true };
    return { ok: true, wrappers: emptyBackpackSlots().map((s) => s.wrapper_id) };
  }
  return { ok: false, reason: "" };
}

/* نقطة الإفلات تحت الماوس: البلاطات pointer-events: none وقت السحب، فده بيرجّع
   السطر (خانة) أو الحاوية. لو الماوس فوق بلاطة وجهة للدمج/التبديل بيرجّعها قبلهم
   عشان الدمج/التبديل ياخدوا الأولوية. */
function dropHitAt(x, y) {
  const tile = mergeTileAt(x, y);
  if (tile && state.drag && tileDropRelation(state.drag, tile)) return tile;
  const hit = document.elementFromPoint(x, y);
  if (!hit) return null;
  return hit.closest(".slot-cell") || hit.closest(".inv-body");
}

/* البلاطة اللي تحت الماوس حتى لو هي pointer-events: none (الوجهات بس وهي
   قابلة للدمج/التبديل). */
function mergeTileAt(x, y) {
  const tiles = document.elementsFromPoint(x, y);
  for (const el of tiles) {
    const tile = el.closest && el.closest(".tile.dnd-live");
    if (tile) return tile;
  }
  return null;
}

function paintDropVisual(hit, x, y) {
  document.querySelectorAll(".inv-body.drop").forEach((b) => b.classList.remove("drop"));
  if (!hit) {
    document.querySelectorAll(".tile.dnd-combo, .tile.dnd-combine, .tile.dnd-swap").forEach(clearTileChoices);
    return;
  }
  if (hit.classList.contains("tile")) {
    const rel = tileDropRelation(state.drag, hit);
    if (!rel) return;
    const half = rel.combine && rel.swap ? dropChoiceOf(hit, rel, x) : (rel.combine ? "combine" : "swap");
    const painted = hit.classList.contains("dnd-combo") || hit.classList.contains("dnd-combine")
      || hit.classList.contains("dnd-swap");
    if (painted && hit.classList.contains("half-left") === (half === "combine")) return;
    document.querySelectorAll(".tile.dnd-combo, .tile.dnd-combine, .tile.dnd-swap")
      .forEach((t) => { if (t !== hit) clearTileChoices(t); });
    paintTileChoices(hit, rel, x);
    if (rel.combine && rel.swap) hit.classList.toggle("half-left", half === "combine");
    return;
  }
  document.querySelectorAll(".tile.dnd-combo, .tile.dnd-combine, .tile.dnd-swap").forEach(clearTileChoices);
  if (hit.classList.contains("inv-body")) hit.classList.add("drop");
}

function markDropTargets(d) {
  document.querySelectorAll(".slot-cell").forEach((cell) => {
    cell.classList.toggle("dnd-ok", !!dropCheck(cell, d).ok);
  });
  document.querySelectorAll(".inv-body").forEach((body) => {
    const key = body.dataset.scroll;
    if (key !== "stash" && key !== "backpack") return;
    body.classList.toggle("dnd-ok", !!bodyDropCheck(body, d).ok);
  });
  markMergeTargets(d);
}

/* الوجهات اللي ممكن يترمي عليها (دمج/تبديل) بتلبس pointer-events: auto وقت السحب
   (CSS)، والباقي pointer-events: none — فالمتصفح مش بيعمل load -hover على كل
   بلاطة بيعدي عليها الماوس. الحساب مرة واحدة وقت الـ dragstart بدل كل dragover. */
function markMergeTargets(d) {
  if (!d || !Array.isArray(d.ids) || d.ids.length !== 1) return;
  document.querySelectorAll(".inv-col .inv-body .tile:not(.cat)").forEach((tile) => {
    tile.classList.toggle("dnd-live", !!tileDropRelation(d, tile));
  });
}

function clearMergeTargets() {
  document.querySelectorAll(".tile.dnd-live").forEach((tile) => tile.classList.remove("dnd-live"));
}

function clearDropMarkers() {
  document.querySelectorAll(".dnd-ok, .drop").forEach((el) =>
    el.classList.remove("dnd-ok", "drop"));
  document.querySelectorAll(".tile.dnd-combo, .tile.dnd-combine, .tile.dnd-swap")
    .forEach(clearTileChoices);
  clearMergeTargets();
}

function endDragVisuals() {
  state.drag = null;
  document.body.classList.remove("dragging");
  if (document._rrCancelSettle) document._rrCancelSettle();
  document.querySelectorAll(".tile.drag-src").forEach((t) => t.classList.remove("drag-src"));
  clearDropMarkers();
  updateSelCount();
}

/* ------------------------------------------------------------------ دمج/تبديل بالسحب
   زي رامبارت: لما السحبة تقف فوق بلاطة تانية الخانة بتتقسم نصين — شمال دمج
   (COMBINE) ويمين تبديل (SWAP) — واللي يقع عليه الماوس وقت الإفلات هو اللي بيتنفذ.
   الدمج بيتعرض لنوع واحد وفيه مكان تحت السقف، والتبديل محتاج خانة حقيقية على
   البوابة (الأوفر فلو مالوش خانة، فبيستقبل دمج بس). */
function tileIds(tile) {
  return String(tile.dataset.ids || "").split(",").filter(Boolean);
}

function tileDropRelation(d, tile) {
  if (!d || !d.ids || d.ids.length !== 1 || !tile) return null;
  if (tile.classList.contains("cat")) return null;
  const ids = tileIds(tile);
  if (ids.length !== 1 || ids[0] === d.ids[0]) return null;
  const from = String(d.container || ""), to = String(tile.dataset.container || "");
  if (to === "stash" && from !== "stash") return null;
  if (!["stash", "backpack"].includes(from) || !["stash", "backpack"].includes(to)) return null;
  const sameCell = !!tile.dataset.wrapper && d.wrapper === tile.dataset.wrapper;
  if (sameCell) return null;
  const target = displayRow(ids[0]);
  if (!target) return null;
  const cap = Number(tile.dataset.cap) || Number(target.stack_size) || 0;
  const qty = Number(tile.dataset.qty) || 0;
  const sameAsset = !!d.asset && !!tile.dataset.asset && String(d.asset) === String(tile.dataset.asset);
  const out = { id: ids[0], combine: false, swap: false, room: 0, name: tile.dataset.name || "" };
  if (sameAsset && cap > 0 && qty < cap) {
    out.combine = true;
    out.room = cap - qty;
    out.cap = cap;
  }
  if (d.wrapper && tile.dataset.wrapper) out.swap = true;
  return out.combine || out.swap ? out : null;
}

function clearTileChoices(tile) {
  tile.classList.remove("dnd-combo", "dnd-combine", "dnd-swap", "half-left");
}

function paintTileChoices(tile, rel, clientX) {
  clearTileChoices(tile);
  if (rel.combine && rel.swap) {
    tile.classList.add("dnd-combo");
    tile.classList.toggle("half-left", dropChoiceOf(tile, rel, clientX) === "combine");
  } else if (rel.combine) tile.classList.add("dnd-combine");
  else tile.classList.add("dnd-swap");
}

function dropChoiceOf(tile, rel, clientX) {
  if (!rel.combine) return "swap";
  if (!rel.swap) return "combine";
  const box = tile.getBoundingClientRect();
  return clientX - box.left < box.width / 2 ? "combine" : "swap";
}

/* ------------------------------------------------------------------ real-server sync indicators */
function syncIdsOf(plan) {
  const ids = new Set();
  for (const m of plan.moves || []) for (const r of m.rows || []) ids.add(r.instance_id);
  return [...ids];
}
function startSync(ids, toStash) {
  if (!ids.length) return;
  ids.forEach((i) => { state.syncing.add(i); state.syncFlash.delete(i); });
  if (toStash) state.stashPending += 1;
  paintSync();
}
function endSync(ids, ok, toStash) {
  ids.forEach((i) => state.syncing.delete(i));
  if (toStash) state.stashPending = Math.max(0, state.stashPending - 1);
  if (ok) {
    ids.forEach((i) => state.syncFlash.add(i));
    setTimeout(() => { ids.forEach((i) => state.syncFlash.delete(i)); paintSync(); }, 260);
  }
  paintSync();
}
function paintSync() {
  document.querySelectorAll(".tile[data-ids]").forEach((t) => {
    const ids = (t.dataset.ids || "").split(",").filter(Boolean);
    const syncing = ids.some((i) => state.syncing.has(i));
    const flashing = ids.some((i) => state.syncFlash.has(i));
    t.classList.toggle("is-syncing", syncing);
    t.classList.toggle("sync-flash", !syncing && flashing);
  });
  document.querySelectorAll(".col-stash").forEach((c) =>
    c.classList.toggle("col-syncing", state.stashPending > 0));
  const head = document.querySelector(".col-stash .inv-head h2");
  if (head) {
    const n = state.stashPending;
    const existing = document.querySelector(".col-stash .stash-sync");
    if (n > 0) {
      const txt = n > 1 ? `⟳ ${n}` : "⟳";
      if (existing && !existing.classList.contains("done")) {
        const b = existing.querySelector("b");
        if (b && b.textContent !== txt) b.textContent = txt;
      } else {
        if (existing) existing.remove();
        const el = document.createElement("span");
        el.className = "stash-sync";
        el.innerHTML = `<span class="sync-ring"></span><b>${txt}</b>`;
        head.appendChild(el);
      }
    } else if (existing && !existing.classList.contains("done")) {
      existing.classList.add("done");
      existing.innerHTML = `<b class="ok">✓</b>`;
      setTimeout(() => {
        const el = document.querySelector(".col-stash .stash-sync");
        if (el && el.classList.contains("done")) el.remove();
      }, 700);
    }
  }
}
async function withSync(ids, toStash, fn) {
  startSync(ids, toStash);
  try {
    const out = await fn();
    endSync(ids, !!(out && out.executed), toStash);
    return out;
  } catch (err) {
    endSync(ids, false, toStash);
    throw err;
  }
}

/* ------------------------------------------------------------------ optimistic moves */
function recalcLoadoutRequired() {
  if (!state.loadout || !state.loadout.slots) return;
  state.loadout.required = ESSENTIAL_SLOTS.filter((key) =>
    !(state.loadout.slots[key] || []).some((s) => s.item)).length;
}

function snapshotMoveState(rows) {
  const sections = {};
  for (const [key, bucket] of Object.entries(state.sections || {})) {
    sections[key] = { bucket, slots: (bucket.slots || []).slice() };
  }
  const loadout = {};
  for (const [key, list] of Object.entries(state.loadout?.slots || {})) {
    loadout[key] = (list || []).map((slot) => ({ slot, item: slot.item }));
  }
  const fields = (rows || []).map((row) => ({
    row, container: row.container, wrapper_id: row.wrapper_id, slot_index: row.slot_index,
  }));
  return { sections, loadout, fields, gen: state.sectionsGen };
}

function restoreMoveSnapshot(snap) {
  for (const key of Object.keys(state.sections || {})) {
    if (!(key in snap.sections)) delete state.sections[key];
  }
  for (const [key, saved] of Object.entries(snap.sections)) {
    saved.bucket.slots = saved.slots;
    state.sections[key] = saved.bucket;
  }
  for (const list of Object.values(snap.loadout)) {
    for (const entry of list) entry.slot.item = entry.item;
  }
  for (const f of snap.fields) {
    f.row.container = f.container;
    f.row.wrapper_id = f.wrapper_id;
    f.row.slot_index = f.slot_index;
  }
  recalcLoadoutRequired();
  applyAugmentCapacity();
}

function applyOneMoveLocally(move) {
  const ids = new Set(move.rows.map((r) => r.instance_id));
  const dbContainer = move.slotKey || move.container;
  for (const bucket of Object.values(state.sections || {})) {
    if (!bucket.slots) bucket.slots = [];
    bucket.slots = bucket.slots.filter((r) => !ids.has(r.instance_id));
  }
  for (const list of Object.values(state.loadout?.slots || {})) {
    for (const slot of list || []) if (slot.item && ids.has(slot.item.instance_id)) slot.item = null;
  }
  state.recentMoves = state.recentMoves || new Map();
  for (const row of move.rows) {
    row.container = dbContainer;
    row.wrapper_id = move.wrapper || "";
    row.slot_index = move.entry ? move.entry.slot_index : null;
    state.recentMoves.set(row.instance_id, {
      container: dbContainer,
      wrapper: move.wrapper || "",
      slot_index: row.slot_index,
      row: { ...row },
      at: Date.now()
    });
  }
  if (move.entry) move.entry.item = move.rows[0];
  let bucket = state.sections[dbContainer];
  if (!bucket) bucket = state.sections[dbContainer] = { container: dbContainer, capacity: null, slots: [] };
  bucket.slots = bucket.slots || [];
  bucket.slots.push(...move.rows);
}

function applyMoveLocally(plan) {
  for (const move of plan.moves || []) applyOneMoveLocally(move);
  recalcLoadoutRequired();
  applyAugmentCapacity();
}

/* الشنطة الملبوسة بتحدد سعة الخانات — بنحسبها محليًا من مواصفات الأوجمنت عشان
   العدد يتغير في نفس اللحظة، والمزامنة بعدها بتأكد الأرقام من السيرفر. */
function augmentSpecFor(assetId) {
  const pub = state.augmentSpecs;
  if (!pub) return null;
  if (assetId === null || assetId === undefined || assetId === "") return pub.base || null;
  const all = [...(pub.augments || []), pub.base].filter(Boolean);
  const hit = all.find((s) => (s.asset_ids || []).some((id) => String(id) === String(assetId)));
  return hit || pub.base || null;
}

function applyAugmentCapacity() {
  const lo = state.loadout;
  if (!lo || !lo.slots) return;
  const item = ((lo.slots.augment || []).find((s) => s.item) || {}).item || null;
  const spec = augmentSpecFor(item ? item.asset_id : "");
  if (!spec) return;
  // رقم السيرفر (من asset_id السنابشوت) أدق من صف العنصر المحلي: لو الصف مش
  // مطابق بعدة لسه، بنفضل رقم السيرفر بدل ما نرجع للشنطة القياسية (10).
  const srv = lo.capacity || {};
  const cap = {
    backpack: Math.max(Number(srv.backpack) || 0, Number(spec.backpack) || 0),
    quick_use: Math.max(Number(srv.quick_use) || 0, Number(spec.quick_use) || 0),
    safe_pocket: Math.max(Number(srv.safe_pocket) || 0, Number(spec.safe_pocket) || 0),
    augmented: Math.max(Number(srv.augmented) || 0, Number(spec.augmented) || 0),
  };
  const filledMax = (key) => (lo.slots[key] || [])
    .filter((s) => s.item)
    .reduce((m, s) => Math.max(m, (Number(s.slot_index) || 0) + 1), 0);
  cap.quick_use = Math.max(cap.quick_use, filledMax("quick_use"));
  cap.safe_pocket = Math.max(cap.safe_pocket, filledMax("safe_pocket"));
  cap.augmented = Math.max(cap.augmented, filledMax("augmented_slots"));
  // البوابة بتسيب حاويات الأوجمنت القديم بعد التبديل — بنزود العدد بس لو الخانة
  // الفاضية الزيادة فيها عنصر، عشان السعة تفضل مواصفات الأوجمنت المجهز.
  cap.backpack = Math.max(cap.backpack, filledMax("backpack"));
  lo.capacity = cap;
  lo.augment = item
    ? { asset_id: String(item.asset_id ?? ""), name: item.name, image: item.image || "", specs: { ...cap }, item }
    : null;
}

function sourceHome(row) {
  const c = String(row?.container || "").toLowerCase();
  if (SLOT_META[c] && c !== "augmented_slots")
    return { container: "loadout", wrapper: row.wrapper_id || "", slotKey: c };
  if (c === "backpack") return { container: "backpack", wrapper: row.wrapper_id || "", slotKey: "backpack" };
  if (c === "stash") return { container: "stash", wrapper: row.wrapper_id || "", slotKey: "" };
  if (c === "overflow") return { container: "overflow", wrapper: "", slotKey: "" };
  return { container: "stash", wrapper: "", slotKey: "" };
}

function homeEntryOf(home) {
  if (home.container === "loadout")
    return (state.loadout?.slots?.[home.slotKey] || []).find((s) => s.wrapper_id === home.wrapper) || null;
  if (home.container === "backpack")
    return (state.loadout?.slots?.backpack || []).find((s) => s.wrapper_id === home.wrapper) || null;
  return null;
}

function swapPlan(old, row, target) {
  // تبديل أماكن: القديم يخرج لخانة ستاش مؤقتة، الجديد ياخد الخانة، وبعدها القديم
  // يرجع بالظبط للخانة اللي الجديد خرج منها — مش بيتحط في أي مكان فاضي على مزاجه.
  // لو الجديد جاي من الأوفر ستاش، القديم بيفضل في الأوفر (مفيش "بيت" نرجّعه ليه).
  const home = sourceHome(row);
  const steps = [
    { container: "stash", wrapper: "", rows: [old], entry: null, slotKey: "" },
    { container: target.container, wrapper: target.wrapper || "", rows: [row], entry: target.entry || null, slotKey: target.slotKey },
  ];
  if (home.container !== "overflow")
    steps.push({ container: home.container, wrapper: home.wrapper, rows: [old], entry: homeEntryOf(home), slotKey: home.slotKey });
  return steps;
}

function validateLocalMove(spec) {
  const ids = spec.instance_ids || [];
  if (!ids.length) return { ok: false, reason: "No item selected." };
  const target = String(spec.target_container || "");
  if (target === "loadout") {
    const slotKey = spec.target_slot || "";
    if (!SLOT_META[slotKey]) return { ok: false, reason: "Unknown loadout slot." };
    const rows = ids.map(findRow);
    if (rows.some((r) => !r)) return { ok: false, reason: "The item is not in the local copy — run SYNCHRONIZE." };
    if (rows.length > 1) {
      // الدفعة: أول عدد الخانات الفاضية بنفس ترتيب العرض، والباقي يفضل في مكانه
      const cells = emptyLoadoutCells(slotKey, spec.target_wrapper_id || "");
      if (!cells.length) return { ok: false, reason: "No free cell in this section." };
      const accepted = rows.slice(0, cells.length);
      const skipped = rows.slice(accepted.length);
      const moves = accepted.map((row, i) => ({
        container: "loadout", wrapper: cells[i].entry.wrapper_id, rows: [row],
        entry: cells[i].entry, slotKey: cells[i].slotKey,
      }));
      return { ok: true, moves, rows: accepted, skipped, skippedCount: skipped.length,
               container: "loadout", slotKey, wrapper: "" };
    }
    const row = rows[0];
    const list = state.loadout?.slots?.[slotKey] || [];
    const entry = spec.target_wrapper_id
      ? list.find((s) => s.wrapper_id === spec.target_wrapper_id)
      : list.find((s) => !s.item && s.wrapper_id);
    if (!entry) return { ok: false, reason: spec.target_wrapper_id ? "The cell is not on the source container." : "No free cell in this section." };
    const touched = [row];
    const moves = [];
    if (entry.item && entry.item.instance_id !== row.instance_id) {
      const old = entry.item;
      moves.push(...swapPlan(old, row, { container: "loadout", wrapper: entry.wrapper_id, slotKey, entry }));
      touched.push(old);
    } else {
      moves.push({ container: "loadout", wrapper: entry.wrapper_id, rows: [row], entry, slotKey });
    }
    return { ok: true, moves, rows: touched, container: "loadout", slotKey, wrapper: entry.wrapper_id };
  }
  if (target === "backpack") {
    const rows = ids.map(findRow);
    if (rows.some((r) => !r)) return { ok: false, reason: "Some items are not in the local copy — run SYNCHRONIZE." };
    if (ids.length === 1) {
      const entry = spec.target_wrapper_id
        ? (state.loadout?.slots?.backpack || []).find((s) => s.wrapper_id === spec.target_wrapper_id)
        : emptyBackpackSlots()[0];
      if (!entry) return { ok: false, reason: spec.target_wrapper_id ? "The backpack cell does not exist." : "Backpack is full." };
      const all = [rows[0]];
      const moves = [];
      if (entry.item && entry.item.instance_id !== rows[0].instance_id) {
        const old = entry.item;
        moves.push(...swapPlan(old, rows[0], { container: "backpack", wrapper: entry.wrapper_id, slotKey: "backpack", entry }));
        all.push(old);
      } else {
        moves.push({ container: "backpack", wrapper: entry.wrapper_id, rows: [rows[0]], entry, slotKey: "backpack" });
      }
      return { ok: true, moves, rows: all, container: "backpack", slotKey: "backpack", wrapper: entry.wrapper_id };
    }
    const entries = emptyBackpackSlots();
    if (!entries.length) return { ok: false, reason: "Backpack is full — no free cells." };
    const accepted = rows.slice(0, entries.length);
    const skipped = rows.slice(accepted.length);
    const moves = accepted.map((row, i) => ({
      container: "backpack", wrapper: entries[i].wrapper_id, rows: [row], entry: entries[i], slotKey: "backpack",
    }));
    return { ok: true, moves, rows: accepted, skipped, skippedCount: skipped.length,
             container: "backpack", slotKey: "backpack", wrapper: "" };
  }
  if (target !== "stash" && target !== "overflow") return { ok: false, reason: "Unknown destination." };
  const rows = ids.map(findRow);
  if (rows.some((r) => !r)) return { ok: false, reason: "Some items are not in the local copy — run SYNCHRONIZE." };
  return { ok: true, moves: [{ container: target, wrapper: "", rows, entry: null, slotKey: "" }], rows,
           container: target, slotKey: "", wrapper: "" };
}

function enqueueMove(spec, plan, account) {
  const snapshot = snapshotMoveState(plan.rows);
  applyMoveLocally(plan);
  startSync(syncIdsOf(plan), spec.target_container === "stash" || spec.target_container === "overflow");
  state.moveSeq += 1;
  state.moveQueue.push({ spec, plan, account, snapshot, seq: state.moveSeq });
  state.selected.clear();
  renderInventory();
  pumpMoveQueue();
}

function movePayload(account, move) {
  return {
    account,
    target_container: move.container,
    target_wrapper_id: move.wrapper || "",
    instance_ids: move.rows.map((r) => r.instance_id),
    target_slot: move.container === "loadout" ? move.slotKey : "",
  };
}

/* النقلات المنتظرة اللي ليها نفس الحساب ونفس الوجهة بتتنفذ كخطة واحدة:
   السيرفر بيخطّطها كلها على شجرة واحدة ويبعت طلب بوابة واحد بدل رحلة لكل نقلة. */
const MOVE_GROUP_MAX_IDS = 24;

function moveGroupKey(job) {
  return [job.account, job.spec.target_container || "", job.spec.slotKey || "", job.spec.wrapper || ""].join("|");
}

function takeMoveGroup() {
  const first = state.moveQueue.shift();
  const group = [first];
  const key = moveGroupKey(first);
  let ids = syncIdsOf(first.plan).length;
  let i = 0;
  while (i < state.moveQueue.length) {
    const job = state.moveQueue[i];
    if (moveGroupKey(job) !== key) { i += 1; continue; }
    const n = syncIdsOf(job.plan).length;
    if (ids + n > MOVE_GROUP_MAX_IDS) break;
    group.push(job);
    state.moveQueue.splice(i, 1);
    ids += n;
  }
  return group;
}

async function sendMove(group) {
  const moves = group.flatMap((job) => (job.plan.moves || []).map((move) => movePayload(job.account, move)));
  if (!moves.length) return { executed: true };
  let out;
  try { out = await post("/api/actions/move-batch", { account: group[0].account, moves }); }
  catch (err) { return { executed: false, error: "network", detail: "Connection failed: " + err.message }; }
  // السيرفر بيرجّع الخانات لأصلها لو التحقق فشل، فمفيش خطوة إصلاح هنا.
  if (out.executed) return { executed: true, elapsed_ms: out.elapsed_ms, items: out.items,
                             to_overflow: !!out.to_overflow, bag: out.bag || null, undo: out.undo };
  return { ...out, executed: false, restored: !!out.restored };
}

async function settleMoveFailure(job, message, partial, restored = false, reason = "") {
  if (state.recentMoves && job && job.plan && job.plan.rows) {
    job.plan.rows.forEach((r) => state.recentMoves.delete(r.instance_id));
  }
  const dropped = state.moveQueue.splice(0);
  if (reason === "gateway_route_down") {
    // الباب مقفول من عند Embark: الخطة ما اتنفذتش ومفيش حاجة اتغيّرت،
    // فنخزّنها عند السيرفر والخيط العام بيشحنها لحاله أول ما المسار يرجع.
    queueToast(await deferMoves([job, ...dropped]), reason, message);
    await loadSections().catch(() => {});
    return;
  }
  toast(failText(reason, message), "bad");
  if (restored) toast("↩ The old item is back in its place — no swap happened.", "");
  if (partial) {
    toast("↩ Part of the move ran — syncing state from the server.", "");
    await Promise.all([loadSections(), loadLog()]).catch(() => {});
    return;
  }
  if (dropped.length) toast(`↩ Cancelled ${dropped.length} pending moves and restored the state from the server.`, "");
  const stale = job.seq !== state.moveSeq || job.snapshot.gen !== state.sectionsGen;
  if (!stale && !dropped.length) {
    restoreMoveSnapshot(job.snapshot);
    renderInventory();
  } else {
    await loadSections().catch(() => {});
  }
}

async function settleMoveGroupFailure(group, message, partial = false, restored = false, reason = "") {
  if (state.recentMoves && group) {
    group.forEach((job) => {
      (job.plan?.rows || []).forEach((r) => state.recentMoves.delete(r.instance_id));
    });
  }
  if (group.length === 1) return settleMoveFailure(group[0], message, partial, restored, reason);
  // الخطة المجمّعة atomic: لو التخطيط فشل مفيش أي نقل اتنفذ، فنرجّع اللوحة من السيرفر
  // بدل ما نرجّع snapshot حركة واحدة (الباقي اتحرك optimistic على اللوحة).
  if (reason === "gateway_route_down") {
    const dropped = state.moveQueue.splice(0);
    queueToast(await deferMoves([...group, ...dropped]), reason, message);
    await loadSections().catch(() => {});
    return;
  }
  toast(failText(reason, message), "bad");
  if (restored) toast("↩ The old item is back in its place — no swap happened.", "");
  if (partial) toast("↩ Part of the move ran — syncing state from the server.", "");
  const dropped = state.moveQueue.splice(0);
  if (dropped.length) toast(`↩ Cancelled ${dropped.length} pending moves and restored the state from the server.`, "");
  await loadSections().catch(() => {});
  loadLog().catch(() => {});
}

let _loadSectionsTimer = null;
function scheduleLoadSections(delay = 3500) {
  if (_loadSectionsTimer) clearTimeout(_loadSectionsTimer);
  _loadSectionsTimer = setTimeout(() => {
    _loadSectionsTimer = null;
    loadSections().catch(() => {});
  }, delay);
}

async function pumpMoveQueue() {
  if (state.moveBusy) return;
  state.moveBusy = true;
  try {
    while (state.moveQueue.length) {
      const group = takeMoveGroup();
      const job = group[0];
      const toStash = job.spec.target_container === "stash" || job.spec.target_container === "overflow";
      const endAll = (ok) => group.forEach((g) => endSync(syncIdsOf(g.plan), ok, toStash));
      let out;
      try {
        out = await sendMove(group);
      } catch (err) {
        endAll(false);
        await settleMoveGroupFailure(group, "Connection failed: " + err.message);
        continue;
      }
      if (out.executed) {
        endAll(true);
        pushHistory(out, group.length > 1 ? `${job.spec.label || "Move"} ×${group.length}`
                                         : (job.spec.label || "Move"), job.account);
        if (out.to_overflow) toast("Stash is full 280/280 — sent to overflow, same as the game.", "");
        const bagMove = job.spec.target_container === "backpack" || job.spec.target_container === "loadout";
        if (bagMove && out.bag && out.bag.pointed === false)
          toast("⚠ Went into «" + (out.bag.container || "the container") + "» but the equipped slot still points at «" +
                (out.bag.equipped || "?") + "» — fixing the targeting.", "bad");
        // بعد ما الطابور يخلص بنرجع نقرأ من السيرفر — السعة وخانات الشنطة
        // بتتغير مع الأوجمنت ولازم الواجهة تاخد الأرقام الرسمية فورًا.
        if (!state.moveQueue.length && state.account === job.account)
          scheduleLoadSections(3500);
        loadLog().catch(() => {});
        continue;
      }
      endAll(false);
      const reason = out.result?.error || out.error || "blocked";
      await settleMoveGroupFailure(group, out.result?.detail || out.detail || reason,
                                   !!out.partial, !!out.restored, reason);
    }
  } finally {
    state.moveBusy = false;
  }
}

/* ---------------- طابور النقل المؤجّل ----------------
   مسار الكتابة عند Embark مقفول من ناحيتهم (reads شغّالة). بدل ما الضيعة تترا،
   الخطة بتتخزن على السيرفر والخيط العام بيشحنها لحاله أول ما أي مسار نقل يرجع —
   من غير ما التابض ده يفضل مفتوح. كل خطة بتتخطط من جديد على الشجرة الحيّة لحظة
   التنفيذ، فالقطعة اللي اتحركت أو اتباعت في البين بتسقط لوحدها. */

function queueSummary(ids, container) {
  const names = (ids || []).map((id) => findRow(id)).filter(Boolean)
    .map((r) => r.name + (Number(r.qty) > 1 ? " ×" + r.qty : ""));
  const shown = names.slice(0, 3).join(", ") + (names.length > 3 ? " +" + (names.length - 3) : "");
  return (shown || "Move") + " → " + String(container || "?").toUpperCase();
}

async function deferMoveSpec(account, spec) {
  if (!spec || spec.kind !== "move" || !(spec.instance_ids || []).length) return 0;
  const moves = [{target_container: spec.target_container, target_wrapper_id: spec.target_wrapper_id || "",
                  target_slot: spec.target_slot || "", instance_ids: spec.instance_ids}];
  try {
    const out = await post("/api/moves/queue", {account, moves, summary: queueSummary(spec.instance_ids, spec.target_container)});
    return out && out.ok ? 1 : 0;
  } catch (err) { return 0; }
}

function moveSummary(job) {
  return queueSummary(syncIdsOf(job.plan), job.spec.target_container);
}

async function deferMoves(jobs) {
  let queued = 0;
  for (const job of jobs || []) {
    const moves = (job.plan?.moves || []).map((m) => movePayload(job.account, m)).filter((m) => m.instance_ids.length);
    if (!moves.length) continue;
    try {
      const out = await post("/api/moves/queue", { account: job.account, moves, summary: moveSummary(job) });
      if (out && out.ok) queued += 1;
    } catch (err) { /* تخزين الطابور فشل — الرسالة تحت بتقول إن حاجة ما اتحركتش */ }
  }
  return queued;
}

function queueToast(n, reason, detail) {
  toast(n ? `⏳ Queued ${n} move${n > 1 ? "s" : ""} — they run on their own the second Embark reopens the write route.`
           : failText(reason, detail), n ? "" : "bad");
  loadQueue().catch(() => {});
}

async function loadQueue() {
  const account = state.account && state.account !== "ALL" ? state.account : "";
  try {
    const rows = await json("/api/moves/queue" + (account ? "?account=" + encodeURIComponent(account) : ""));
    const before = state.queue.count || 0;
    state.queue = { items: rows.items || [], count: rows.count || 0, route_alive: !!(rows.route || {}).alive };
    renderQueue();
    if (before && rows.count === 0) {
      toast("✔ The write route is back — the queued moves ran.", "ok");
      loadSections().catch(() => {});
      loadLog().catch(() => {});
    } else if (before && rows.count < before) loadSections().catch(() => {});
  } catch (err) { /* السيرفر مش راضي — الشيب يفضل زي ما هو */ }
}

function renderQueue() {
  const pill = $("#btn-queue");
  const pop = $("#queue-pop");
  if (!pill || !pop) return;
  const n = state.queue.count || 0;
  pill.hidden = n === 0;
  $("#queue-count").textContent = String(n);
  pop.hidden = !state.queueOpen || n === 0;
  if (!pop.hidden) {
    const routeDown = !!(state.writes || {}).gateway_route_down;
    const qNote = routeDown
      ? "Embark has the write route off their gateway. These plans are stored on this machine and run by themselves the moment it is back — this tab does not have to stay open."
      : "The write route is live. These plans are waiting for room in their destination — they replay themselves from this machine, and this tab does not have to stay open.";
    pop.innerHTML = `<div class="q-head">QUEUED MOVES<span class="q-num">${n}</span></div>` +
      `<p class="q-note">${qNote}</p>` +
      `<div class="q-list">` + state.queue.items.map((it) =>
        `<div class="q-row"><span class="q-name">${esc(it.summary || "Move")}</span>` +
        `<span class="q-age">${ageText(Math.round((Date.now() / 1000 - (it.created_at || 0)) / 60))}</span>` +
        `<button class="q-x" data-q="${esc(it.id)}" title="Drop this one">✕</button></div>`).join("") +
      `</div><div class="q-foot"><button class="pill" id="q-run" title="Ask the gateway once right now">TRY NOW</button>` +
      `<button class="pill danger" id="q-clear">CLEAR ALL</button></div>`;
    pop.querySelectorAll(".q-x").forEach((b) => b.onclick = async () => {
      await del("/api/moves/queue/" + encodeURIComponent(b.dataset.q)).catch(() => {});
      loadQueue();
    });
    const run = $("#q-run");
    if (run) run.onclick = async () => {
      run.disabled = true;
      const out = await post("/api/moves/queue/run", {}).catch(() => null);
      run.disabled = false;
      if (out && out.result === "executed") { toast("✔ Moved.", "ok"); loadSections().catch(() => {}); }
      else if (out && out.result === "route_down") toast("Still closed — Embark has not mounted a move path yet.", "");
      else toast("Tried: " + (out?.detail || out?.result || "no answer"), "bad");
      loadQueue();
    };
    const clear = $("#q-clear");
    if (clear) clear.onclick = async () => {
      const account = state.account && state.account !== "ALL" ? state.account : "";
      await post("/api/moves/queue/clear", { account }).catch(() => {});
      loadQueue();
    };
  }
}

function wireQueue() {
  const pill = $("#btn-queue");
  if (!pill) return;
  pill.onclick = (e) => {
    e.stopPropagation();
    state.queueOpen = !state.queueOpen;
    renderQueue();
  };
}

function wireInventory() {
  const gatherBtn = $("#btn-gather");
  if (gatherBtn) gatherBtn.onclick = gatherStacks;
  const spreadBtn = $("#btn-spread");
  if (spreadBtn) spreadBtn.onclick = spreadStacks;
  const allBtn = $("#btn-merge-all");
  if (allBtn) allBtn.onclick = mergeAllStacks;
  const sortBtn = $("#sort-btn");
  if (sortBtn) sortBtn.onclick = (e) => {
    e.stopPropagation();
    const pop = $("#sort-pop");
    if (!pop) return;
    pop.hidden = !pop.hidden;
    $("#sort-dd")?.classList.toggle("open", !pop.hidden);
  };
  document.querySelectorAll("#sort-pop [data-sort]").forEach((b) => b.onclick = (e) => {
    e.stopPropagation();
    state.sortBy = b.dataset.sort;
    renderInventory();
  });

  const applySearch = (e) => {
    state.queries.inventory = e.target.value;
    if (!e.target.value.trim() && state.queries.qty) {
      // الرقم بلا معنى من غير بحث: بيفضل معلّق بعد ما يخلص الكميّة فيلخبطه في المرة الجاية.
      state.queries.qty = "";
    }
    state.searchFocus = e.target.id;
    clearTimeout(searchTimer);
    searchTimer = setTimeout(renderInventory, 130);
  };
  document.querySelectorAll("[data-search='inventory']").forEach((input) => {
    input.oninput = applySearch;
  });

  const qtyInput = document.querySelector("[data-qty-input]");
  if (qtyInput) qtyInput.oninput = () => {
    /* خانة نص بأرقام بس (مش type=number): setSelectionRange على type=number بترمي
       استثناء في كروم، فالإشارة كانت بترجع لبداية الخانة بعد كل رسم و"60" بتبقى "06". */
    const digits = qtyInput.value.replace(/\D+/g, "").slice(0, 6);
    if (digits !== qtyInput.value) qtyInput.value = digits;
    state.queries.qty = digits;
    state.searchFocus = "inv-qty";
    clearTimeout(searchTimer);
    searchTimer = setTimeout(renderInventory, 160);
  };

  document.querySelectorAll('[data-act="stacked"]').forEach((b) => b.onclick = () => {
    state.stacked = !state.stacked; renderInventory();
  });

  /* stopPropagation: المستمع العام على document بيشيل التحديد أي ضغطة بره البلاطات،
     وكان بيصفّر التحديد اللي الزرار ده بيعمله في نفس اللحظة. */
  document.querySelectorAll("[data-transfer-target]").forEach((select) => select.onchange = () => {
    state.transferTarget = select.value;
    state.selected.clear();
    renderInventory();
  });
  document.querySelectorAll('[data-act="dupes"]').forEach((b) => b.onclick = (e) => {
    e.stopPropagation();
    state.dupeFilter = !state.dupeFilter;
    state.tomainFilter = false;
    state.transferGroups = null;
    if (!state.dupeFilter) state.selected.clear();
    renderInventory();
  });
  document.querySelectorAll('[data-act="dupes-pick"]').forEach((b) => b.onclick = (e) => {
    e.stopPropagation();
    const allowed = new Set(transferGroup()?.ids || []);
    state.selected = new Set(["stash", "overflow"].flatMap((key) => state.sections[key]?.slots || []).filter((row) => allowed.has(row.instance_id) && matchesSearch(row, state.queries.inventory || "") && (state.showUnknown || state.queries.inventory || row.image)).map((row) => row.instance_id));
    renderInventory();
    toast(`${num(state.selected.size)} suggested items selected — verify both accounts are synchronized before carrying them over`, "ok");
  });

  document.querySelectorAll('[data-act="tomain"]').forEach((b) => b.onclick = (e) => {
    e.stopPropagation();
    state.tomainFilter = !state.tomainFilter;
    state.dupeFilter = false;
    if (!state.tomainFilter) state.selected.clear();
    renderInventory();
  });
  document.querySelectorAll('[data-act="tomain-pick"]').forEach((b) => b.onclick = (e) => {
    e.stopPropagation();
    state.selected = new Set(toMainRows().map((r) => r.instance_id));
    renderInventory();
    toast(`${num(state.selected.size)} items your main accounts do not have — drag them to the backpack and carry them over in-game`, "ok");
  });

  /* إظهار/إخفاء بلاطات "?" (قطع الباتش اللي ملهاش اسم في الفهارس). */
  document.querySelectorAll('[data-act="unknown"]').forEach((b) => b.onclick = (e) => {
    e.stopPropagation();
    state.showUnknown = !state.showUnknown;
    localStorage.setItem("fahmy.showUnknown", state.showUnknown ? "1" : "0");
    renderInventory();
  });

  /* زارع واحد على الصفحة بيستقبل كل أحداث السحب: البلاطات نفسها pointer-events: none
     وقت السحب، فالـ target هو الحاوية/السطر تحت الماوس، وبنعرف البلاطة الحقيقية
     بـ elementsFromPoint. كده مفيش رابطة dragover شغالة على كل بلاطة. */
  document.querySelectorAll(".tile:not(.cat)").forEach(wireTile);
  if (!document._rrDropSink) {
    let paintFrame = 0;
    let settleTimer = 0;
    let settled = "";
    /* الماوس لازم يستقر فوق الخانة ~170ms قبل ما نرسم الهايلايت ونحسب القبول/الرفض.
       أثناء المرور السريع على عشرات الخانات بنصفّر المؤقت ومبنعملش أي شغل، فالباكدج
       واللوداوت مبيتحسبوش لكل خانة بيعدي عليها المؤشر في الطريق للهدف. */
    const SETTLE_MS = 170;
    document._rrCancelSettle = () => {
      if (settleTimer) { clearTimeout(settleTimer); settleTimer = 0; }
      settled = "";
    };
    const hitOf = (e) => dropHitAt(e.clientX, e.clientY);
    const clearPaint = () => {
      const live = document.querySelector(".inv-body.drop, .tile.dnd-combo, .tile.dnd-combine, .tile.dnd-swap");
      if (live) paintDropVisual(null, 0, 0);
      settled = "";
    };
    document.addEventListener("dragover", (e) => {
      const d = state.drag;
      if (!d) return;
      const el = hitOf(e);
      if (!el) { if (settleTimer) { clearTimeout(settleTimer); settleTimer = 0; } clearPaint(); return; }
      const droppable = el.classList.contains("tile") || el.dataset.slotCell
        || el.classList.contains("dnd-ok");
      if (!droppable) { if (settleTimer) { clearTimeout(settleTimer); settleTimer = 0; } clearPaint(); return; }
      e.preventDefault();
      if (e.dataTransfer) e.dataTransfer.dropEffect = "move";
      const key = el.classList.contains("tile")
        ? "t" + (el.dataset.ids || "") + el.dataset.container
        : (el.dataset.slotCell ? "c" + el.dataset.slotCell + el.dataset.slot + el.dataset.slotIndex : "b" + el.dataset.scroll);
      if (key === settled) return;
      const x = e.clientX, y = e.clientY;
      if (settleTimer) { clearTimeout(settleTimer); settleTimer = 0; }
      settleTimer = setTimeout(() => {
        settleTimer = 0;
        if (!state.drag) return;
        settled = key;
        if (paintFrame) return;
        paintFrame = requestAnimationFrame(() => {
          paintFrame = 0;
          paintDropVisual(dropHitAt(x, y), x, y);
        });
      }, SETTLE_MS);
    });
    document.addEventListener("drop", (e) => {
      const d = state.drag;
      if (!d) return;
      if (settleTimer) { clearTimeout(settleTimer); settleTimer = 0; }
      settled = "";
      const el = hitOf(e);
      if (!el) return;
      if (el.classList.contains("tile")) {
        const rel = tileDropRelation(d, el);
        if (!rel) return;
        e.preventDefault(); e.stopPropagation();
        clearTileChoices(el);
        // سحبة بكمية محددة فوق خانة شنطة مشغولة: الدمج/التبديل بينقل الرصة كلها، وده
        // اللي كان بيرمي 4 في الشنطة والرقم المطلوب 1. فالخطة بتاخد مكانها، والبابه
        // بتحط الرقم في أي خانة فاضية.
        if (d.fill && el.dataset.container === "backpack") { runFill(d.fill, ""); return; }
        const src = (d.ids || [])[0];
        if (dropChoiceOf(el, rel, e.clientX) === "combine") runCombine(src, rel);
        else runSwap(src, rel);
        return;
      }
      if (el.dataset.slotCell) {
        e.preventDefault(); e.stopPropagation();
        const check = dropCheck(el, d);
        if (!check.ok) {
          if (check.reason) toast(check.reason, "bad");
          endDragVisuals();
          return;
        }
        if (el.dataset.slotCell === "loadout") onDropTarget("loadout", el.dataset.slot, el.dataset.wrapper || "");
        else onDropTarget(el.dataset.slotCell, "", el.dataset.wrapper || "");
        endDragVisuals();
        return;
      }
      const key = el.dataset.scroll;
      if (key !== "stash" && key !== "backpack") return;
      e.preventDefault();
      const check = bodyDropCheck(el, d);
      if (!check.ok) {
        if (check.reason) toast(check.reason, "bad");
        endDragVisuals();
        return;
      }
      if (key === "backpack") onDropTarget("backpack", "", "");
      else onDropTarget("stash", "", "");
      endDragVisuals();
    });
    document._rrDropSink = true;
  }
  document.querySelectorAll(".inv-body").forEach((body) => body.onscroll = hideCard);

  const bpClear = $("#bp-clear");
  if (bpClear) bpClear.onclick = () => clearBackpack("backpack");
  const bpClearAll = $("#bp-clear-all");
  if (bpClearAll) bpClearAll.onclick = () => clearBackpack("all");
  document.querySelectorAll("[data-undo-btn]").forEach((b) => b.onclick = undoStep);
  renderUndoButtons();

  const save = $("#lo-save"); if (save) save.onclick = saveLoadout;
  const reset = $("#lo-reset");
  if (reset) reset.onclick = () => {
    state.loadoutSel = ""; state.loPopOpen = false; state.loPreview = null; renderInventory();
  };
  wireLoadoutMenu();
  wirePreview();

  if (state.searchFocus) {
    const el = document.getElementById(state.searchFocus);
    if (el) {
      const len = (el.value || "").length;
      const sel = state.searchSel;
      el.focus();
      try {
        if (sel) el.setSelectionRange(Math.min(sel[0], len), Math.min(sel[1], len));
        else el.setSelectionRange(len, len);
      } catch { /* أنواع مش بتدعم مؤشر */ }
    }
    state.searchFocus = null;
    state.searchSel = null;
  }
}

function wireTile(tile) {
  const ids = tile.dataset.ids.split(",").filter(Boolean);
  tile.onclick = (e) => {
    // الكليك العادي = تحديد قطعة واحدة، ctrl = يضيف/يشيل، شفت = مدى بين قطعتين.
    // كارت التفاصيل بيظهر بالوقوف على العنصر فمش بنفتح بالكليك.
    pick(tile, ids, e);
  };
  tile.oncontextmenu = (e) => { e.preventDefault(); hideCard(); openCtx(e, tile, ids); };
  tile.ondragstart = (e) => {
    hideCard();
    let dragIds = ids;
    // بطاقة QTY = الرقم اللي مكتوب فيها لوحدها. قبل كده كانت السحبة بتلمّ أي محدد
    // تاني في نفس العمود معها، فالشنطة كانت تستلم الرقم + قطع زيادة ما اتطلبش.
    const qtyCard = !!tile.closest(".qty-card");
    if (!qtyCard && ids.some((i) => state.selected.has(i)) && state.selected.size > ids.length) {
      const sameCol = (t) => t.dataset.container === tile.dataset.container
        && (!tile.dataset.slot || (t.dataset.slot || "") === tile.dataset.slot);
      const scope = tile.closest(".inv-col") || document;
      const pool = [];
      scope.querySelectorAll(".tile:not(.cat)").forEach((t) => {
        if (!sameCol(t)) return;
        const tIds = t.dataset.ids.split(",").filter(Boolean);
        if (tIds.some((i) => state.selected.has(i))) pool.push(...tIds);
      });
      if (pool.length > ids.length) dragIds = [...new Set(pool)];
    }
    // قبل الإفلات: الشريط السفلي بيقول عدد القطع اللي السحبة دي شايلها فعلاً،
    // مش كل التحديد — عشان ما تفضلش سحبة بتحرّك قطع هو ما علمش عليها.
    const chip = document.getElementById("sel-float-count");
    if (chip && dragIds.length !== state.selected.size) {
      chip.textContent = `this drag: ${num(dragIds.length)} piece${dragIds.length > 1 ? "s" : ""}`;
    }
    // بطاقة QTY اللي الرقم ما بيتعملش برصّات كاملة بتسحب خطة تقسيم كاملة، مش الستاكات دي.
    const card = tile.closest("[data-fill-asset]");
    const fillAmount = Number(card && card.dataset.fillAmount) || 0;
    state.drag = {
      ids: dragIds, wrapper: tile.dataset.wrapper, container: tile.dataset.container,
      slot: tile.dataset.slot || "", name: tile.dataset.name, type: tile.dataset.type || "",
      group: tile.dataset.group || "", kind: tile.dataset.kind || "",
      asset: tile.dataset.asset || "",
      fill: card && fillAmount > 0 ? { asset: card.dataset.fillAsset, amount: fillAmount } : null,
    };
    e.dataTransfer.setData("text/plain", tile.dataset.name);
    e.dataTransfer.effectAllowed = "move";
    tile.classList.add("drag-src");
    document.body.classList.add("dragging");
    markDropTargets(state.drag);
  };
  tile.ondragend = () => endDragVisuals();
  tile.onmouseenter = (e) => { if (!state.drag) showCard(tile, e); };
  tile.onmousemove = (e) => { if (!state.drag) positionCard(e); };
  tile.onmouseleave = () => hideCard();
}

function pick(tile, ids, e, forceAdditive = false) {
  const container = tile.dataset.container;
  const additive = forceAdditive || e.ctrlKey || e.metaKey;
  if (["stash", "overflow", "backpack", "loadout"].includes(container)) {
    if (e.shiftKey && state.lastPicked) {
      const list = [...document.querySelectorAll(".inv-col[data-container='" + container + "'] .inv-body .tile:not(.cat)")];
      const a = list.findIndex((t) => t.dataset.id === state.lastPicked);
      const b = list.findIndex((t) => t.dataset.id === tile.dataset.id);
      if (a >= 0 && b >= 0) {
        if (!additive) state.selected.clear();
        list.slice(Math.min(a, b), Math.max(a, b) + 1).forEach((t) => t.dataset.ids.split(",").forEach((i) => state.selected.add(i)));
        renderInventory(); updateSelCount(); return;
      }
    }
  }
  if (additive) ids.forEach((i) => state.selected.has(i) ? state.selected.delete(i) : state.selected.add(i));
  else { state.selected.clear(); ids.forEach((i) => state.selected.add(i)); }
  state.lastPicked = tile.dataset.id;
  renderInventory(); updateSelCount();
}
function selectedRows() {
  const seen = new Set();
  const out = [];
  const add = (r) => {
    if (!r || !r.instance_id || seen.has(r.instance_id) || !state.selected.has(r.instance_id)) return;
    seen.add(r.instance_id);
    out.push(r);
  };
  for (const part of Object.values(state.sections || {}))
    for (const r of part.slots || []) add(r);
  for (const list of Object.values(state.loadout?.slots || {}))
    for (const s of list || []) add(s.item);
  return out;
}
function findRow(instanceId) {
  for (const part of Object.values(state.sections || {}))
    for (const r of part.slots || []) if (r.instance_id === instanceId) return r;
  for (const list of Object.values(state.loadout?.slots || {}))
    for (const s of list || []) if (s.item && s.item.instance_id === instanceId) return s.item;
  return null;
}

/* للعرض بس — بلاطة من حساب تاني مسجلة من نتائج البحث. أي مسار نقل بيفضل يستعمل
   findRow وحده، فصف حساب غريب ما يدخلش في validateLocalMove خالص. */
function displayRow(instanceId) {
  return findRow(instanceId) || state.foreign[instanceId] || null;
}
function updateSelCount() {
  const n = state.selected.size;
  const el = $("#sel-count");
  if (el) el.textContent = n ? `${n} selected` : "";
  const f = $("#sel-float");
  if (f) {
    f.hidden = !n;
    const fc = $("#sel-float-count");
    if (fc) fc.textContent = `${n} selected`;
  }
}

/* ------------------------------------------------------------------ actions */
/* التحديد بيشتغل عبر الأعمدة، فقبل ما نكتب نستبعد أي قطعة هي أصلاً في الوجهة:
   لو سيبناها هتستهلك خانة فاضية في الستاش (سقفها 280) من غير ما تتنقل. */
function dropIds(d, target, slot, wrapper) {
  return d.ids.filter((id) => {
    const row = findRow(id) || {};
    const from = String(row.container || "").toLowerCase();
    if (target === "loadout") return from !== slot;
    if (from !== target) return true;
    // نفس العمود بس الخانة المقصودة بعينها مختلفة = إعادة ترتيب جوّه العمود،
    // ودي نقلة سليمة (ستاش → خانة ستاش فاضية متحققة على البوابة).
    return !!wrapper && String(row.wrapper_id || "") !== String(wrapper);
  });
}

async function onDropTarget(target, slot, wrapper) {
  const d0 = state.drag;
  if (!d0) return;
  const ids = dropIds(d0, target, slot, wrapper);
  if (!ids.length) { toast("The whole selection is already in this destination.", ""); return; }
  const d = ids.length === d0.ids.length ? d0 : { ...d0, ids };
  // الاسم لوحده بيخفي إن السحبة شايلة أكتر من قطعة (المحدد بـ ctrl)، فالنص
  // بيقول العدد صراحة قبل ما الكتابة تروح للبوابه.
  const tag = d.ids.length > 1 ? `${d.name} ×${d.ids.length}` : d.name;
  if (target === "loadout") {
    const check = slotDropCheck(slot, wrapper, false, d);
    if (!check.ok) { if (check.reason) toast(check.reason, "bad"); return; }
    await runAction({
      kind: "move", target_container: "loadout", target_slot: slot, target_wrapper_id: wrapper,
      instance_ids: d.ids, label: `${tag} → ${SLOT_META[slot]?.label || slot}`,
    });
    return;
  }
  if (target === "backpack") {
    if (d.fill) { await runFill(d.fill, wrapper); return; }
    if (wrapper) {
      const check = slotDropCheck("backpack", wrapper, false, d);
      if (!check.ok) { if (check.reason) toast(check.reason, "bad"); return; }
    }
    await runAction({
      kind: "move", target_container: "backpack", target_wrapper_id: wrapper || "",
      instance_ids: d.ids, label: `${tag} → BACKPACK`,
    });
    return;
  }
  await runAction({
    kind: "move", target_container: target, target_wrapper_id: wrapper || "",
    instance_ids: d.ids, label: `${tag} → ${target.toUpperCase()}`,
  });
}

/* ------------------------------------------------------------------ الدمج والتبديل بالسحب
   الاتنين كتابة على البوابة الرسمية، فالرفض بيطلع نصاً زي ما هو (نفس سياسة SPLIT).
   الدمج مبيغيرش الأماكن والتبديل مبيغيرش الكميات — وكل واحد منهم ليه رسالة واضحة. */
function writeGate(what) {
  if (state.account === "ALL") { toast("Pick one account first before any action.", "bad"); return false; }
  if (state.frozen) { frozenBlock(what); return false; }
  if (!writesLive()) { toast(writeBlockMsg(), "bad"); return false; }
  return true;
}

/* السحبة بكمية محددة: الباكند بيعيد حساب الخطة على الشجرة الحية — ينقل الرصّات
   الكاملة أولًا وبعدين يفصل الفاضل على مسار التقسيم الرسمي — فالشنطة بتستلم
   الرقم بالضبط ولو عدّى سقف الأكوم (15 + 2 للرقم 17). */
async function runFill(fill, wrapper) {
  if (!writeGate("Quantity move")) return;
  let out;
  try {
    out = await post("/api/actions/fill", {
      account: state.account, asset_id: fill.asset, amount: fill.amount,
      target_wrapper_id: wrapper || "", confirmed: true,
    });
  } catch (err) { toast("⛔ Connection failed: " + err.message, "bad"); return; }
  if (out.executed) {
    state.selected.clear();
    pushHistory(out, `${num(out.delivered || fill.amount)} → BACKPACK`);
    await Promise.all([loadSections(), loadLog()]);
    toast("✔ " + (out.detail || `${num(out.delivered || fill.amount)} delivered to the backpack.`), "ok", 9000);
    return;
  }
  toast("⛔ " + (out.detail || out.error || "The gateway did not answer."), "bad", 9000);
  if (out.partial || (out.steps || []).some((s) => s.executed)) {
    await Promise.all([loadSections(), loadLog()]).catch(() => {});
  }
}

async function runCombine(srcId, rel) {
  if (!writeGate("This merge")) return;
  let out;
  try {
    out = await withSync([srcId, rel.id], false, () => post("/api/actions/combine", {
      account: state.account, instance_id: srcId, target_instance_id: rel.id, confirmed: true,
    }));
  } catch (err) { toast("⛔ Connection failed: " + err.message, "bad"); return; }
  if (out.executed) {
    await Promise.all([loadSections(), loadLog()]);
    toast(`✔ ${out.detail || "Merge " + rel.name + ": now " + num(out.after?.target) + "."}`, "ok");
    return;
  }
  if (out.error === "confirm_required") { showPreview("COMBINE", out.preview, out.detail); return; }
  toast("⛔ " + ((out.result || {}).detail || out.detail || out.error || "Merge refused"), "bad");
  await Promise.all([loadSections(), loadLog()]).catch(() => {});
}

async function runSwap(srcId, rel) {
  if (!writeGate("This swap")) return;
  let out;
  try {
    out = await withSync([srcId, rel.id], false, () => post("/api/actions/swap", {
      account: state.account, instance_id: srcId, target_instance_id: rel.id, confirmed: true,
    }));
  } catch (err) { toast("⛔ Connection failed: " + err.message, "bad"); return; }
  if (out.executed) {
    pushHistory(out, "Swap " + (rel.name || "two items"));
    await Promise.all([loadSections(), loadLog()]);
    toast("✔ " + (out.detail || "Swap done."), "ok");
    return;
  }
  if (out.error === "confirm_required") { showPreview("SWAP", out.preview, out.detail); return; }
  toast("⛔ " + ((out.result || {}).detail || out.detail || out.error || "Swap refused"), "bad");
  await Promise.all([loadSections(), loadLog()]).catch(() => {});
}

async function runAction(spec) {
  const account = state.account;
  if (account === "ALL") { toast("Pick one account first before any action.", "bad"); return; }
  if (state.frozen) { frozenBlock("This move"); return; }

  if (spec.kind === "move" && (state.writes?.armed || state.writes?.move_armed)) {
    const plan = validateLocalMove(spec);
    if (!plan.ok) { toast("⛔ " + (plan.reason || "This move is not allowed."), "bad"); return; }
    if (plan.skippedCount) {
      const total = plan.rows.length + plan.skippedCount;
      toast(`↪ Moved ${plan.rows.length} of ${total} — the rest has no free cell in the destination.`, "");
    }
    enqueueMove(spec, plan, account);
    return;
  }

  let out;
  try {
    const toStash = spec.kind === "move" && (spec.target_container === "stash" || spec.target_container === "overflow");
    out = await withSync(spec.instance_ids || [], toStash, () =>
      spec.kind === "move"
        ? post("/api/actions/move", { account, target_container: spec.target_container,
                                      target_wrapper_id: spec.target_wrapper_id || "", instance_ids: spec.instance_ids,
                                      target_slot: spec.target_slot || "" })
        : post("/api/actions/mutate", { account, action: spec.action, instance_ids: spec.instance_ids,
                                        target_wrapper_id: spec.target_wrapper_id || "",
                                        target_instance_id: spec.target_instance_id || "", amount: spec.amount }));
  } catch (err) { toast("Failed: " + err.message, "bad"); return; }

  if (out.executed) {
    state.selected.clear();
    pushHistory(out, spec.label || spec.kind);
    await Promise.all([loadSections(), loadLog()]);
    toast("✔ Executed on the game account: " + spec.label, "ok");
    return;
  }
  const reason = out.result?.error || out.error || "blocked";
  if (reason === "gateway_route_down") {
    // مسار الكتابة مقفول من عند Embark: حاجة ما اتغيّرتش في اللعبة،
    // فنخزّن النقلّة عند السيرفر تستنى المسار يرجع بدل ما تترا.
    queueToast(await deferMoveSpec(account, spec), reason, out.result?.detail || out.detail);
    return;
  }
  if (reason === "read_only") showPreview(spec.label, out.preview, "Writes are paused — say 009 to open them.");
  else if (reason === "direct_move_endpoint_unknown") showPreview(spec.label, out.preview, out.detail);
  else if (reason === "destructive_blocked") toast("⛔ Destructive action blocked: " + (out.result?.detail || ""), "bad");
  else toast(failText(reason, out.result?.detail || out.detail), "bad");
}

/* ------------------------------------------------------------------ سجل الحركة: UNDO خطوة خطوة (زي Excel)
   كل كتابة ناجحة بترجعلنا out.undo.cells = حالة كل خانة قبل الحركة، فالتراجع
   بيبعت الفرق ده لنفس مسار النقل المتحقق منه. آخر خطوة = أول حاجة تتراجع.
   السجل بيتقارن بالحساب: التاب اللي على G14 ما يشيلش حاجة اتعملت في G22. */
function pushHistory(out, label, account) {
  const cells = (out && out.undo && out.undo.cells) || null;
  if (!cells || !Object.keys(cells).length) return;
  state.history.push({ account: account || state.account, cells, label: label || "Move", at: Date.now() });
  const mine = state.history.filter((s) => s.account === (account || state.account));
  if (mine.length > 40) state.history.splice(state.history.indexOf(mine[0]), 1);
  renderUndoButtons();
}

/* خطوات الحساب اللي شغال دلوقتي بس — وضع ALL مفيش ليه خطوات لأنه مش حساب. */
function undoStack() {
  return state.account === "ALL" ? [] : state.history.filter((s) => s.account === state.account);
}

const WRITE_BUTTONS = ["#lo-apply", "#bp-clear", "#bp-clear-all", "#btn-gather", "#btn-spread",
                       "#btn-merge-all"];

/* ------------------------------------------------------------------ قفل اللوحة بعد ↑ UPDATE
   اللمسة دي معناها "خلّي اللي على اللوحة هو اللي في اللعبة" — فأي سحبة أو
   إضافة بعدها بتلغي معنى التثبيت وبتبلع القطعة في حاوية تانية. بيقفل الموقع
   كله (ستاش + شنطة + أوفر فلو) ويبعتّم اللوحة، والفك ببطل CANCEL أو ESC.
   القفل حالة في التاب نفسه (sessionStorage) عشان إعادة تحميل التاب ماتفتحش
   اللوحة من وراه وهو لسه محتاج يدخل ماتش. */
const FROZEN_KEY = "fahmy.tab.frozen";

function frozenRead() {
  try { return sessionStorage.getItem(FROZEN_KEY) === state.account; } catch { return false; }
}

function setFrozen(on, quiet) {
  state.frozen = !!on && state.account !== "ALL";
  try {
    if (state.frozen) sessionStorage.setItem(FROZEN_KEY, state.account);
    else sessionStorage.removeItem(FROZEN_KEY);
  } catch { /* وضع خاص */ }
  document.body.classList.toggle("locked", state.frozen);
  const cancel = $("#btn-unlock");
  if (cancel) cancel.hidden = !state.frozen;
  // SCRAPPY في الهيدر برّه اللوحة — بنقفل الحفظ بتاعه بس (النقل كتابة)
  const scrappy = $("#btn-scrappy");
  if (scrappy) scrappy.disabled = state.frozen || !SCRAPPY_LIVE;
  syncScrappyPill();
  renderUndoButtons();
  if (!quiet) toast(state.frozen
    ? "🔒 Board is locked — no moves and no adds until you press CANCEL or ESC."
    : "🔓 Board unlocked again.", "ok");
}

function frozenBlock(what) {
  toast("🔒 " + (what || "This move") + " is locked after UPDATE — press CANCEL (or ESC) to unlock the board.", "bad");
}

function renderUndoButtons() {
  const steps = undoStack();
  const n = steps.length;
  const live = writesLive() && !state.frozen;
  document.querySelectorAll("[data-undo-btn]").forEach((b) => {
    b.disabled = !n || !live;
    b.textContent = n ? `UNDO (${n})` : "UNDO";
    b.title = !writesLive() ? writeBlockMsg()
      : (state.frozen ? "🔒 Board is locked after UPDATE — press CANCEL first"
        : (n ? `Undo on ${state.account}: ` + steps[n - 1].label
          : "No recorded step for this account"));
  });
  // SAVE محلي بالكامل فبيفضل شغال وقت التجميد — الباقي بيكتب على حساب اللعبة
  WRITE_BUTTONS.forEach((sel) => {
    const b = $(sel);
    if (!b) return;
    if (b.dataset.title === undefined) b.dataset.title = b.getAttribute("title") || "";
    b.disabled = !live;
    b.title = live ? b.dataset.title
      : (state.frozen ? "🔒 Board is locked after UPDATE — press CANCEL first" : writeBlockMsg());
  });
}

async function undoStep() {
  const steps = undoStack();
  const step = steps[steps.length - 1];
  if (!step) { toast(`No undo step was recorded for ${state.account}.`, "bad"); return; }
  if (!writesLive()) { toast(writeBlockMsg(), "bad"); return; }
  let out;
  try {
    out = await withSync(Object.values(step.cells).flat(), true, () => post("/api/actions/undo",
      { account: step.account, cells: step.cells }));
  } catch (err) { toast("⛔ Connection failed: " + err.message, "bad"); return; }
  if (!out.executed) { toast("⛔ " + (out.detail || out.error || "Refused"), "bad"); return; }
  // بشيل الخطوة دي بالذات، مش آخر عنصر في السجل المشترك
  state.history.splice(state.history.indexOf(step), 1);
  renderUndoButtons();
  await Promise.all([loadSections(), loadLog()]);
  toast("↩ " + (out.detail || "Undo done.") + ` (${step.label})`, "ok");
}

async function clearBackpack(scope) {
  if (state.account === "ALL") { toast("Pick one account first.", "bad"); return; }
  const all = scope === "all";
  const ids = [...document.querySelectorAll(all ? ".col-backpack .tile[data-ids], [data-slot-cell] .tile[data-ids]"
    : ".col-backpack .tile[data-ids]")].flatMap((t) => (t.dataset.ids || "").split(",").filter(Boolean));
  if (!ids.length) return;

  state.recentMoves = state.recentMoves || new Map();
  const bpRows = (state.sections.backpack?.slots || []).filter((r) => ids.includes(r.instance_id));
  bpRows.forEach((r) => {
    state.recentMoves.set(r.instance_id, {
      container: "stash",
      wrapper: "",
      slot_index: null,
      row: { ...r, container: "stash" },
      at: Date.now()
    });
  });
  if (state.sections.backpack) {
    state.sections.backpack.slots = (state.sections.backpack.slots || []).filter((r) => !ids.includes(r.instance_id));
  }
  if (!state.sections.stash) state.sections.stash = { container: "stash", slots: [] };
  state.sections.stash.slots.push(...bpRows);
  renderInventory();

  let out;
  try {
    out = await withSync([...new Set(ids)], true,
      () => post("/api/actions/clear-backpack", { account: state.account, scope }));
  } catch (err) {
    bpRows.forEach((r) => state.recentMoves.delete(r.instance_id));
    await loadSections().catch(() => {});
    toast("⛔ Connection failed: " + err.message, "bad");
    return;
  }
  if (out.executed) {
    pushHistory(out, all ? "CLEAR ALL" : "CLEAR");
    scheduleLoadSections(3500);
    loadLog().catch(() => {});
    toast("✔ " + (out.note || "Backpack emptied into the stash."), "ok");
    return;
  }
  bpRows.forEach((r) => state.recentMoves.delete(r.instance_id));
  await loadSections().catch(() => {});
  toast("⛔ " + ((out.result || {}).detail || out.detail || "Refused"), "bad");
}

/* ------------------------------------------------------------------ SCRAPPY: ديك الورشة
   كل الأرقام من البوابة الرسمية: data/scrappy_catalog.json (38 عرض RoundCrafting من
   game-data بتاع Embark) + شجرة المخزون الحيّة — مفيش وسيط ولا قراءة ذاكرة.

   اللي بيتنفّذ فعلًا: التحويلات الزراعية على `POST /v1/pioneer/offers/accept` — نفس
   مسار قبول التصنيع، والبوابة بتصرف الخامة وترجّع transaction بموعد.
   اللي مرفوض: قبض الدقائق — 15+ شكل جسم على تلات حسابات بمستويات مختلفة كلها رجّعت
   400، ومفيش مسار claim/complete في البوابة أصلًا (مسح 335 مسار). فسيرفر اللعبة
   بيدفعها: الصفوف بتعرض الموعد والتكلفة الرسمية جوه بلاطة واحدة معدودة، من غير زرار.
   المكافأة المؤجّلة بتتحقق بفارق الشجرة (READ DROP) — مش بالكلام. */
const SCRAPPY_LIVE = true;
const SCR = { max: 20, qty: 1, offer: null, tick: null };

function scrClock(seconds) {
  const s = Math.max(0, Math.round(Number(seconds) || 0));
  if (s < 60) return s + "s";
  const m = Math.floor(s / 60);
  return m < 60 ? m + "m" : Math.floor(m / 60) + "h " + (m % 60) + "m";
}

function scrCountdown(seconds) {
  const s = Math.max(0, Math.round(Number(seconds) || 0));
  return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
}

function scrImg(src, cls) {
  return src ? `<img class="${cls || ""}" src="${asset(src)}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">`
             : `<i class="scr-noimg"></i>`;
}

function scrChips(items, perQty) {
  return (items || []).map((x) => `<span class="scr-chip">${scrImg(x.image)}<b>${num((x.amount || 1) * (perQty || 1))}</b></span>`).join("");
}

function scrCostHTML(lines, perQty) {
  return (lines || []).map((l) => `
    <span class="ws-mat ${l.missing ? "short" : ""}" title="${esc(l.name)} — ${num(l.have)} in the stash, ${num(l.need)} needed${perQty ? " for this amount" : ""}">
      ${scrImg(l.image)}<span>${esc(l.name)}</span><b>${num(l.have)}</b><i>/ ${num(l.need)}</i>
    </span>`).join("");
}

/* العدّاد في الهيدر: كل حاجة تنفع دلوقتي — تحويل متقدّر عليه أو موعد لسه شغال */
function scrReadyCount(st) {
  if (!st || st.error) return 0;
  return (st.feed || []).filter((r) => r.affordable).length + (st.timers || []).length;
}

async function loadScrappy() {
  if (!SCRAPPY_LIVE || state.account === "ALL") { state.scrappy = null; syncScrappyPill(); return; }
  let st;
  try { st = await json("/api/scrappy?account=" + encodeURIComponent(state.account)); }
  catch (err) { state.scrappy = { error: err.message }; syncScrappyPill(); return; }
  state.scrappy = st;
  syncScrappyPill();
}

function syncScrappyPill() {
  const pill = $("#btn-scrappy"), label = $("#scr-top-label");
  if (!pill || !label) return;
  if (!SCRAPPY_LIVE) {
    pill.disabled = true;
    pill.classList.add("off");
    label.textContent = "";
    return;
  }
  pill.classList.remove("off");
  const st = state.scrappy;
  const roman = st && st.found ? (ROMAN[st.tier] || "") : "";
  const ready = scrReadyCount(st);
  pill.classList.toggle("ready", ready > 0);
  label.textContent = ready ? String(ready) : roman;
  pill.title = state.frozen ? "🔒 Board is locked — press CANCEL first"
    : (st && st.error) ? "SCRAPPY — " + st.error
    : `SCRAPPY${roman ? " " + roman : ""} — opens the rooster: crop conversions run on the official gateway, the minute payouts and the upgrade show their official cost and timer.`;
}

function scrFeedRow(r) {
  const cost = (r.cost || [])[0] || {};
  const pool = (r.reward_pool || []).map((p) => p.name).join(", ");
  return `<button type="button" class="scr-row ${r.affordable ? "" : "short"}" data-scr-offer="${r.offer_id}"
      title="${esc(r.label)} — ${num(cost.have)} ${esc(cost.name || "")} available · ${scrClock(r.duration_seconds)} timer · pays ${esc((r.reward || []).map((x) => x.name + " ×" + x.amount).join(", "))}${pool ? " + one of: " + esc(pool) : ""}">
    <span class="scr-row-ico">${scrImg(cost.image)}</span>
    <span class="scr-row-main">
      <b>${esc(r.label)}</b>
      <i>−${num(cost.need)} ${esc(cost.name || "")} · have ${num(cost.have)}</i>
    </span>
    <span class="scr-row-out">${scrChips(r.reward)}${(r.reward_pool || []).length ? `<em class="scr-pool">+draw</em>` : ""}</span>
    <span class="scr-row-time">${scrClock(r.duration_seconds)}</span>
  </button>`;
}

/* صفوف الدقائق: تنفيذها ملك سيرفر اللعبة (البوابة بترفض 400 لكل أجسام القبول)،
   فبتعرض بمواعيدها وتكاليفها من غير زرار تنفيذ. */
function scrClaimRow(r) {
  const cost = (r.cost || [])[0] || {};
  return `<div class="scr-row claim" title="${esc(r.label)} — ${scrClock(r.duration_seconds)} payout, costs ${num(cost.need)} ${esc(cost.name || "")}. The gateway refuses this offer for a companion token (400 on every accepted body shape), so the site shows the schedule and never fires it.">
    <span class="scr-row-ico">${scrImg(cost.image)}</span>
    <span class="scr-row-main">
      <b>${esc(r.label)}</b>
      <i>−${num(cost.need)} ${esc(cost.name || "")} · have ${num(cost.have)}</i>
    </span>
    <span class="scr-row-out">${scrChips(r.reward)}</span>
    <span class="scr-row-time">${scrClock(r.duration_seconds)}</span>
  </div>`;
}

function scrTimerRow(t) {
  const pct = Math.min(100, Math.max(0, 100 * (1 - (t.remaining || 0) / Math.max(1, t.duration || 1))));
  return `<div class="scr-timer">
    <span class="scr-t-main"><b>${esc(t.label || t.title)}</b><i>×${num(t.amount || 1)}</i></span>
    <span class="scr-t-bar"><span id="scr-tb-${t.offer_id}" style="width:${pct.toFixed(1)}%"></span></span>
    <span class="scr-t-left" id="scr-t-${t.offer_id}">${scrCountdown(t.remaining)}</span>
  </div>`;
}

/* كل ما نزل فعلًا (فارق الشجرة) مع كل ميعاد خلص — سطر واحد مضغوط */
function scrDropHTML(st) {
  const settled = st.settled || [], landed = st.landed || [];
  if (!settled.length && !landed.length) return "";
  return `<div class="buy-label">WHAT DROPPED</div><div class="scr-drops">`
    + settled.map((s) => `<span class="scr-settle"><b>${esc(s.label || s.title)}</b>${
        s.landed.length ? s.landed.map((l) => `<i>+${num(l.gained)} ${esc(l.name)}</i>`).join("")
                        : `<em class="scr-pool">not paid yet</em>`}</span>`).join("")
    + landed.map((l) => `<span class="scr-settle in" title="${esc(l.name)} — ${num(l.gained)} new units across ${num(l.stacks)} stack(s)">${scrImg(l.image)}<b>+${num(l.gained)}</b><i>${esc(l.name)}</i></span>`).join("")
    + `</div>`;
}

function scrBodyHTML(st) {
  const feed = st.feed || [], claims = st.claims || [], timers = st.timers || [];
  const up = st.upgrade || {};
  const ready = feed.filter((r) => r.affordable);
  const blocked = feed.filter((r) => !r.affordable);
  return `
  <div class="buy-head">
    <div class="buy-hero">${scrImg(st.icon)}</div>
    <div class="buy-meta">
      <h4 class="buy-name">${esc(st.tier_label || ("Scrappy " + (ROMAN[st.tier] || "")))}</h4>
      <div class="buy-trader">Hideout generator · tier ${esc(ROMAN[st.tier] || "—")}</div>
      <div class="buy-unit"><i class="scr-noimg rounds"></i><b>${num(st.rounds)}</b><span>Rounds Played</span></div>
    </div>
  </div>
  ${timers.length ? `<div class="buy-label">RUNNING</div><div class="scr-timers">${timers.map(scrTimerRow).join("")}</div>` : ""}
  ${scrDropHTML(st)}
  ${up.max ? "" : `<div class="buy-label">UPGRADE TO ${esc(up.next_label || "")}</div>
       <div class="ws-lines">${scrCostHTML(up.cost)}</div>
       <p class="buy-note" dir="ltr">The generator swap runs in the hideout build menu, not on the offers route — the site shows the official cost only.</p>`}
  <div class="buy-label">CROP FEEDS <span class="scr-count">${ready.length} ready</span></div>
  <div class="scr-grid">${ready.map(scrFeedRow).join("") || `<p class="buy-note" dir="ltr">No crop conversion is payable with what is in the stash.</p>`}</div>
  ${blocked.length ? `<button class="scr-more" type="button" data-scr-toggle="blocked">CROP FEEDS YOU CAN'T PAY (${blocked.length})<i>show</i></button>
  <div class="scr-grid" data-scr-box="blocked" hidden>${blocked.map(scrFeedRow).join("")}</div>` : ""}
  ${claims.length ? `<button class="scr-more" type="button" data-scr-toggle="claims">MINUTE PAYOUTS (${claims.length})<i>show</i></button>
  <div class="scr-claims" data-scr-box="claims" hidden>${claims.map(scrClaimRow).join("")}</div>` : ""}
  <div class="buy-error" id="scr-error"></div>
  <div class="buy-foot">
    <button class="ghost" type="button" id="scr-refresh" title="Re-read the rooster from the official gateway">⟳ RE-READ</button>
    <button class="ghost" type="button" id="scr-close">CLOSE</button>
    <button class="buy-confirm" type="button" id="scr-read" title="Re-read the live tree and record anything that dropped on top of the existing piles">✔ READ DROP</button>
  </div>`;
}

function showScrappy() {
  const st = state.scrappy || {};
  openModal(`SCRAPPY — ${state.account}`, st.error && !st.found
    ? `<div class="buy-error">${esc(String(st.error))}</div>
       <p class="buy-note" dir="ltr">Nothing was sent to the game. The panel reads the live tree from the official gateway, so it needs a readable inventory.</p>
       <div class="buy-foot"><button class="ghost" type="button" id="scr-refresh">⟳ RE-READ</button><button class="buy-confirm" type="button" id="scr-close">CLOSE</button></div>`
    : scrBodyHTML(st), null, null, { hideFoot: true, cls: "buy-modal scr-modal" });
  $("#scr-close").onclick = () => { $("#modal").hidden = true; };
  const refresh = $("#scr-refresh");
  if (refresh) refresh.onclick = async () => { await loadScrappy(); showScrappy(); };
  document.querySelectorAll("[data-scr-toggle]").forEach((btn) => {
    btn.onclick = () => {
      const box = document.querySelector(`[data-scr-box="${btn.dataset.scrToggle}"]`);
      const open = box.hidden;
      box.hidden = !open;
      btn.querySelector("i").textContent = open ? "hide" : "show";
    };
  });
  document.querySelectorAll("[data-scr-offer]").forEach((row) => {
    row.onclick = () => openScrappyFeed(Number(row.dataset.scrOffer));
  });
  const read = $("#scr-read");
  if (read) read.onclick = scrappyReadDrop;
  scrTickStart();
}

/* عدّاد بالثانية بس — بيشتغل طول ما لوحة الديك مفتوحة وبيموت أول ما تتقفل */
function scrTickStart() {
  if (SCR.tick) return;
  SCR.tick = setInterval(() => {
    const modal = $("#modal");
    if (!modal || modal.hidden || !modal.querySelector(".scr-modal")) {
      clearInterval(SCR.tick);
      SCR.tick = null;
      return;
    }
    const st = state.scrappy || {};
    (st.timers || []).forEach((t) => {
      const left = Math.max(0, Math.round((Number(t.eta) || 0) - Date.now() / 1000));
      const cell = document.getElementById("scr-t-" + t.offer_id);
      if (cell) cell.textContent = left ? scrCountdown(left) : "DONE";
      const bar = document.getElementById("scr-tb-" + t.offer_id);
      if (bar) bar.style.width = Math.min(100, Math.max(0, 100 * (1 - left / Math.max(1, t.duration || 1)))).toFixed(1) + "%";
    });
  }, 1000);
}

async function scrappyTopClick() {
  if (!SCRAPPY_LIVE) return;
  if (state.account === "ALL") { toast("Pick one account first.", "bad"); return; }
  const pill = $("#btn-scrappy");
  if (pill) pill.disabled = true;
  await loadScrappy().catch(() => {});
  if (pill) pill.disabled = state.frozen;
  showScrappy();
}

/* نافذة تأكيد مستقلة: اختيار العرض ماكفيش — الكتابة بتتم بس من FEED HERE */
function openScrappyFeed(offerId) {
  const row = ((state.scrappy || {}).feed || []).find((r) => r.offer_id === offerId);
  if (!row) return;
  SCR.offer = row;
  SCR.max = Math.max(0, Math.min(20, ...(row.cost || []).filter((cost) => cost.need > 0).map((cost) => Math.floor((cost.have || 0) / cost.need))));
  SCR.qty = 1;
  openModal(`SCRAPPY — ${row.label}`, `
    <div class="buy-head">
      <div class="buy-hero">${scrImg((row.cost[0] || {}).image)}</div>
      <div class="buy-meta">
        <h4 class="buy-name">${esc(row.label)}</h4>
        <div class="buy-trader">Crop conversion · ${scrClock(row.duration_seconds)} timer</div>
        <div class="buy-unit">${scrImg((row.reward[0] || {}).image)}<b>×${num(row.reward_total)}</b><span>${esc((row.reward[0] || {}).name || "reward")} per feed</span></div>
      </div>
    </div>
    <div class="buy-label">QUANTITY</div>
    <div class="qty-picker">
      <button type="button" id="scr-minus" aria-label="Decrease quantity">−</button>
      <input id="scr-qty" type="number" min="1" max="20" step="1" inputmode="numeric" value="${SCR.qty}" aria-label="Quantity">
      <button type="button" id="scr-plus" aria-label="Increase quantity">+</button>
      <button type="button" class="max" id="scr-max" title="As many as the stash can pay">MAX</button>
    </div>
    <div class="ws-lines" id="scr-lines"></div>
    ${(row.reward_pool || []).length ? `<p class="buy-note" dir="ltr">Scrappy also pulls one bonus resource from: <b>${esc(row.reward_pool.map((p) => p.name).join(", "))}</b></p>` : ""}
    <div class="buy-error" id="scr-feed-error"></div>
    <div class="buy-foot">
      <button class="ghost" type="button" id="scr-feed-cancel">CLOSE</button>
      <button class="buy-confirm" type="button" id="scr-feed-confirm">FEED HERE</button>
    </div>`, null, null, { hideFoot: true, cls: "buy-modal" });

  const err = $("#scr-feed-error");
  const btn = $("#scr-feed-confirm");
  const input = $("#scr-qty");
  const paint = () => {
    const qty = SCR.qty;
    if (document.activeElement !== input) input.value = qty;
    $("#scr-lines").innerHTML = `<p class="ws-mats-title">Cost for this feed</p>` + scrCostHTML(
      (row.cost || []).map((l) => ({ ...l, need: l.need * qty, have: l.have, missing: Math.max(0, l.need * qty - l.have) })), qty)
      + `<div class="ws-line total"><span>OUTPUT</span><b>${num(qty * (row.reward_total || 0))} ${esc((row.reward[0] || {}).name || "")} + 1 bonus draw</b></div>`;
    const paused = Boolean((state.writes || {}).write_paused) || Boolean((state.scrappy || {}).write_paused);
    const short = (row.cost || []).some((l) => l.need * qty > l.have);
    btn.disabled = qty < 1 || short || paused || state.frozen;
    btn.textContent = paused ? "WRITE PAUSED" : short ? "NEED MATERIALS" : `FEED ×${num(qty)}`;
  };
  input.oninput = () => { SCR.qty = Math.max(1, Math.min(20, parseInt(input.value, 10) || 1)); paint(); };
  input.onblur = () => { SCR.qty = Math.max(1, Math.min(20, parseInt(input.value, 10) || 1)); input.value = SCR.qty; paint(); };
  const stepQty = (delta) => {
    SCR.qty = Math.max(1, Math.min(Math.max(1, SCR.max), SCR.qty + delta));
    input.value = SCR.qty;
    paint();
  };
  holdRepeat($("#scr-minus"), -1, stepQty);
  holdRepeat($("#scr-plus"), 1, stepQty);
  $("#scr-max").onclick = () => { SCR.qty = Math.max(1, SCR.max); paint(); };
  $("#scr-feed-cancel").onclick = () => { $("#modal").hidden = true; };
  btn.onclick = async () => {
    if (btn.disabled) return;
    btn.disabled = true;
    btn.textContent = "FEEDING…";
    err.textContent = "";
    let out;
    try {
      out = await post("/api/scrappy/feed", { account: state.account, offer_id: row.offer_id, amount: SCR.qty, confirmed: true });
    } catch (e) { err.textContent = "⛔ Connection failed: " + e.message; paint(); return; }
    if (!out.ok) {
      err.textContent = "⛔ " + (out.detail || out.error || "The gateway refused.");
      paint();
      return;
    }
    $("#modal").hidden = true;
    toast("✔ " + (out.detail || "Scrappy took the conversion."), "ok");
    await Promise.all([loadScrappy(), loadSections(), loadLog()].map((p) => p.catch(() => {})));
    showScrappy();
  };
  paint();
}

/* اللوت المؤجّل بيتقاس من الشجرة الحيّة مقابل آخر سنابشوت — الباكند مابعثش
   طلب قبض للدقايق أصلًا، فالقراءة دي هي التحقق الوحيد. */
async function scrappyReadDrop() {
  const err = $("#scr-error");
  if (err) err.textContent = "";
  let out;
  try { out = await post("/api/actions/collect-scrappy", { account: state.account }); }
  catch (e) { if (err) err.textContent = "⛔ Connection failed: " + e.message; return; }
  if (out.executed) {
    toast("✔ " + out.detail, "ok");
    await Promise.all([loadScrappy(), loadSections(), loadLog()].map((p) => p.catch(() => {})));
    showScrappy();
    return;
  }
  if (err) err.textContent = out.reason === "nothing_landed"
    ? "ℹ " + (out.detail || "Nothing new in the official tree.")
    : "⛔ " + (out.detail || out.error || "Refused.");
  await loadScrappy();
}

function loadoutNameDefault() {
  const list = state.loadout?.saved || [];
  return `Loadout ${list.filter((l) => l.account === state.account).length + 1}`;
}

/* قائمة التجهيزات المحفوظة: القوالب مشتركة بين حساباته، فكل سطر بيوريصاه
   بالاسم وبالحساب اللي اتعمل فيه، ومعاه قلم للتسمية وإكس للحذف. */
function wireLoadoutMenu() {
  const dd = $("#lo-dd");
  if (!dd) return;
  const toggle = $("#lo-toggle");
  if (toggle) toggle.onclick = (e) => {
    e.stopPropagation();
    state.loPopOpen = !state.loPopOpen;
    dd.classList.toggle("open", state.loPopOpen);
    const pop = $("#lo-pop");
    if (pop) pop.hidden = !state.loPopOpen;
  };
  dd.querySelectorAll("[data-lo]").forEach((row) => {
    row.onclick = (e) => {
      if (e.target.closest("[data-lo-rename],[data-lo-del]")) return;
      e.stopPropagation();
      selectProfile(row.dataset.lo);
    };
  });
  dd.querySelectorAll("[data-lo-rename]").forEach((b) => b.onclick = (e) => {
    e.stopPropagation();
    renameLoadout(b.dataset.loRename);
  });
  dd.querySelectorAll("[data-lo-del]").forEach((b) => b.onclick = (e) => {
    e.stopPropagation();
    deleteLoadout(b.dataset.loDel);
  });
}

function savedLoadout(id) {
  return (state.loadout?.saved || []).find((l) => String(l.id) === String(id));
}

function renameLoadout(id) {
  const rec = savedLoadout(id);
  if (!rec) { toast("This loadout does not exist.", "bad"); return; }
  openModal("RENAME LOADOUT", `
    <p class="note">Templates are shared across your accounts — the new name shows up in every tab.
    The edit is fully local; nothing is written to the game account.</p>
    <div class="field"><label>LOADOUT NAME</label>
      <input id="lo-rename" type="text" maxlength="64" value="${esc(rec.name)}"></div>`,
    async () => {
      const name = ($("#lo-rename").value || "").trim();
      if (!name) throw new Error("Loadout name is required.");
      if (name === rec.name) return;
      const out = await patch(`/api/loadouts/${encodeURIComponent(id)}`, { name });
      await loadSections();
      toast(`✔ Name is now "${out.loadout.name}".`, "ok");
    }, "RENAME",
    { onMount: (host) => {
        const i = host.querySelector("#lo-rename");
        if (!i) return;
        i.focus();
        i.select();
        i.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); $("#m-confirm").click(); } };
      } });
}

function deleteLoadout(id) {
  const rec = savedLoadout(id);
  if (!rec) { toast("This loadout does not exist.", "bad"); return; }
  openModal("DELETE LOADOUT", `
    <p class="note">Will delete <b>${esc(rec.name)}</b> (by ${esc(rec.owner || rec.account)}) from the saved templates —
    in every account, because the template is shared. The items themselves stay where they are and nothing is written to the game account.</p>`,
    async () => {
      await del(`/api/loadouts/${encodeURIComponent(id)}`);
      if (String(state.loadoutSel) === String(id)) state.loadoutSel = "";
      await loadSections();
      toast(`✔ "${rec.name}" deleted.`, "ok");
    }, "DELETE", { confirmKind: "danger" });
}

function accLabel(name) {
  return (state.accounts.find((a) => a.name === name) || {}).display_name || name || "";
}

function saveLoadout() {
  if (state.account === "ALL") { toast("Pick one account first.", "bad"); return; }
  openModal("SAVE LOADOUT", `
    <p class="note">Every current position is saved exactly — loadout cells (AUGMENT / SHIELD / WEAPON 1 / WEAPON 2 /
    QUICK USE / SAFE POCKET) + the loadout backpack cell by cell — from account <b>${esc(accLabel(state.account))}</b>.
    The template registers for all accounts: it shows and loads from any other tab, and loading places what is available and skips what is not.
    Saving is fully local — no write to the game account.</p>
    <div class="field"><label>LOADOUT NAME</label>
      <input id="lo-name" type="text" maxlength="64" value="${esc(loadoutNameDefault())}"></div>`,
    async () => {
      const name = ($("#lo-name").value || "").trim();
      if (!name) throw new Error("Loadout name is required.");
      const out = await post("/api/loadouts", { account: state.account, name });
      state.loadoutSel = String(out.loadout.id);
      state.loPopOpen = true;
      await loadSections();
      toast(`✔ Saved "${out.loadout.name}" (${out.loadout.count} items).`, "ok");
    }, "SAVE");
}

async function loadLoadout() {
  if (state.account === "ALL") { toast("Pick one account first.", "bad"); return; }
  const id = state.loadoutSel || "";
  if (!id) { toast("Choose a Saved Loadout from the list first.", "bad"); return; }
  let plan;
  try { plan = await json(`/api/loadouts/${encodeURIComponent(id)}/plan?account=${encodeURIComponent(state.account)}`); }
  catch (e) { toast(e.message, "bad"); return; }
  if (plan.already) { toast("This loadout already matches the current state.", "ok"); exitPreview(); return; }
  if (!plan.executable) {
    const bits = (plan.skipped || []).slice(0, 3).map((s) => s.name).join(", ");
    toast("⛔ Nothing from this loadout is available right now" + (bits ? ` (${bits})` : ""), "bad");
    return;
  }
  if (!writesLive()) { toast(writeBlockMsg(), "bad"); return; }
  const touched = [...(plan.steps || []).map((s) => s.instance_id),
    ...((plan.evict || []).map((e) => e.instance_id))];
  let out;
  try {
    out = await withSync(touched, false,
      () => post(`/api/loadouts/${encodeURIComponent(id)}/apply`, { account: state.account }));
  } catch (err) { toast("⛔ Connection failed: " + err.message, "bad"); return; }
  if (out.executed) {
    pushHistory(out, `LOAD — ${out.loadout?.name || ""}`.trim());
    state.loPreview = null;
    state.loadoutSel = "";
    await Promise.all([loadSections(), loadLog()]);
    const bits = [];
    const moved = Number(out.moved);
    if (moved > 0 || (plan.steps || []).length) bits.push(`${num(moved || (plan.steps || []).length)} items in place`);
    const cleared = Number(out.cleared) || (plan.evict || []).length;
    if (cleared) bits.push(`${num(cleared)} returned to the stash`);
    if (Number(out.topped) > 0) bits.push(`${num(out.topped)} units pulled from your stash into their cells`);
    if ((plan.skipped || []).length) bits.push(`${plan.skipped.length} unavailable (skipped)`);
    toast(bits.length ? "✔ " + bits.join(" — ") : "✔ " + (out.detail || "Profile loaded."), "ok");
    if (out.detail_note) toast("⚠ " + out.detail_note, "bad");
    if (Number(out.topup_failed) > 0) {
      toast("⚠ " + (out.topup_detail || `The stash refused ${num(out.topup_failed)} units.`), "bad");
    }
    return;
  }
  toast("⛔ " + (out.detail || out.error || "Refused"), "bad");
}

/* ===================== تنفيذ المعاينة: تعبئة الناقص ثم النقل ===================== */

async function fetchPreview(id, acc) {
  const data = await json(`/api/loadouts/${encodeURIComponent(id)}/preview?account=${encodeURIComponent(acc)}`);
  (data.cards || []).forEach((c, i) => { c.i = i; });
  return data;
}

/* اختيار بروفيل = معاينة بس: مفيش ولا حركة بتتنفذ هنا. */
async function selectProfile(id) {
  state.loadoutSel = String(id || "");
  state.loPopOpen = false;
  state.loPreview = null;
  renderInventory();
  if (!id || state.account === "ALL") return;
  const acc = state.account;
  let data;
  try { data = await fetchPreview(id, acc); }
  catch (e) { toast("⛔ Preview failed: " + e.message, "bad"); return; }
  if (acc !== state.account || String(state.loadoutSel) !== String(id)) return;
  state.loPreview = data;
  renderInventory();
}

async function refreshPreview() {
  const id = state.loadoutSel;
  if (!id || state.account === "ALL") return;
  const acc = state.account;
  try {
    const data = await fetchPreview(id, acc);
    if (acc === state.account && String(state.loadoutSel) === String(id)) {
      state.loPreview = data;
      renderInventory();
    }
  } catch { /* اللوحةفضل شغالة حتى لو المعاينة رجعت خطأ */ }
}

function pvMatTile(m) {
  const short = Number(m.have) < Number(m.need);
  return `<div class="rec-mat ${short ? "miss" : ""} r-${esc(m.rarity || "Common")}">
    <div class="rec-mat-tile">${m.image_filename ? `<img src="${asset(m.image_filename)}" alt="" onerror="this.style.visibility='hidden'">` : "?"}
      <span class="rec-mat-qty">${num(m.have)}/${num(m.need)}</span></div>
    <div class="rec-mat-name">${esc(m.name)}</div></div>`;
}

function pvCraftPanel(card) {
  const c = (card.fill || {}).craft || {};
  const sel = pvRoute(card) === "craft";
  const mats = (c.materials || []).map(pvMatTile).join("");
  const line = c.possible
    ? `Craft <b>${num(c.crafts)}</b> run${Number(c.crafts) > 1 ? "s" : ""} of ${num(c.per_craft)} at <b>${esc(c.station_label || "the station")}</b>`
    : esc(c.detail || "This recipe cannot be run on your account.");
  return `<div class="pv-opt ${c.possible ? "ok" : "no"} ${sel ? "sel" : ""}">
    <div class="pv-opt-head"><span>⚒ CRAFT</span>${sel ? "<b class=\"pv-opt-on\">WILL BE USED</b>" : ""}</div>
    <p class="pv-opt-line">${line}</p>
    ${c.level_required ? `<p class="pv-opt-sub">${esc(c.station_label || "")} is level ${num(c.level_current)} — the recipe needs ${num(c.level_required)}</p>` : ""}
    ${mats ? `<div class="rec-mats">${mats}</div>` : ""}
  </div>`;
}

function pvBuyPanel(card) {
  const b = (card.fill || {}).buy || {};
  const sel = pvRoute(card) === "buy";
  const line = b.possible
    ? `Buy <b>${num(b.buys)}</b> × ${num(b.reward_amount)} from <b>${esc(b.trader || "a trader")}</b> at ${num(b.unit)} each`
    : esc(b.detail || "No trader on your account sells this.");
  return `<div class="pv-opt ${b.possible ? "ok" : "no"} ${sel ? "sel" : ""}">
    <div class="pv-opt-head"><span>🛒 BUY</span>${sel ? "<b class=\"pv-opt-on\">WILL BE USED</b>" : ""}</div>
    <p class="pv-opt-line">${line}</p>
    ${b.possible ? `<p class="pv-opt-sub">${num(b.unit)} × ${num(b.buys)} = <b>${num(b.total)} ${esc((b.currency || {}).name || "Coins")}</b> · balance ${num(b.have)}${typeof b.remaining === "number" ? ` · ${num(b.remaining)} left in the offer` : ""}</p>` : ""}
  </div>`;
}

function pvDetails(card) {
  const body = card.status === "missing"
    ? `${pvCraftPanel(card)}${pvBuyPanel(card)}`
    : `<p class="note">${esc(pvHint(card))}</p>`
      + (card.status === "short" && card.fill ? `${pvCraftPanel(card)}${pvBuyPanel(card)}` : "");
  openModal("PROFILE CELL — " + card.name, `
    ${gearHero({ name: card.name + (Number(card.qty) > 1 ? " ×" + num(card.qty) : ""), image: card.image, rarity: card.rarity || "Common" },
      `${card.slot_label || ""} · cell ${Number(card.slot_index) + 1}`)}
    ${body}`, null, "", { wide: true });
}

async function runFillJobs(jobs) {
  const done = [], failed = [];
  for (const j of jobs) {
    let out;
    try {
      out = j.route === "craft"
        ? await post("/api/workshop/craft", { account: state.account, slug: j.opt.slug,
            amount: Number(j.opt.crafts) || 1, confirmed: true })
        : await post("/api/traders/buy", { account: state.account, offer_id: j.opt.offer_id,
            amount: Number(j.opt.buys) || 1, confirmed: true });
    } catch (e) { failed.push({ j, detail: e.message }); continue; }
    if (out && out.executed) done.push(j);
    else failed.push({ j, detail: (out && (out.detail || out.error)) || "refused" });
  }
  return { done, failed };
}

/* APPLY = تنفيذ وخلاص: المسار المختار في الشريط (CRAFT/BUY) بيتنفذ على
   البوابة الرسمية، وبعده البروفيل يت_place — من غير أي لوحة تأكيد.
   الفشل لوحده هو اللي بيبان، لأن ده معلومة مش موافقة. */
async function silentFill(jobs) {
  const out = await runFillJobs(jobs);
  await Promise.all([loadSections(), loadLog()]);
  if (out.failed.length) {
    toast("⛔ " + out.failed.map((f) => `${f.j.card.name}: ${f.detail}`).join(" · ").slice(0, 300), "bad");
  }
  await refreshPreview();
  await loadLoadout();
}

/* بعد التنفيذ اللوحة بترجع حية: المعاينة والقالب المختار بيتصفروا لوحدهم. */
function exitPreview() {
  state.loPreview = null;
  state.loadoutSel = "";
  renderInventory();
}

function pvApply() {
  const p = pvLive();
  if (!p) { loadLoadout(); return; }
  const jobs = pvJobs();
  const pulls = (p.cards || []).filter((c) => c.status === "short" && Number(c.from_stash) > 0);
  const extras = (p.evict || []).filter((e) => e.extra);
  if (!jobs.length) {
    // النقل لوحده أو السحب من المخزن لوحده أو تفريغ الفضلة لوحدها = مفيش صرف،
    // فالزرار نفسه هو Confirmation.
    if (!(p.steps || []).length && !pulls.length && !extras.length) {
      const s = p.summary || {};
      toast(s.missing || s.blocked || s.short ? "⛔ Nothing from this profile can be placed right now."
                                             : "✔ This profile is already in place — nothing to do.",
            s.missing || s.blocked || s.short ? "bad" : "ok");
      exitPreview();
      return;
    }
    loadLoadout();
    return;
  }
  if (!writesLive()) { toast(writeBlockMsg(), "bad"); return; }
  silentFill(jobs);
}

function wirePreview() {
  const host = $("#column-host");
  if (!host) return;
  host.querySelectorAll("[data-pv]").forEach((el) => el.onclick = (e) => {
    e.stopPropagation();
    const p = pvLive();
    const card = p && (p.cards || [])[Number(el.dataset.pv)];
    if (card) pvDetails(card);
  });
  host.querySelectorAll("[data-pv-mode]").forEach((b) => b.onclick = (e) => {
    e.stopPropagation();
    state.loFillMode = b.dataset.pvMode === "buy" ? "buy" : "craft";
    try { localStorage.setItem("fahmy.loFillMode", state.loFillMode); } catch { /* وضع خاص */ }
    renderInventory();
  });
  const apply = $("#lo-apply"); if (apply) apply.onclick = pvApply;
}

function showPreview(label, preview, note) {
  openModal("PREVIEW — " + label, `
    <p class="note">${esc(note)} is exactly the request that will be sent to the Embark gateway once writes are enabled:</p>
    <pre class="code">${esc(JSON.stringify(preview, null, 2))}</pre>`, null);
}

/* ------------------------------------------------------------------ نوافذ UPGRADE / REPAIR / RECYCLE / SELL */
function gearHero(item, sub) {
  const rarity = item.rarity || "Common";
  const img = item.image_filename || item.image || "";
  return `<div class="gear-hero">
    <div class="gear-icon r-${esc(rarity)}">${img ? `<img src="${asset(img)}" alt="" onerror="this.style.visibility='hidden'">` : ""}</div>
    <div class="gear-id"><h4>${esc(item.name || item.display_name || "")}</h4>${sub ? `<span>${esc(sub)}</span>` : ""}</div>
  </div>`;
}

function materialRow(m, mode) {
  const need = mode === "gain" ? Number(m.amount) || 0 : Number(m.needed) || 0;
  const have = Number(m.available) || 0;
  const ok = mode === "gain" || !!m.has_enough;
  return `<div class="gear-mat">
    <span class="gear-mat-ico">${m.image_filename ? `<img src="${asset(m.image_filename)}" alt="" onerror="this.style.visibility='hidden'">` : ""}</span>
    <span class="gear-mat-name">${esc(m.name || "Material")}</span>
    ${mode === "gain"
      ? `<b class="gain">+${num(need)}</b>`
      : `<b class="${ok ? "ok" : "bad"}">${num(have)} / ${num(need)}</b>`}
  </div>`;
}

function gearArmNote() {
  if (state.writes?.armed) return "";
  if (state.writes?.write_paused) {
    return `<p class="gear-note warn">🧊 Writes are frozen — someone is playing this account right now. Say 009 when you are done.</p>`;
  }
  return `<p class="gear-note warn">🔒 READ-ONLY — writes are locked right now; say 009 to open them.</p>`;
}

function fetchPlan(kind, ids, targets) {
  return post("/api/actions/plan", { account: state.account, kind, instance_ids: ids, targets: targets || {} });
}

/* الترقية: اختيار الدرجة بيغيّر العرض بس (كارت السلاح + مجموع الخامات)،
   والتنفيذ بيحصل لما تدوس زرار التأكيد. البوابة بترفع درجة واحدة في كل
   نداء، والـ backend بيكمّل النداءات لحد الدرجة المطلوبة. */
function upgTargets(ids, level) {
  const t = {};
  ids.forEach((i) => { t[i] = level; });
  return t;
}

/* كارت السلاح فوق: الأيقونة وفيها درجته الرومانية، جنبها اسمه وندرته، ومن تحت FL الحالي ▸ المطلوب. */
function upgWeaponCard(i, selected) {
  const cur = Number(i.current) || 1;
  const ico = i.image_filename || i.image || "";
  return `<div class="rep-item ${rarCls(i.rarity)}">
    <div class="rep-item-tile">${ico ? `<img src="${asset(ico)}" alt="" onerror="this.style.visibility='hidden'">` : "?"}
      <span class="upg-tier">${ROMAN[cur] || cur}</span></div>
    <div class="rep-item-main">
      <div class="rep-item-top"><span class="rep-item-name">${esc(i.name || "Weapon")}</span>
        <span class="upg-rar">${esc(String(i.rarity || "common").toUpperCase())}</span></div>
      <div class="rep-hp"><b>FL ${ROMAN[cur] || cur}</b><span class="rep-arrow">▸</span>
        <b class="rep-new">FL ${ROMAN[selected] || selected}</b></div>
    </div>
  </div>`;
}

async function openUpgradeModal(rows) {
  if (state.account === "ALL") { toast("Pick one account first.", "bad"); return; }
  if (!writesLive()) { toast(writeBlockMsg(), "bad"); return; }
  const ids = rows.map((r) => r.instance_id);
  const plans = {};
  for (const lvl of [2, 3, 4]) {
    try {
      const p = await fetchPlan("upgrade", ids, upgTargets(ids, lvl));
      if (!p.error) plans[lvl] = p;
    } catch (err) { /* نكمّل بالباقي */ }
  }
  const plan = plans[4] || plans[3] || plans[2];
  if (!plan || !plan.items?.length) { toast("No upgradable weapons.", "bad"); return; }
  const items = plan.items;
  const current = Math.max(...items.map((i) => Number(i.current) || 1));
  let selected = current < 4 ? 4 : current;

  /* اختيار الدرجة بيحدّث العرض بس — البوابة بتتنادى لما زرار التأكيد يتدوس. */
  function paint() {
    /* الباك اند بيراجع كل سلاح من درجته هو لـ selected، فـ plans[selected].materials هو المجموع جاهز. */
    const mats = (plans[selected] || {}).materials || [];
    $("#m-title").textContent = items.length === 1
      ? "UPGRADE " + String(items[0].name || "WEAPON").toUpperCase()
      : "UPGRADE " + num(items.length) + " WEAPONS";
    $("#m-body").innerHTML = `
      <div class="rep-label">UPGRADING</div>
      <div class="rep-list">${items.map((i) => upgWeaponCard(i, selected)).join("")}</div>
      <div class="upg-levels">${[1, 2, 3, 4].map((lvl) => `
        <button type="button" class="upg-chip ${lvl === current ? "now" : ""} ${lvl < current ? "past" : ""} ${lvl === selected ? "sel" : ""}" data-lvl="${lvl}" ${lvl <= current ? "disabled" : ""}>
          FL ${ROMAN[lvl] || lvl}${lvl === current ? "<i>now</i>" : ""}
        </button>`).join("")}</div>
      ${mats.length ? `<div class="rep-label">REQUIRED RESOURCES</div>
        <div class="rec-mats">${mats.map(upgMatTile).join("")}</div>` : ""}
      <div class="rec-foot">
        <button type="button" class="ghost" id="upg-cancel">CANCEL</button>
        <button type="button" class="upg-go" id="upg-go" ${selected <= current ? "disabled" : ""}>${
          selected > current ? `UPGRADE TO FL ${ROMAN[selected] || selected}` : "Weapon is at max grade"}</button>
      </div>`;

    $("#upg-cancel").onclick = () => { $("#modal").hidden = true; };
    document.querySelectorAll("#m-body [data-lvl]").forEach((chip) => {
      chip.onclick = () => {
        const lvl = Number(chip.dataset.lvl);
        if (lvl <= current) return;
        selected = lvl;
        paint();
      };
    });

    const go = $("#upg-go");
    go.onclick = async () => {
      if (selected <= current) return;
      const target = selected;
      go.disabled = true;
      go.textContent = "WORKING…";
      let out;
      try {
        out = await withSync(ids, false, () =>
          post("/api/actions/upgrade", {
            account: state.account, instance_ids: ids,
            targets: upgTargets(ids, target), confirmed: true,
          }));
      } catch (err) {
        toast("⛔ Connection failed: " + err.message, "bad");
        paint();
        return;
      }
      $("#modal").hidden = true;
      await Promise.all([loadSections(), loadLog()]);
      if (out.executed) {
        state.selected.clear();
        const lvl = (out.results || []).map((r) => r.current).filter(Boolean)[0];
        if (lvl && lvl < target) toast(`⚠ Reached FL ${ROMAN[lvl] || lvl} — the gateway refused the remaining grades.`, "bad");
        else toast(`✔ Upgraded to FL ${ROMAN[lvl] || target}.`, "ok");
      } else {
        toast("⛔ " + (out.detail || out.error || "The gateway refused the upgrade."), "bad");
      }
    };
  }

  openModal("UPGRADE", "", null, null, { hideFoot: true, onMount: paint });
}


/* اللي البوابة بترجّعه في الـ changeset (مواد/كرديت) — الفرق اللي اتضاف فعلًا. */
function gainsText(out) {
  const g = (out && out.gained) || [];
  return g.length ? " · " + g.slice(0, 3).map((x) => `${esc(x.name)} +${num(x.delta)}`).join(" · ") : "";
}

/* لمّ الأكوام: دمج ستاكين في ستاك مرفوض على البوابة (خانة بآيتمين = INVALID_ARGUMENT،
   مقيس لايف)، فالزرار بيجيب كل أكوام النوع — من الستاش والأوفر — على خانات جنب
   بعضها، واللمة نفسها بتفضل سحبة واحدة جوه اللعبة.
   النطاق ممكن فيه أكتر من نوع (بحث "bandage" بيطلع Herbal وSterilized وBandage
   العاديين)، وكل نوع ليه حد تكديس مختلف (3/5/10/15/50/100) — فبدل الرفض بنلمّ
   كل نوع لوحده بالحد بتاعه. */
async function gatherPass(job) {
  const row = job.rows.find((r) => r.asset_id) || job.rows[0];
  try {
    const out = await withSync([row.instance_id], false, () =>
      post("/api/actions/gather", {
        account: state.account, instance_ids: [row.instance_id],
        asset_id: String(row.asset_id || ""),
      }));
    return { job, out, g: out.merge || out.gather || {} };
  } catch (err) {
    return { job, error: "Connection failed: " + err.message };
  }
}

async function runGather(jobs) {
  const moved = [], packed = [], failed = [];
  let slots = 0;
  for (const job of jobs) {
    const r = await gatherPass(job);
    if (r.error) { failed.push([job.name, r.error]); continue; }
    if (r.out.executed) { moved.push(r); slots += (r.g.moves || []).length; continue; }
    if (r.out.reason === "already_together" || r.g.packed) packed.push(r);
    else failed.push([job.name, r.out.detail || r.out.error || "Refused"]);
  }
  if (moved.length) {
    state.selected.clear();
    await Promise.all([loadSections(), loadLog()]);
  }
  const bits = [];
  if (moved.length) bits.push(`Brought together ${num(moved.length)} types in ${num(slots)} cells`);
  if (packed.length) bits.push(`${num(packed.length)} types already side by side`);
  if (failed.length) bits.push(`${num(failed.length)} refused (${esc(failed[0][1] || "")})`);
  if (!bits.length) bits.push("Nothing to gather in this range");
  const one = moved.length === 1 && !packed.length && !failed.length ? moved[0] : null;
  const detail = one ? ` — cap ${num(one.g.limit)}, and gathering takes ${(one.g.ideal || []).join(" + ")} per drag.` : "";
  toast((moved.length ? "✔ " : "↔ ") + bits.join(" · ") + detail,
        moved.length ? "ok" : (failed.length ? "bad" : "info"));
}

function gatherPreview(jobs, run) {
  return new Promise((resolve) => {
    let settled = false;
    const settle = (ok) => { if (!settled) { settled = true; resolve(ok); } };
    const prevCancel = $("#m-cancel").onclick;
    const prevX = $("#m-x").onclick;
    const rows = jobs.map((j) =>
      `<li><span>${esc(j.name)}</span><b>${num(j.rows.length)} piles · cap ${num(j.rows[0].stack_size || 0)} · ${num(j.rows.reduce((a, r) => a + (r.qty || 0), 0))} units</b></li>`).join("");
    openModal("GATHER PILES",
      `<p>${num(jobs.length)} types in range — each type gathers to its own cap separately, and moves are sideways only (the gateway never changes quantities).</p>`
      + `<ul class="confirm-list">${rows}</ul>`,
      async () => { settle(true); await run(); }, "GATHER ALL", {
        confirmKind: "primary", cancelLabel: "CANCEL",
        onMount: () => {
          $("#m-cancel").onclick = () => { settle(false); $("#m-cancel").onclick = prevCancel; $("#modal").hidden = true; };
          $("#m-x").onclick = () => { settle(false); $("#m-x").onclick = prevX; $("#modal").hidden = true; };
        },
      });
  });
}

/* النطاق مشترك بين MERGE وSPREAD: التحديد الأول، ولو مفيش تحديد كلمة البحث.
   كل نوع بيبقى شغلة لوحده — كل نوع ليه حد تكديس وخانات مختلفة، وكل نوع
   بيقرا الشجرة كاملة وبيضرب دفعة نقل، فالعدد بيتحصر في 12. */
function stackScopeJobs(minStacks) {
  if (state.account === "ALL") { toast("Pick one account first.", "bad"); return null; }
  const sel = Array.from(state.selected || []).map(findRow).filter(Boolean);
  const query = String(state.queries.inventory || "").trim();
  const pool = [...((state.sections?.stash || {}).slots || []), ...((state.sections?.overflow || {}).slots || [])];
  if (!sel.length && !query) { toast("Select the piles or type their name in search first — with no range it highlights every cell.", "bad"); return null; }
  const hit = sel.length ? sel : pool.filter((r) => matchesSearch(r, query));
  if (!hit.length) { toast("Select an item or type its name in search first.", "bad"); return null; }
  const groups = new Map();
  for (const r of hit) {
    const key = String(r.asset_id || r.name || "");
    if (!key) continue;
    const g = groups.get(key);
    if (g) g.push(r);
    else groups.set(key, [r]);
  }
  const jobs = Array.from(groups, ([asset, rows]) =>
    ({ asset, name: rows[0].display_name || rows[0].name || asset, rows }))
    .filter((j) => j.rows.length >= minStacks);
  if (jobs.length > 12) { toast(`The range has ${num(jobs.length)} types — narrow the search to at most 12 types.`, "bad"); return null; }
  return jobs;
}

async function gatherStacks() {
  const jobs = stackScopeJobs(2);
  if (!jobs) return;
  if (!jobs.length) { toast("This range has one pile per type — nothing to gather.", "info"); return; }
  if (jobs.length > 1) return gatherPreview(jobs, () => runGather(jobs));
  await runGather(jobs);
}

/* SPREAD: البوابة مابتقسمش الكوم (أي amount مختلف = INVALID_ARGUMENT، مقيس
   لايف)، فالحركة دي مش "نصف الكوم في خانة" — هي تفريد الأكوام الموجودة:
   خانة فاضية لكل كوم وأبعد تباعد ممكن، واللي خانتها كويسة بتفضل مكانها. */
async function spreadAsk(job, dry) {
  const row = job.rows.find((r) => r.asset_id) || job.rows[0];
  const body = { account: state.account, instance_ids: [row.instance_id], asset_id: String(row.asset_id || "") };
  if (dry) body.dry = 1;
  try {
    const out = dry
      ? await post("/api/actions/spread", body)
      : await withSync([row.instance_id], false, () => post("/api/actions/spread", body));
    return { job, out, s: out.spread || {} };
  } catch (err) {
    return { job, error: "Connection failed: " + err.message };
  }
}

function spreadRow(r) {
  const s = r.s || {};
  const cells = (s.targets || []).slice(0, 14).map((i) => num(i + 1)).join(" · ");
  return `<li><span>${esc(r.job.name)}</span><b>${num(s.total || r.job.rows.length)} piles`
    + ` · free ${num(s.free || 0)} · moves ${num((s.moves || []).length)}`
    + ` · gap ${num(s.gap || 0)}</b>${cells ? `<i class="where">cells ${cells}</i>` : ""}</li>`;
}

async function spreadStacks() {
  const jobs = stackScopeJobs(1);
  if (!jobs) return;
  if (!jobs.length) { toast("This range is empty — select piles or type their name in search.", "info"); return; }
  const plans = [], refused = [];
  for (const job of jobs) {
    const r = await spreadAsk(job, true);
    if (r.error) { refused.push([job.name, r.error]); continue; }
    if (r.out.reason === "preview") plans.push(r);
    else refused.push([job.name, r.out.detail || r.out.error || "Refused"]);
  }
  if (!plans.length) {
    const why = refused.length ? refused[0][1] : "Nothing to spread";
    toast((refused.length > 1 ? `${num(refused.length)} types refused — ` : "") + why,
          refused.length ? "bad" : "info");
    return;
  }
  const shown = plans.slice(0, 4);
  const more = plans.length - shown.length;
  const total = plans.reduce((a, r) => a + ((r.s.moves || []).length), 0);
  const refusedBits = refused.length
    ? `<p class="note">${num(refused.length)} types need no move or were refused: ${esc(refused[0][1] || "")}</p>` : "";
  const go = await confirmDestructive("SPREAD PILES",
      `<p>${num(plans.length)} types — ${num(total)} moves: every pile goes to its own free cell`
      + ` and as far apart as possible from its siblings. Quantities never change (the gateway refuses quantity changes),`
      + ` and whatever is already placed well does not move.</p>`
      + `<ul class="confirm-list">${shown.map(spreadRow).join("")}</ul>`
      + (more ? `<p class="note">and ${num(more)} more types in the range.</p>` : "")
      + refusedBits,
      `SPREAD ${num(total)}`);
  if (!go) return;
  const done = [], bad = [];
  let moves = 0;
  for (const p of plans) {
    const r = await spreadAsk(p.job, false);
    if (r.out && r.out.executed) {
      pushHistory(r.out, "Spread " + p.job.name, state.account);
      moves += ((r.s.moves || []).length);
      done.push(p.job.name);
    } else bad.push([p.job.name, (r.out && (r.out.detail || r.out.error)) || r.error || "Refused"]);
  }
  state.selected.clear();
  await Promise.all([loadSections(), loadLog()]);
  const bits = [];
  if (done.length) bits.push(`Spread ${num(done.length)} types in ${num(moves)} cells`);
  if (bad.length) bits.push(`${num(bad.length)} refused (${esc(bad[0][1] || "")})`);
  if (refused.length) bits.push(`${num(refused.length)} placed well already`);
  toast((done.length ? "✔ " : "↔ ") + bits.join(" · "), done.length ? "ok" : "bad");
}

/* ⇄ دمج الكل: الباكند بيبعت لكل نوع طلب update+delete بيحفظ الوحدات، فالدمج
   بيحصل فعليًا على البوابة — تنفيذ فوري من غير لوحة ولا سؤال، والنتيجة توست بس. */
async function mergeAllStacks() {
  if (state.account === "ALL") { toast("Pick one account first.", "bad"); return; }
  if (!writesLive()) { toast(writeBlockMsg(), "bad"); return; }
  if (state.merging) return;
  const btn = $("#btn-merge-all");
  state.merging = true;
  if (btn) { btn.disabled = true; btn.textContent = "⇄ MERGING…"; }
  let out;
  try {
    out = await post("/api/actions/merge-all", { account: state.account, execute: 1 });
  } catch (err) {
    toast("⛔ Connection failed: " + err.message, "bad");
  }
  if (btn) { btn.disabled = false; btn.textContent = "⇄ MERGE ALL"; }
  state.merging = false;
  if (!out) return;
  await Promise.all([loadSections(), loadLog()]);
  const s = (out.merge_all || {}).summary || {};
  if (out.executed) {
    toast(`✔ Merged ${num(out.merged)} piles across ${num(s.owed || 0)} types.`, "ok");
  } else if (out.reason === "already_merged") {
    toast("Every pile is already at its cap.", "info");
  } else {
    toast("⛔ " + (out.detail || out.error || "The gateway refused the merge."), "bad");
  }
}


/* بيع/تفكيك/إصلاح: إجراءات ما بتترجعش — لازم تأكيد صريح قبل ما تتبعت للبوابة. */
function confirmDestructive(title, bodyHTML, confirmLabel, extra) {
  return new Promise((resolve) => {
    let settled = false;
    const prevCancel = $("#m-cancel").onclick;
    const prevX = $("#m-x").onclick;
    const settle = (ok) => {
      if (settled) return;
      settled = true;
      $("#m-cancel").onclick = prevCancel;
      $("#m-x").onclick = prevX;
      resolve(ok);
    };
    openModal(title, bodyHTML, async () => { settle(true); }, confirmLabel, {
      confirmKind: "danger",
      cancelLabel: "CANCEL",
      ...(extra || {}),
      onMount: () => {
        $("#m-cancel").onclick = () => { settle(false); $("#modal").hidden = true; };
        $("#m-x").onclick = () => { settle(false); $("#modal").hidden = true; };
      },
    });
  });
}

function planItemsList(items) {
  return `<ul class="confirm-list">` + (items || []).map((i) =>
    `<li><span>${esc(i.name || "")}</span><b>×${num(i.qty || 1)}</b></li>`).join("") + `</ul>`;
}

/* إعادة التدوير: شبه نافذة اللعبة — عدد المحدد فوق، ومورد واحد لكل بلاطة تحت. */
function recMatTile(m) {
  const ico = m.image_filename || m.image || "";
  return `<div class="rec-mat ${rarCls(m.rarity)}" title="${esc(m.name || "Material")}">
    <div class="rec-mat-tile">${ico ? `<img src="${asset(ico)}" alt="" onerror="this.style.visibility='hidden'">` : "?"}
      <span class="rec-mat-wrench">${ICO.wrench}</span>
      <span class="rec-mat-qty">×${num(m.qty || 0)}</span></div>
    <div class="rec-mat-name">${esc(m.name || "Material")}</div>
  </div>`;
}

async function openRecycleModal(rows) {
  if (state.account === "ALL") { toast("Pick one account first.", "bad"); return; }
  if (!writesLive()) { toast(writeBlockMsg(), "bad"); return; }
  let ids = rows.map((r) => r.instance_id);
  let plan;
  try { plan = await fetchPlan("recycle", ids); } catch (err) { toast(err.message, "bad"); return; }
  if (plan.error) { toast(plan.detail || plan.error, "bad"); return; }
  if (!plan.items?.length) { toast(plan.detail || "No items can be dismantled.", "bad"); return; }
  ids = plan.items.map((i) => i.instance_id);

  if (!plan.can_recycle || !ids.length) { toast("⛔ No items can be dismantled.", "bad"); return; }
  const count = plan.items.length;
  const mats = plan.materials || [];
  const body = `
    <p class="rec-lead">You have selected <b>${num(count)} items</b> to recycle. These are the resources you will get back:</p>
    ${plan.unknown_yields ? `<p class="rec-note">${num(plan.unknown_yields)} of them have no known yield.</p>` : ""}
    <div class="rec-mats">${mats.length ? mats.map(recMatTile).join("") : '<span class="rec-note">The gateway decides the yield at execution.</span>'}</div>
    <div class="rec-foot">
      <button type="button" class="ghost" id="rec-cancel">CANCEL</button>
      <button type="button" class="pill primary" id="rec-go">RECYCLE</button>
    </div>`;

  openModal("RECYCLE " + num(count) + " ITEMS", body, null, null, {
    hideFoot: true,
    onMount: (host) => {
      const cancel = host.querySelector("#rec-cancel");
      if (cancel) cancel.onclick = () => { $("#modal").hidden = true; };
      const go = host.querySelector("#rec-go");
      go.onclick = async () => {
        go.disabled = true;
        go.textContent = "WORKING…";
        let out;
        try {
          out = await withSync(ids, false, () =>
            post("/api/actions/recycle", { account: state.account, instance_ids: ids, confirmed: true }));
        } catch (err) {
          toast("⛔ Connection failed: " + err.message, "bad");
          go.disabled = false;
          go.textContent = "RECYCLE";
          return;
        }
        $("#modal").hidden = true;
        await Promise.all([loadSections(), loadLog()]);
        const refused = out.refused || [];
        if (out.executed) {
          state.selected.clear();
          const left = refused.length
            ? ` — the game refused ${num(refused.length)}: ${refused.map((r) => r.item).join(", ")}`
            : "";
          toast(`✔ Dismantled ${(out.changed || ids).length} items${gainsText(out)}.${left}`, "ok");
          return;
        }
        if ((out.result || {}).error === "read_only") {
          showPreview("RECYCLE", out.preview, "Writes are paused — say 009 to open them.");
          return;
        }
        toast("⛔ " + (out.detail || out.result?.detail || out.error || "Refused"), "bad");
      };
    },
  });
}

/* التصليح: نسخة طبق الأصل من كارت اللعبة — REPAIRING ثم MATERIALS REQUIRED ثم CONFIRM REPAIR.
   compact للدفعة الكبيرة: الاسم والصحة في سطر واحد عشان كل حاجة تبان من غير سكرول. */
function repItemCard(it, compact) {
  const hp = it.health || {};
  const max = Number(hp.max) || 0;
  const cur = Number(hp.current) || 0;
  const q = Math.max(1, Number(it.qty) || 1);
  const next = Number(hp.new_current);
  const gain = Math.max(0, Number(hp.gain)) * q;
  const curPct = max ? Math.min(100, (cur / max) * 100) : 100;
  const ico = it.image_filename || it.image || "";
  const tile = `<div class="rep-item-tile">${ico ? `<img src="${asset(ico)}" alt="" onerror="this.style.visibility='hidden'">` : "?"}${
    q > 1 ? `<span class="rep-item-qty">×${num(q)}</span>` : ""}</div>`;
  const drop = `<button type="button" class="rep-drop" data-rep-drop="${esc(it.instance_id)}" title="Remove from this repair">×</button>`;
  const hpLine = `<div class="rep-hp"><b>${num(cur)}</b><span class="rep-arrow">▸</span><b class="rep-new">${num(next)}</b>
      <span class="rep-of">/${num(max)}</span><span class="rep-gain">+${num(gain)}</span></div>`;
  const bar = `<div class="rep-bar"><i style="width:${curPct.toFixed(1)}%"></i></div>`;
  if (compact) {
    return `<div class="rep-item compact ${rarCls(it.rarity)}">${tile}
      <div class="rep-item-main">
        <div class="rep-item-top"><span class="rep-item-name">${esc(it.name || "Item")}</span>${hpLine}${drop}</div>
        ${bar}
      </div>
    </div>`;
  }
  return `<div class="rep-item ${rarCls(it.rarity)}">${tile}
    <div class="rep-item-main">
      <div class="rep-item-top"><span class="rep-item-name">${esc(it.name || "Item")}</span>${drop}</div>
      ${hpLine}
      ${bar}
    </div>
  </div>`;
}

function repMatTile(m) {
  const need = Number(m.needed) || 0;
  const have = Number(m.available) || 0;
  const ico = m.image_filename || m.image || "";
  return `<div class="rep-mat ${rarCls(m.rarity)} ${have >= need ? "ok" : "miss"}" title="${esc(m.name || "Material")}">
    <div class="rep-mat-tile">${ico ? `<img src="${asset(ico)}" alt="" onerror="this.style.visibility='hidden'">` : "?"}
      <span class="rep-mat-num">${num(have)}/${num(need)}</span></div>
    <div class="rep-mat-name">${esc(m.name || "Material")}</div>
  </div>`;
}

/* بلاطة مورد زي لوحة الريسايل (صورته اللي عاجبته): الأيقونة كبيرة والعدد
   المطلوب بس، ويحمّر لو مش متوفر — من غير سطور "متوفر/مطلوب". */
function upgMatTile(m) {
  const need = Number(m.needed) || 0;
  const have = Number(m.available) || 0;
  const ico = m.image_filename || m.image || "";
  return `<div class="rec-mat ${rarCls(m.rarity)} ${have >= need ? "ok" : "miss"}" title="${esc(m.name || "Material")} · have ${num(have)}">
    <div class="rec-mat-tile">${ico ? `<img src="${asset(ico)}" alt="" onerror="this.style.visibility='hidden'">` : "?"}
      <span class="rec-mat-qty">${num(need)}</span></div>
    <div class="rec-mat-name">${esc(m.name || "Material")}</div>
  </div>`;
}

async function openRepairModal(rows) {
  if (state.account === "ALL") { toast("Pick one account first.", "bad"); return; }
  if (!writesLive()) { toast(writeBlockMsg(), "bad"); return; }
  let ids = rows.map((r) => r.instance_id);
  let plan;
  try { plan = await fetchPlan("repair", ids); } catch (err) { toast(err.message, "bad"); return; }
  if (plan.error) { toast(plan.detail || plan.error, "bad"); return; }
  if (!plan.items?.length) { toast(plan.detail || "No damaged items to repair.", "bad"); return; }

  function paint() {
    const items = plan.items || [];
    const mats = plan.materials || [];
    const short = mats.filter((m) => !m.has_enough).length;
    const blocked = !plan.can_repair;
    ids = items.map((i) => i.instance_id);
    $("#m-title").textContent = items.length === 1
      ? "REPAIR " + String(items[0].name || "ITEM").toUpperCase()
      : "REPAIR " + num(items.length) + " ITEMS";
    $("#m-body").innerHTML = `
      <div class="rep-label">REPAIRING</div>
      <div class="rep-list">${items.map((i) => repItemCard(i, items.length > 1)).join("")}</div>
      <div class="rep-label">MATERIALS REQUIRED${plan.cost_estimated
        ? ` <span class="rep-est" title="No measured price for every item yet — ${
            num(plan.cost_estimated)} use${plan.cost_estimated === 1 ? "s" : ""} the class default. The gateway charges the real amount.">≈</span>`
        : ""}</div>
      <div class="rep-mats">${mats.map(repMatTile).join("")}</div>
      <div class="rec-foot">
        <button type="button" class="ghost" id="rep-cancel">CANCEL</button>
        <button type="button" class="rep-go" id="rep-go" ${blocked ? "disabled" : ""}>CONFIRM REPAIR</button>
      </div>`;

    $("#rep-cancel").onclick = () => { $("#modal").hidden = true; };
    for (const btn of document.querySelectorAll("[data-rep-drop]")) {
      btn.onclick = async () => {
        const left = ids.filter((id) => id !== btn.dataset.repDrop);
        if (!left.length) { $("#modal").hidden = true; return; }
        let next;
        try { next = await fetchPlan("repair", left); } catch (err) { toast(err.message, "bad"); return; }
        if (next.error || !next.items?.length) { toast(next.detail || "Nothing left to repair.", "bad"); return; }
        plan = next;
        paint();
      };
    }

    const go = $("#rep-go");
    if (blocked) go.title = "⛔ Short on materials: " + num(short) + " item" + (short === 1 ? "" : "s") + ".";
    go.onclick = async () => {
      go.disabled = true;
      go.textContent = "WORKING…";
      let out;
      try {
        out = await withSync(ids, false, () =>
          post("/api/actions/repair", { account: state.account, instance_ids: ids, confirmed: true }));
      } catch (err) {
        toast("⛔ Connection failed: " + err.message, "bad");
        go.disabled = false;
        go.textContent = "CONFIRM REPAIR";
        return;
      }
      $("#modal").hidden = true;
      state.selected.clear();
      await Promise.all([loadSections(), loadLog()]);
      if (out.executed) { toast(`✔ Repaired ${(out.changed || ids).length} items${gainsText(out)}.`, "ok"); return; }
      if ((out.result || {}).error === "read_only") {
        showPreview("REPAIR", out.preview, "Writes are paused — say 009 to open them.");
        return;
      }
      toast("⛔ " + (out.detail || out.result?.detail || out.error || "Refused"), "bad");
    };
  }

  openModal("REPAIR", "", null, null, { hideFoot: true, onMount: paint });
}

async function openSellModal(rows) {
  if (state.account === "ALL") { toast("Pick one account first.", "bad"); return; }
  if (!writesLive()) { toast(writeBlockMsg(), "bad"); return; }
  const ids = rows.map((r) => r.instance_id);
  let plan;
  try { plan = await fetchPlan("sell", ids); } catch (err) { toast(err.message, "bad"); return; }
  if (plan.error) { toast(plan.detail || plan.error, "bad"); return; }
  if (!plan.items?.length) { toast("Nothing to sell.", "bad"); return; }
  const total = Number(plan.total) || 0;
  const ok = await confirmDestructive("SELL",
    `<p class="note">Selling = destroying the item on the game gateway for credits — the action is final and cannot be undone.</p>`
    + planItemsList(plan.items)
    + `<p class="confirm-total">Return: <b>+${numSpaced(total)}</b></p>`, "SELL");
  if (!ok) return;
  let out;
  try {
    out = await withSync(ids, false, () =>
      post("/api/actions/sell", { account: state.account, instance_ids: ids, confirmed: true }));
  } catch (err) { toast("⛔ Connection failed: " + err.message, "bad"); return; }
  if (out.executed) {
    state.selected.clear();
    await Promise.all([loadSections(), loadLog()]);
    const got = (out.gained || []).length ? gainsText(out) : ` for +${numSpaced(total)}`;
    toast(`✔ Sold ${(out.changed || ids).length} items${got}.`, "ok");
    return;
  }
  if ((out.result || {}).error === "read_only") {
    showPreview("SELL", out.preview, "Writes are paused — say 009 to open them.");
    return;
  }
  toast("⛔ " + (out.detail || out.result?.detail || out.error || "Refused"), "bad");
}

/* ------------------------------------------------------------------ SPLIT STACK */
function splitPlanFor(row) {
  const container = String(row.container || "").toLowerCase();
  if (container === "stash" || container === "overflow") {
    const target = (state.loadout?.slots?.backpack || []).find((s) => !s.item && s.wrapper_id)?.wrapper_id || "";
    return target ? { group: "stash", mode: "to_backpack", target_wrapper_id: target, split_wrapper_id: "" } : null;
  }
  if (["backpack", "safe_pocket", "quick_use"].includes(container)) {
    const empty = (state.loadout?.slots?.[container] || [])
      .find((s) => !s.item && s.wrapper_id && s.wrapper_id !== row.wrapper_id)?.wrapper_id || "";
    return empty ? { group: "loadout", mode: "split", target_wrapper_id: "", split_wrapper_id: empty } : null;
  }
  return null;
}

function openSplitModal(row) {
  if (state.account === "ALL") { toast("Pick one account first.", "bad"); return; }
  const qty = Number(row.qty) || 0;
  if (qty < 2) { toast("This item is not stacked.", "bad"); return; }
  const plan = splitPlanFor(row);
  const wrapper = plan ? (plan.target_wrapper_id || plan.split_wrapper_id || "") : "";
  const max = qty - 1;
  const initial = Math.max(1, Math.floor(qty / 2));
  const where = String(row.container || "").toUpperCase();
  const DEST = { backpack: "Backpack", safe_pocket: "Safe pocket", quick_use: "Quick use",
                 stash: "Stash", overflow: "Overflow" };
  const destName = plan ? (plan.group === "stash" ? "Backpack"
                         : (DEST[String(row.container || "").toLowerCase()] || where)) : "";
  const body = `
    <div class="split-modal">
      ${gearHero(row, `${num(qty)} × ${where}`)}
      <div class="split-controls">
        <label for="split-amount">SPLIT AMOUNT</label>
        <div class="split-row">
          <button type="button" class="split-step" data-step="-1" aria-label="Decrease">−</button>
          <input id="split-amount" type="number" min="1" max="${max}" step="1" value="${initial}" inputmode="numeric">
          <button type="button" class="split-step" data-step="1" aria-label="Increase">+</button>
        </div>
        <input id="split-range" type="range" min="1" max="${max}" step="1" value="${initial}">
        <div class="split-hint"><span id="split-preview"></span><span>ALLOWED: 1 TO ${max}</span></div>
      </div>
      <div class="split-actions">
        <button type="button" class="pill purple" data-split-run="go">✂ SPLIT</button>
      </div>
      <p class="gear-note">The site performs the split on the official gateway route in one atomic batch: <b>moveAmount</b> takes the amount off the source pile into a brand-new piece, and <b>setParents</b> drops that piece into the free cell${plan ? ` in ${esc(destName)}` : ""} — live-verified, no in-game step needed. ${plan ? "" : "It needs an empty cell: free one if the gateway refuses."} To undo: merge the two piles back with COMBINE.</p>
      ${gearArmNote()}
    </div>`;

  openModal(`SPLIT STACK — ${row.display_name || row.name}`, body, null, "", {
    cls: "modal-split", cancelLabel: "CANCEL",
    onMount: (host) => {
      const input = host.querySelector("#split-amount");
      const range = host.querySelector("#split-range");
      const preview = host.querySelector("#split-preview");
      const sync = (v, write = true) => {
        const amount = Math.min(max, Math.max(1, Math.round(Number(v) || 1)));
        if (write && input) input.value = amount;
        if (range) range.value = amount;
        if (preview) preview.textContent = `${num(qty)} → ${num(amount)} + ${num(qty - amount)}`;
        return amount;
      };
      sync(initial);
      if (input) {
        input.addEventListener("input", () => sync(input.value, false));
        input.addEventListener("change", () => sync(input.value));
        input.focus();
        input.select();
      }
      if (range) range.addEventListener("input", () => sync(range.value));
      host.querySelectorAll("[data-step]").forEach((b) => b.onclick = () => {
        sync(Number(input?.value || initial) + Number(b.dataset.step || 0));
        input?.focus();
      });
      host.querySelectorAll("[data-split-run]").forEach((b) => b.onclick = () => {
        runSplit(row, sync(input?.value || initial), wrapper);
      });
    },
  });
}

/* ------------------------------------------------------------------ ATTACHMENT MANAGER */
let mgrState = null;
// فك أي مرفق بيروح للأوفر ستاش دايماً — الخانة دي مش بتضيع مكان في الستاش المليان.
const MGR_TARGET = "overflow";

function mgrFilledSlots(ids) {
  const wanted = new Set(ids || []);
  const slots = [];
  for (const w of mgrState?.data?.weapons || []) {
    if (!wanted.has(w.instance_id)) continue;
    for (const s of w.slots || []) if (!s.is_empty && !isStencil(s) && s.wrapper_id) slots.push(s.wrapper_id);
  }
  return slots;
}

function mgrDetachLabel() {
  const all = mgrState?.data?.weapons?.length || 0;
  const n = mgrState?.sel?.size || 0;
  const slots = mgrFilledSlots(n === all ? (mgrState.data.weapons || []).map((w) => w.instance_id) : [...mgrState.sel]);
  return slots.length ? `⚡ DETACH ALL (${slots.length}) → OVERFLOW` : "⚡ DETACH ALL → OVERFLOW";
}

async function openAttachmentManager(weaponRows) {
  if (state.account === "ALL") { toast("Pick one account first.", "bad"); return; }
  const ids = (weaponRows || []).filter((r) => isWeapon(r) && !r.is_blueprint).map((r) => r.instance_id);
  if (!ids.length) { toast("No weapons selected to manage attachments for.", "bad"); return; }
  mgrState = { ids, sel: new Set(), data: null, initialized: false };
  openModal("ATTACHMENT MANAGER", `<div class="mgr-wrap"><p class="note">Preparing the slots and what is available from the stash…</p></div>`, null, "", {
    wide: true, cancelLabel: "DONE",
  });
  await refreshManagerView();
}

async function refreshManagerView() {
  if (!mgrState) return;
  let data;
  try {
    data = await json(`/api/attachments/manager?account=${encodeURIComponent(state.account)}&ids=${encodeURIComponent(mgrState.ids.join(","))}`);
  } catch (err) { toast(err.message, "bad"); return; }
  if (data.error) {
    const body = $("#m-body");
    if (body) body.innerHTML = `<p class="note bad">${esc(data.detail || data.error)}</p>`;
    return;
  }
  mgrState.data = data;
  const alive = new Set((data.weapons || []).map((w) => w.instance_id));
  if (!mgrState.initialized) {
    for (const w of data.weapons || []) mgrState.sel.add(w.instance_id);
    mgrState.initialized = true;
  } else {
    mgrState.sel = new Set([...mgrState.sel].filter((id) => alive.has(id)));
    if (!mgrState.sel.size) for (const w of data.weapons || []) mgrState.sel.add(w.instance_id);
  }
  renderManager();
}

function mgrWeaponCard(w) {
  const hp = w.health || {};
  const max = Number(hp.max) || 0;
  const pct = max ? Math.round((Number(hp.current) || 0) / max * 100) : 100;
  const slots = (w.slots || []).map((s) => `<span class="mgr-wslot ${s.is_empty ? "empty" : rarCls(s.rarity)}" title="${esc(s.is_empty ? "Empty Slot" : (s.display_name || "Attachment"))}">${
    s.is_empty ? `<span class="plus">+</span>` : (s.image_filename ? `<img src="${asset(s.image_filename)}" alt="">` : "")
  }</span>`).join("");
  const stencils = (w.stencils || []).length
    ? `<div class="mgr-wstencils">${(w.stencils || []).map((s) => `<span class="mgr-wstencil" title="${esc(s.display_name || "Stencil")} — cosmetic finish, it stays on the weapon">
        ${s.image_filename ? `<img src="${asset(s.image_filename)}" alt="">` : ""}<span>${esc(s.display_name || "Stencil")}</span><em>STENCIL · KEEPS</em></span>`).join("")}</div>`
    : "";
  return `<div class="mgr-weapon">
    <label class="mgr-check"><input type="checkbox" data-check="${esc(w.instance_id)}" ${mgrState.sel.has(w.instance_id) ? "checked" : ""}></label>
    <div class="mgr-wicon">${w.image ? `<img src="${asset(w.image)}" alt="">` : ""}</div>
    <div class="mgr-wmain">
      <div class="mgr-wname">${esc(w.name || "")}</div>
      <div class="mgr-whp ${pct < 100 ? "hurt" : ""}">${pct}% HP <span>•</span> ${w.equipped}/${w.total_slots} slots</div>
      <div class="mgr-wslots">${slots || `<span class="note">no slots</span>`}</div>
      ${stencils}
    </div>
    <div class="mgr-wacts">
      <button type="button" class="ghost tiny" data-wcopy="${esc(w.instance_id)}">Copy</button>
      <button type="button" class="ghost tiny" data-wpaste="${esc(w.instance_id)}" ${state.clipboard ? "" : "disabled"}>Paste</button>
      <button type="button" class="ghost tiny" data-winspect="${esc(w.instance_id)}">Inspect</button>
    </div>
  </div>`;
}

function renderManager() {
  const data = mgrState?.data;
  const body = $("#m-body");
  if (!data || !body) return;
  const slotMap = {};
  for (const w of data.weapons || []) for (const s of w.slots || []) if (s.wrapper_id) slotMap[s.wrapper_id] = s;
  const armed = writesLive();
  const counts = data.counts || {};

  const groupsHTML = (data.groups || []).map((group, idx) => {
    const empties = (group.weapons || []).filter((w) => w.is_empty && w.wrapper_id);
    const available = group.available || [];
    const slotRows = (group.weapons || []).map((w) => {
      const slot = slotMap[w.wrapper_id];
      const filled = !w.is_empty;
      return `<div class="mgr-slot-row ${filled ? "" : "empty"}">
        <span class="mgr-wpn">${esc(w.name || "")}</span>
        <button type="button" class="mgr-slot ${filled ? "filled " + rarCls(slot?.rarity) : "empty"}"
                data-detach-w="${esc(w.instance_id)}" data-detach-s="${esc(w.wrapper_id || "")}"
                ${filled && w.wrapper_id && armed ? "" : "disabled"}
                title="${filled ? `Detach ${esc(slot?.display_name || "attachment")} → OVERFLOW` : "Empty slot"}">
          ${filled
            ? (slot?.image_filename ? `<img src="${asset(slot.image_filename)}" alt="">` : `<span class="dot"></span>`)
            : `<span class="plus">+</span>`}
        </button>
      </div>`;
    }).join("");
    const filledSlots = (group.weapons || []).filter((w) => !w.is_empty && w.wrapper_id);
    const availCards = available.map((item) => {
      // أي خانة فاضية في القسم ده تخدم أي نوع متاح فيه. القرن بالترتيب
      // (empties[i]) كان بيدي "EQUIP" لأول كارت بس ويخلي الباقي "FULL".
      const empty = empties[0];
      const occupied = filledSlots.find((w) => w.asset_id !== item.asset_id);
      const target = empty || occupied;
      const mode = empty ? "EQUIP" : (item.installed ? "EQUIPPED" : (occupied ? "SWAP" : "FULL"));
      const canAct = armed && !!target && mode !== "EQUIPPED";
      const hint = mode === "EQUIP" ? "Fits into the first free cell"
        : mode === "SWAP" ? `Swaps ${esc(occupied.attachment_name || "the current attachment")} with yours`
        : mode === "EQUIPPED" ? "This type is already fitted in these cells"
        : "No free cell and no swappable cell";
      return `<div class="mgr-avail-card ${rarCls(item.rarity)}">
        <div class="mgr-avail-ico">${item.image_filename ? `<img src="${asset(item.image_filename)}" alt="" onerror="this.style.visibility='hidden'">` : ""}</div>
        <div class="mgr-avail-name" title="${esc(item.name || "")}">${esc(item.name || "")}</div>
        <button type="button" class="mgr-equip ${mode === "SWAP" ? "mgr-swap" : ""} ${mode === "EQUIPPED" ? "mgr-on" : ""}"
                data-equip-w="${esc(target?.instance_id || "")}" data-equip-s="${esc(target?.wrapper_id || "")}"
                data-att="${esc(item.instance_id)}" data-src="${esc(item.wrapper_id || "")}"
                ${canAct ? "" : "disabled"}
                title="${armed ? hint : writeBlockMsg()}">${mode}${mode === "EQUIP" || mode === "SWAP" ? ` (${num(item.qty || 1)})` : ""}</button>
      </div>`;
    }).join("");
    return `<section class="mgr-group">
      <div class="mgr-group-head"><span class="mgr-idx">${idx + 1}</span><span>${esc(group.label || group.slot_name || "Slot")}</span>
        <span class="mgr-meta">${group.empty}/${(group.weapons || []).length} empty</span></div>
      <div class="mgr-slot-rows">${slotRows}</div>
      <div class="mgr-avail-head">AVAILABLE IN INVENTORY (${available.length})</div>
      <div class="mgr-avail-grid">${availCards || `<p class="note">No attachments of this type are available in the stash.</p>`}</div>
    </section>`;
  }).join("");

  body.innerHTML = `<div class="mgr-wrap">
    <div class="mgr-toolbar">
      <button type="button" class="ghost tiny mgr-detachall" id="mgr-detachall"
              title="${armed ? "Moves every attachment of the selected weapons to overflow in one click — UNDO brings them back" : writeBlockMsg()}">${mgrDetachLabel()}</button>
      <div class="spacer"></div>
      <button type="button" class="ghost tiny mgr-autofill" id="mgr-autofill" title="${armed ? "Best available attachments for every free cell" : "Writes are locked right now — say 009"}">✨ AUTO-FILL BEST</button>
    </div>
    <div class="mgr-counts">
      <span><b>${counts.weapons || 0}</b> WEAPONS</span>
      <span><b>${counts.slots || 0}</b> SLOTS</span>
      <span><b>${counts.empty || 0}</b> EMPTY</span>
      <span><b>${counts.available || 0}</b> IN INVENTORY</span>
    </div>
    <h5 class="mgr-h">WEAPON ATTACHMENT SLOTS</h5>
    ${groupsHTML || `<p class="note">No known attachment slots for these weapons.</p>`}
    <h5 class="mgr-h">INDIVIDUAL WEAPONS (${(data.weapons || []).length})</h5>
    <div class="mgr-weapons">${(data.weapons || []).map(mgrWeaponCard).join("")}</div>
    ${gearArmNote()}
  </div>`;

  const detachAll = $("#mgr-detachall");
  if (detachAll) detachAll.onclick = async () => {
    if (!writesLive()) { toast(writeBlockMsg(), "bad"); return; }
    const all = (data.weapons || []).map((w) => w.instance_id);
    const weaponIds = mgrState.sel.size ? [...mgrState.sel] : all;
    const slots = mgrFilledSlots(weaponIds);
    if (!slots.length) { toast("The selected weapons have no fitted attachments.", "bad"); return; }
    detachAll.disabled = true;
    const out = await attachmentAction(`detach ${slots.length} → OVERFLOW`,
      "/api/actions/attachments/detach",
      { weapon_ids: weaponIds, slot_wrapper_ids: slots, target_container: MGR_TARGET, confirmed: true });
    detachAll.disabled = false;
    if (out?.executed) refreshManagerView();
  };
  const auto = $("#mgr-autofill");
  if (auto) auto.onclick = async () => {
    if (!writesLive()) { toast(writeBlockMsg(), "bad"); return; }
    const weaponIds = mgrState.sel.size ? [...mgrState.sel] : (data.weapons || []).map((w) => w.instance_id);
    if (!weaponIds.length) { toast("Select at least one weapon.", "bad"); return; }
    auto.disabled = true;
    const out = await attachmentAction(`auto-fill best (${weaponIds.length} weapons)`,
      "/api/actions/attachments/autofill", { weapon_ids: weaponIds, confirmed: true });
    auto.disabled = false;
    if (out?.executed) refreshManagerView();
  };

  body.querySelectorAll("[data-check]").forEach((cb) => cb.onchange = () => {
    const id = cb.dataset.check;
    if (cb.checked) mgrState.sel.add(id); else mgrState.sel.delete(id);
    const btn = $("#mgr-detachall");
    if (btn) btn.textContent = mgrDetachLabel();
  });

  body.querySelectorAll("[data-detach-w]").forEach((b) => b.onclick = async () => {
    if (!writesLive()) { toast(writeBlockMsg(), "bad"); return; }
    const wid = b.dataset.detachW, swid = b.dataset.detachS;
    if (!wid || !swid) return;
    b.disabled = true;
    const out = await attachmentAction(`detach → ${MGR_TARGET.toUpperCase()}`,
      "/api/actions/attachments/detach",
      { weapon_ids: [wid], slot_wrapper_ids: [swid], target_container: MGR_TARGET, confirmed: true });
    if (out?.executed) refreshManagerView();
    else b.disabled = false;
  });

  body.querySelectorAll("[data-equip-w]").forEach((b) => b.onclick = async () => {
    if (!writesLive()) { toast(writeBlockMsg(), "bad"); return; }
    const wid = b.dataset.equipW, swid = b.dataset.equipS, att = b.dataset.att, src = b.dataset.src;
    if (!wid || !swid || !att) { toast("No free cell and no swappable cell.", "bad"); return; }
    b.disabled = true;
    const swap = b.classList.contains("mgr-swap");
    const out = await attachmentAction(swap ? "SWAP — old attachment removed" : "equip attachment",
      "/api/actions/attachments/attach",
      { weapon_id: wid, slot_wrapper_id: swid, attachment_id: att, source_wrapper_id: src || null,
        target_container: MGR_TARGET });
    if (out?.executed) refreshManagerView();
    else b.disabled = false;
  });

  body.querySelectorAll("[data-wcopy]").forEach((b) => b.onclick = () => {
    const w = (data.weapons || []).find((x) => x.instance_id === b.dataset.wcopy);
    if (w) copyAttachmentSetup(w);
    renderManager();
  });
  body.querySelectorAll("[data-wpaste]").forEach((b) => b.onclick = async () => {
    if (!state.clipboard) { toast("No build copied — Copy from a weapon first.", "bad"); return; }
    if (!writesLive()) { toast(writeBlockMsg(), "bad"); return; }
    const w = (data.weapons || []).find((x) => x.instance_id === b.dataset.wpaste);
    if (!w) return;
    b.disabled = true;
    const out = await attachmentAction(`paste → ${w.name}`, "/api/actions/attachments/paste",
      { weapon_ids: [w.instance_id], setup: state.clipboard, confirmed: true });
    if (out?.executed) refreshManagerView();
    else b.disabled = false;
  });
  body.querySelectorAll("[data-winspect]").forEach((b) => b.onclick = () => {
    const id = b.dataset.winspect;
    $("#modal").hidden = true;
    inspect(id);
  });
}

/* ------------------------------------------------------------------ ماركات + قائمة الكليك اليمين */
function rowLevel(r) {
  const lv = Number(r?.level) || 0;
  if (lv) return lv;
  const q = Number(r?.quality_level) || 0;
  if (q) return Math.min(5, q + 1);
  return 0;
}

function rowDamaged(r) {
  if (!r) return false;
  if (r.damaged) return true;
  if (!durabilityVisible(r)) return false;
  const d = durabilityInfo(r);
  return d.current < d.max;
}

function rowSellTotal(rows) {
  return (rows || []).reduce((sum, r) => sum + itemTotalValue(r, r.qty || 1), 0);
}

function rememberClipboard(payload) {
  state.clipboard = payload;
  try { localStorage.setItem("fahmy.attach.clipboard", JSON.stringify(payload)); } catch { /* storage disabled */ }
}

function copyAttachmentSetup(row) {
  const raw = Array.isArray(row?.slots) ? row.slots : attachmentsOf(row);
  const slots = raw.filter((s) => !s.is_empty && s.asset_id).map((s) => ({
    slot_name: s.slot_name || null,
    slot_asset_id: s.slot_asset_id !== undefined && s.slot_asset_id !== null ? String(s.slot_asset_id) : null,
    asset_id: s.asset_id !== undefined && s.asset_id !== null ? String(s.asset_id) : null,
    name: s.display_name || s.name || "",
  }));
  if (!slots.length) { toast("This weapon has no attachments to copy.", "bad"); return; }
  rememberClipboard({ weapon: row.display_name || row.name || "weapon", slots, at: Date.now() });
  toast(`📋 Copied build ${row.display_name || row.name} (${slots.length} attachments).`, "ok");
}

async function attachmentAction(label, url, body) {
  if (state.account === "ALL") { toast("Pick one account first.", "bad"); return null; }
  if (!writesLive()) { toast(writeBlockMsg(), "bad"); return null; }
  const ids = [...new Set([...(body.weapon_id ? [body.weapon_id] : []), ...((body.weapon_ids) || [])])];
  let out;
  try { out = await withSync(ids, false, () => post(url, { account: state.account, ...(body || {}) })); }
  catch (err) { toast("Failed: " + err.message, "bad"); return null; }
  if (out.executed) {
    state.selected.clear();
    pushHistory(out, label);
    await Promise.all([loadSections(), loadLog()]);
    toast("✔ " + label, "ok");
  } else if (out.result?.error === "read_only") {
    showPreview(label, out.preview, "Writes are paused — say 009 to open them.");
  } else {
    toast("⛔ " + (out.result?.detail || out.detail || out.error || "Refused"), "bad");
  }
  return out;
}

function openCtx(e, tile, ids) {
  const row = findRow(ids[0]) || {};
  const displayName = row.display_name || row.name || tile.dataset.name || "";
  const container = tile.dataset.container;
  const sourceContainer = String(row.container || "").toLowerCase() || container;
  const multiSelected = state.selected.size > 1 && ids.some((id) => state.selected.has(id));
  const useIds = multiSelected ? [...new Set([...state.selected, ...ids])] : ids;
  const useRows = useIds.map((id) => findRow(id)).filter(Boolean);
  const count = useRows.length || useIds.length;
  const weapons = useRows.filter((r) => isWeapon(r) && !r.is_blueprint);
  const allWeapons = weapons.length > 0 && weapons.length === useRows.length;
  const damaged = useRows.filter(rowDamaged);
  const lvl = rowLevel(row);
  const lvlText = lvl > 0 && lvl < 5 ? (ROMAN[lvl] || "") : "";
  const name = displayName + (lvlText && !displayName.trim().toUpperCase().endsWith(" " + lvlText) ? " " + lvlText : "");
  const splitRow = ids.map((id) => findRow(id))
    .filter((r) => r && (r.qty || 0) > 1 && !r.is_blueprint)
    .sort((a, b) => (Number(b.qty) || 0) - (Number(a.qty) || 0))[0] || null;
  const splitGroup = !splitRow ? ""
    : ["stash", "overflow"].includes(String(splitRow.container || "").toLowerCase()) ? "stash"
    : ["backpack", "safe_pocket", "quick_use"].includes(String(splitRow.container || "").toLowerCase()) ? "loadout" : "";
  const bpEmpty = (state.loadout?.slots?.backpack || []).find((s) => !s.item && s.wrapper_id)?.wrapper_id || "";
  const splitEmpty = !splitRow ? "" : (state.loadout?.slots?.[String(splitRow.container || "").toLowerCase()] || [])
    .find((s) => !s.item && s.wrapper_id && s.wrapper_id !== splitRow.wrapper_id)?.wrapper_id || "";
  const splitReady = splitGroup === "stash" ? !!bpEmpty : !!splitEmpty;
  const canSplit = !!splitRow && !!splitGroup && (Number(splitRow.qty) || 0) > 1;
  const sellTotal = rowSellTotal(useRows);
  const upgradeable = allWeapons && useRows.some((r) => rowLevel(r) < 4);
  const allMaxed = allWeapons && useRows.every((r) => rowLevel(r) >= 4);

  let html = `<div class="ctx-title"><span>${esc(name)}</span>${count > 1 ? `<span class="ctx-count">${count} ITEMS</span>` : ""}</div>`;

  if (allWeapons) {
    html += `<div class="ctx-item">
      <button type="button" class="ctx-label" data-sub="1">ATTACHMENTS<span class="arrow">›</span></button>
      <div class="ctx-sub">
        <button type="button" data-manage="1">MANAGE<span class="ctx-tag">${weapons.length}</span></button>
        <button type="button" data-copy="1">COPY</button>
        <button type="button" data-paste="1" ${state.clipboard ? "" : "disabled"} title="${esc(state.clipboard?.weapon || "No build copied")}">PASTE</button>
        <button type="button" class="danger" data-strip="1">STRIP</button>
      </div>
    </div>`;
  }

  /* اللي البوابة الرسمية بتنفّذه فعلاً: النقل + recycle/scrap/repair/erase + ترقية
     الأسلحة + تقسيم ودمج الكميات (كلها متقيسة لايف على mutate). */
  if (allWeapons) {
    html += `<button type="button" class="ctx-row" data-upgrade="1" ${upgradeable ? "" : "disabled"} title="Upgrade the weapon on the game gateway — the requirements panel shows up and you pick the grade">${allMaxed ? "UPGRADE (MAX LEVEL)" : "UPGRADE"}</button>`;
  }
  if (damaged.length) {
    html += `<button type="button" class="ctx-row" data-repair="1" title="Repairs with materials from your stash on the game gateway — asks for confirmation">REPAIR</button>`;
  }
  html += `<button type="button" class="ctx-row" data-sell="1" title="Destroys the item on the game gateway and gives credits — asks for confirmation">SELL<span class="sell-total ${sellTotal > 0 ? "" : "zero"}">+${numSpaced(sellTotal)}</span></button>`;
  html += `<button type="button" class="ctx-row danger" data-recycle="1" title="Breaks down into materials on the game gateway — asks for confirmation">RECYCLE</button>`;
  if (canSplit) {
    html += `<button type="button" class="ctx-row" data-splitstack="1" title="Split on the Embark gateway itself: moveAmount creates the new piece and setParents drops it into ${splitReady ? "the free cell" : "a free cell in the same section"} — one atomic request, no in-game step at all.">SPLIT STACK<span class="ctx-tag" title="Direct write to the source">WRITE</span></button>`;
  }
  const unknownHit = useRows.map((r) => String((r && r.asset_id) || "")).find((id) => id && state.newItems[id]);
  if (unknownHit) {
    html += `<button type="button" class="ctx-row" data-identify="${esc(unknownHit)}" title="An item that landed in a patch and has no name in the indexes — name it once and it behaves normally">` +
      `NAME NEW ITEM<span class="ctx-tag">${esc(String((state.newItems[unknownHit] || {}).count || 1))}</span></button>`;
  }

  const ctx = $("#ctx");
  clearTimeout(ctxOpenTimer);
  ctxOpenTimer = 0;
  ctxOpenItem = null;
  ctx.hidden = false;
  ctx.innerHTML = html;
  const pad = 12;
  const w = ctx.offsetWidth, h = ctx.offsetHeight;
  ctx.classList.toggle("left", e.clientX + w + 220 > window.innerWidth);
  let x = Math.min(e.clientX, window.innerWidth - w - pad);
  let y = e.clientY;
  if (y + h > window.innerHeight - pad) y = Math.max(pad, window.innerHeight - h - pad);
  ctx.style.left = Math.max(pad, x) + "px";
  ctx.style.top = Math.max(pad, y) + "px";

  if (FINE_POINTER) {
    ctx.querySelectorAll(".ctx-label").forEach((label) => {
      const item = label.closest(".ctx-item");
      label.onmouseenter = () => {
        clearTimeout(item._ctxCloseTimer);
        item._ctxCloseTimer = 0;
        if (item.classList.contains("hover")) {
          clearTimeout(ctxOpenTimer);
          ctxOpenTimer = 0;
          ctxOpenItem = null;
          return;
        }
        const delay = ctx.querySelector(".ctx-item.hover") ? 90 : 0;
        clearTimeout(ctxOpenTimer);
        ctxOpenItem = item;
        const open = () => {
          if (ctxOpenItem !== item) return;
          ctx.querySelectorAll(".ctx-item.hover").forEach((o) => { if (o !== item) o.classList.remove("hover"); });
          item.classList.add("hover");
          ctxOpenItem = null;
          ctxOpenTimer = 0;
        };
        if (delay) ctxOpenTimer = setTimeout(open, delay);
        else open();
      };
      label.onmouseleave = () => {
        if (ctxOpenItem === item) {
          clearTimeout(ctxOpenTimer);
          ctxOpenTimer = 0;
          ctxOpenItem = null;
        }
        clearTimeout(item._ctxCloseTimer);
        item._ctxCloseTimer = setTimeout(() => {
          item.classList.remove("hover");
          item._ctxCloseTimer = 0;
        }, 260);
      };
    });
    ctx.querySelectorAll(".ctx-item").forEach((item) => {
      item.onmousemove = () => {
        if (!item.classList.contains("hover")) return;
        clearTimeout(item._ctxCloseTimer);
        item._ctxCloseTimer = 0;
      };
    });
    ctx.querySelectorAll(".ctx-sub").forEach((sub) => {
      sub.onmouseenter = () => {
        clearTimeout(ctxOpenTimer);
        ctxOpenTimer = 0;
        ctxOpenItem = null;
        const owner = sub.closest(".ctx-item");
        if (owner) {
          clearTimeout(owner._ctxCloseTimer);
          owner._ctxCloseTimer = 0;
          owner.classList.add("hover");
        }
      };
      sub.onmouseleave = () => {
        const owner = sub.closest(".ctx-item");
        if (!owner) return;
        clearTimeout(owner._ctxCloseTimer);
        owner._ctxCloseTimer = setTimeout(() => {
          owner.classList.remove("hover");
          owner._ctxCloseTimer = 0;
        }, 260);
      };
    });
  }
  ctx.querySelectorAll("[data-sub]").forEach((b) => b.onclick = (ev) => {
    ev.stopPropagation();
    const item = b.closest(".ctx-item");
    ctx.querySelectorAll(".ctx-item.open").forEach((o) => { if (o !== item) o.classList.remove("open"); });
    item.classList.toggle("open");
  });
  ctx.querySelectorAll("[data-manage]").forEach((b) => b.onclick = () => {
    hideCtx();
    openAttachmentManager(weapons);
  });
  ctx.querySelectorAll("[data-copy]").forEach((b) => b.onclick = () => {
    hideCtx();
    copyAttachmentSetup(weapons[0]);
  });
  ctx.querySelectorAll("[data-paste]").forEach((b) => b.onclick = () => {
    hideCtx();
    if (!state.clipboard) { toast("No build copied — COPY from a weapon first.", "bad"); return; }
    attachmentAction(`paste → ${weapons.map((w) => w.display_name || w.name).join(", ")}`,
      "/api/actions/attachments/paste",
      { weapon_ids: weapons.map((w) => w.instance_id), setup: state.clipboard, confirmed: true });
  });
  ctx.querySelectorAll("[data-strip]").forEach((b) => b.onclick = () => {
    hideCtx();
    attachmentAction(`strip ${weapons.length} weapon(s) → OVERFLOW`,
      "/api/actions/attachments/detach",
      { weapon_ids: weapons.map((w) => w.instance_id), target_container: "overflow", confirmed: true });
  });
  ctx.querySelectorAll("[data-upgrade]").forEach((b) => b.onclick = () => {
    hideCtx();
    openUpgradeModal(weapons);
  });
  ctx.querySelectorAll("[data-recycle]").forEach((b) => b.onclick = () => {
    hideCtx();
    openRecycleModal(useRows);
  });
  ctx.querySelectorAll("[data-repair]").forEach((b) => b.onclick = () => {
    hideCtx();
    openRepairModal(useRows);
  });
  ctx.querySelectorAll("[data-sell]").forEach((b) => b.onclick = () => {
    hideCtx();
    openSellModal(useRows);
  });
  ctx.querySelectorAll("[data-splitstack]").forEach((b) => b.onclick = () => {
    hideCtx();
    openSplitModal(splitRow);
  });
  ctx.querySelectorAll("[data-identify]").forEach((b) => b.onclick = () => {
    hideCtx();
    identifyAsset(b.dataset.identify);
  });
}
function hideCtx() {
  clearTimeout(ctxOpenTimer);
  ctxOpenTimer = 0;
  ctxOpenItem = null;
  const ctx = $("#ctx");
  ctx.querySelectorAll(".ctx-item").forEach((o) => clearTimeout(o._ctxCloseTimer));
  ctx.querySelectorAll(".ctx-item.hover, .ctx-item.open").forEach((o) => o.classList.remove("hover", "open"));
  ctx.hidden = true;
}
document.addEventListener("click", (e) => {
  if (!e.target.closest("#ctx")) hideCtx();
  else if (!e.target.closest("#ctx .ctx-item")) {
    clearTimeout(ctxOpenTimer);
    ctxOpenTimer = 0;
    ctxOpenItem = null;
    $("#ctx").querySelectorAll(".ctx-item.open, .ctx-item.hover").forEach((o) => {
      o.classList.remove("open", "hover");
    });
  }
  if (e.target.id === "modal") $("#modal").hidden = true;
  if (!e.target.closest("#drawer")) $("#drawer").hidden = true;
  if (!e.target.closest("#sort-dd")) {
    const pop = $("#sort-pop");
    if (pop) pop.hidden = true;
    const dd = $("#sort-dd");
    if (dd) dd.classList.remove("open");
  }
  if (state.menuOpen && !e.target.closest("#acc-switch")) { state.menuOpen = false; renderHeader(); }
  if (state.queueOpen && !e.target.closest("#btn-queue, #queue-pop")) { state.queueOpen = false; renderQueue(); }
  if (!e.target.closest("#lo-dd, #modal") && state.loPopOpen) {
    state.loPopOpen = false;
    const pop = $("#lo-pop");
    if (pop) pop.hidden = true;
    $("#lo-dd")?.classList.remove("open");
  }
  if (!e.target.closest(".tile")) hideCard();
  const keepSel = e.target.closest(".tile, #ctx, #modal, #drawer, .sys-drawer, .sys-backdrop, .item-card, #sort-dd, #acc-switch, #lo-dd");
  if (!keepSel && state.selected.size) {
    const field = e.target.closest("input, textarea");
    if (field?.id) state.searchFocus = field.id;
    state.selected.clear();
    renderColumns(); updateSelCount();
  }
});

/* ------------------------------------------------------------------ drawer */
function dbMats(list) {
  const rows = (list || []).map((m) => `<span class="d-mat">${
    m.image_filename ? `<img src="${asset(m.image_filename)}" alt="" onerror="this.style.visibility='hidden'">` : ""
    }${esc(m.name)} <b>×${num(m.qty)}</b></span>`).join("");
  return rows ? `<div class="d-mats">${rows}</div>` : "—";
}

function dbSection(db) {
  if (!db) return "";
  const station = (db.craft_bench || []).join(" + ") +
    (db.station_level ? ` · lvl ${num(db.station_level)}` : "");
  return `<h4>ARCTRACKER</h4>
    <table class="d-table">
      <tr><td>WEIGHT</td><td>${db.weight_kg == null ? "—" : `${num(db.weight_kg)} kg`}</td></tr>
      <tr><td>STACK</td><td>${db.stack_size == null ? "—" : num(db.stack_size)}</td></tr>
      <tr><td>RECYCLE</td><td>${dbMats(db.recycles_into)}</td></tr>
      <tr><td>SALVAGE</td><td>${dbMats(db.salvages_into)}</td></tr>
      <tr><td>CRAFT</td><td>${dbMats(db.recipe)}${station ? `<div class="d-label">${esc(station.toUpperCase())}</div>` : ""}</td></tr>
      <tr><td>UPGRADE</td><td>${dbMats(db.upgrade_next)}${
        db.upgrades_to ? `<div class="d-label">TO ${esc(db.upgrade_next_name || db.upgrades_to)}</div>` : ""}</td></tr>
      <tr><td>FOUND IN</td><td>${(db.found_in || []).length ? esc((db.found_in || []).join(", ")) : "—"}</td></tr>
    </table>
    ${db.description ? `<p class="note">${esc(db.description)}</p>` : ""}`;
}

async function inspect(instanceId) {
  const row = findRow(instanceId);
  const fallback = (state.accounts.find((a) => a.name === state.account)
    || state.accounts.find((a) => a.is_active) || state.accounts[0] || {}).name || "";
  const account = row?.account || fallback;
  let d;
  try { d = await json(`/api/item?account=${encodeURIComponent(account)}&instance_id=${encodeURIComponent(instanceId)}`); }
  catch (err) { toast(err.message, "bad"); return; }
  const drawer = $("#drawer");
  drawer.hidden = false;
  $("#d-name").textContent = d.display_name || d.name;
  const cond = d.condition;
  $("#d-body").innerHTML = `
    <div class="d-hero r-${esc(d.rarity)}">${d.image ? `<img src="${asset(d.image)}" alt="">` : ""}</div>
    <div class="d-label">${esc((d.rarity + " " + (d.type_label || d.type)).trim().toUpperCase())}</div>
    <table class="d-table">
      <tr><td>QTY</td><td><b>${num(d.qty)}</b>${d.stack_size ? ` / stack ${num(d.stack_size)}` : ""}</td></tr>
      <tr><td>UNIT VALUE</td><td><b>${num(d.value)}</b></td></tr>
      <tr><td>TOTAL</td><td><b>${num(d.total_value)}</b></td></tr>
      <tr><td>CONDITION</td><td>${cond === null ? "—" : `<span class="condbar"><i style="width:${cond}%"></i></span> ${cond}%`}
        ${d.damaged ? '<span class="tag bad">DAMAGED</span>' : ""}</td></tr>
      <tr><td>LEVEL</td><td>${d.level ? (ROMAN[d.level] || d.level) : "—"}</td></tr>
      <tr><td>WHERE</td><td>${esc((d.container || "").toUpperCase())} · slot ${esc(d.slot_index)}</td></tr>
      <tr><td>BLUEPRINT</td><td>${d.is_blueprint ? "yes" : "no"}</td></tr>
      <tr><td>ACCOUNT</td><td>${esc(d.account)}</td></tr>
      <tr><td>INSTANCE</td><td class="mono">${esc(d.instance_id)}</td></tr>
      <tr><td>WRAPPER</td><td class="mono">${esc(d.wrapper_id)}</td></tr>
      <tr><td>ETAG</td><td class="mono">${esc(d.etag)}</td></tr>
    </table>
    ${Object.keys(d.mapping || {}).length ? `<h4>MAPPING</h4><pre class="code">${esc(JSON.stringify(d.mapping, null, 2))}</pre>` : ""}
    ${dbSection(d.db)}
    <p class="note">The basic part comes from the gateway, the LOCAL INDEX section from the offline item database — nothing runs until you press a button.</p>`;
  $("#d-foot").innerHTML = `
    <button class="ghost" data-to="stash">→ STASH</button>
    <button class="ghost" data-to="backpack">→ BACKPACK</button>
    <button class="ghost" data-to="overflow">→ OVERFLOW</button>`;
  $("#d-foot").querySelectorAll("[data-to]").forEach((b) => b.onclick = () =>
    runAction({ kind: "move", target_container: b.dataset.to, instance_ids: [d.instance_id],
                label: `${d.name} → ${b.dataset.to.toUpperCase()}` }));
}
$("#d-close").onclick = () => { $("#drawer").hidden = true; };

/* ------------------------------------------------------------------ modal + arm */
let modalConfirm = null;
let modalGen = 0;
function openModal(title, bodyHTML, onConfirm, confirmLabel, opts = {}) {
  modalGen += 1;
  $("#m-title").textContent = title;
  $("#m-body").innerHTML = bodyHTML;
  const card = $("#modal .modal-card");
  if (card) {
    card.className = "modal-card" + (opts.wide ? " modal-wide" : "") + (opts.cls ? " " + opts.cls : "");
    card.scrollTop = 0;
  }
  const cancel = $("#m-cancel");
  if (cancel) cancel.textContent = opts.cancelLabel || "CLOSE";
  const btn = $("#m-confirm");
  btn.className = "pill " + (opts.confirmKind || "primary");
  btn.disabled = false;
  const foot = $("#modal .modal-foot");
  if (foot) foot.hidden = !!opts.hideFoot;
  modalConfirm = onConfirm || null;
  if (onConfirm) { btn.hidden = false; btn.textContent = confirmLabel || "CONFIRM"; }
  else btn.hidden = true;
  $("#modal").hidden = false;
  if (opts.onMount) opts.onMount($("#m-body"));
  return $("#m-body");
}
$("#m-cancel").onclick = () => { $("#modal").hidden = true; };
const modalX = $("#m-x");
if (modalX) modalX.onclick = () => { $("#modal").hidden = true; };
$("#m-confirm").onclick = async () => {
  if (!modalConfirm) { $("#modal").hidden = true; return; }
  const gen = modalGen;
  const btn = $("#m-confirm");
  const label = btn.textContent;
  btn.disabled = true;
  btn.textContent = "WORKING…";
  try { await modalConfirm(); } catch (err) { toast(err.message, "bad"); }
  if (gen === modalGen) {
    $("#modal").hidden = true;
    btn.disabled = false;
    btn.textContent = label;
  }
};

/* ------------------------------------------------------------------ item card */
const COIN_SVG = `<svg class="ic-coin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v10"/><path d="M14.5 9.2c-.6-.7-1.5-1.2-2.5-1.2-1.4 0-2.5.9-2.5 2s1.1 2 2.5 2 2.5.9 2.5 2-1.1 2-2.5 2c-1 0-1.9-.5-2.5-1.2"/></svg>`;
const WARN_SVG = `<svg class="ic-warn" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>`;

/* كل الصفوف اللي واقفة ورا البلاطة — بلاطة STACKED ممكن تكون 31 سلاح،
   وكارت التفاصيل لازم يحاسب القطع كلها مش أول واحدة بس. */
function tileRows(tile) {
  return String(tile.dataset.ids || "").split(",").filter(Boolean)
    .map((id) => displayRow(id)).filter(Boolean);
}

function tileRow(tile) {
  const rows = tileRows(tile);
  if (!rows.length) return null;
  let chosen = rows[0];
  let chosenInfo = durabilityVisible(chosen) ? durabilityInfo(chosen) : null;
  for (const row of rows.slice(1)) {
    if (!durabilityVisible(row)) continue;
    const info = durabilityInfo(row);
    if (!chosenInfo || info.current / info.max < chosenInfo.current / chosenInfo.max) {
      chosen = row;
      chosenInfo = info;
    }
  }
  return chosen;
}

function ownedQty(name) {
  const needle = String(name || "").trim().toLowerCase();
  if (!needle) return 0;
  let total = 0;
  for (const part of Object.values(state.sections || {})) {
    for (const row of part.slots || []) {
      if (String(row.display_name || row.name || "").trim().toLowerCase() === needle) total += Number(row.qty) || 0;
    }
  }
  return total;
}

const cardRecycleCache = new Map();
let cardRecycleRequest = 0;

/* مرفق مالهوش أيقونة: بنعرض اسمه المختصر جوه الخانة نفسها بدل ما تفضل فاضية.
   من غير أيقونة الخانة 70px فيبقى كلمتين بيفرقوا مش نص طويل. */
function shortAttachmentName(name) {
  const parts = String(name || "").trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  if (parts.length === 1) return parts[0].slice(0, 7);
  return parts.slice(0, 2).map((w) => w.slice(0, 7)).join(" ");
}

function slotWord(slotName) {
  const text = String(slotName || "").replace(/_/g, " ").trim();
  return text ? text.replace(/\b\w/g, (c) => c.toUpperCase()) + " Slot" : "Empty Slot";
}

function showCard(tile, e) {
  const row = tileRow(tile);
  const rows = tileRows(tile);
  const card = $("#item-card");
  if (!row || !card) return;
  const amount = Number(tile.dataset.qty) || Number(row.qty) || 1;
  /* الخانات المعروضة في الكارت لازم تبقى اللي كل القطع في البلاطة شايفاه.
     لو لقينا اختلاف (حالة قديمة من قبل التجميع بالملحقات) ما نكدبش بالخانات
     الفاضية — بنقول إن فيه أكتر من تركيبة. */
  const owned = sharedAttachments(rows.length ? rows : [row]);
  const atts = owned.length ? owned : modsOf(attachmentsOf(row));
  const mixedBuilds = !owned.length && modsOf(attachmentsOf(row)).length > 0 && rows.length > 1;
  const stencils = sharedStencils(rows.length ? rows : [row]);
  const rarity = RARITY_ORDER.find((r) => r.toLowerCase() === String(row.rarity || "").toLowerCase()) || "Common";
  const color = rarityColor(rarity);
  const kind = itemKind(row);
  const special = kind === "design" || kind === "stencil";
  const typeLabel = String(row.type_label || row.arctracker_type || row.type || "Item").toUpperCase();
  const dura = durabilityVisible(row) ? durabilityInfo(row) : null;
  const lvl = tierLabel(row);
  const baseName = row.display_name || row.name;
  const hasLvl = lvl && baseName.trim().toUpperCase().endsWith(" " + lvl.toUpperCase());
  const name = baseName + (lvl && !hasLvl ? " " + lvl : "");
  const filled = atts.filter((a) => !a.is_empty).length;
  const totalCount = row.total_count;
  const compat = Array.isArray(row.compatible_with) ? row.compatible_with.filter(Boolean) : [];
  const materials = Array.isArray(row.required_materials) ? row.required_materials : [];
  const badges = special ? `<div class="ic-badges">
      <span class="ic-badge" style="background:${color};color:${badgeInk(rarity)}">${kind.toUpperCase()}</span>
      <span class="ic-badge" style="background:${color};color:${badgeInk(rarity)}">${esc(rarity.toUpperCase())}</span>
    </div>` : `<p class="ic-sub"><span style="color:${color}">${esc(rarity.toUpperCase())}</span><span class="ic-type">${esc(typeLabel)}</span></p>`;

  card.innerHTML = `
    <div class="ic-top">
      <div class="ic-id">
        <h3 class="ic-name">${esc(name)}</h3>
        ${badges}
      </div>
      <div class="ic-side">
        ${totalCount !== null && totalCount !== undefined ? `<div class="ic-total"><span>TOTAL</span><b>${esc(String(totalCount))}</b></div>` : ""}
        <div class="ic-value">${COIN_SVG}<b>${numSpaced(itemTotalValue(row, amount))}</b></div>
      </div>
    </div>
    ${compat.length ? `<div class="ic-compat"><span class="ic-label">COMPATIBLE WITH</span>
      <span class="ic-compat-list">${esc(compat.join(", "))}</span></div>` : ""}
    ${dura ? `<div class="ic-sec"><div class="ic-row"><span class="ic-label">DURABILITY</span>
      <span class="ic-dura ${dura.warn ? "is-" + dura.warn : ""}">${dura.warn ? WARN_SVG : ""}${dura.current}/${dura.max}</span></div>
      <div class="ic-durability-track ${dura.warn ? "is-" + dura.warn : ""}"><i style="width:${Math.max(0, Math.min(100, dura.max > 0 ? dura.current / dura.max * 100 : 0))}%"></i></div></div>` : ""}
    ${materials.length ? `<div class="ic-sec"><div class="ic-row"><span class="ic-label">REQUIRED RESOURCES</span></div>
      <div class="ic-mats">${materials.map((m) => {
        const need = Number(m.qty) || 0;
        const owned = ownedQty(m.name);
        return `<div class="ic-mat">
          <div class="ic-mat-ico">${m.image ? `<img src="${asset(m.image)}" alt="" onerror="this.style.visibility='hidden'">` : ""}</div>
          <span class="ic-mat-name">${esc(m.name || "")}</span>
          <b class="ic-mat-qty ${owned >= need ? "ok" : "bad"}">${owned}/${need}</b>
        </div>`;
      }).join("")}</div></div>` : ""}
    <div class="ic-recycle" hidden></div>
    ${atts.length ? `<div class="ic-sec"><div class="ic-row"><span class="ic-label">ATTACHMENTS</span><span class="ic-count">${mixedBuilds ? "MIXED BUILDS" : `${filled}/${atts.length}`}</span></div>
      <div class="ic-atts">${atts.map((a) => a.is_empty
        ? `<div class="ic-att empty" title="${esc(a.display_name || a.slot_label || slotWord(a.slot_name))}"></div>`
        : `<div class="ic-att ${rarCls(a.rarity)}" title="${esc(a.display_name || a.name || "Attachment")}">
            ${a.image_filename ? `<img src="${asset(a.image_filename)}" alt="" onerror="this.style.visibility='hidden';this.nextElementSibling.hidden=false">` : ""}
            <span class="ic-att-word"${a.image_filename ? " hidden" : ""}>${esc(shortAttachmentName(a.display_name || a.name))}</span>
          </div>`).join("")}</div></div>` : ""}
    ${stencils.length ? `<div class="ic-sec"><div class="ic-row"><span class="ic-label">STENCIL</span><span class="ic-count">FINISH · NOT DETACHABLE</span></div>
      <div class="ic-stencils">${stencils.map((a) => `<div class="ic-stencil ${rarCls(a.rarity)}" title="${esc(a.display_name || a.name || "Stencil")} — cosmetic finish, it stays on the weapon">
        ${a.image_filename ? `<img src="${asset(a.image_filename)}" alt="">` : ""}
        <span class="ic-stencil-name">${esc(a.display_name || a.name || "Stencil")}</span>
      </div>`).join("")}</div></div>` : ""}`;
  card.style.setProperty("--card-accent", color);
  card.classList.toggle("is-special", special);
  card.hidden = false;
  positionCard(e);
  const request = ++cardRecycleRequest;
  const account = row.account || state.account;
  const cacheKey = JSON.stringify([account, row.asset_id, row.name]);
  if (!cardRecycleCache.has(cacheKey)) {
    cardRecycleCache.set(cacheKey, json(`/api/item?account=${encodeURIComponent(account)}&instance_id=${encodeURIComponent(row.instance_id)}`)
      .then((item) => item.db?.recycles_into || [])
      .catch(() => { cardRecycleCache.delete(cacheKey); return []; }));
  }
  cardRecycleCache.get(cacheKey).then((yields) => {
    if (request !== cardRecycleRequest || card.hidden || !yields.length) return;
    const section = card.querySelector(".ic-recycle");
    section.innerHTML = `<div class="ic-label">RECYCLE RETURNS · EACH</div><div class="ic-recycle-items">${yields.map((m) => `<div class="ic-recycle-item" title="${esc(m.name)}">${m.image_filename ? `<img src="${asset(m.image_filename)}" alt="${esc(m.name)}">` : `<span>${esc(m.name)}</span>`}<b>×${num(m.qty)}</b></div>`).join("")}</div>`;
    section.hidden = false;
    positionCard(e);
  });
}

function positionCard(e) {
  const card = $("#item-card");
  if (!card || card.hidden) return;
  const pad = 14, gap = 16;
  const w = card.offsetWidth, h = card.offsetHeight;
  let x = e.clientX + gap;
  let y = e.clientY + gap;
  if (x + w > window.innerWidth - pad) x = e.clientX - w - gap;
  if (y + h > window.innerHeight - pad) y = e.clientY - h - gap;
  card.style.transform = "translate(" + Math.max(pad, x) + "px," + Math.max(pad, y) + "px)";
}

function hideCard() {
  const card = $("#item-card");
  if (card) card.hidden = true;
}

/* ------------------------------------------------------------------ traders + boot */
const TRADER_STATE = { data: null, offer: null, trader: null, qty: 1, max: 1, balance: 0 };

const traderRarity = (rarity) => (RARITY_ORDER.includes(rarity) ? rarity : "Common");

/* مساحة الستاش = capacity ناقص الخانات المشغولة. الحساب من الرد الحي مباشرة:
   eslots بتيجي فاضية لأي قسم مش محمّل، وdecorate بتخصم البلاطات المخفية. */
function stashRoom() {
  const stash = state.sections && state.sections.stash;
  if (!stash || !stash.capacity) return null;
  const free = (stash.empty_wrappers || []).length;
  return { free, total: Number(stash.capacity) };
}

function priceHTML(amount, currency) {
  return `<b>${num(amount)}</b>${currency?.image ? `<img src="${asset(currency.image)}" alt="">` : ""}<span>${esc(currency?.name || "")}</span>`;
}

function traderOfferHTML(trader, o) {
  const limited = Number(o.limit) > 0 && o.remaining !== null && o.remaining !== undefined;
  const left = limited ? Number(o.remaining) : null;
  const sold = limited && left <= 0;
  const planned = (TRADER_STATE.data?.plan?.items || [])
    .find((it) => String(it.offer_id) === String(o.offer_id));
  return `
    <button class="tr-offer r-${esc(traderRarity(o.reward?.rarity))} ${planned ? "in-plan" : ""}" type="button"
            data-offer="${esc(o.offer_id)}" ${sold ? "disabled" : ""}
            title="${esc(o.reward?.name || "")} — ${esc(o.reward?.amount || 0)} × ${esc(o.cost?.name || "")} ${esc(o.cost?.amount || 0)}">
      <span class="tr-ico">${o.reward?.image ? `<img src="${asset(o.reward.image)}" alt="" loading="lazy">` : ""}</span>
      <span class="tr-body">
        <span class="tr-top"><span class="tr-item-name">${esc(o.reward?.name || "")}</span>
          <span class="tr-qty">×${num(o.reward?.amount || 0)}</span>${planned ? `<span class="tr-planned" title="Saved in the buy list">+${num(planned.qty)}</span>` : ""}</span>
        <span class="tr-bottom">
          ${limited ? `<span class="tr-stock ${sold ? "sold" : ""}">${num(left)} / ${num(o.limit)} left</span>` : ""}
          <span class="tr-price">${priceHTML(o.cost?.amount || 0, o.cost)}</span>
        </span>
      </span>
    </button>`;
}

function traderCardHTML(trader) {
  return `
    <article class="tr-card">
      <header class="tr-card-head">
        <div class="tr-avatar">${trader.image
          ? `<img src="${asset(trader.image)}" alt="" loading="lazy">`
          : `<span>${esc((trader.name || "?").slice(0, 1))}</span>`}</div>
        <div class="tr-id">
          <h3 class="tr-name">${esc(trader.name)} <span class="tr-trades">${num(trader.trades)}</span></h3>
          <span class="tr-sub">${num(trader.trades)} TRADES AVAILABLE</span>
        </div>
      </header>
      <div class="tr-offers" data-trader="${esc(trader.asset_id)}">
        ${trader.offers.map((o) => traderOfferHTML(trader, o)).join("")}
      </div>
    </article>`;
}

async function loadTraders() {
  const account = state.account && state.account !== "ALL" ? state.account : "";
  const data = await json("/api/traders" + (account ? `?account=${encodeURIComponent(account)}` : ""));
  TRADER_STATE.data = data;
  $("#tr-wallet").innerHTML = (data.currency_order || Object.keys(data.balances || {}))
    .map((id) => data.balances?.[id]).filter(Boolean).map((c) => `
    <span class="tr-bal" title="${esc(c.name)}">
      ${c.image ? `<img src="${asset(c.image)}" alt="">` : ""}<b>${num(c.amount)}</b><span>${esc(c.name)}</span>
    </span>`).join("");
  renderTraderPlan(data.plan);

  const scrolls = {};
  document.querySelectorAll("#traders .tr-offers").forEach((el) => { scrolls[el.dataset.trader] = el.scrollTop; });
  const host = $("#traders");
  if (!data.traders.length) {
    host.innerHTML = `<p class="note">No offers are available for the current account.</p>`;
    return;
  }
  host.innerHTML = data.traders.map(traderCardHTML).join("");
  host.querySelectorAll(".tr-offers").forEach((el) => {
    if (scrolls[el.dataset.trader]) el.scrollTop = scrolls[el.dataset.trader];
  });
  host.querySelectorAll("[data-offer]").forEach((btn) => {
    btn.onclick = () => openBuy(btn.dataset.offer);
  });
}

/* قائمة الشراء: العرض بيحسّب التكلفة بس — الشراء نفسه بيتنفذ جوه اللعبة،
   فالبنود دي بتتخزن على الحساب (meta في قاعدة فحمي) عشان تفضل لما يفتح اللعبة. */
function renderTraderPlan(plan) {
  const host = $("#tr-plan");
  if (!host) return;
  const items = (plan && plan.items) || [];
  if (!items.length) { host.hidden = true; host.innerHTML = ""; return; }
  const chips = items.map((it) => `
    <span class="tr-pitem ${it.shortfall ? "short" : ""}"
          title="${esc(it.trader)} · ${num(it.qty)} × ${num(it.cost?.amount || 0)} ${esc(it.cost?.name || "")}">
      ${it.reward?.image ? `<img src="${asset(it.reward.image)}" alt="">` : ""}
      <b>${esc(it.reward?.name || "")}</b>
      <span class="tr-pqty">×${num(it.qty)}</span>
      <span class="tr-pgain">+${num(it.reward_total)}</span>
      <span class="tr-pcost">${num(it.total)} ${esc(it.cost?.name || "")}${it.shortfall ? ` · short ${num(it.shortfall)}` : ""}</span>
      <button type="button" class="tr-pdel" data-del="${esc(it.offer_id)}" title="Remove this entry">✕</button>
    </span>`).join("");
  const totals = (plan.totals || []).map((t) => `
    <span class="tr-ptotal ${t.shortfall ? "short" : ""}">
      ${t.image ? `<img src="${asset(t.image)}" alt="">` : ""}<b>${num(t.amount)}</b><span>${esc(t.name)}</span>
      <em>leaves ${num(Math.max(0, (t.balance || 0) - t.amount))}</em>
    </span>`).join("");
  host.innerHTML = `
    <div class="tr-phead">
      <span class="tr-ptitle">BUY LIST — ${esc(TRADER_STATE.data?.account || "")}</span>
      <div class="tr-ptotals">${totals}</div>
      <div class="spacer"></div>
      <button type="button" class="ghost tiny" id="tr-pclear">CLEAR</button>
    </div>
    <div class="tr-pitems">${chips}</div>`;
  host.hidden = false;
  $("#tr-pclear").onclick = () => runPlanEdit({ action: "clear" }, "🧹 Buy list cleared.");
  host.querySelectorAll("[data-del]").forEach((b) => {
    b.onclick = () => runPlanEdit({ action: "remove", offer_id: b.dataset.del });
  });
}

async function editTraderPlan(body, note) {
  const payload = Object.assign({ account: TRADER_STATE.data?.account || "" }, body);
  let out;
  try {
    out = await post("/api/traders/plan", payload);
  } catch (err) {
    return { ok: false, detail: "Connection failed: " + err.message };
  }
  if (!out.ok) return out;
  if (note) toast(note, "ok");
  await loadTraders();
  return out;
}

async function buyTraderOffer(offerId, qty) {
  const payload = { account: TRADER_STATE.data?.account || "", offer_id: offerId, amount: qty, confirmed: true };
  try {
    return await post("/api/traders/buy", payload);
  } catch (err) {
    return { ok: false, detail: "Connection failed: " + err.message };
  }
}

function runPlanEdit(body, note) {
  editTraderPlan(body, note).then((out) => {
    if (!out.ok) toast("⛔ " + (out.detail || out.error || "Not recorded."), "bad");
  });
}

function findTraderOffer(offerId) {
  for (const trader of TRADER_STATE.data?.traders || []) {
    for (const offer of trader.offers) {
      if (String(offer.offer_id) === String(offerId)) return { trader, offer };
    }
  }
  return null;
}

function buyTotal() {
  const unit = Number(TRADER_STATE.offer?.cost?.amount || 0);
  return unit * Number(TRADER_STATE.qty || 0);
}

function updateBuyState() {
  const { offer, qty, max, balance } = TRADER_STATE;
  if (!offer) return;
  const total = buyTotal();
  const $qty = $("#buy-qty");
  if ($qty && document.activeElement !== $qty) $qty.value = qty;
  const totalEl = $("#buy-total");
  if (totalEl) totalEl.innerHTML = priceHTML(total, offer.cost);
  const afterEl = $("#buy-after");
  if (afterEl) afterEl.innerHTML = priceHTML(Math.max(0, balance - total), offer.cost);
  const btn = $("#buy-confirm");
  if (!btn) return;
  const tooMuch = total > balance;
  const overStock = qty > max;
  const soldOut = TRADER_STATE.soldOut;
  const live = Boolean(TRADER_STATE.data?.buyable);
  const paused = live && Boolean(TRADER_STATE.data?.write_paused);
  /* تنبيه بس مش منع: الستاش مليان = الحاجات بتنزل في الأوفر ستاش تلقائياً */
  const room = stashRoom();
  const warn = $("#buy-space");
  if (warn) {
    const short = room && room.free <= 0;
    warn.hidden = !short;
    if (short) warn.textContent = `⚠ Stash is full (${num(room.free)} / ${num(room.total)} free) — items will be delivered directly to the overflow stash.`;
  }
  btn.disabled = qty < 1 || tooMuch || overStock || soldOut || paused;
  const label = live ? "BUY" : "ADD TO LIST";
  btn.textContent = paused ? "WRITE PAUSED"
    : soldOut ? "DAILY LIMIT DONE"
      : tooMuch ? "INSUFFICIENT FUNDS" : overStock ? `MAX ${num(max)}` : label;
}

function stepBuyQty(delta) {
  const next = Math.max(1, Math.min(TRADER_STATE.max, TRADER_STATE.qty + delta));
  if (next === TRADER_STATE.qty) return;
  TRADER_STATE.qty = next;
  const input = $("#buy-qty");
  if (input) input.value = next;
  updateBuyState();
}

function holdRepeat(btn, delta, step = stepBuyQty) {
  if (!btn) return;
  let delay = null;
  let repeat = null;
  const stop = () => { clearTimeout(delay); clearInterval(repeat); delay = repeat = null; };
  const fire = () => {
    if (!document.body.contains(btn) || $("#modal").hidden) { stop(); return; }
    step(delta);
  };
  btn.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    fire();
    delay = setTimeout(() => { repeat = setInterval(fire, 70); }, 330);
  });
  ["pointerup", "pointerleave", "pointercancel"].forEach((ev) => btn.addEventListener(ev, stop));
  btn.addEventListener("click", (e) => {
    e.preventDefault();
    if (e.detail === 0) fire();
  });
}

function openBuy(offerId) {
  const hit = findTraderOffer(offerId);
  if (!hit) return;
  const { trader, offer } = hit;
  const currency = offer.cost || {};
  const plan = TRADER_STATE.data?.plan || { items: [], totals: [] };
  const wallet = Number((TRADER_STATE.data?.balances || {})[currency.asset_id]?.amount || 0);
  const spent = Number((plan.totals || []).find((t) => String(t.asset_id) === String(currency.asset_id))?.amount || 0);
  // الرصيد المتاح للحساب ده = الجيب ناقص اللي محجوز بالفعل في قائمة الشراء.
  const balance = Math.max(0, wallet - spent);
  const unit = Number(currency.amount || 0);
  const limited = Number(offer.limit) > 0 && offer.remaining !== null && offer.remaining !== undefined;
  const planned = Number((plan.items || []).find((it) => String(it.offer_id) === String(offer.offer_id))?.qty || 0);
  const stock = limited ? Math.max(0, Number(offer.remaining) - planned) : null;
  const affordable = unit > 0 ? Math.floor(balance / unit) : 999;
  const maxQty = Math.max(1, Math.min(stock ?? 99, affordable > 0 ? affordable : 1));
  TRADER_STATE.offer = offer;
  TRADER_STATE.trader = trader;
  TRADER_STATE.qty = 1;
  TRADER_STATE.max = maxQty;
  TRADER_STATE.balance = balance;
  TRADER_STATE.planned = planned;
  TRADER_STATE.soldOut = limited && stock <= 0;
  const rarity = traderRarity(offer.reward?.rarity);
  const rewardQty = Number(offer.reward?.amount || 0);

  openModal(`PURCHASE — ${trader.name}`, `
    <div class="buy-head">
      <div class="buy-hero r-${esc(rarity)}">${offer.reward?.image ? `<img src="${asset(offer.reward.image)}" alt="">` : ""}</div>
      <div class="buy-meta">
        <h4 class="buy-name">${esc(offer.reward?.name || "")}</h4>
        <div class="buy-trader">${esc(trader.name)} · ${esc(offer.reward?.type || "TRADE")} · ${esc(rarity)}</div>
        <div class="buy-unit">${priceHTML(unit, currency)}<span>/ unit</span></div>
      </div>
    </div>
    <div class="buy-label">QUANTITY</div>
    <div class="qty-picker">
      <button type="button" id="buy-minus" aria-label="Decrease quantity">−</button>
      <input id="buy-qty" type="number" min="1" step="1" inputmode="numeric" value="1" aria-label="Quantity">
      <button type="button" id="buy-plus" aria-label="Increase quantity">+</button>
      <button type="button" class="max" id="buy-max" title="Largest amount allowed by your balance and the daily limit">MAX</button>
    </div>
    <div class="buy-lines">
      <div class="buy-line"><span>Unit price</span><b>${num(unit)} ${esc(currency.name || "")} · ${num(rewardQty)} item${rewardQty === 1 ? "" : "s"}</b></div>
      <div class="buy-line"><span>Available</span><b>${num(balance)} ${esc(currency.name || "")}${spent ? ` (of ${num(wallet)})` : ""}</b></div>
      ${planned ? `<div class="buy-line"><span>Already in list</span><b class="stock-note">${num(planned)}</b></div>` : ""}
      ${limited ? `<div class="buy-line"><span>Daily limit</span><b class="stock-note">${num(Math.max(0, stock))} / ${num(offer.limit)}</b></div>` : ""}
      <div class="buy-line"><span>After this</span><b id="buy-after"></b></div>
      <div class="buy-line total"><span>TOTAL</span><b id="buy-total"></b></div>
    </div>
    <div class="buy-error" id="buy-error"></div>
    <div class="buy-error buy-warn" id="buy-space" hidden></div>
    <div class="buy-foot">
      <button class="ghost" type="button" id="buy-cancel">CLOSE</button>
      <button class="buy-confirm" type="button" id="buy-confirm">${TRADER_STATE.data?.buyable ? "BUY" : "ADD TO LIST"}</button>
    </div>
    <p class="buy-note" dir="ltr">${esc(TRADER_STATE.data?.buy_note || "")}</p>
  `, null, null, { hideFoot: true, cls: "buy-modal" });

  const input = $("#buy-qty");
  input.oninput = () => {
    if (input.value === "") { TRADER_STATE.qty = 1; updateBuyState(); return; }
    const value = parseInt(input.value, 10);
    if (!Number.isFinite(value)) return;
    TRADER_STATE.qty = value;
    updateBuyState();
  };
  input.onblur = () => {
    TRADER_STATE.qty = Math.max(1, Math.min(TRADER_STATE.max, parseInt(input.value, 10) || 1));
    input.value = TRADER_STATE.qty;
    updateBuyState();
  };
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); $("#buy-confirm")?.click(); }
  });
  holdRepeat($("#buy-minus"), -1);
  holdRepeat($("#buy-plus"), 1);
  $("#buy-max").onclick = () => {
    TRADER_STATE.qty = TRADER_STATE.max;
    input.value = TRADER_STATE.qty;
    updateBuyState();
  };
  $("#buy-cancel").onclick = () => { $("#modal").hidden = true; };
  $("#buy-confirm").onclick = async () => {
    const btn = $("#buy-confirm");
    if (!btn || btn.disabled || !TRADER_STATE.offer) return;
    const qty = TRADER_STATE.qty;
    const total = buyTotal();
    const live = Boolean(TRADER_STATE.data?.buyable);
    btn.disabled = true;
    btn.textContent = live ? "BUYING…" : "SAVING…";
    $("#buy-error").textContent = "";
    const out = live
      ? await buyTraderOffer(TRADER_STATE.offer.offer_id, qty)
      : await editTraderPlan({ action: "add", offer_id: TRADER_STATE.offer.offer_id, amount: qty }, null);
    if (out.ok) {
      $("#modal").hidden = true;
      if (live) {
        const summary = out.summary || {};
        const fallback = `Bought ${num(qty)} × ${TRADER_STATE.offer.reward.name} ` +
                         `for ${num(total)} ${TRADER_STATE.offer.cost.name}.`;
        toast((out.verified ? "✔ " : "⚠ ") + (out.detail || fallback) +
              (out.verified && summary.reward_delta < qty * Number(TRADER_STATE.offer.reward?.amount || 1)
                ? ` (reached ${num(summary.reward_delta)} so far)` : ""),
              out.verified ? "ok" : "bad");
        await Promise.all([loadTraders(), loadSections(), loadHeader(), loadLog()].map((p) => p.catch(() => {})));
      } else {
        toast(`✔ In the buy list: ${num(qty)} × ${TRADER_STATE.offer.reward.name} for ${num(total)} ${TRADER_STATE.offer.cost.name}.`, "ok");
      }
      return;
    }
    $("#buy-error").textContent = "⛔ " + (out.detail || out.error || "The order was not recorded.");
    updateBuyState();
  };
  updateBuyState();
}

/* ------------------------------------------------------------------ workshop */
const WS_STATE = { data: null, recipe: null, qty: 1, max: 1,
                   q: "", bp: null, bpFilter: "all" };

const wsRarity = (rarity) => (RARITY_ORDER.includes(rarity) ? rarity : "Common");
const WS_ROMAN = ["", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"];
const wsLv = (n) => (WS_ROMAN[Number(n)] || String(n));

function wsLockHTML(r) {
  if (r.lock === "not_unlocked") {
    const why = r.blueprint === "in_stash" ? "The blueprint is still in the stash — activate it in-game (LEARN AND CONSUME)"
      : r.blueprint === "not_learned" ? "Your account tree has no <b>Unlock Craft</b> node for it — the recipe is not yours"
        : "The blueprint is not activated on the account";
    return `<div class="ws-locknote bp">🔒 ${why}
      <button type="button" class="ws-fix" id="craft-fix-bp">Fix blueprint state</button></div>`;
  }
  if (r.lock === "level") {
    return `<div class="ws-locknote lv">🔒 Needs station level ${wsLv(r.level_required)}${r.level_current ? ` · yours is ${wsLv(r.level_current)}` : " · station level not set"}
      <button type="button" class="ws-fix" id="craft-fix-lv">Set station level</button></div>`;
  }
  return "";
}

/* صف الوصفة في العمود: رسمة الأيقونة والاسم والكمية بس — باقي التفاصيل في النافذة،
   والخامات اللي ناقصة بتبان في التولتيب عشان الصفحة تفضل مريحة للعين. */
function wsRowHTML(r) {
  const mats = (r.materials || []).map((m) => `${m.name}: ${num(m.have)} / ${num(m.need)}`).join("\n");
  return `
    <button class="ws-row r-${esc(wsRarity(r.rarity))} ${r.planned ? "in-plan" : ""}" type="button"
            data-slug="${esc(r.slug)}"
            title="${esc(`${r.name} · ${r.station_label}${r.station_level ? " · LV " + wsLv(r.station_level) : ""} · ${r.rarity || ""}`)}\n${esc(mats)}">
      <span class="ws-ico">${r.image ? `<img src="${asset(r.image)}" alt="" loading="lazy">` : ""}</span>
      <span class="ws-row-name">${esc(r.name)}</span>
      <span class="ws-row-qty">×${num(r.quantity)}</span>
      ${r.planned ? `<span class="ws-planned" title="Saved in the craft list">+${num(r.planned)}</span>` : ""}
      ${r.can_craft ? `<span class="ws-dot" title="All of its materials are in your stash"></span>` : ""}
    </button>`;
}

function wsColumnHTML(station, rows, locked) {
  return `
    <article class="ws-col">
      <header class="ws-col-head">
        <div class="ws-avatar">${station.icon
          ? `<img src="${esc(station.icon)}" alt="" loading="lazy">`
          : `<span>${esc((station.label || "?").slice(0, 1))}</span>`}</div>
        <div class="ws-col-id">
          <h3 class="ws-col-name">${esc(station.label)}<span class="ws-col-lv ${station.level ? (station.level_source === "server" ? "srv" : "man") : "none"}"
                title="${station.level ? `Station level ${wsLv(station.level)} — ${station.level_source === "server" ? "read from your account tree on the game server" : "set manually"}`
                  : (station.level_read_at ? "This station has no body in your account tree = it was never built."
                                           : "This account tree has not been read since station levels were added — it reads automatically on the next sync.")}">${station.level ? `LV ${wsLv(station.level)}` : "LV —"}</span>
            <span class="ws-col-count">${num(rows.length)}</span></h3>
          <span class="ws-col-sub">${num(rows.length)} recipes${locked ? ` · ${num(locked)} locked by level` : ""}</span>
        </div>
      </header>
      <div class="ws-rows" data-station="${esc(station.key)}">${rows.map(wsRowHTML).join("")}</div>
    </article>`;
}

const wsRank = (r) => RARITY_ORDER.indexOf(wsRarity(r.rarity));
/* الندرة الأول: ذهبي → بنفسجي → أزرق → أخضر → رمادي، وبعدها الاسم أبجديًا */
const wsSort = (a, b) => (wsRank(b) - wsRank(a)) || String(a.name || "").localeCompare(String(b.name || ""));

function wsVisible(r) {
  if (r.lock) return false;
  const q = WS_STATE.q.trim().toLowerCase();
  if (!q) return true;
  return String(r.name || "").toLowerCase().includes(q)
    || (r.materials || []).some((m) => String(m.name || "").toLowerCase().includes(q));
}

function renderWorkshop() {
  const host = $("#ws-cols");
  const data = WS_STATE.data;
  if (!host || !data) return;
  const groups = {};
  const lockedBy = {};
  for (const r of data.recipes || []) {
    if (r.lock) lockedBy[r.station] = (lockedBy[r.station] || 0) + 1;
    if (!wsVisible(r)) continue;
    (groups[r.station] = groups[r.station] || []).push(r);
  }
  Object.values(groups).forEach((list) => list.sort(wsSort));
  const known = data.stations || [];
  // الترتيب ده ثابت ومطولب: WORKBENCH ← GEAR BENCH ← GUNSMITH ← MEDICAL ← UTILITY ← EXPLOSIVES ← REFINER ← FIELD BENCH
  // (صفحة التجار كانت ترتب بالحجم، هنا الترتيب معناه نفسه ترتيب شاشات المحطات جوه اللعبة)
  const order = known.map((s) => s.key);
  const cols = known.filter((s) => (groups[s.key] || []).length);
  const extra = Object.keys(groups)
    .filter((key) => !order.includes(key))
    .map((key) => ({ key, label: groups[key][0].station_label || key, icon: "", level: groups[key][0].station_level }));
  const shown = cols.concat(extra);
  const scrolls = {};
  host.querySelectorAll(".ws-rows").forEach((el) => { scrolls[el.dataset.station] = el.scrollTop; });
  const hidden = Number((data.totals || {}).hidden_not_unlocked || 0);
  const hiddenNote = hidden && !data.pick_account
    ? `<p class="ws-empty ws-hidden">🔒 ${num(hidden)} recipes are not in your account tree — they have no <b>Unlock Craft</b> node and are not in the default set, so they are hidden completely.</p>`
    : "";
  host.innerHTML = (shown.length
    ? shown.map((s) => wsColumnHTML(s, groups[s.key], lockedBy[s.key] || 0)).join("")
    : `<p class="ws-empty">No recipe matches that name or material.</p>`) + hiddenNote;
  host.querySelectorAll(".ws-rows").forEach((el) => {
    if (scrolls[el.dataset.station]) el.scrollTop = scrolls[el.dataset.station];
  });
  host.querySelectorAll("[data-slug]").forEach((btn) => { btn.onclick = () => openCraft(btn.dataset.slug); });
}

function renderWsPlan(plan) {
  const host = $("#ws-plan");
  if (!host) return;
  const items = (plan && plan.items) || [];
  if (!items.length) { host.hidden = true; host.innerHTML = ""; return; }
  const chips = items.map((it) => `
    <span class="ws-pitem ${it.short ? "short" : ""}" title="${(it.materials || []).map((m) => `${m.name} ${num(m.need)}`).join(" · ")}">
      ${it.image ? `<img src="${asset(it.image)}" alt="">` : ""}
      <b>${esc(it.name)}</b>
      <span class="ws-pqty">×${num(it.qty)}</span>
      <span class="ws-pgain">+${num(it.produces)}</span>
      <span class="ws-pmats">${(it.materials || []).length} materials</span>
      <button type="button" class="ws-pdel" data-del="${esc(it.slug)}" title="Remove this entry">✕</button>
    </span>`).join("");
  const totals = (plan.totals || []).map((t) => `
    <span class="ws-ptotal ${t.shortfall ? "short" : ""}" title="${esc(t.name)} — needs ${num(t.amount)} of ${num(t.balance)}">
      ${t.image ? `<img src="${asset(t.image)}" alt="">` : ""}<b>${num(t.amount)}</b><span>${esc(t.name)}</span>
      <em>${t.shortfall ? `missing ${num(t.shortfall)}` : `leaves ${num(Math.max(0, t.balance - t.amount))}`}</em>
    </span>`).join("");
  host.innerHTML = `
    <div class="ws-phead">
      <span class="ws-ptitle">CRAFT LIST — ${esc(WS_STATE.data?.account || "")}</span>
      <div class="ws-ptotals">${totals}</div>
      <div class="spacer"></div>
      <button type="button" class="ghost tiny" id="ws-pclear">CLEAR</button>
    </div>
    <div class="ws-pitems">${chips}</div>`;
  host.hidden = false;
  $("#ws-pclear").onclick = () => runWsPlanEdit({ action: "clear" }, "🧹 Craft list cleared.");
  host.querySelectorAll("[data-del]").forEach((b) => {
    b.onclick = () => runWsPlanEdit({ action: "remove", slug: b.dataset.del });
  });
}

async function loadWorkshop() {
  const account = state.account && state.account !== "ALL" ? state.account : "";
  const data = await json("/api/workshop" + (account ? `?account=${encodeURIComponent(account)}` : ""));
  WS_STATE.data = data;
  renderWsPlan(data.plan);
  renderWorkshop();
}

async function editWsPlan(body, note) {
  const payload = Object.assign({ account: WS_STATE.data?.account || "" }, body);
  let out;
  try {
    out = await post("/api/workshop/plan", payload);
  } catch (err) {
    return { ok: false, detail: "Connection failed: " + err.message };
  }
  if (!out.ok) return out;
  if (note) toast(note, "ok");
  await loadWorkshop();
  return out;
}

function wsLiveCraft(recipe) {
  return Boolean(WS_STATE.data?.craftable) && Boolean(recipe?.offer_id);
}

async function craftWorkshopOffer(slug, qty) {
  const payload = { account: WS_STATE.data?.account || "", slug: slug, amount: qty, confirmed: true };
  try {
    return await post("/api/workshop/craft", payload);
  } catch (err) {
    return { ok: false, detail: "Connection failed: " + err.message };
  }
}

function runWsPlanEdit(body, note) {
  editWsPlan(body, note).then((out) => {
    if (!out.ok) toast("⛔ " + (out.detail || out.error || "Not recorded."), "bad");
  });
}

/* ------------------------------------------------- معرفة الحساب: مخطوطات + مستويات */
async function postKnowledge(body) {
  const payload = Object.assign({ account: WS_STATE.data?.account || "" }, body);
  try {
    return await post("/api/workshop/knowledge", payload);
  } catch (err) {
    return { ok: false, detail: "Connection failed: " + err.message };
  }
}

function wsLvBody() {
  const list = ((WS_STATE.data || {}).stations || []).map((s) => {
    const opts = s.max_level
      ? Array.from({ length: s.max_level + 1 }, (_, n) => `
          <button type="button" class="lv-btn ${Number(s.level) === n ? "on" : ""}" data-key="${esc(s.key)}" data-lv="${n}"
                  title="${n ? "Level " + wsLv(n) : "Clear the selection"}">${n ? wsLv(n) : "—"}</button>`).join("")
      : `<span class="lv-none">This station has no levels</span>`;
    const cost = s.next ? `<div class="lv-cost"><span class="lv-next">▲ ${wsLv(s.next.level)}</span>
        ${s.next.cost.map((c) => `<span class="lv-m ${c.short ? "short" : ""}" title="${esc(c.name)} — you have ${num(c.have)} of ${num(c.qty)}">
            ${c.image ? `<img src="${asset(c.image)}" alt="">` : ""}<b>${num(c.have)}/${num(c.qty)}</b><i>${esc(c.name)}</i></span>`).join("")}</div>`
      : "";
    return `<div class="lv-row">
      <div class="lv-id">${s.icon ? `<img src="${esc(s.icon)}" alt="">` : ""}
        <span class="lv-txt"><b>${esc(s.label)}</b><em>${num(s.allowed)}/${num(s.count)} allowed${s.unlocks_next ? ` · the next upgrade unlocks ${num(s.unlocks_next)}` : ""}</em></span>
        <span class="lv-src ${s.level ? (s.level_source === "server" ? "srv" : "man") : "none"}"
              title="${s.level ? (s.level_source === "server" ? "read from your account tree on the server" : "set manually")
                : (s.level_read_at ? "This station has no body in your account tree = it was never built."
                                   : "This account tree has not been read since station levels were added — it reads automatically on the next sync.")}">${
          s.level ? (s.level_source === "server" ? "from server" : "manual") : "not read"}</span>
      </div>
      <div class="lv-set">${opts}</div>${cost}
    </div>`;
  }).join("");
  return `<div class="lv-wrap">
    <p class="lv-note" dir="ltr">The level is read from your account tree on the game server: the station body itself is in the tree (named for example «Gunsmith III») inside a <b>Workshop Slot</b> container, and the Roman numeral in its name is exactly your station level — no guessing. If the station has no body in your tree (it was never built) or the account has not been read, these buttons set it by hand.</p>
    <div class="lv-list">${list || `<p class="ws-empty">No stations in this data copy.</p>`}</div>
  </div>`;
}

function wireWsLevels() {
  document.querySelectorAll("#m-body [data-lv]").forEach((btn) => {
    btn.onclick = async () => {
      const key = btn.dataset.key;
      const out = await postKnowledge({ station: key, level: Number(btn.dataset.lv) });
      if (!out.ok) { toast("⛔ " + (out.detail || out.error || "Not recorded."), "bad"); return; }
      const st = ((WS_STATE.data || {}).stations || []).find((s) => s.key === key) || {};
      await loadWorkshop();
      toast(`✔ ${st.label || key} is now level ${btn.dataset.lv === "0" ? "not set" : wsLv(btn.dataset.lv)}.`, "ok");
      if (!$("#modal").hidden) { $("#m-body").innerHTML = wsLvBody(); wireWsLevels(); }
    };
  });
}

function openWsLevels() {
  if (!WS_STATE.data) return;
  openModal("STATION LEVELS", wsLvBody(), null, null, { hideFoot: true, cls: "lv-modal" });
  wireWsLevels();
}

const BP_LABEL = { learned: "Active", in_stash: "In stash", not_learned: "Not active" };

function bpCell(c) {
  const st = c.state || "not_learned";
  return `<div class="bpm-cell s-${esc(st)}">
    <span class="bpm-ico r-${esc(wsRarity(c.rarity))}">${c.image ? `<img src="${asset(c.image)}" alt="">` : ""}</span>
    <span class="bpm-id"><b title="${esc(c.name)}">${esc(c.name)}</b>
      <em>${esc(c.station_label || "")}${c.station_level ? ` · ${wsLv(c.station_level)}` : ""}</em></span>
    <span class="bpm-badge">${esc(BP_LABEL[st])}${st === "in_stash" && c.copies > 1 ? ` ×${num(c.copies)}` : ""}</span>
    <span class="bpm-acts">
      <button type="button" class="bpm-y ${st === "learned" ? "on" : ""}" data-t="${esc(c.target || "")}" data-s="learned" title="Active on this account">✓</button>
      <button type="button" class="bpm-n ${st === "not_learned" ? "on" : ""}" data-t="${esc(c.target || "")}" data-s="not_learned" title="Not active — pin it that way">✗</button>
      <button type="button" class="bpm-a" data-t="${esc(c.target || "")}" data-s="auto" title="Back to the game guide: the Unlock Craft node in the account tree">↺</button>
    </span>
  </div>`;
}

function renderBpList() {
  const host = $("#bpm-list");
  const head = $("#bpm-head");
  const bp = WS_STATE.bp;
  if (!host || !bp) return;
  const t = bp.totals || {};
  if (head) {
    const chip = (key, label, n) => `<button type="button" class="ws-chip ${WS_STATE.bpFilter === key ? "active" : ""}" data-f="${key}">${esc(label)} <b>${num(n)}</b></button>`;
    head.innerHTML = `<div class="ws-stations">
        ${chip("all", "ALL", t.total)}${chip("learned", "Active", t.learned)}
        ${chip("in_stash", "In stash", t.in_stash)}${chip("not_learned", "Not active", t.not_learned)}
      </div>`;
    head.querySelectorAll("[data-f]").forEach((b) => {
      b.onclick = () => { WS_STATE.bpFilter = b.dataset.f; renderBpList(); };
    });
  }
  const rows = (bp.blueprints || []).filter((c) => WS_STATE.bpFilter === "all" || (c.state || "not_learned") === WS_STATE.bpFilter);
  host.innerHTML = rows.map(bpCell).join("") || `<p class="ws-empty">No blueprints in this section.</p>`;
  host.querySelectorAll("[data-t]").forEach((b) => {
    b.onclick = () => markBlueprint(b.dataset.t, b.dataset.s);
  });
}

async function reloadBlueprints() {
  const account = WS_STATE.data?.account || "";
  const data = await json("/api/workshop/blueprints" + (account ? `?account=${encodeURIComponent(account)}` : ""));
  WS_STATE.bp = data;
  renderBpList();
}

async function markBlueprint(target, state) {
  if (!target) { toast("⛔ This blueprint has no linked item in the database.", "bad"); return; }
  const out = await postKnowledge({ target, state });
  if (!out.ok) { toast("⛔ " + (out.detail || out.error || "Not recorded."), "bad"); return; }
  await loadWorkshop();
  if (!$("#modal").hidden) await reloadBlueprints();
  toast(state === "learned" ? "✔ Recorded as active — the recipe is open."
    : state === "not_learned" ? "✔ Recorded as not active — the recipe is hidden." : "↺ Back to the game guide: the Unlock Craft node.", "ok");
}

async function openWsBlueprints() {
  const account = WS_STATE.data?.account || (state.account !== "ALL" ? state.account : "");
  if (!account) { toast("⛔ Pick one account first.", "bad"); return; }
  try {
    WS_STATE.bp = await json("/api/workshop/blueprints?account=" + encodeURIComponent(account));
  } catch (err) {
    toast("⛔ " + err.message, "bad");
    return;
  }
  WS_STATE.bpFilter = "all";
  const t = WS_STATE.bp.totals || {};
  openModal(`BLUEPRINTS — ${t.learned || 0}/${t.total || 0} active`, `
    <div class="bpm-bar" id="bpm-head"></div>
    <p class="lv-note" dir="ltr">Source: your account tree on the game server — every blueprint you activate leaves one <b>Unlock Craft</b> node there named after the item. Anything without a node in your tree = <b>not active</b> and its recipe disappears from the factory completely; there is no "maybe active" state. The only exception: <b>${num(t.default_recipes || 0)}</b> base recipes that ship unlocked with any new account (they have no blueprint in the game at all). The ✓/✗ buttons set it manually — ✓ brings the recipe back even if the index has no activation record for this item.</p>
    <div class="bpm-grid" id="bpm-list"></div>
  `, null, null, { hideFoot: true, cls: "bpm-modal" });
  renderBpList();
}

function findWsRecipe(slug) {
  return ((WS_STATE.data || {}).recipes || []).find((r) => String(r.slug) === String(slug)) || null;
}

function wsCraftCosts(qty) {
  // الخامات بتجي من الباكند باسم image_filename، والرسمة لازم تطلع جنب كل خامة
  return (WS_STATE.recipe?.materials || []).map((m) => ({
    ...m, total: m.need * qty, image: m.image || m.image_filename,
  }));
}

function updateCraftState() {
  const recipe = WS_STATE.recipe;
  if (!recipe) return;
  const qty = WS_STATE.qty;
  const $qty = $("#craft-qty");
  if ($qty && document.activeElement !== $qty) $qty.value = qty;
  const host = $("#craft-lines");
  if (host) {
    host.innerHTML = `<p class="ws-mats-title">Needed for this craft</p>`
      + wsCraftCosts(qty).map((m) => `
      <span class="ws-mat ${m.total > m.have ? "short" : ""}"
            title="${esc(m.name)} — ${num(m.have)} available of ${num(m.owned)} in the stash, needed ${num(m.total)}">
        ${m.image ? `<img src="${asset(m.image)}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">` : ""}
        <span>${esc(m.name)}</span><b>${num(m.have)}</b><i>/ ${num(m.total)}</i>
      </span>`).join("")
      + `<div class="ws-line total"><span>OUTPUT</span><b>${num(qty * Number(recipe.quantity || 1))} × ${esc(recipe.name)}</b></div>`;
  }
  const btn = $("#craft-confirm");
  if (!btn) return;
  const over = qty > WS_STATE.max;
  const live = wsLiveCraft(recipe);
  const paused = live && Boolean(WS_STATE.data?.write_paused);
  const short = live && qty * Number(recipe.quantity || 1) > 0 && !recipe.can_craft;
  btn.disabled = qty < 1 || over || paused || short;
  btn.textContent = paused ? "WRITE PAUSED" : short ? "NEED MATERIALS"
    : over ? `MAX ${num(WS_STATE.max)}` : live ? "CRAFT" : "ADD TO LIST";
}

function stepCraftQty(delta) {
  const next = Math.max(1, Math.min(WS_STATE.max, WS_STATE.qty + delta));
  if (next === WS_STATE.qty) return;
  WS_STATE.qty = next;
  const input = $("#craft-qty");
  if (input) input.value = next;
  updateCraftState();
}

function openCraft(slug) {
  const recipe = findWsRecipe(slug);
  if (!recipe) return;
  WS_STATE.recipe = recipe;
  WS_STATE.max = Math.max(1, Math.min(99, Number(recipe.max_now || 1)));
  WS_STATE.qty = Math.min(WS_STATE.max, Math.max(1, recipe.planned || 1));
  openModal(`CRAFT — ${recipe.name}`, `
    <div class="buy-head">
      <div class="buy-hero r-${esc(wsRarity(recipe.rarity))}">${recipe.image ? `<img src="${asset(recipe.image)}" alt="">` : ""}</div>
      <div class="buy-meta">
        <h4 class="buy-name">${esc(recipe.name)}</h4>
        <div class="buy-trader">${esc(recipe.station_label)}${recipe.station_level ? ` · LEVEL ${wsLv(recipe.station_level)}` : ""} · ${esc(recipe.rarity || "")}</div>
        <div class="buy-unit">${recipe.image ? `<img src="${asset(recipe.image)}" alt="">` : ""}<b>×${num(recipe.quantity)}</b><span>per craft</span></div>
      </div>
    </div>
    <div class="buy-label">QUANTITY</div>
    <div class="qty-picker">
      <button type="button" id="craft-minus" aria-label="Decrease quantity">−</button>
      <input id="craft-qty" type="number" min="1" step="1" inputmode="numeric" value="${WS_STATE.qty}" aria-label="Quantity">
      <button type="button" id="craft-plus" aria-label="Increase quantity">+</button>
      <button type="button" class="max" id="craft-max" title="Largest amount whose materials are all in the stash">MAX</button>
    </div>
    <div class="ws-lines" id="craft-lines"></div>
    ${wsLockHTML(recipe)}
    ${recipe.skills?.length ? `<p class="buy-note" dir="ltr">Skill requirement from the game: <b>${esc(recipe.skills.join(", "))}</b></p>` : ""}
    <div class="buy-error" id="craft-error"></div>
    <div class="buy-foot">
      <button class="ghost" type="button" id="craft-cancel">CLOSE</button>
      <button class="buy-confirm" type="button" id="craft-confirm">ADD TO LIST</button>
    </div>
    <p class="buy-note" dir="ltr">${esc(WS_STATE.data?.craft_note || "")}</p>
  `, null, null, { hideFoot: true, cls: "buy-modal" });

  const input = $("#craft-qty");
  input.oninput = () => {
    if (input.value === "") { WS_STATE.qty = 1; updateCraftState(); return; }
    const value = parseInt(input.value, 10);
    if (!Number.isFinite(value)) return;
    WS_STATE.qty = value;
    updateCraftState();
  };
  input.onblur = () => {
    WS_STATE.qty = Math.max(1, Math.min(WS_STATE.max, parseInt(input.value, 10) || 1));
    input.value = WS_STATE.qty;
    updateCraftState();
  };
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); $("#craft-confirm")?.click(); }
  });
  holdRepeat($("#craft-minus"), -1);
  holdRepeat($("#craft-plus"), 1);
  $("#craft-max").onclick = () => {
    WS_STATE.qty = WS_STATE.max;
    input.value = WS_STATE.qty;
    updateCraftState();
  };
  $("#craft-cancel").onclick = () => { $("#modal").hidden = true; };
  $("#craft-confirm").onclick = async () => {
    const btn = $("#craft-confirm");
    if (!btn || btn.disabled || !WS_STATE.recipe) return;
    const recipe = WS_STATE.recipe;
    const qty = WS_STATE.qty;
    const live = wsLiveCraft(recipe);
    btn.disabled = true;
    btn.textContent = live ? "CRAFTING…" : "SAVING…";
    $("#craft-error").textContent = "";
    const out = live
      ? await craftWorkshopOffer(recipe.slug, qty)
      : await editWsPlan({ action: "add", slug: recipe.slug, amount: qty }, null);
    if (out.ok) {
      $("#modal").hidden = true;
      if (live) {
        toast((out.verified ? "✔ " : "⚠ ") + (out.detail || `Crafted ${num(qty)} × ${recipe.name}.`),
              out.verified ? "ok" : "bad");
        await Promise.all([loadWorkshop(), loadSections(), loadHeader(), loadLog()]
          .map((p) => p.catch(() => {})));
      } else {
        toast(`✔ In the craft list: ${num(qty)} × ${recipe.name}.`, "ok");
      }
      return;
    }
    $("#craft-error").textContent = "⛔ " + (out.detail || out.error || "The order was not recorded.");
    updateCraftState();
  };
  wireWsLockFixes();
  updateCraftState();
}

const wsSearch = $("#ws-search");
if (wsSearch) wsSearch.oninput = () => { WS_STATE.q = wsSearch.value; renderWorkshop(); };

/* شاشة المخطوطات وشاشة مستويات المحطات مابقوش أزرار في الهيدر — بيتفتحوا من
   جوه نافذة الوصفة نفسها لما الوصفة تكون مقفولة بس. */
function wireWsLockFixes() {
  const bp = $("#craft-fix-bp");
  if (bp) bp.onclick = () => openWsBlueprints().catch((e) => toast("⛔ " + e.message, "bad"));
  const lv = $("#craft-fix-lv");
  if (lv) lv.onclick = openWsLevels;
}

function showView(view) {
  state.view = view;
  state.menuOpen = false;
  document.querySelectorAll(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  ["inventory", "accounts", "traders", "workshop"].forEach((v) => { $("#view-" + v).hidden = v !== view; });
  if (view === "accounts") {
    renderAccountsPage();
    Promise.all([loadAccounts(), loadHeader()]).catch((e) => acctNote(e.message, "bad"));
  }
  if (view === "traders") loadTraders().catch((e) => toast("⛔ " + e.message, "bad"));
  if (view === "workshop") loadWorkshop().catch((e) => toast("⛔ " + e.message, "bad"));
}
window.showView = showView;

$("#btn-scrappy").onclick = scrappyTopClick;
$("#acct-add").onclick = addAccount;
$("#acct-token").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); addAccount(); } });
$("#acct-sync-all").onclick = async (e) => {
  const btn = e.currentTarget;
  const label = btn.innerHTML;
  btn.disabled = true;
  btn.textContent = "SYNCING…";
  acctNote("Pulling every account from the Embark gateway (read only)…", "");
  try {
    const out = await post("/api/refresh", {});
    const results = out.results || [];
    const online = results.filter((r) => r.ok).length;
    acctNote(`✔ Sync ${online}/${results.length} accounts · ${out.mode} · ${out.duration_sec}s`, online === results.length ? "ok" : "bad");
    await Promise.all([loadAccounts(), loadHeader(), loadStatus(), loadSections(), loadLegend()]);
    toast(`✔ Synced ${online} accounts.`, "ok");
  } catch (err) { acctNote("⛔ " + err.message, "bad"); }
  btn.disabled = false;
  btn.innerHTML = label;
};

const syncBtn = $("#btn-sync");
if (syncBtn) syncBtn.onclick = async (e) => {
  const btn = e.currentTarget;
  btn.disabled = true;
  btn.textContent = "SYNCING…";
  try { await post("/api/refresh", {}); } catch (err) { console.warn(err); }
  await refreshAll();
  btn.disabled = false;
  btn.textContent = "↻ SYNC";
};

const liveSyncBtn = $("#btn-live-sync");
if (liveSyncBtn) liveSyncBtn.onclick = async () => {
  if (state.account === "ALL") { toast("Pick one account first to sync.", "bad"); return; }
  const btn = liveSyncBtn;
  btn.disabled = true;
  btn.classList.add("spinning");
  try {
    const out = await post("/api/actions/sync", { account: state.account });
    if (!out.executed) throw new Error(out.result?.detail || out.result?.error || "SYNC failed");
    await Promise.all([loadSections(), loadLegend(), loadHeader(), loadStatus(), loadLog()]);
    loadScrappy().catch(() => {});
    toast("✔ " + (out.note || "Synced — inventory and loadout updated."), "ok");
  } catch (err) {
    toast("⛔ " + err.message, "bad");
  }
  btn.disabled = false;
  btn.classList.remove("spinning");
};
document.querySelectorAll(".nav-item").forEach((b) => b.onclick = () => showView(b.dataset.view));

function showPanels(show) {
  const drawer = $("#sys-drawer");
  const backdrop = $("#sys-backdrop");
  if (!drawer) return;
  drawer.hidden = !show;
  if (backdrop) backdrop.hidden = !show;
  if (show) {
    loadStatus().catch(() => {});
    loadLegend().catch(() => {});
    loadLog().catch(() => {});
  }
}
const sysClose = $("#sys-close");
if (sysClose) sysClose.onclick = () => showPanels(false);
const sysBackdrop = $("#sys-backdrop");
if (sysBackdrop) sysBackdrop.onclick = () => showPanels(false);

const unlockBtn = $("#btn-unlock");
if (unlockBtn) unlockBtn.onclick = () => setFrozen(false);

/* دفعتين Esc من خانة البحث = مسح البحث والكمية معًا (زي الأكس بالظبط، من غير ما يدي عليه).
   الأولى تسلّح والتانية تنفّذ؛ لوحها في الخانة فقط عشان Esc بره يفضل سلوكه القديم. */
let escTapAt = 0;
const ESC_DOUBLE_MS = 1500;

function clearSearchAndQty() {
  state.queries.inventory = "";
  state.queries.qty = "";
  // الرجوع لخانة البحث بعد الرسم: يلاقي الكيرسور جاهز على الكلمة الجاية.
  state.searchFocus = "inv-search";
  state.searchSel = null;
  renderInventory();
}

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    // أول هرب من قفل ↑ UPDATE — الـ CANCEL بتاع الهيدر نفسه
    if (state.frozen) { setFrozen(false); return; }
    const sortPop = $("#sort-pop");
    const loPop = $("#lo-pop");
    const overlayOpen = !$("#ctx").hidden || !$("#modal").hidden || !$("#drawer").hidden
      || !$("#sys-drawer").hidden || !!(sortPop && !sortPop.hidden) || state.loPopOpen || state.menuOpen;
    if (overlayOpen) {
      hideCtx();
      $("#drawer").hidden = true;
      $("#modal").hidden = true;
      showPanels(false);
      if (sortPop) sortPop.hidden = true;
      const dd = $("#sort-dd");
      if (dd) dd.classList.remove("open");
      if (loPop) loPop.hidden = true;
      $("#lo-dd")?.classList.remove("open");
      state.loPopOpen = false;
      if (state.menuOpen) { state.menuOpen = false; renderHeader(); }
      return;
    }
    const id = (document.activeElement || {}).id || "";
    if (id === "inv-search" || id === "inv-qty") {
      const now = Date.now();
      if (now - escTapAt <= ESC_DOUBLE_MS) {
        escTapAt = 0;
        e.preventDefault();
        clearSearchAndQty();
      } else {
        escTapAt = now;
      }
      return;
    }
    escTapAt = 0;
    if (state.selected.size) { state.selected.clear(); renderColumns(); updateSelCount(); }
  }
});

async function refreshAll() {
  await Promise.all([loadStatus(), loadSections(), loadLegend(), loadLog(), loadHeader(), loadAccounts(), loadQueue()]);
}

async function boot() {
  wireQueue();
  await loadAccounts().catch((e) => console.warn("[accounts]", e));
  // لو التاب ده كان مقفول من ↑ UPDATE قبل ما يتعمله ريفرش — القفل بيضل صاحبه
  if (state.account !== "ALL" && frozenRead()) setFrozen(true, true);
  await Promise.all([loadSections(), loadHeader(), loadStatus()]);
  await Promise.all([loadLegend(), loadLog(), loadQueue()]);
}
boot().catch((e) => { $("#column-host").innerHTML = `<p class="note">${esc(e.message)}</p>`; });
setInterval(() => {
  if (state.moveBusy || state.moveQueue.length) return;
  refreshAll().catch(() => {});
}, 60000);

/* ---------------- عيون على الأجن ----------------
   الأجن (CMSync) بيبعت التوكن والباكند يسحب المخزن قراءةً — فاللوحة بتتحدّث
   فعلاً في القاعدة، بس التاب المفتوح كان لسه عارض القديم لحد ما حد يدوس SYNCHRONIZE
   أو ياستنى دورة الـ 60 ثانية. بنراقب مؤشر الإرسال بطلب خفيف ونسحب الأقسام أول ما
   يجي جديد — من غير أي كتابة على حساب اللعبة، قراءة بس. */
let syncMark = null;

function syncVersion(st) {
  const acc = Object.entries(st.accounts || {}).map(([a, v]) => `${a}:${v.items || 0}`);
  acc.sort();
  return `${(st.agent || {}).at || 0}|${acc.join(",")}`;
}

async function watchAgentSync() {
  if (document.hidden || state.frozen || state.moveBusy || state.moveQueue.length) return;
  if (state.menuOpen || state.drag || state.loPopOpen) return; // ما نقضّش وهو بيتعامل مع البلاطات
  if (!$("#modal") || !$("#modal").hidden) return; // مفيش نقض على نافذة مفتوحة
  const st = await json("/api/status");
  const mark = syncVersion(st);
  const previous = syncMark;
  syncMark = mark;
  state.status = st;
  // الطابور بيتفرّغ في الخلفية من غير ما حد يدوس حاجة — الشيب لازم يلحقه.
  const q = (st.queue || {}).count || 0;
  if (q !== state.queue.count) loadQueue().catch(() => {});
  if (previous === null || previous === mark) return;
  const a = st.agent || {};
  await Promise.all([loadSections(), loadHeader(), loadAccounts(), loadStatus()]);
  if (a.created || /refresh|registered/.test(String(a.note || ""))) {
    const rec = (state.accounts || []).find((x) => x.name === a.account) || {};
    toast(`✔ The agent pulled the state of ${rec.display_name || a.account || "the account"} — the board updated on its own.`, "ok");
  }
}
setInterval(() => { watchAgentSync().catch(() => {}); }, 6000);
