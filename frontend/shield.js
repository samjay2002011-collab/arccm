/* ══════════════════════════════════════════════════════════════════════════
   CM SHIELD — حماية شاملة ضد نسخ الكود وفحص المصدر
   ══════════════════════════════════════════════════════════════════════════
   الطبقات:
     1. منع كليك يمين
     2. منع كل اختصارات DevTools و View-Source و Save
     3. منع تحديد النص ونسخه وسحبه
     4. فخ debugger مستمر (بيوقف DevTools لو اتفتح)
     5. كشف فتح DevTools بقياس الحجم + performance
     6. تحذير في الكونسول
     7. إعادة كتابة document.title لو حد حاول يحفظ
   ══════════════════════════════════════════════════════════════════════════ */
(function _shield() {
  "use strict";

  // ─── 1. منع كليك يمين المتصفح العادي (مع السماح بـ context menu الموقع) ─
  document.addEventListener("contextmenu", function (e) {
    // السماح بالكليك يمين على بلاطات العناصر (الموقع عنده custom ctx menu)
    if (e.target.closest && e.target.closest(".tile")) return;
    // السماح بالكليك يمين على أزرار الحسابات
    if (e.target.closest && e.target.closest("[data-pick]")) return;
    // لو الحدث من كود الموقع الداخلي — نسيبه
    if (e.__cm_internal) return;
    e.preventDefault();
    e.stopPropagation();
    return false;
  }, true);

  // ─── 2. منع اختصارات لوحة المفاتيح ───────────────────────────────────
  var BLOCKED_KEYS = {
    // DevTools
    "F12": true,
    // Ctrl+Shift+I  (Inspect)
    "ctrl+shift+73": true,
    // Ctrl+Shift+J  (Console)
    "ctrl+shift+74": true,
    // Ctrl+Shift+C  (Element picker)
    "ctrl+shift+67": true,
    // Ctrl+U         (View Source)
    "ctrl+85": true,
    // Ctrl+S         (Save page)
    "ctrl+83": true,
    // Ctrl+A         (Select all) — اختياري
    "ctrl+65": true,
    // Ctrl+P         (Print — بيكشف الكود)
    "ctrl+80": true,
    // Ctrl+Shift+K   (Firefox console)
    "ctrl+shift+75": true,
    // F5 + Ctrl+F5   (مش هنمنعهم — المستخدم محتاج refresh)
  };

  document.addEventListener("keydown", function (e) {
    var combo = "";
    if (e.ctrlKey || e.metaKey) combo += "ctrl+";
    if (e.shiftKey) combo += "shift+";
    combo += e.keyCode;

    if (BLOCKED_KEYS[combo] || BLOCKED_KEYS[e.key]) {
      e.preventDefault();
      e.stopPropagation();
      return false;
    }
  }, true);

  // ─── 3. منع تحديد النص ونسخه وسحبه ──────────────────────────────────
  // منع النسخ
  document.addEventListener("copy", function (e) {
    e.preventDefault();
    e.stopPropagation();
  }, true);

  // منع القص
  document.addEventListener("cut", function (e) {
    e.preventDefault();
    e.stopPropagation();
  }, true);

  // منع تحديد النص بالماوس (ما عدا الـ inputs)
  document.addEventListener("selectstart", function (e) {
    var tag = (e.target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea") return; // السماح للـ inputs
    e.preventDefault();
  }, true);

  // منع السحب
  document.addEventListener("dragstart", function (e) {
    // السماح بالسحب الداخلي للموقع (drag & drop tiles)
    if (e.target.closest && e.target.closest("[draggable]")) return;
    e.preventDefault();
  }, true);

  // CSS: منع تحديد النص على كل الصفحة ما عدا الـ inputs
  var style = document.createElement("style");
  style.textContent =
    "body, body * { -webkit-user-select: none !important; -moz-user-select: none !important; " +
    "-ms-user-select: none !important; user-select: none !important; }" +
    "input, textarea, [contenteditable] { -webkit-user-select: text !important; " +
    "-moz-user-select: text !important; user-select: text !important; }";
  (document.head || document.documentElement).appendChild(style);

  // استثناء الأدمين من الحظر حتى يتمكن من إدارة وتطوير موقعه
  var _isAdmin = false;
  try {
    fetch("/api/auth/me").then(function (r) { return r.json(); }).then(function (d) {
      if (d && d.is_admin) {
        _isAdmin = true;
        _hideOverlay();
      }
    }).catch(function () {});
  } catch (e) {}

  // ─── 4. فخ debugger ───────────────────────────────────────────────────
  // لو حد فتح DevTools وحط breakpoint أو بيتابع الكود، الـ debugger statement
  // بيوقفه كل 50 ملي ثانية — مستحيل يتابع أي حاجة.
  var _trap = function () {
    if (_isAdmin) return;
    // بنعمل function جديدة كل مرة عشان يبقى صعب يتشال بـ breakpoint واحد
    (function () { debugger; })();
  };
  setInterval(_trap, 100);

  // ─── 5. كشف DevTools بالحجم ───────────────────────────────────────────
  var _dtOpen = false;
  var _checkDevTools = function () {
    if (_isAdmin) return;
    var widthThreshold = window.outerWidth - window.innerWidth > 160;
    var heightThreshold = window.outerHeight - window.innerHeight > 160;
    var isOpen = widthThreshold || heightThreshold;

    if (isOpen && !_dtOpen) {
      _dtOpen = true;
      // تنبيه: DevTools مفتوحة — ممكن تعمل overlay أو redirect
      _showOverlay();
    } else if (!isOpen && _dtOpen) {
      _dtOpen = false;
      _hideOverlay();
    }
  };
  setInterval(_checkDevTools, 500);

  // ─── 6. Overlay لما DevTools تتفتح ────────────────────────────────────
  var _overlay = null;
  function _showOverlay() {
    if (_isAdmin) return;
    if (_overlay) return;
    _overlay = document.createElement("div");
    _overlay.id = "shield-overlay";
    _overlay.style.cssText =
      "position:fixed;inset:0;z-index:999999;background:rgba(8,8,12,.97);" +
      "display:flex;align-items:center;justify-content:center;flex-direction:column;" +
      "font-family:'Segoe UI',system-ui,sans-serif;color:#ff4d4d;text-align:center;";
    _overlay.innerHTML =
      '<div style="font-size:48px;margin-bottom:20px">🛡️</div>' +
      '<h1 style="font-size:28px;font-weight:900;letter-spacing:2px;margin:0 0 14px">ACCESS DENIED</h1>' +
      '<p style="font-size:14px;color:#94a3b8;max-width:400px;line-height:1.7">' +
      'Developer tools are not allowed on this site.<br>' +
      'Close DevTools to continue using the dashboard.</p>';
    document.body.appendChild(_overlay);
  }
  function _hideOverlay() {
    if (_overlay) {
      _overlay.remove();
      _overlay = null;
    }
  }

  // ─── 7. كشف DevTools بـ console timing ────────────────────────────────
  // console.log على object بـ getter — لما DevTools مفتوحة بتقرأ الـ getter
  var _consoleCheck = new Image();
  Object.defineProperty(_consoleCheck, "id", {
    get: function () {
      if (_isAdmin) return;
      _dtOpen = true;
      _showOverlay();
    }
  });
  // بنطبعه كل 4 ثواني — لو DevTools مش مفتوحة الـ getter مش بيتنادى
  setInterval(function () {
    _dtOpen = false;
    console.log("%c", _consoleCheck);
    console.clear();
  }, 4000);

  // ─── 8. تحذير في الكونسول ─────────────────────────────────────────────
  console.log(
    "%c⚠ WARNING",
    "color:#ff4d4d;font-size:32px;font-weight:900;text-shadow:2px 2px #000"
  );
  console.log(
    "%cThis is a protected application. Any attempt to copy, modify, or reverse-engineer " +
    "the code is prohibited and monitored.",
    "color:#94a3b8;font-size:14px"
  );

  // ─── 9. منع حفظ الصفحة بـ Ctrl+S ─────────────────────────────────────
  window.addEventListener("beforeunload", function () {
    // مش بنمنع الخروج — بس بنمسح أي بيانات مؤقتة
  });

  // ─── 10. حماية الـ source من View Source ────────────────────────────────
  // لو حد فتح view-source: — الصفحة بتبان فاضية لأن الكود بيتحمل dynamic
  // (ده بيتعمل من السيرفر — شوف الـ middleware في main.py)

  // ─── 11. منع Console eval ─────────────────────────────────────────────
  // إعادة تعريف بعض الدوال الحساسة
  try {
    Object.defineProperty(window, "eval", {
      get: function () { return function () { return null; }; },
      set: function () {},
      configurable: false
    });
  } catch (ex) { /* بعض المتصفحات بترفض */ }

  // ─── 12. مراقبة حجم الصفحة بدقة أعلى (للـ DevTools المحمولة/منفصلة) ──
  var _lastW = window.outerWidth, _lastH = window.outerHeight;
  window.addEventListener("resize", function () {
    var dW = Math.abs(window.outerWidth - window.innerWidth);
    var dH = Math.abs(window.outerHeight - window.innerHeight);
    if (dW > 200 || dH > 200) {
      _showOverlay();
      _dtOpen = true;
    }
    _lastW = window.outerWidth;
    _lastH = window.outerHeight;
  });

  // ─── 13. منع الطباعة (Print) — بيكشف الكود كاملاً ──────────────────
  var _printStyle = document.createElement("style");
  _printStyle.textContent = "@media print { body { display: none !important; } " +
    "body::after { content: 'Printing is disabled for security reasons.'; " +
    "display: block; text-align: center; padding: 40px; font-size: 20px; color: #666; } }";
  (document.head || document.documentElement).appendChild(_printStyle);

})();
