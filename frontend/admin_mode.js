(async function initAdminMode() {
  // ⚙️ تهيئة قائمة الترس والإعدادات المنسدلة (Gear Dropdown Menu)
  const gearWrap = document.getElementById("gear-menu-wrap");
  const btnGear = document.getElementById("btn-gear-toggle");
  const gearDropdown = document.getElementById("gear-dropdown");
  const btnGearClose = document.getElementById("btn-gear-close");
  const btnGearAccounts = document.getElementById("btn-gear-accounts");
  const btnGearSyncAll = document.getElementById("btn-gear-sync-all");

  if (btnGear && gearDropdown) {
    btnGear.onclick = (e) => {
      e.stopPropagation();
      const isVisible = gearDropdown.style.display === "flex";
      gearDropdown.style.display = isVisible ? "none" : "flex";
    };

    if (btnGearClose) {
      btnGearClose.onclick = (e) => {
        e.stopPropagation();
        gearDropdown.style.display = "none";
      };
    }

    if (btnGearAccounts) {
      btnGearAccounts.onclick = (e) => {
        e.stopPropagation();
        gearDropdown.style.display = "none";
        if (typeof showView === "function") {
          showView("accounts");
        } else if (typeof window.showView === "function") {
          window.showView("accounts");
        }
      };
    }

    if (btnGearSyncAll) {
      btnGearSyncAll.onclick = (e) => {
        e.stopPropagation();
        gearDropdown.style.display = "none";
        const mainSyncAll = document.getElementById("acct-sync-all");
        if (mainSyncAll) mainSyncAll.click();
      };
    }

    // إغلاق عند الضغط خارج قائمة الترس
    document.addEventListener("click", (e) => {
      if (!e.target.closest("#gear-menu-wrap")) {
        gearDropdown.style.display = "none";
      }
    });
  }

  try {
    const res = await fetch("/api/auth/me");
    const data = await res.json();

    // التحقق من وضع تصفح حساب مشترك (Viewing As)
    const urlParams = new URLSearchParams(window.location.search);
    const viewingName = data.viewing_as || urlParams.get("view_as") || "";

    const viewAsBar = document.getElementById("view-as-bar");
    const viewAsNameEl = document.getElementById("view-as-name");

    if (viewingName && viewAsBar) {
      if (viewAsNameEl) viewAsNameEl.textContent = viewingName;
      viewAsBar.style.display = "inline-flex";
    }

    if (!data.is_admin) return;

    // شريط أدوات الأدمن في صفحة الحسابات Accounts
    const acctAdminBar = document.getElementById("acct-admin-quick-bar");
    const btnAdminPage = document.getElementById("btn-admin-mode-page");
    if (acctAdminBar) acctAdminBar.style.display = "flex";

    // زر ADMIN MODE
    const btn = document.getElementById("btn-admin-mode");
    const modal = document.getElementById("admin-auth-modal");
    const pwInput = document.getElementById("admin-mode-pw");
    const errMsg = document.getElementById("admin-mode-err");
    const btnCancel = document.getElementById("admin-mode-cancel");
    const btnUnlock = document.getElementById("admin-mode-unlock");

    const openAdminModal = () => {
      if (gearDropdown) gearDropdown.style.display = "none";
      errMsg.textContent = "";
      pwInput.value = "";
      modal.hidden = false;
      setTimeout(() => pwInput.focus(), 60);
    };

    if (btn) {
      btn.style.display = "flex";
      if (data.is_local) {
        btn.onclick = () => { window.location.href = "/admin"; };
      } else {
        btn.onclick = (e) => {
          e.stopPropagation();
          openAdminModal();
        };
      }
    }

    if (btnAdminPage) {
      if (data.is_local) {
        btnAdminPage.onclick = () => { window.location.href = "/admin"; };
      } else {
        btnAdminPage.onclick = openAdminModal;
      }
    }

    // زر وقائمة التبديل السريع للمشتركين (Subscribers Switcher)
    const subSwitchWrap = document.getElementById("sub-switch-wrap");
    const btnSubSwitch = document.getElementById("btn-sub-switch");
    const subDropdown = document.getElementById("sub-switch-dropdown");
    const subLabel = document.getElementById("sub-switch-label");

    if (subSwitchWrap && btnSubSwitch && subDropdown) {
      subSwitchWrap.style.display = "flex";
      
      // جلب قائمة المشتركين
      try {
        const acctRes = await fetch("/api/accounts");
        const acctData = await acctRes.json();
        const subs = acctData.subscribers || [];
        
        if (viewingName) {
          subLabel.textContent = `المشترك: ${viewingName}`;
        } else {
          subLabel.textContent = `حساباتي الشخصية (${subs.length ? subs.length + " مشترك" : ""})`;
        }

        let html = `
          <div style="padding:6px 10px; font-weight:800; color:#94a3b8; border-bottom:1px solid #1e293b; font-size:11px; text-transform:uppercase;">
            تبديل البروفايل المعروض
          </div>
          <div style="padding:4px 0;">
            <a href="/admin/exit-view-as?to=/" style="display:flex; align-items:center; gap:8px; padding:7px 10px; border-radius:6px; color:#f1f5f9; text-decoration:none; font-weight:700; ${!viewingName ? 'background:rgba(168,85,247,.25); color:#d8b4fe;' : ''}">
              <span>★</span><span>حساباتي الشخصية (Admin)</span>
            </a>
          </div>
        `;

        if (subs.length) {
          html += `<div style="padding:4px 10px; font-size:10px; color:#64748b; font-weight:700; border-top:1px solid #1e293b;">المشتركين (${subs.length}):</div>`;
          subs.forEach(s => {
            const isCur = viewingName && viewingName.toLowerCase() === s.name.toLowerCase();
            const accList = (s.accounts && s.accounts.length) ? s.accounts.join(", ") : "لا يوجد حسابات بعد";
            html += `
              <div style="padding:2px 0;">
                <a href="/admin/api/subscribers/${s.id}/view-as" style="display:flex; flex-direction:column; padding:6px 10px; border-radius:6px; color:#cbd5e1; text-decoration:none; ${isCur ? 'background:rgba(245,158,11,.2); color:#fde047;' : ''}">
                  <div style="display:flex; justify-content:space-between; align-items:center;">
                    <b style="color:#fff;">👤 ${s.name}</b>
                    <span style="font-size:10px; background:#1e293b; padding:1px 6px; border-radius:4px; color:#94a3b8;">${s.accounts_count} حساب</span>
                  </div>
                  <small style="font-size:10px; color:#94a3b8; margin-top:2px;">${accList}</small>
                </a>
              </div>
            `;
          });
        } else {
          html += `<div style="padding:8px 10px; color:#64748b; font-size:11px;">لا يوجد مشتركون حالياً</div>`;
        }

        subDropdown.innerHTML = html;

        btnSubSwitch.onclick = (e) => {
          e.stopPropagation();
          subDropdown.style.display = subDropdown.style.display === "none" ? "block" : "none";
        };

        subDropdown.onclick = (e) => {
          e.stopPropagation();
        };

        document.addEventListener("click", () => {
          subDropdown.style.display = "none";
        });
      } catch (e) {
        console.warn("Sub switch init error:", e);
      }
    }

    const doUnlock = async () => {
      const pw = pwInput.value.trim();
      if (!pw) return;
      btnUnlock.disabled = true;
      errMsg.textContent = "";
      try {
        const resp = await fetch("/admin/api/login", {
          method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({password: pw})
        });
        const d = await resp.json();
        if (d.ok) {
          window.location.href = "/admin";
        } else {
          errMsg.textContent = "❌ Incorrect admin password.";
          pwInput.focus();
          pwInput.select();
        }
      } catch (e) {
        errMsg.textContent = "Connection error.";
      }
      btnUnlock.disabled = false;
    };

    if (btnUnlock) btnUnlock.onclick = doUnlock;
    if (pwInput) {
      pwInput.onkeydown = (e) => {
        if (e.key === "Enter") doUnlock();
        if (e.key === "Escape") modal.hidden = true;
      };
    }
    if (btnCancel) btnCancel.onclick = () => { modal.hidden = true; };
  } catch (ex) {}
})();
