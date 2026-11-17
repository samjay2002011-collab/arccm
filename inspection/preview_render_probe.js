/* Smoke test لقوالب المعاينة من غير متصفح: بنشيل الدوال من app.js ونشغّلها
   على JSON حقيقي طالع من /api/loadouts/…/preview.
   node inspection/preview_render_probe.js <preview.json>
*/
const fs = require("fs");
const vm = require("vm");

const src = fs.readFileSync(__dirname + "/../frontend/app.js", "utf8");
const names = ["pvLive", "pvMode", "pvRoute", "pvCross", "pvCosts", "pvJobs",
  "pvBarHTML", "pvTopupRows", "pvExtraRows", "pvFillRow", "pvShortHint", "pvHint"];

function grab(name) {
  const at = src.indexOf("function " + name + "(");
  if (at < 0) throw new Error("missing " + name);
  let i = src.indexOf("{", at), depth = 0, j = i;
  for (; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}") { depth--; if (!depth) break; }
  }
  return src.slice(at, j + 1);
}

const ctx = {
  state: { loPreview: null, loFillMode: "craft", account: "G22", loadoutSel: "68" },
  num: (n) => String(n), esc: (s) => String(s == null ? "" : s).replace(/[&<>"]/g, ""),
  asset: (f) => "/assets/" + f, console,
};
vm.createContext(ctx);
vm.runInContext(names.map(grab).join("\n"), ctx);

const p = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
ctx.state.loPreview = p;

for (const expr of ["pvBarHTML()", "pvTopupRows(pvLive())", "pvExtraRows(pvLive())",
                    "pvJobs().length"]) {
  const out = vm.runInContext(expr, ctx);
  console.log("\n--- " + expr + " ---\n" + (typeof out === "string" ? out : JSON.stringify(out)));
}
