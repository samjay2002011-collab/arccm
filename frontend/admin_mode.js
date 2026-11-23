(async function initAdminMode() {
  try {
    const res = await fetch("/api/auth/me");
    const data = await res.json();

    // التحقق من وضع تصفح حساب مشترك (Viewing As)
    const urlParams = new URLSearchParams(window.location.search);
    const sessionViewing = sessionStorage.getItem("cm_as_subscriber") || "";
    const cookieMatch = document.cookie.match(/(?:^|;\s*)cm_viewing_subscriber=([^;]*)/);
    const cookieViewing = cookieMatch ? decodeURIComponent(cookieMatch[1]) : "";
    const viewingName = data.viewing_as || urlParams.get("as_subscriber") || urlParams.get("view_as") || sessionViewing || cookieViewing || "";

    const viewAsBar = document.getElementById("view-as-bar");
    const viewAsNameEl = document.getElementById("view-as-name");
    const btn = document.getElementById("btn-admin-mode");
    const returnBtn = document.getElementById("btn-return-admin");

    if (viewingName) {
      if (viewAsBar) {
        if (viewAsNameEl) viewAsNameEl.textContent = viewingName;
        viewAsBar.style.display = "inline-flex";
      }
      if (returnBtn) {
        returnBtn.onclick = (e) => {
          e.preventDefault();
          sessionStorage.removeItem("cm_as_subscriber");
          window.close();
          setTimeout(() => { window.location.href = "/admin"; }, 150);
        };
      }
      // إخفاء زرار ADMIN MODE أثناء التصفح كمشترك
      if (btn) btn.style.display = "none";
      return;
    }

    if (!data.is_admin) {
      if (btn) btn.style.display = "none";
      return;
    }

    if (btn) {
      btn.style.display = "inline-flex";
      // فتح لوحة الأدمن مباشرة بدون طلب أي باسورد ثانٍ
      btn.onclick = () => { window.location.href = "/admin"; };
    }
  } catch (ex) {}
})();
