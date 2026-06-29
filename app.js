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
let likedSet = new Set();
function render() {
  const s = STATE, m = s.metrics;
  likedSet = new Set(((s.prefs && s.prefs.liked) || []).map(x => x.id));
  $("#heroMeta").textContent = `夕食${s.profile.dinner}人 ・ 弁当${s.profile.bento}人 ・ ${s.week.month}月`;

  const chips = $("#chips"); chips.replaceChildren();
  if (m.error) { chips.append(el("span", "chip chip--warn", m.error)); }
  else {
    chips.append(el("span", "chip chip--accent", `和食 ${m.washoku}%`));
    if (m.inventory_unused && m.inventory_unused.length)
      chips.append(el("span", "chip", `未使用: ${m.inventory_unused.join("・")}`));
  }
  renderDays(); renderShopping(); syncPanel(); renderPrefs();
  hasPlan = !!(STATE.days && STATE.days.length && !m.error);
  buildWizSteps();
}

/* ---------------- 好み（いいね/バッド一覧） ---------------- */
function renderPrefs() {
  const p = (STATE && STATE.prefs) || { liked: [], banned: [] };
  const lw = $("#likedList"); if (lw) {
    lw.replaceChildren();
    if (!p.liked.length) lw.append(el("p", "pref__empty", "まだありません。料理カードの ♥ でいいねできます。"));
    p.liked.forEach(r => lw.append(prefItem(r, "like")));
  }
  const bw = $("#bannedList"); if (bw) {
    bw.replaceChildren();
    if (!p.banned.length) bw.append(el("p", "pref__empty", "まだありません。料理カードの ✕ で今後の提案から外せます。"));
    p.banned.forEach(r => bw.append(prefItem(r, "ban")));
  }
}
function prefItem(r, kind) {
  const row = el("div", "pref-item");
  const info = el("div", "pref-item__info");
  info.append(el("div", "pref-item__name", r.name));
  info.append(el("div", "pref-item__meta", `${CUISINE[r.cuisine] || r.cuisine} ・ ${r.cook}分`));
  row.append(info);
  if (kind === "like") {
    const x = el("button", "pref-item__btn", "解除");
    x.addEventListener("click", () => command({ cmd: "unlike", id: r.id }));
    row.append(x);
  } else {
    const x = el("button", "pref-item__btn pref-item__btn--accent", "プールに戻す");
    x.addEventListener("click", () => command({ cmd: "unban", id: r.id }));
    row.append(x);
  }
  return row;
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

// 日別エディタ：ジャンル/種類で「絞り込み」→ 一覧から選ぶ。すべて「その日だけ」変わる。
const PROTEIN_PICK = [["chicken", "鶏"], ["pork", "豚"], ["beef", "牛"], ["fish", "魚"], ["egg", "卵"], ["tofu", "豆腐"]];
const CUISINE_PICK = [["和", "和食"], ["洋", "洋食"], ["中", "中華"], ["エスニック", "エスニック"]];
let filterC = null, filterP = null, editorFilterDay = null, editorMode = "choice";   // 開いているエディタの状態
function currentProteinGroup(main) {
  const p = main && main.protein;
  if (p === "chicken" || p === "pork" || p === "beef") return p;
  if (p === "fish" || p === "seafood") return "fish";
  if (p === "egg") return "egg";
  if (p === "tofu" || p === "soy") return "tofu";
  return null;
}
function editChip(label, onClick, on) {
  const b = el("button", "echip" + (on ? " echip--on" : ""), label);
  b.addEventListener("click", onClick);
  return b;
}
function buildDayEditor(d) {
  const ed = el("div", "day__edit");
  ed.hidden = openEditorDay !== d.idx;
  if (openEditorDay === d.idx) renderEditorBody(d, ed);   // 開いている日だけ描画
  return ed;
}
function choiceBtn(label, sub, onClick) {
  const b = el("button", "edit-choice__btn");
  b.append(el("span", "edit-choice__t", label));
  if (sub) b.append(el("span", "edit-choice__s", sub));
  b.addEventListener("click", onClick);
  return b;
}
function renderEditorBody(d, ed) {
  if (editorFilterDay !== d.idx) {     // 別の日を開いたら初期化（まず2択から）
    filterC = d.main ? d.main.cuisine : null;
    filterP = currentProteinGroup(d.main);
    editorMode = "choice";
    editorFilterDay = d.idx;
  }
  ed.replaceChildren();
  if (editorMode === "choice") {       // ① どう変えるかを選ぶ
    const row = el("div", "edit-choice");
    row.append(choiceBtn("おまかせで別の案", "自動で別の料理に", () => command({ cmd: "swap", day: d.idx })));
    row.append(choiceBtn("一覧から選ぶ", "ジャンル・種類で探す", () => { editorMode = "list"; renderEditorBody(d, ed); }));
    ed.append(row);
    if (d.pinned) {
      const r2 = el("div", "edit-row edit-row--end");
      r2.append(editChip("自動に戻す", () => command({ cmd: "unpin", day: d.idx })));
      ed.append(r2);
    }
    return;
  }
  // ② 一覧から選ぶ：ジャンル/種類で絞り込み
  const back = el("button", "edit-back", "‹ 選び方に戻る");
  back.addEventListener("click", () => { editorMode = "choice"; renderEditorBody(d, ed); });
  ed.append(back);
  const crow = el("div", "edit-row");
  crow.append(el("span", "edit-row__label", "ジャンル"));
  const cchips = el("div", "edit-row__chips");
  CUISINE_PICK.forEach(([c, lb]) =>
    cchips.append(editChip(lb, () => { filterC = (filterC === c ? null : c); renderEditorBody(d, ed); }, filterC === c)));
  crow.append(cchips); ed.append(crow);
  const prow = el("div", "edit-row");
  prow.append(el("span", "edit-row__label", "種類"));
  const pchips = el("div", "edit-row__chips");
  PROTEIN_PICK.forEach(([g, lb]) =>
    pchips.append(editChip(lb, () => { filterP = (filterP === g ? null : g); renderEditorBody(d, ed); }, filterP === g)));
  prow.append(pchips); ed.append(prow);
  const list = el("div", "pick-list");
  list.append(el("div", "pick-list__msg", "探しています…"));
  ed.append(list);
  refreshCandidates(d.idx, list, d.main ? d.main.id : null);
}
async function refreshCandidates(day, listEl, currentId) {
  let cands = [];
  try {
    const r = await api("/api/candidates", { day, cuisine: filterC, protein: filterP });
    cands = r.candidates || [];
  } catch (e) { listEl.replaceChildren(el("div", "pick-list__msg", "取得できませんでした")); return; }
  if (editorFilterDay !== day) return;     // 表示中の日が変わっていたら破棄
  listEl.replaceChildren();
  listEl.append(el("div", "pick-list__head", `合う料理 ${cands.length}品（タップで決定）`));
  if (!cands.length) {
    listEl.append(el("div", "pick-list__msg", "条件に合う料理がありません。フィルタを外してください。"));
    return;
  }
  const box = el("div", "pick-list__box");
  cands.forEach(c => {
    const it = el("button", "pick-item" + (c.id === currentId ? " pick-item--on" : ""));
    it.append(el("span", "pick-item__name", c.name));
    it.append(el("span", "pick-item__meta", `${CUISINE[c.cuisine] || c.cuisine}・${c.cook}分`));
    it.addEventListener("click", () => command({ cmd: "pick", day, id: c.id }));
    box.append(it);
  });
  listEl.append(box);
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
      if (d.main.bento === false) meta.append(el("span", "day__nobento", "翌日の弁当に不向き"));
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
    if (d.main) {
      const react = el("div", "day__react");
      const liked = likedSet.has(d.main.id);
      const likeBtn = el("button", "react" + (liked ? " react--liked" : ""), "♥");
      likeBtn.setAttribute("aria-label", liked ? "いいね済み" : "いいね");
      likeBtn.addEventListener("click", () => command({ cmd: liked ? "unlike" : "like", id: d.main.id }));
      const banBtn = el("button", "react react--ban", "✕");
      banBtn.setAttribute("aria-label", "バッド（今後出さない）");
      banBtn.addEventListener("click", () => {
        if (confirm(`「${d.main.name}」を今後の提案から外します。よろしいですか？`)) command({ cmd: "ban", id: d.main.id });
      });
      react.append(likeBtn, banBtn);
      acts.append(react);
    }

    const editor = buildDayEditor(d);
    editBtn.addEventListener("click", () => {
      if (openEditorDay === d.idx) { openEditorDay = null; editor.hidden = true; }
      else { openEditorDay = d.idx; renderEditorBody(d, editor); editor.hidden = false; }
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
  const resetBtn = $(".reset-quiet");
  if (resetBtn) resetBtn.addEventListener("click", () => {
    if (confirm("献立を最初から（全部おまかせ）に戻します。よろしいですか？")) command({ cmd: "reset" });
  });

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
  $("#viewPref").hidden = v !== "pref";
  if (v === "cal") { if (!calMonth) calMonth = ymNow(); renderCalendar(); }
  if (v === "pref") renderPrefs();
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
