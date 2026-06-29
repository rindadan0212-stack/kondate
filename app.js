"use strict";
const WD = ["月", "火", "水", "木", "金", "土", "日"];
const CUISINE = { "和": "和食", "洋": "洋食", "中": "中華", "エスニック": "エスニック" };
const $ = (s, r = document) => r.querySelector(s);
const el = (t, c, txt) => { const e = document.createElement(t); if (c) e.className = c; if (txt != null) e.textContent = txt; return e; };
const LOCK = '<svg class="mini__lock" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"><rect x="4" y="11" width="16" height="9" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>';

let STATE = null;
let invDraft = [];        // 条件パネルの在庫作業コピー
let busy = false;
let openEditorDay = null; // 日別エディタを開いている曜日index

async function api(path, body) {
  const opt = body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {};
  const r = await fetch(path, opt);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.statusText);
  return r.json();
}

let toastTimer;
function toast(msg, warn) {
  const t = $("#toast");
  t.textContent = msg; t.classList.toggle("toast--warn", !!warn); t.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.hidden = true; }, 3200);
}

async function command(payload) {
  if (busy) return;
  busy = true; $("#days").style.opacity = ".5";
  document.querySelectorAll(".tool,.mini,.primary").forEach(b => b.disabled = true);
  try { STATE = await api("/api/command", payload); render(); }
  catch (e) { toast("エラー: " + e.message, true); }
  finally { busy = false; $("#days").style.opacity = ""; document.querySelectorAll(".tool,.mini,.primary").forEach(b => b.disabled = false); }
}

/* ---------------- 描画 ---------------- */
function render() {
  const s = STATE, m = s.metrics;
  $("#heroMeta").textContent = `夕食${s.profile.dinner}人 ・ 弁当${s.profile.bento}人 ・ ${s.week.month}月`;

  const chips = $("#chips"); chips.replaceChildren();
  if (m.error) { chips.append(el("span", "chip chip--warn", m.error)); }
  else {
    chips.append(el("span", "chip chip--accent", `和食 ${m.washoku}%`));
    if (m.inventory_unused && m.inventory_unused.length)
      chips.append(el("span", "chip", `未使用: ${m.inventory_unused.join("・")}`));
    if (m.violations.length) chips.append(el("span", "chip chip--warn", "制約注意"));
  }
  renderDays(); renderShopping(); syncPanel(); syncTools();
  hasPlan = !!(STATE.days && STATE.days.length && !m.error);
  buildWizSteps();
}

// 材料（分量つき）＋手順の詳細ブロック。献立カードとカレンダーで共用。
function renderRecipeDetail(r) {
  const det = el("div", "recipe-detail");
  const portions = Math.round(r.servings * (r.mult || 1));
  det.append(el("div", "recipe-detail__head", `${portions}人分 ・ ${r.cook}分`));
  const mainIngs = r.ings.filter(i => !i.seasoning).map(i => `${i.name} ${i.amount}`).join("、");
  const seas = r.ings.filter(i => i.seasoning).map(i => `${i.name} ${i.amount}`).join("、");
  det.append(el("div", null, "材料: " + mainIngs));
  if (seas) det.append(el("div", "recipe-detail__seas", "調味料: " + seas));
  if (r.steps && r.steps.length) {
    const ol = el("ol", "recipe-detail__steps");
    r.steps.forEach(st => ol.append(el("li", null, st)));
    det.append(ol);
  }
  return det;
}

// 日別エディタ（ジャンル変更・種類変更・別の料理に）。すべて「その日だけ」変わる。
const PROTEIN_PICK = [["chicken", "鶏"], ["pork", "豚"], ["beef", "牛"], ["fish", "魚"]];
const CUISINE_PICK = [["和", "和食"], ["洋", "洋食"], ["中", "中華"], ["エスニック", "エスニック"]];
function currentProteinGroup(main) {
  const p = main && main.protein;
  if (p === "chicken" || p === "pork" || p === "beef") return p;
  if (p === "fish" || p === "seafood") return "fish";
  return null;
}
function editChip(label, onClick, on) {
  const b = el("button", "echip" + (on ? " echip--on" : ""), label);
  b.addEventListener("click", onClick);
  return b;
}
function buildDayEditor(d) {
  const ed = el("div", "day__edit"); ed.hidden = true;
  // ジャンルで選ぶ（和/洋/中/エスニック）
  const crow = el("div", "edit-row");
  crow.append(el("span", "edit-row__label", "ジャンル"));
  const curC = d.main ? d.main.cuisine : null;
  CUISINE_PICK.forEach(([c, lb]) =>
    crow.append(editChip(lb, () => command({ cmd: "cuisine", day: d.idx, cuisine: c }), curC === c)));
  ed.append(crow);
  // 肉/魚の種類で選ぶ
  const prow = el("div", "edit-row");
  prow.append(el("span", "edit-row__label", "種類"));
  const curG = currentProteinGroup(d.main);
  PROTEIN_PICK.forEach(([g, lb]) =>
    prow.append(editChip(lb, () => command({ cmd: "protein", day: d.idx, group: g }), curG === g)));
  ed.append(prow);
  // 別の料理に／おまかせに戻す
  const arow = el("div", "edit-row");
  arow.append(editChip("別の料理に", () => command({ cmd: "swap", day: d.idx })));
  if (d.pinned) arow.append(editChip("おまかせに戻す", () => command({ cmd: "unpin", day: d.idx })));
  ed.append(arow);
  return ed;
}

function renderDays() {
  const wrap = $("#days"); wrap.replaceChildren();
  for (const d of STATE.days) {
    const row = el("div", "day");
    const date = el("div", "day__date");
    date.append(el("div", "day__dow", d.weekday)); date.append(el("div", "day__md", d.date));
    row.append(date);

    const main = el("div", "day__main");
    const dish = el("button", "day__dish"); dish.textContent = d.main ? d.main.name : "—";
    dish.style.cssText = "background:none;border:none;text-align:left;padding:0;color:inherit;font:inherit;cursor:pointer;";
    main.append(dish);
    if (d.main) {
      const meta = el("div", "day__sub day__meta",
        `${CUISINE[d.main.cuisine] || d.main.cuisine} ・ ${d.main.cook}分`);
      if (d.pinned) meta.append(el("span", "day__chosen", "選択済"));
      main.append(meta);
    }
    if (d.side) main.append(el("div", "day__sub", "副菜: " + d.side.name));
    if (d.soup) main.append(el("div", "day__sub", "汁物: " + d.soup.name));
    if (d.main) {
      // 開かなくても食材がざっくり見える（主材料の名前のみ）
      const names = d.main.ings.filter(i => !i.seasoning).map(i => i.name);
      if (names.length) main.append(el("div", "day__ings", names.join("・")));
      // 料理名タップで詳しい分量＋手順
      const det = renderRecipeDetail(d.main); det.hidden = true; det.classList.add("day__detail");
      main.append(det);
      dish.addEventListener("click", () => { det.hidden = !det.hidden; });
    }
    row.append(main);

    const acts = el("div", "day__acts");
    const editBtn = el("button", "mini" + (openEditorDay === d.idx ? " mini--on" : ""), "変更");
    acts.append(editBtn); row.append(acts);

    const editor = buildDayEditor(d);
    if (openEditorDay === d.idx) editor.hidden = false;
    editBtn.addEventListener("click", () => {
      openEditorDay = (openEditorDay === d.idx) ? null : d.idx;
      editor.hidden = openEditorDay !== d.idx;
      editBtn.classList.toggle("mini--on", openEditorDay === d.idx);
    });
    row.append(editor);
    wrap.append(row);
  }
}

function renderShopping() {
  const wrap = $("#shopping"); wrap.replaceChildren();
  const checks = JSON.parse(localStorage.getItem("kondate_checks") || "{}");
  for (const sec of STATE.shopping) {
    wrap.append(el("div", "shop__sec", sec.section));
    for (const it of sec.items) {
      const label = el("label", "shop__item" + (checks[it.name] ? " shop__item--done" : ""));
      const cb = el("input"); cb.type = "checkbox"; cb.checked = !!checks[it.name];
      cb.addEventListener("change", () => {
        const c = JSON.parse(localStorage.getItem("kondate_checks") || "{}");
        if (cb.checked) c[it.name] = 1; else delete c[it.name];
        localStorage.setItem("kondate_checks", JSON.stringify(c));
        label.classList.toggle("shop__item--done", cb.checked);
      });
      label.append(cb);
      label.append(el("span", "shop__name", it.name));
      label.append(el("span", "shop__qty", it.qty));
      if (it.reused) label.append(el("span", "shop__reuse", `${it.dishes.length}品`));
      wrap.append(label);
    }
  }
  // その他（手入力で買うものを追加）
  const extra = getExtra();
  wrap.append(el("div", "shop__sec", "その他（手入力）"));
  for (const name of extra) {
    const label = el("label", "shop__item" + (checks[name] ? " shop__item--done" : ""));
    const cb = el("input"); cb.type = "checkbox"; cb.checked = !!checks[name];
    cb.addEventListener("change", () => {
      toggleCheck(name, cb.checked);
      label.classList.toggle("shop__item--done", cb.checked);
    });
    label.append(cb, el("span", "shop__name", name));
    const rm = el("button", "shop__rm", "×"); rm.setAttribute("aria-label", "削除");
    rm.addEventListener("click", e => { e.preventDefault(); removeExtra(name); renderShopping(); });
    label.append(rm);
    wrap.append(label);
  }
  const add = el("div", "shop__add");
  const inp = el("input"); inp.type = "text"; inp.placeholder = "買うものを追加（例: 牛乳）";
  const btn = el("button", "ghost", "追加");
  const doAdd = () => { const v = inp.value.trim(); if (v) { addExtra(v); renderShopping(); } };
  btn.addEventListener("click", doAdd);
  inp.addEventListener("keydown", e => { if (e.key === "Enter") doAdd(); });
  add.append(inp, btn); wrap.append(add);

  wrap.append(el("p", "shop__note", `常備品として除外: ${STATE.shopping_excluded}件`));
}

function getExtra() { return JSON.parse(localStorage.getItem("kondate_extra") || "[]"); }
function setExtra(a) { localStorage.setItem("kondate_extra", JSON.stringify(a)); }
function addExtra(name) { const a = getExtra(); if (!a.includes(name)) a.push(name); setExtra(a); }
function removeExtra(name) { setExtra(getExtra().filter(x => x !== name)); }
function toggleCheck(name, on) {
  const c = JSON.parse(localStorage.getItem("kondate_checks") || "{}");
  if (on) c[name] = 1; else delete c[name];
  localStorage.setItem("kondate_checks", JSON.stringify(c));
}

/* ---------------- 条件パネル ---------------- */
// 弁当ピッカーの表示ラベル（source基準: 月〜日の夕食を翌朝の弁当に。日曜→翌週月曜）
const BENTO_LABELS = ["火", "水", "木", "金", "土", "日", "翌月"];
function buildDayPick(id, days, onToggle, labels) {
  const L = labels || WD;
  const wrap = $(id); wrap.replaceChildren();
  for (let i = 0; i < 7; i++) {
    const c = el("div", "dcell" + (days[i] ? " dcell--on" : ""), L[i]);
    c.setAttribute("role", "button"); c.tabIndex = 0;
    const flip = () => { days[i] = !days[i]; c.classList.toggle("dcell--on", days[i]); onToggle(); };
    c.addEventListener("click", flip);
    c.addEventListener("keydown", e => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); flip(); } });
    wrap.append(c);
  }
}
let dinnerDraft = [], bentoDraft = [];
function syncPanel() {
  dinnerDraft = STATE.week.dinner_days.slice();
  bentoDraft = STATE.week.bento_days.slice();
  buildDayPick("#pickDinner", dinnerDraft, () => { });
  buildDayPick("#pickBento", bentoDraft, () => { }, BENTO_LABELS);
  $("#month").value = STATE.week.month;
  $("#catalogList").replaceChildren(...(STATE.catalog || []).map(c => {
    const o = el("option"); o.value = c.name; return o;
  }));
  invDraft = STATE.week.inventory.map(x => ({ key: x.key, name: x.name, qty: x.qty, unit: x.unit }));
  renderInv();
  $("#optSide").checked = STATE.mods.include_side;
  $("#optSoup").checked = STATE.mods.include_soup;
  $("#optWa").checked = STATE.mods.washoku_target != null;
}
function catByName(name) { return (STATE.catalog || []).find(c => c.name === name); }
function updateInvUnit() {
  const c = catByName($("#invName").value.trim());
  $("#invUnit").textContent = c ? c.unit : "";
}
function renderInv() {
  const wrap = $("#inv"); wrap.replaceChildren();
  invDraft.forEach((it, i) => {
    const chip = el("span", "invchip", `${it.name} ${String(it.qty)}${it.unit || ""}`);
    const x = el("button", null, "×"); x.setAttribute("aria-label", "削除");
    x.addEventListener("click", () => { invDraft.splice(i, 1); renderInv(); });
    chip.append(x); wrap.append(chip);
  });
}
function addInv() {
  const c = catByName($("#invName").value.trim());
  if (!c) { toast("一覧から食材を選んでください"); return; }
  let qty = parseFloat($("#invQty").value);
  if (isNaN(qty) || qty <= 0) qty = 1;
  if (!invDraft.some(x => x.key === c.key)) invDraft.push({ key: c.key, name: c.name, qty, unit: c.unit });
  $("#invName").value = ""; $("#invQty").value = ""; $("#invUnit").textContent = "";
  $("#invName").focus(); renderInv();
}
/* ---------------- ウィザード（画面遷移） ---------------- */
const WIZ = ["曜日", "食材", "構成", "献立", "買い物"];
let curStep = 0, hasPlan = false;
function goStep(to, dir) {
  to = Math.max(0, Math.min(WIZ.length - 1, to));
  if (to >= 3 && !hasPlan) { toast("先に献立を作ってください"); return; }
  document.querySelectorAll(".screen").forEach(s => { s.hidden = (+s.dataset.step !== to); });
  const cur = document.querySelector(`.screen[data-step="${to}"]`);
  cur.classList.remove("screen--fwd", "screen--back");
  void cur.offsetWidth;                       // アニメ再生のためreflow
  cur.classList.add(dir === "back" ? "screen--back" : "screen--fwd");
  curStep = to; buildWizSteps();
  window.scrollTo(0, 0);
}
function buildWizSteps() {
  const wrap = $("#wizSteps"); if (!wrap) return; wrap.replaceChildren();
  WIZ.forEach((label, i) => {
    const locked = i >= 3 && !hasPlan;
    const b = el("button", "wstep"
      + (i === curStep ? " wstep--on" : "")
      + (i < curStep ? " wstep--done" : "")
      + (locked ? " wstep--lock" : ""));
    b.append(el("span", "wstep__no", i < curStep ? "✓" : String(i + 1)));
    b.append(el("span", "wstep__lb", label));
    if (locked) b.disabled = true;
    else b.addEventListener("click", () => goStep(i, i < curStep ? "back" : "fwd"));
    wrap.append(b);
  });
}

function syncTools() {
  const pd = STATE.mods.protein_delta || {};
  $('[data-cmd="more"][data-group="fish"]').classList.toggle("tool--on", (pd.fish || 0) > 0);
  $('[data-cmd="less"][data-group="meat"]').classList.toggle("tool--on", (pd.chicken || 0) < 0 || (pd.pork || 0) < 0);
  $('[data-cmd="time"]').classList.toggle("tool--on", STATE.mods.time_override != null);
}

/* ---------------- 起動・イベント ---------------- */
function bind() {
  document.querySelectorAll("[data-go]").forEach(b =>
    b.addEventListener("click", () => goStep(+b.dataset.go, b.dataset.dir)));
  $("#invAdd").addEventListener("click", addInv);
  $("#invName").addEventListener("input", updateInvUnit);
  $("#invName").addEventListener("keydown", e => { if (e.key === "Enter") addInv(); });
  $("#invQty").addEventListener("keydown", e => { if (e.key === "Enter") addInv(); });
  $("#btnApply").addEventListener("click", async () => {
    if (busy) return;
    // ドラフトを先に確定（configの再描画でinvDraft等が旧値に戻る前に取り込む）
    const weekPayload = {
      dinner: dinnerDraft.slice(), bento: bentoDraft.slice(),
      month: parseInt($("#month").value) || 6,
      inventory: invDraft.map(it => ({ key: it.key, qty: it.qty })),
    };
    const wt = $("#optWa").checked ? 0.8 : null;
    const cfg = { cmd: "config", include_side: $("#optSide").checked,
                  include_soup: $("#optSoup").checked, washoku_target: wt };
    try {
      busy = true;
      await api("/api/command", cfg);          // 構成を反映（renderはしない）
      STATE = await api("/api/week", weekPayload);
      render(); hasPlan = true; goStep(3, "fwd");
      toast("献立を作りました");
    } catch (e) { toast("エラー: " + e.message, true); } finally { busy = false; }
  });
  document.querySelectorAll(".tool").forEach(b => b.addEventListener("click", () => {
    const cmd = b.dataset.cmd;
    if (cmd === "reset" && !confirm("手直しを全部捨てて、素の提案に戻します。よろしいですか？")) return;
    const p = { cmd };
    if (b.dataset.group) p.group = b.dataset.group;
    if (b.dataset.min) p.minutes = parseInt(b.dataset.min);
    command(p);
  }));

  document.querySelectorAll(".tab-btn").forEach(b =>
    b.addEventListener("click", () => showView(b.dataset.view)));
  $("#btnRecord").addEventListener("click", recordWeek);
  $("#calPrev").addEventListener("click", () => shiftMonth(-1));
  $("#calNext").addEventListener("click", () => shiftMonth(1));
  $("#calDow").replaceChildren(...["月", "火", "水", "木", "金", "土", "日"].map(w => el("div", "cal-dowcell", w)));
}

/* ---------------- タブ・カレンダー ---------------- */
let calMonth = null;
function showView(v) {
  document.querySelectorAll(".tab-btn").forEach(b => b.classList.toggle("tab-btn--on", b.dataset.view === v));
  $("#viewPlan").hidden = v !== "plan";
  $("#viewCal").hidden = v !== "cal";
  if (v === "cal") { if (!calMonth) calMonth = ymNow(); renderCalendar(); }
}
function ymNow() { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`; }
function shiftMonth(delta) {
  let [y, m] = calMonth.split("-").map(Number);
  m += delta; if (m < 1) { m = 12; y--; } if (m > 12) { m = 1; y++; }
  calMonth = `${y}-${String(m).padStart(2, "0")}`;
  renderCalendar();
}
async function recordWeek() {
  try {
    const r = await api("/api/record", { _: 1 });
    toast(`${r.recorded}日分をカレンダーに記録しました`);
    if (!calMonth) calMonth = ymNow();
    showView("cal");
  } catch (e) { toast("記録に失敗: " + e.message, true); }
}
async function renderCalendar() {
  let data;
  try { data = await fetch(`/api/calendar?month=${calMonth}`).then(r => r.json()); }
  catch (e) { toast("カレンダー取得失敗", true); return; }
  const [y, m] = calMonth.split("-").map(Number);
  $("#calTitle").textContent = `${y}年${m}月`;
  const first = new Date(y, m - 1, 1);
  const lead = (first.getDay() + 6) % 7;            // 月曜始まりの先頭空白
  const days = new Date(y, m, 0).getDate();
  const grid = $("#calGrid"); grid.replaceChildren();
  for (let i = 0; i < lead; i++) grid.append(el("div", "cal-cell cal-cell--empty"));
  for (let d = 1; d <= days; d++) {
    const iso = `${calMonth}-${String(d).padStart(2, "0")}`;
    const ent = data.entries[iso];
    const cell = el("div", "cal-cell" + (iso === data.today ? " cal-cell--today" : "") + (ent ? " cal-cell--has" : ""));
    cell.append(el("div", "cal-num", String(d)));
    if (ent) cell.append(el("div", "cal-meal", ent.main));
    cell.addEventListener("click", () => showCalDetail(iso, ent));
    grid.append(cell);
  }
  $("#calDetail").replaceChildren();
}
async function showCalDetail(iso, ent) {
  const det = $("#calDetail"); det.replaceChildren();
  if (!ent) { det.append(el("p", "cal-detail__empty", `${iso} は記録なし`)); return; }
  det.append(el("div", "cal-detail__date", iso));
  det.append(el("div", "cal-detail__main", ent.main));
  const sub = [];
  if (ent.side) sub.push("副菜: " + ent.side);
  if (ent.soup) sub.push("汁: " + ent.soup);
  if (sub.length) det.append(el("div", "cal-detail__sub", sub.join(" ／ ")));
  // 記録から主菜のレシピ（材料＋手順）を表示
  if (ent.main_id) {
    try {
      const r = await api(`/api/recipe/${ent.main_id}`);
      det.append(renderRecipeDetail(r));
    } catch (e) { /* 旧データ等でidが無い/見つからない場合は名前のみ */ }
  }
}

(async function init() {
  bind();
  try { STATE = await api("/api/state"); render(); }
  catch (e) { toast("読み込み失敗: " + e.message, true); }
  goStep(0, "fwd");
})();
