document.getElementById("login-form").onsubmit = async (e) => {
  e.preventDefault();
  const token = document.getElementById("token").value.trim();
  const msg = document.getElementById("msg");
  const btn = document.getElementById("btn");
  if (!token) { msg.className = "msg err"; msg.textContent = "يرجى لصق التوكن الخاص بك (Please enter your token)"; return; }
  btn.disabled = true; msg.className = "msg"; msg.textContent = "جاري التحقق… Verifying…";
  try {
    const res = await fetch("/auth/subscriber/login", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({token})
    });
    const data = await res.json();
    if (data.ok) {
      msg.className = "msg ok"; msg.textContent = "✔ مرحباً بك، " + (data.name || "User") + "! (Welcome)";
      setTimeout(() => { window.location.href = data.redirect || "/"; }, 500);
    } else {
      msg.className = "msg err"; msg.textContent = data.detail || "توكن غير صالح أو منتهي (Invalid access token)";
    }
  } catch (ex) { msg.className = "msg err"; msg.textContent = "خطأ في الاتصال بالسيرفر (Connection error)"; }
  btn.disabled = false;
};

// Auto-login if token is present in URL
(function checkUrlToken() {
  try {
    const params = new URLSearchParams(window.location.search);
    let tok = (params.get("token") || "").trim();
    const b64 = (params.get("b64") || "").trim();
    if (!tok && b64) {
      try {
        tok = decodeURIComponent(escape(atob(b64))).trim();
      } catch (e) {}
    }
    if (tok) {
      const input = document.getElementById("token");
      if (input) {
        input.value = tok;
        const form = document.getElementById("login-form");
        if (form) {
          setTimeout(() => { form.dispatchEvent(new Event("submit")); }, 50);
        }
      }
    }
  } catch (e) {}
})();
