document.getElementById("login-form").onsubmit = async (e) => {
  e.preventDefault();
  const token = document.getElementById("token").value.trim();
  const msg = document.getElementById("msg");
  const btn = document.getElementById("btn");
  if (!token) { msg.className = "msg err"; msg.textContent = "Please enter your access token."; return; }
  btn.disabled = true; msg.className = "msg"; msg.textContent = "Verifying…";
  try {
    const res = await fetch("/auth/subscriber/login", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({token})
    });
    const data = await res.json();
    if (data.ok) {
      msg.className = "msg ok"; msg.textContent = "✔ Welcome, " + (data.name || "User") + "!";
      setTimeout(() => { window.location.href = data.redirect || "/"; }, 500);
    } else {
      msg.className = "msg err"; msg.textContent = data.detail || "Invalid access token.";
    }
  } catch (ex) { msg.className = "msg err"; msg.textContent = "Connection error."; }
  btn.disabled = false;
};

fetch("/api/cmsync/version").then(r => r.json()).then(v => {
  const btn = document.getElementById("login-dl-btn");
  if (btn && v && v.version) {
    const span = btn.querySelector("span:nth-child(2)");
    if (span) span.textContent = `Download CMSync v${v.version}`;
  }
}).catch(() => {});
