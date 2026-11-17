(async function initAdminMode() {
  // ⚙️ تهيئة قائمة الترس والإعدادات المنسدلة (Gear Dropdown Menu)
  const gearWrap = document.getElementById("gear-menu-wrap");
  const btnGear = document.getElementById("btn-gear-toggle");
  const gearDropdown = document.getElementById("gear-dropdown");
  const btnGearClose = document.getElementById("btn-gear-close");
  const btnGearAccounts = document.getElementById("btn-gear-accounts");

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
      btn.onclick = () => { window.location.href = "/admin"; };
    }

    if (btnAdminPage) {
      btnAdminPage.onclick = () => { window.location.href = "/admin"; };
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
