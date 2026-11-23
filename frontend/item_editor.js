/* محرّر بيانات العناصر — تعديل يدوي دائم (manual_override).

  أي مسار الفتح واحد: نافذة واحدة فيها الاسم والندرة والتصنيف والسعر والصورة.
  كل حقل قابل للكتابة قبل الحفظ، واختيار عنصر من البحث بيعبّي الحقول تلقائياً.
  الحفظ على /admin/api/item/override — والبيانات المعدّلة يدوياً بتحصل على
  الأولوية القصوى في العرض، وبيانات اللعبة/المزامنة مابتمسحش أي حقل اتعدّل. */
(function () {
  "use strict";

  const RARITIES = ["Common", "Uncommon", "Rare", "Epic", "Legendary"];
  let admin = null;
  const TYPE_HINTS = ["Trinket", "Weapon", "Shield", "Augment", "Material", "Blueprint", "Quick Use",
    "Key", "Ammunition", "Modification", "Outfit", "Resource", "Grenade"];

  function q(sel, root) { return (root || document).querySelector(sel); }
  function esc(v) {
    return String(v === null || v === undefined ? "" : v).replace(/[&<>"']/g,
      (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  function toast(msg, kind) {
    if (typeof window.toast === "function") window.toast(msg, kind);
  }
  async function req(url, opts) {
    const res = await fetch(url, opts);
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);
    return body;
  }
  const push = (url, method, body) => req(url, {
    method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}),
  });
  // اللوحة بتقرا بياناتها من مسارها المخزّن — علم التحديث هو اللي بيخليها تعيد القراءة
  const refresh = () => {
    try { window.dispatchEvent(new CustomEvent("items:edited")); } catch (e) { /* قديم */ }
  };

  const assetUrl = (f, v) => {
    if (!f) return "";
    let s = String(f).trim();
    if (/^https?:\/\/[^/]+/i.test(s)) s = s.replace(/^https?:\/\/[^/]+/i, "");
    let path = "";
    if (s.startsWith("/")) {
      path = s;
    } else if (s.startsWith("static/") || s.startsWith("item_icons/")) {
      path = s.startsWith("static/") ? `/${s}` : `/static/${s}`;
    } else if (s.startsWith("items/")) {
      path = `/assets/${s}`;
    } else if (s.startsWith("arctracker/") || s.startsWith("metaforge/")) {
      path = `/assets/items/${s}`;
    } else {
      path = `/assets/items/${s}`;
    }
    return v ? `${path}${path.includes("?") ? "&" : "?"}v=${encodeURIComponent(v)}` : path;
  };
  const imagePreview = (f) => {
    const text = String(f || "");
    if (!text) return "";
    if (text.startsWith("data:image/")) return text;
    return assetUrl(text);
  };
  const searchThumb = (f) => {
    if (!f) return "";
    const text = String(f);
    if (text.startsWith("data:image/")) return text;
    const base = text.startsWith("static/") ? text : "static/item_icons/" + text.split("/").pop();
    return assetUrl(base);
  };

  function fileToDataURL(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ""));
      reader.onerror = () => reject(new Error("the picture could not be read"));
      reader.readAsDataURL(file);
    });
  }

  // حاجات مفيش لها صف مخزّن (عنصر جديد بالـ ID) — بتتعرض فوراً من هنا لحد ما
  // المخزن نفسه يبقى فيه سطر بالـ ID ده.
  const localEdits = new Map();
  // كل التعديلات المحفوظة (بتتقرا من الأدمن) — لربط عنصر جديد بالصورة الأصلية بتاعته
  const itemOverrides = { map: {}, find(id) { return this.map[String(id || "").trim()] || null; } };

  async function lookup(assetId, name) {
    if (!assetId) return null;
    const params = new URLSearchParams({ asset_id: assetId });
    if (name) params.set("name", name);
    return req("/admin/api/item/raw?" + params.toString()).catch(() => null);
  }

  /* ------------------------------------------------------------------ editor */
  function openEditor(assetId, options) {
    if (!admin) {
      if (typeof toast === "function") toast("Admin access required.", "bad");
      return;
    }
    const opts = options || {};
    const aid = String(assetId || "").trim();
    let picked = null;
    let state = {
      id: aid, source: opts.source || "dialog", done: false,
      card_bg: "standard",
      icon: { mode: "keep", value: "" },          // keep | picked | upload | upload-pending
      baseline: null, override: null, dirty: false, typing: 0,
    };
    const preset = opts.preset || {};

    document.body.insertAdjacentHTML("beforeend", `
    <div class="modal item-editor" id="ie-modal" role="dialog" aria-modal="true">
      <div class="modal-card ie-card">
        <div class="ie-head">
          <h3>ITEM DATA <span class="ie-mode">· MANUAL OVERRIDE</span></h3>
          <div class="ie-tabs" role="tablist">
            <button type="button" class="ie-tab on" role="tab" data-tab="editor">EDITOR</button>
            <button type="button" class="ie-tab" role="tab" data-tab="saved">SAVED OVERRIDES <b id="ie-tab-count">0</b></button>
          </div>
          <button type="button" class="ie-x" id="ie-close" title="Close (Esc)">✕</button>
        </div>
        <div class="ie-pane ie-pane-editor" data-pane="editor">
        <div class="ie-idrow">
          <label class="ie-field ie-id">
            <span>ASSET ID / DEF ID</span>
            <input id="ie-id" type="text" inputmode="numeric" autocomplete="off" value="${esc(aid)}" placeholder="e.g. 972768070">
          </label>
          <div class="ie-idstatus" id="ie-idstatus"></div>
          <div class="ie-idacts">
            <button type="button" class="pill" id="ie-load">LOOKUP</button>
            <button type="button" class="pill danger" id="ie-del" hidden>DELETE OVERRIDE</button>
          </div>
        </div>
        <div class="ie-grid">
          <div class="ie-left">
            <div class="ie-card-preview" id="ie-preview"></div>
            <label class="ie-label">RARITY — the card border changes the moment you pick</label>
            <div class="ie-rarity" id="ie-rarity">
              ${RARITIES.map((r) => `<button type="button" class="ident-rar r-${r}" data-rar="${r}">${r}</button>`).join("")}
            </div>
            <label class="ie-label">CARD BACKGROUND — overrides the card background style</label>
            <div class="ie-card-bg" id="ie-card-bg">
              <button type="button" class="ie-bg-pill on" data-bg="standard">Standard</button>
              <button type="button" class="ie-bg-pill" data-bg="blueprint">Blueprint</button>
              <button type="button" class="ie-bg-pill" data-bg="design">Design</button>
            </div>
            <div class="ie-src" id="ie-src"></div>
          </div>
          <div class="ie-right">
            <label class="ie-label">FIND THE ITEM — search the local library</label>
            <div class="ie-search-field">
              <input id="ie-search" class="inline-search ie-search" type="text" autocomplete="off"
                     placeholder="Type the first letters of the name...">
              <div id="ie-results" class="ie-results" hidden></div>
            </div>
            <div class="ie-fields">
              <label class="ie-field ie-name-field"><span>ITEM NAME</span>
                <input id="ie-name" class="inline-search" type="text" autocomplete="off" placeholder="Type the name — matches appear right away">
                <div id="ie-suggest" class="ie-suggest" hidden></div></label>
              <label class="ie-field"><span>TYPE / CATEGORY — free text</span>
                <input id="ie-type" class="inline-search" type="text" autocomplete="off" list="ie-types" placeholder="Trinket, Weapon, Shield...">
                <datalist id="ie-types">${TYPE_HINTS.map((t) => `<option value="${t}"></option>`).join("")}</datalist></label>
              <label class="ie-field"><span>SELL PRICE</span>
                <input id="ie-value" class="inline-search" type="number" min="0" step="1" placeholder="0"></label>
              <label class="ie-field"><span>NOTE (optional)</span>
                <input id="ie-note" class="inline-search" type="text" autocomplete="off" placeholder="Anything to remember about this piece..."></label>
            </div>
            <div class="ie-icon-row">
              <label class="ident-filebtn"><input id="ie-file" type="file" accept="image/png,image/jpeg,image/webp" hidden>UPLOAD IMAGE...</label>
              <button type="button" class="ghost tiny" id="ie-keep">KEEP CATALOG IMAGE</button>
              <button type="button" class="ghost tiny" id="ie-pick">PICK FROM LIBRARY</button>
              <span class="note" id="ie-file-name"></span>
            </div>
          </div>
        </div>
        <div class="ie-foot">
          <span class="note" id="ie-msg"></span>
          <div class="ie-foot-btns">
            <button type="button" class="ghost" id="ie-cancel">CANCEL</button>
            <button type="button" class="pill primary" id="ie-save">SAVE OVERRIDE</button>
          </div>
        </div>
        </div>
        <div class="ie-pane ie-pane-saved" data-pane="saved" hidden>
          <p class="note ie-saved-note">These fields always win: catalog sync or new game data never overwrite them. Pick a row to edit it.</p>
          <div class="ie-list" id="ie-list"></div>
        </div>
      </div>
    </div>`);

    const modal = q("#ie-modal");
    // نافذة واحدة بس: لو محرّر مفتوح معاه، يتقفل الأول (القفل لا يتقفل)
    document.querySelectorAll("#ie-modal").forEach((old) => { if (old !== modal) old.remove(); });
    const el = (id) => q("#" + id, modal);
    const fields = { name: el("ie-name"), type: el("ie-type"), value: el("ie-value"), note: el("ie-note"), id: el("ie-id") };

    function msg(text, kind) {
      el("ie-msg").textContent = text || "";
      el("ie-msg").className = "note" + (kind ? " " + kind : "");
    }

    // تبويبين في نافذة واحدة: المحرّر، وقائمة التعديلات المحفوظة (زر واحد بس بره)
    let tab = "editor";
    async function showTab(name) {
      tab = name === "saved" ? "saved" : "editor";
      modal.querySelectorAll(".ie-tab").forEach((b) => b.classList.toggle("on", b.dataset.tab === tab));
      modal.querySelectorAll(".ie-pane").forEach((p) => { p.hidden = p.dataset.pane !== tab; });
      if (tab === "saved") await renderSaved();
    }
    modal.querySelectorAll(".ie-tab").forEach((b) => b.onclick = () => showTab(b.dataset.tab));

    async function renderSaved() {
      const box = el("ie-list");
      box.innerHTML = `<p class="note empty-col">reading...</p>`;
      try {
        const d = await req("/admin/api/item/overrides");
        const rows = Object.entries(d.items || {}).sort((a, b) => String(a[1].name).localeCompare(String(b[1].name)));
        el("ie-tab-count").textContent = String(rows.length);
        box.innerHTML = rows.length ? rows.map(([id, r]) => {
          const bg = r.card_bg || "standard";
          const bgClass = bg === "blueprint" ? "bp" : bg === "design" ? "design" : "";
          return `
              <button type="button" class="ie-list-row" data-id="${esc(id)}">
                ${r.image ? `<span class="ident-ico r-${esc(r.rarity || "Common")} ${bgClass}"><img src="${esc(assetUrl(r.image, r.at))}" alt="" loading="lazy"></span>` : `<span class="ident-ico noimg ${bgClass}"><span class="ph">?</span></span>`}
                <span class="ie-list-name"><b>${esc(r.name)}</b><small>${esc(id)}</small></span>
                <span class="r-${esc(r.rarity || "Common")} ie-list-rar">${esc(r.rarity || "—")}</span>
                <span class="ie-list-type">${esc(r.type || "—")}</span>
                <span class="ie-list-bg ie-bg-${esc(bg)}">${esc(bg.toUpperCase())}</span>
                <span class="ie-list-val">${r.value === null || r.value === undefined ? "—" : esc(r.value)}</span>
              </button>`;
        }).join("") : `<p class="note empty-col">No manual overrides yet.</p>`;
        box.querySelectorAll(".ie-list-row").forEach((b) => b.onclick = () => {
          const id = b.dataset.id;
          showTab("editor");
          state.dirty = false;
          picked = null;
          fields.id.value = id;
          fields.name.value = "";
          load(id, "").catch(() => {});
        });
      } catch (err) {
        box.innerHTML = `<p class="note empty-col">${esc(err.message)}</p>`;
      }
    }

    function currentRarity() {
      const on = q("#ie-rarity [data-rar].on", modal);
      return on ? on.dataset.rar : "";
    }

    function setRarity(r) {
      q("#ie-rarity [data-rar]", modal) && modal.querySelectorAll("#ie-rarity [data-rar]").forEach((b) =>
        b.classList.toggle("on", b.dataset.rar === String(r || "")));
      paint();
    }

    function currentCardBg() {
      const on = q("#ie-card-bg [data-bg].on", modal);
      return on ? on.dataset.bg : (state.card_bg || "standard");
    }

    function setCardBg(bg) {
      const val = (bg || "standard").toLowerCase();
      state.card_bg = (val === "blueprint" || val === "design") ? val : "standard";
      if (q("#ie-card-bg [data-bg]", modal)) {
        modal.querySelectorAll("#ie-card-bg [data-bg]").forEach((b) =>
          b.classList.toggle("on", b.dataset.bg === state.card_bg));
      }
      paint();
    }

    function readForm() {
      return {
        asset_id: String(fields.id.value || "").trim(),
        name: String(fields.name.value || "").trim(),
        rarity: currentRarity(),
        card_bg: currentCardBg(),
        type: String(fields.type.value || "").trim(),
        value: String(fields.value.value || "").trim(),
        note: String(fields.note.value || "").trim(),
      };
    }

    function paint() {
      const f = readForm();
      const image = state.icon.mode === "upload-pending" ? state.icon.value
        : state.icon.mode === "keep" ? (state.baseline && state.baseline.image) || ""
        : state.icon.value;
      const rar = f.rarity || "Common";
      const bg = state.card_bg || "standard";
      const bgClass = bg === "blueprint" ? "bp" : bg === "design" ? "design" : "";
      const tile = `<div class="tile r-${esc(rar)} ie-tile ${bgClass}" data-card-bg="${esc(bg)}">
          ${image ? `<img src="${esc(imagePreview(image))}" alt="" onerror="this.style.visibility='hidden'">` : `<span class="ph">?</span>`}
          ${bg === "design" ? `<span class="cat-strip"><svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 2v20M2 12h20"/></svg><span>DESIGN</span></span>` : ""}
      </div>`;
      const rows = [
        ["NAME", f.name || "—"],
        ["RARITY", rar],
        ["CARD BG", bg.toUpperCase()],
        ["TYPE", f.type || "—"],
        ["SELL PRICE", f.value === "" ? "—" : f.value],
      ];
      el("ie-preview").innerHTML = `${tile}<div class="ie-preview-kv">${rows.map(([k, v]) =>
        `<div><span>${esc(k)}</span><b>${esc(v)}</b></div>`).join("")}</div>`;
      el("ie-save").disabled = !f.asset_id || !f.name;
      el("ie-save").title = "";
      const idChanged = f.asset_id && f.asset_id !== state.id;
      el("ie-idstatus").innerHTML = !f.asset_id
        ? `<span class="warn">An asset id is required.</span>`
        : idChanged ? `<span class="warn">${state.picked ? "Auto-filled from the library for this id — LOOKUP re-checks the game data." : "ID changed — press LOOKUP to load its data."}</span>`
        : state.loaded ? sourceText() : `<span class="muted">${esc(state.note || "—")}</span>`;
    }

    function sourceText() {
      const b = state.baseline || {};
      const over = state.override;
      const src = [];
      if (over) src.push(`<span class="ok">✓ manual override saved</span>`);
      if (b.inventory) src.push(`inventory: <b>${esc(b.inventory.name || "")}</b> · ${esc(b.inventory.rarity || "no rarity")} · ${esc(b.inventory.type || "—")} · ${b.inventory.value === null || b.inventory.value === undefined ? "—" : esc(b.inventory.value)}`);
      else if (b.catalog) src.push(`game data: <b>${esc(b.catalog.name || "")}</b> · ${esc(b.catalog.rarity || "no rarity")} · ${esc(b.catalog.type || "—")} · ${b.catalog.value === null || b.catalog.value === undefined ? "—" : esc(b.catalog.value)}`);
      else src.push(`<span class="muted">not in this inventory or the game data — you can still save it by id</span>`);
      return src.join(" · ");
    }

    function fillFrom(row, keepIcon) {
      if (!row) return;
      fields.name.value = row.name || "";
      fields.type.value = row.type || "";
      fields.value.value = row.value === null || row.value === undefined ? "" : row.value;
      setRarity(row.rarity || "");
      if (row.card_bg) setCardBg(row.card_bg);
      else if (row.item_kind === "blueprint" || String(row.type || "").toLowerCase() === "blueprint" || /blueprint$/i.test(row.name || "")) setCardBg("blueprint");
      else if (row.item_kind === "design" || String(row.type || "").toLowerCase() === "design") setCardBg("design");
      else setCardBg("standard");
      if (!keepIcon && row.image) {
        state.icon = { mode: "picked", value: row.image };
      }
      el("ie-src").innerHTML = "";
      paint();
    }

    function applyRaw(raw) {
      state.baseline = raw;
      state.override = raw && raw.override;
      state.loaded = true;
      el("ie-del").hidden = !state.override;
      // الأولوية: التعديل اليدوي، بعده بيانات المخزون، بعده بيانات اللعبة، بعده التعريف المحلي
      const over = raw && raw.override;
      if (over) {
        const src = itemOverrides.find(fields.id.value);
        fillFrom({ name: over.name, rarity: over.rarity, type: over.type,
                   card_bg: over.card_bg || (src && src.card_bg),
                   value: over.value, image: over.image || (src && src.image) || "" }, false);
        if (state.baseline) state.baseline.image = over.image || (src && src.image) || "";
      } else if (picked) {
        // السطر اللي المستخدم اختاره من المكتبة الصورة بتاعته بتفضل معاه
        const keep = { ...picked };
        if (!keep.type) keep.type = (raw && ((raw.catalog && raw.catalog.type) || (raw.known && raw.known.type))) || "";
        fillFrom(keep, false);
      } else {
        const base = (raw && raw.inventory) || (raw && raw.catalog) || {};
        const known = raw && raw.known;
        fillFrom({
          name: base.name || (known && known.name) || "",
          rarity: base.rarity || (known && known.rarity) || "",
          type: base.type || (known && known.type) || "",
          value: base.value,
          image: base.image || (known && known.image) || "",
        }, false);
      }
      if (state.baseline && !state.baseline.image) {
        state.baseline.image = (state.baseline.catalog && state.baseline.catalog.image) || state.icon.value || "";
      }
      paint();
    }

    async function load(assetId, name) {
      state.id = assetId;
      state.loaded = false;
      msg("Reading the game data for this piece...");
      const raw = await lookup(assetId, name);
      msg("");
      if (!raw) { paint(); return; }
      // ID جديد مفيش له أي بيانات ومفيش اسم مختار: النافذة بتفضل زي ما هي جاهزة
      // للإدخال، والرقم اللي اتكتب بيفضل في الخانة.
      if (!raw.override && !raw.inventory && !raw.catalog && !picked && !String(fields.name.value || "").trim()) {
        state.baseline = {};
        state.loaded = false;
        state.note = "New id — no saved data or game data yet. Type a name (or pick from the library) and the fields fill in.";
        paint();
        return;
      }
      applyRaw(raw);
    }

    // بعد ما المستخدم يكتب/يختار ID: تكمّل السعر وتغيّر الاسم لو مكتوب سطر محفوظ —
    // بدون ما تمسح أي حاجة كتبها بنفسه.
    async function hydrate(assetId, name) {
      const raw = await lookup(assetId, name || fields.name.value);
      if (!raw) { paint(); return; }
      const current = String(fields.id.value || "").trim();
      if (current !== String(assetId)) return;
      state.baseline = raw;
      state.override = raw.override;
      state.loaded = true;
      el("ie-del").hidden = !raw.override;
      if (!String(fields.name.value || "").trim() && raw.override && raw.override.name) fields.name.value = raw.override.name;
      const over = raw.override || {};
      if (over.card_bg) setCardBg(over.card_bg);
      if (fields.value.value === "" && over.value !== null && over.value !== undefined) fields.value.value = over.value;
      if (fields.value.value === "" && raw.catalog && raw.catalog.value !== null && raw.catalog.value !== undefined) fields.value.value = raw.catalog.value;
      if (!String(fields.type.value || "").trim()) fields.type.value = over.type || (raw.catalog && raw.catalog.type) || (raw.known && raw.known.type) || "";
      if (!currentRarity()) setRarity(over.rarity || (raw.catalog && raw.catalog.rarity) || "");
      if (!state.icon.value) {
        const art = over.image || (raw.catalog && raw.catalog.image) || (raw.known && raw.known.image) || "";
        if (art) state.icon = { mode: "picked", value: art };
        if (state.baseline) state.baseline.image = art;
      }
      el("ie-src").innerHTML = raw.override ? `This id already has a saved manual override.` : "";
      paint();
    }

    // آخر نتائج المكتبة — القائمتين (البحث الاسمي واقتراحات الاسم) بيتشاركوا فيها
    let found = [];
    const searchRow = (row, extra) => {
      const ov = itemOverrides.find(row.asset_id);
      const bg = (ov && ov.card_bg) || row.card_bg || (String(row.type || "").toLowerCase() === "blueprint" || /blueprint$/i.test(row.name || "") ? "blueprint" : String(row.type || "").toLowerCase() === "design" ? "design" : "standard");
      const bgClass = bg === "blueprint" ? "bp" : bg === "design" ? "design" : "";
      return `
          <button type="button" class="ident-row" data-asset="${esc(row.asset_id)}" data-image="${esc(row.image || "")}" data-type="${esc(row.type || "")}" ${extra || ""}>
            <span class="ident-ico r-${esc(row.rarity || "Common")} ${bgClass}">${row.image ? `<img src="${esc(searchThumb(row.image))}" alt="" loading="lazy">` : `<span class="ph">?</span>`}</span>
            <span class="ident-row-name">${esc(row.name)}${row.asset_id ? `<small>${esc(row.asset_id)}</small>` : ""}</span>
            <span class="ident-row-rar r-${esc(row.rarity || "Common")}">${esc(row.rarity || "")}</span>
          </button>`;
    };

    async function query(term) {
      const r = await req(`/api/icons?q=${encodeURIComponent(term)}&limit=24`).catch(() => null);
      found = (r && r.results) || [];
      return found;
    }

    // اختيار عنصر من المكتبة: الاسم/الندرة/النوع/السعر/الصورة كلهم من القاعدة المحلية،
    // والحقول كلها بتفضل مفتوحة للتعديل بعدها. الـ ID إحنا اللي بينكتب من المستخدم —
    // لو فاضي بناخد الـ asset id بتاع العنصر نفسه، ولو مكتوب بيفضل زي ما هو.
    async function pick(row, how) {
      if (!row) return;
      state.picked = true;
      if (how && normalize(row.name) === normalize(fields.name.value)) state.auto = normalize(row.name);
      el("ie-suggest").hidden = true;
      // القائمة المنسدلة بتقفل على طول بعد الاختيار — مش بتفضل مغطية حقل الاسم
      el("ie-results").hidden = true;
      const ownId = String(fields.id.value || "").trim();
      if (!ownId && row.asset_id) {
        fields.id.value = String(row.asset_id);
        state.id = String(row.asset_id);
      }
      if (String(fields.id.value || "").trim() === state.id) state.picked = true;
      const id = String(fields.id.value || "").trim();
      picked = { name: row.name, rarity: row.rarity, image: row.image || "", type: row.type || "" };
      state.icon = { mode: "picked", value: row.image || "" };
      fields.name.value = row.name || "";
      setRarity(row.rarity || "");
      fields.type.value = row.type || fields.type.value || "";
      state.dirty = true;
      paint();
      msg(`Auto-filled from the local library — every field stays editable.`, "ok");
      if (!id) return;
      // السعر (وباقي الحقول الناقصة) من بيانات اللعبة لنفس الـ ID
      const raw = await lookup(id, row.name).catch(() => null);
      if (String(fields.id.value || "").trim() !== id) return;
      if (raw) {
        state.baseline = raw;
        state.override = raw.override;
        state.loaded = true;
        el("ie-del").hidden = !raw.override;
      }
      // التعديل اليدوي المحفوظ على نفس الـ ID بيكسب على المكتبة
      if (raw && raw.override) {
        const o = raw.override;
        if (fields.name.value === row.name) fields.name.value = o.name || row.name;
        if (o.rarity) setRarity(o.rarity);
        if (o.type) fields.type.value = o.type;
        if (o.value !== null && o.value !== undefined) fields.value.value = o.value;
        if (o.image) state.icon = { mode: "picked", value: o.image };
        el("ie-src").innerHTML = `This id already has a saved manual override — shown here with its picture: <b>${esc(o.name || row.name)}</b>`;
      } else {
        const cat = raw && ((raw.catalog && raw.catalog.type) || (raw.inventory && raw.inventory.type));
        if (!fields.type.value && cat) fields.type.value = cat;
        const price = (raw && raw.catalog && raw.catalog.value) ?? (raw && raw.inventory && raw.inventory.value);
        if (price !== null && price !== undefined && String(price) !== "") fields.value.value = price;
        el("ie-src").innerHTML = `${row.image ? "Picture" : "No picture"} from the library: <b>${esc(row.name)}</b>`;
      }
      paint();
    }

    async function search(term) {
      const box = el("ie-results");
      if (!term.trim()) { box.innerHTML = ""; box.hidden = true; return; }
      box.hidden = false;
      const seq = (state.searchSeq = (state.searchSeq || 0) + 1);
      box.innerHTML = `<p class="note empty-col">searching...</p>`;
      try {
        const rows = await query(term);
        if (seq !== state.searchSeq) return;
        box.innerHTML = rows.length ? rows.map((row) => searchRow(row)).join("")
          : `<p class="note empty-col">Nothing in the local library matches “${esc(term)}”.</p>`;
        const rowsEls = [...box.querySelectorAll(".ident-row")];
        rowsEls.forEach((b, i) => b.onclick = () => pick(rows[i], "search"));
        const exact = rows.find((r) => normalize(r.name) === normalize(term));
        if (exact && state.auto !== normalize(term) && !fields.id.value.trim()) pick(exact, "search");
      } catch (err) {
        box.innerHTML = `<p class="note empty-col">${esc(err.message)}</p>`;
      }
    }

    // اقتراحات مباشرة تحت خانة الاسم: صورة + اسم + ندرة، واختيارها بيعبّي كل الحقول
    async function suggest(term) {
      const box = el("ie-suggest");
      const seq = (state.suggestSeq = (state.suggestSeq || 0) + 1);
      if (String(term || "").trim().length < 2) { box.hidden = true; box.innerHTML = ""; return; }
      try {
        const rows = (await query(term)).slice(0, 8);
        if (seq !== state.suggestSeq) return;
        if (document.activeElement !== fields.name) { box.hidden = true; return; }
        box.innerHTML = rows.length ? rows.map((row) => searchRow(row, `data-suggest="1"`)).join("")
          : `<p class="note empty-col">No local library match yet — keep typing, or pick from FIND THE ITEM below.</p>`;
        box.hidden = false;
        suggestJs = [...box.querySelectorAll(".ident-row")];
        suggestJs.forEach((b, i) => b.onclick = () => pick(rows[i], "name"));
        // الاسم اللي اتكتب لايق على اسم في المكتبة بالظبط — التعبئة تلقائياً
        const exact = rows.find((r) => normalize(r.name) === normalize(term));
        if (exact && state.auto !== normalize(term) && !fields.id.value.trim()) pick(exact, "name");
      } catch (err) { box.hidden = true; }
    }
    const normalize = (s) => String(s || "").toLowerCase().replace(/\s+/g, " ").trim();

    Object.values(fields).forEach((f) => {
      f.addEventListener("input", () => { state.dirty = true; paint(); });
      f.addEventListener("change", () => { state.dirty = true; paint(); });
    });

    el("ie-rarity").querySelectorAll("[data-rar]").forEach((b) => b.onclick = () => {
      state.dirty = true;
      setRarity(b.dataset.rar);
    });

    el("ie-card-bg").querySelectorAll("[data-bg]").forEach((b) => b.onclick = () => {
      state.dirty = true;
      setCardBg(b.dataset.bg);
    });

    let timer = 0;
    el("ie-search").addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(() => search(el("ie-search").value), 120);
    });

    let nameTimer = 0;
    let suggestJs = [];
    fields.name.addEventListener("input", () => {
      if (String(fields.id.value || "").trim() === "") state.auto = "";
      clearTimeout(nameTimer);
      nameTimer = setTimeout(() => { suggestJs = []; suggest(fields.name.value); }, 150);
    });
    fields.name.addEventListener("focus", () => { if (fields.name.value.trim().length >= 2) suggest(fields.name.value); });
    fields.name.addEventListener("keydown", (e) => {
      if (el("ie-suggest").hidden) return;
      const on = el("ie-suggest").querySelector(".ident-row.on") || suggestJs[0];
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        const i = suggestJs.indexOf(on);
        const next = suggestJs[(i + (e.key === "ArrowDown" ? 1 : suggestJs.length - 1)) % Math.max(1, suggestJs.length)];
        suggestJs.forEach((b) => b.classList.toggle("on", b === next));
        if (next) next.scrollIntoView({ block: "nearest" });
      } else if (e.key === "Enter" && on) {
        e.preventDefault();
        on.click();
      } else if (e.key === "Escape") {
        e.stopPropagation();
        el("ie-suggest").hidden = true;
      }
    });
    document.addEventListener("mousedown", (e) => {
      if (!e.target.closest || !e.target.closest(".ie-name-field")) el("ie-suggest").hidden = true;
      if (!e.target.closest || !e.target.closest(".ie-search-field")) el("ie-results").hidden = true;
    });

    let idTimer = 0;
    el("ie-load").onclick = async () => {
      const id = String(fields.id.value || "").trim();
      if (!id) { msg("Type the asset id first.", "warn"); return; }
      state.id = id;
      await load(id, fields.name.value);
      if (!state.loaded) msg("Nothing came back for this id — the fields stay as they are, and you can still save it by id.", "warn");
    };
    fields.id.addEventListener("input", () => {
      state.loaded = false;
      clearTimeout(idTimer);
      const id = String(fields.id.value || "").trim();
      if (!/^[0-9A-Za-z_-]{3,}$/.test(id)) { paint(); return; }
      // السعر/الندرة/الصورة الافتراضية بتتقري من غير ما المستخدم يدوس READ
      idTimer = setTimeout(() => { hydrate(id).catch(() => {}); }, 450);
    });
    fields.id.addEventListener("change", () => {
      const id = String(fields.id.value || "").trim();
      if (id !== state.id) {
        state.loaded = false;
        state.baseline = null;
        state.override = null;
        el("ie-del").hidden = true;
        if (id) hydrate(id).catch(() => {});
        paint();
      }
    });

    el("ie-keep").onclick = () => {
      const src = state.baseline && (state.baseline.image || (state.baseline.catalog && state.baseline.catalog.image));
      state.icon = { mode: "keep", value: src || "" };
      el("ie-file").value = "";
      el("ie-file-name").textContent = src ? "catalog image kept" : "no catalog image";
      paint();
    };
    el("ie-pick").onclick = () => {
      el("ie-search").focus();
      msg("Search a name below and pick the row — its picture becomes this item's picture.", "");
    };
    el("ie-file").onchange = async () => {
      const f = el("ie-file").files[0];
      if (!f) return;
      if (f.size > 4 * 1024 * 1024) { msg("The picture is over 4 MB.", "bad"); el("ie-file").value = ""; return; }
      try {
        const dataUrl = await fileToDataURL(f);
        state.icon = { mode: "upload-pending", value: dataUrl };
        el("ie-file-name").textContent = f.name;
        state.dirty = true;
        paint();
      } catch (err) { msg(err.message, "bad"); }
    };

    function close() {
      if (state.dirty && !state.done && !opts.force) {
        msg("You changed fields — press SAVE OVERRIDE to keep them, or CANCEL again to discard.", "warn");
        state.dirty = false;
        return;
      }
      modal.remove();
      document.removeEventListener("keydown", onKey);
      if (opts.onClose) opts.onClose(state.done);
    }
    function onKey(e) {
      if (e.key === "Escape") { e.stopPropagation(); close(); }
      if (e.key === "Enter" && !e.shiftKey && e.target && e.target.tagName === "INPUT"
          && e.target.id !== "ie-search" && e.target.type !== "file") { e.preventDefault(); save(); }
    }
    document.addEventListener("keydown", onKey);
    async function save() {
      const f = readForm();
      if (!f.asset_id) { msg("The asset id is required.", "bad"); return; }
      if (!f.name) { msg("The item name is required.", "bad"); fields.name.focus(); return; }
      if (f.value !== "" && !(Number(f.value) >= 0)) { msg("The sell price must be a number of zero or more.", "bad"); return; }
      const btn = el("ie-save");
      btn.disabled = true;
      msg("Saving...");
      try {
        const pixel = await inlineTilePixel(state.icon.value);
        const payload = {
          asset_id: f.asset_id, name: f.name, rarity: f.rarity || "Common",
          card_bg: f.card_bg || "standard",
          type: f.type, value: f.value === "" ? null : f.value, note: f.note,
        };
        let chosenImage = state.icon.value;
        if (!chosenImage) {
          chosenImage = (state.baseline && (state.baseline.image || (state.baseline.catalog && state.baseline.catalog.image)))
            || (state.override && state.override.image)
            || (picked && picked.image) || "";
        }
        if (state.icon.mode === "upload-pending") {
          payload.image = await pixel;
          payload.filename = (el("ie-file").files[0] || {}).name || "";
        } else {
          payload.image = chosenImage;
        }
        const out = await push("/admin/api/item/override", "POST", payload);
        state.done = true;
        const row = out.override || {};
        localEdits.set(String(f.asset_id), out.row || row);
        itemOverrides.map[String(f.asset_id)] = out.override || row;
        refresh();
        // اللوحة بتاخد التعديل على طول: نفس القطعة في أي حساب بتتحدّث هنا من غير
        // انتظار القراءة اللي بعدها — وأي عنصر جديد (ID مش في المخزن) بيظهر بلاطة
        // مؤقتة في أول عمود، والقراءة من السيرفر بعدها بتثبّت الاسم النهائي.
        try { window.dispatchEvent(new CustomEvent("items:edited", { detail: { asset_id: String(f.asset_id), row: out.row || row } })); } catch (e) { /* قديم */ }
        toast(`✔ SAVED — ${row.name || f.name} · ${row.rarity || f.rarity} · ${row.value === null || row.value === undefined ? "—" : row.value} (manual override on ${f.asset_id})`, "ok");
        modal.remove();
        document.removeEventListener("keydown", onKey);
        if (opts.onSaved) opts.onSaved(out);
      } catch (err) {
        btn.disabled = false;
        msg(err.message, "bad");
      }
    }

    el("ie-save").onclick = save;
    el("ie-cancel").onclick = () => { state.dirty = false; close(); };
    el("ie-close").onclick = () => { state.dirty = false; close(); };
    el("ie-del").onclick = async () => {
      const id = String(fields.id.value || "").trim();
      if (!id) return;
      if (!window.confirm(`Delete the manual override on ${id}? The item goes back to the game data.`)) return;
      try {
        await push(`/admin/api/item/override?asset_id=${encodeURIComponent(id)}`, "DELETE", {});
        localEdits.delete(id);
        delete itemOverrides.map[id];
        refresh();
        try { window.dispatchEvent(new CustomEvent("items:edited", { detail: { asset_id: String(id), deleted: true } })); } catch (e) { /* قديم */ }
        // صورة العنصر التجريبي/المحذوف مالهاش لازمة بعد الحذف — بتتشال من المكتبتين
        for (const base of ["/assets/items/arctracker/", "/static/item_icons/"]) {
          const name = base + "asset_" + encodeURIComponent(String(id).replace(/[^0-9A-Za-z_-]+/g, "_")) + ".png";
          fetch(name, { method: "DELETE" }).catch(() => {});
        }
        toast(`Override removed — ${id} shows the game data again.`, "ok");
        state.override = null;
        state.done = true;
        modal.remove();
        document.removeEventListener("keydown", onKey);
        if (opts.onSaved) opts.onSaved(null);
      } catch (err) { msg(err.message, "bad"); }
    };

    // التعبئة الأولى: عنصر من المخزون بشكل مباشر (من صف اللوحة)، أو عنصر جديد
    if (opts.anchor) {
      const a = opts.anchor;
      fillFrom({
        name: a.display_name || a.name || "", rarity: a.rarity || "",
        type: a.type || "", value: a.value,
        image: a.image || (a.dbid && (a.dbid.image_local || a.dbid.metaforge_image)) || "",
      });
      state.baseline = { image: state.icon.value, inventory: { name: a.display_name || a.name, rarity: a.rarity,
        type: a.type, value: a.value } };
    }
    if (preset.name) {
      fillFrom({ name: preset.name, rarity: preset.rarity, type: preset.type, value: preset.value, image: preset.image });
    }
    if (aid) {
      state.id = aid;
      load(aid, (preset && preset.name) || (opts.anchor && (opts.anchor.display_name || opts.anchor.name)) || "").then(() => {
        if (!aid && !preset.name) el("ie-search").focus();
        paint();
      });
    } else {
      // فتح نظيف من زر الأدمن: مفيش ID ومفيش اسم — الخانات فاضية والرقم هو أول حاجة
      state.loaded = false;
      fields.name.value = preset.name || "";
      fields.type.value = preset.type || "";
      fields.value.value = preset.value === undefined || preset.value === null ? "" : preset.value;
      setRarity(preset.rarity || "Common");
      el("ie-del").hidden = true;
      state.note = "New entry — type an asset id, then a name (or pick from the library) and every field fills in.";
      setTimeout(() => fields.id.focus(), 60);
    }
    paint();
    return modal;
  }

  /* ------------------------------------------------------------------ helpers */
  // صورة المكتبة (static/item_icons) بتبان على البلاطة من مسارها العادي — لكن نسخة
  // مربعة بتتحفظ كـ asset خاص بالـ ID، فالعنصر الجديد مش بيعتمد على اسم ملف حد تاني.
  async function uploadedIcon(src, assetId) {
    if (!src || !src.startsWith("static/")) return src;
    try {
      const img = new Image();
      await new Promise((ok, bad) => { img.onload = ok; img.onerror = bad; img.src = "/admin/api/item/icon?path=" + encodeURIComponent(src); });
      const size = 256;
      const canvas = document.createElement("canvas");
      canvas.width = size; canvas.height = size;
      const ctx = canvas.getContext("2d");
      const scale = Math.min(size / img.width, size / img.height);
      const w = Math.max(1, Math.round(img.width * scale));
      const h = Math.max(1, Math.round(img.height * scale));
      ctx.drawImage(img, Math.round((size - w) / 2), Math.round((size - h) / 2), w, h);
      return canvas.toDataURL("image/png");
    } catch (err) {
      return src;
    }
  }
  // صورة الجهاز بتتحول مربّع PNG (256px) — نفس نسبة البلاطة، والشرح بيتبقى واضح
  async function inlineTilePixel(src) {
    if (!src) return "";
    if (!src.startsWith("data:image/")) return src;
    try {
      const img = new Image();
      await new Promise((ok, bad) => { img.onload = ok; img.onerror = bad; img.src = src; });
      const size = 256;
      const canvas = document.createElement("canvas");
      canvas.width = size; canvas.height = size;
      const ctx = canvas.getContext("2d");
      const scale = Math.min(size / img.width, size / img.height);
      const w = Math.max(1, Math.round(img.width * scale));
      const h = Math.max(1, Math.round(img.height * scale));
      ctx.drawImage(img, Math.round((size - w) / 2), Math.round((size - h) / 2), w, h);
      return canvas.toDataURL("image/png");
    } catch (err) {
      return src;
    }
  }

  /* ------------------------------------------------------------------ public */
  window.ItemEditor = {
    open: openEditor,
    edits: () => localEdits,
    itemOverrides: () => itemOverrides,
    // بيانات العناصر للأدمن الفعلي فقط
    ready: (cb) => {
      const fire = async () => {
        try {
          const me = await req("/api/auth/me");
          admin = !!me.is_admin && !me.preview && !me.impersonating;
        } catch (err) { admin = false; }
        cb(!!admin);
      };
      fire();
    },
  };

  // Only fetch item overrides if admin
  window.ItemEditor.ready((isAdm) => {
    if (!isAdm) return;
    fetch("/admin/api/item/overrides", { cache: "no-store" }).then((r) => r.json()).then((d) => {
      itemOverrides.map = { ...(d.items || {}), ...Object.fromEntries(localEdits) };
    }).catch(() => {});
  });

  // زر واحد بس في الهيدر: ITEM DATA — للأدمن الفعلي فقط
  document.querySelectorAll("#btn-item-data, #btn-item-overrides").forEach((old) => old.remove());
  const adminBtn = document.getElementById("btn-admin-item-data");
  if (adminBtn) {
    window.ItemEditor.ready((ok) => {
      adminBtn.style.display = ok ? "inline-flex" : "none";
      if (ok) {
        adminBtn.onclick = () => openEditor("", { source: "admin" });
      } else {
        adminBtn.onclick = null;
      }
    });
  }
})();