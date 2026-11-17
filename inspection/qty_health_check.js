/* تحقق من اختيار QTY: لازم الصحة الكاملة تتقدّم — بيستورد الدوال الحقيقية من app.js */
const fs = require("fs");
const path = require("path");

const src = fs.readFileSync(path.join(__dirname, "..", "frontend", "app.js"), "utf8");
const rows = JSON.parse(fs.readFileSync(path.join(__dirname, "_toro_rows.json"), "utf8"));
const want = Number(process.argv[2] || 10);

function grab(name) {
  const start = src.indexOf(`function ${name}(`);
  if (start < 0) throw new Error("مش لاقي الدالة " + name);
  let depth = 0;
  for (let j = src.indexOf("{", start); j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}" && --depth === 0) return src.slice(start, j + 1);
  }
  throw new Error("قوس مقفول مش موجود: " + name);
}

const code = [src.match(/const FIREARM_TYPES = [\s\S]*?;/)[0],
  grab("isWeapon"), grab("durabilityInfo"), grab("durabilityVisible"),
  grab("healthRank"), grab("pickStacks")].join("\n");

const api = new Function(code + "\nreturn { pick: pickStacks, info: durabilityInfo, rank: healthRank };")();
const pick = api.pick(rows, want);
if (!pick) { console.log("ولا ستاك داخل الحساب"); process.exit(1); }

const buckets = {};
for (const r of pick.items) {
  const info = api.info(r);
  const k = `${Math.round(info.current)}/${info.max}`;
  buckets[k] = (buckets[k] || 0) + 1;
}
console.log("المطلوب %d | المختار %d قطعة | المجموع %d | مظبوط %s",
  want, pick.items.length, pick.total, pick.exact);
console.log("توزيع الصحة في المختار:", JSON.stringify(buckets));
console.log("أقل صحة في المختار: %s | أعلى صحة متاحة: %s",
  Math.min(...pick.items.map(api.rank)).toFixed(6), Math.max(...rows.map(api.rank)).toFixed(6));
