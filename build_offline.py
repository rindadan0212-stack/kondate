"""オフライン版(Pyodide)用の Python バンドルを生成する。

engine(models/ingredient_map/shopping/planner/session) とサーバの純ロジック(Core)を
1ファイル `web/kondate_bundle.py` に束ねる。Flask不要・ファイルI/O不要にして、
ブラウザの Pyodide 上でそのまま動かす（PC版と同一エンジン＝献立の質を保証）。

使い方: python web/build_offline.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# 束ねる順（依存順）。相互import/__future__ は除去して連結する。
SOURCES = [
    ROOT / "engine" / "models.py",
    ROOT / "build" / "ingredient_map.py",
    ROOT / "engine" / "shopping.py",
    ROOT / "engine" / "planner.py",
    ROOT / "engine" / "session.py",
]

_STRIP = re.compile(r"^\s*from\s+(\.|engine\.|ingredient_map)")
_FUTURE = re.compile(r"^\s*from\s+__future__")


def strip_source(text: str) -> str:
    out = []
    skip_paren = False
    for line in text.splitlines():
        if skip_paren:                       # 複数行import (...) の継続を飛ばす
            if ")" in line:
                skip_paren = False
            continue
        if _FUTURE.match(line) or _STRIP.match(line):
            if "(" in line and ")" not in line:
                skip_paren = True
            continue
        out.append(line)
    return "\n".join(out)


# ---- ブラウザ用 Core（server.py の純ロジックを移植：Flask/ファイルI/O無し） ----
GLUE = r'''

# ================= ブラウザ用グルー（server.py 相当・Flask無し） =================
from datetime import date, timedelta

_UNIT_DISP = {"tbsp": "大さじ", "tsp": "小さじ"}
_BAD_COUNT_UNITS = {"tbsp", "tsp", "ml", "cc"}


def _fmt_qty(qty, unit):
    if unit in ("適量", "少々", "少量", "少し", "つまみ", "ひとつまみ", "お好み", "お好みで", "適宜"):
        return "適量"
    if unit in ("tbsp", "tsp"):
        r = round(qty * 2) / 2
        s = str(int(r)) if abs(r - int(r)) < 1e-9 else f"{r:g}"
        return f"{_UNIT_DISP[unit]}{s}"
    if unit in COUNTABLE_UNITS:
        r = round(qty * 2) / 2
        if r == 0 and qty > 0:
            r = 0.5
        s = str(int(r)) if abs(r - int(r)) < 1e-9 else f"{r:g}"
        return f"{s}{unit}"
    return f"{int(__import__('math').ceil(qty / 5.0) * 5)}{unit}"


def _next_monday():
    today = date.today()
    return today - timedelta(days=today.weekday()) + timedelta(days=7)


def _week_dates():
    mon = _next_monday()
    return [(mon + timedelta(days=i)).strftime("%m/%d") for i in range(7)]


def _parse_days(spec):
    if isinstance(spec, list) and len(spec) == 7 and all(isinstance(x, bool) for x in spec):
        return spec
    if isinstance(spec, list):
        return [WEEKDAYS[i] in spec for i in range(7)]
    s = str(spec).strip()
    if s in ("all", "毎日"):
        return [True] * 7
    if s in ("weekday", "平日"):
        return [i in (0, 1, 2, 3, 4) for i in range(7)]
    if s in ("none", "なし", ""):
        return [False] * 7
    out = [False] * 7
    wd = {w: i for i, w in enumerate(WEEKDAYS)}
    if "-" in s and all(p in wd for p in s.split("-")):
        a, b = s.split("-")
        for i in range(wd[a], wd[b] + 1):
            out[i] = True
        return out
    for ch in s.replace("、", ",").replace(" ", ",").split(","):
        if ch in wd:
            out[wd[ch]] = True
    return out


class Core:
    """サーバの App + ルート群に相当。状態を保持し dict を返す（JSON化はJS側）。"""

    def __init__(self, recipes_data, profile_data):
        self.recipes = [Recipe.from_dict(r) for r in recipes_data["recipes"]]
        self.profile = Profile.from_dict(profile_data or {})
        self.by_id = {r.id: r for r in self.recipes}
        self.catalog = self._build_catalog()
        self.catalog_unit = {c["key"]: c["unit"] for c in self.catalog}
        self.catalog_name = {c["key"]: c["name"] for c in self.catalog}
        self.session = None
        self.inv_names = {}

    def _build_catalog(self):
        by_key = {}
        for r in self.recipes:
            for ing in r.ingredients:
                if ing.category in ("protein", "vegetable"):
                    slot = by_key.setdefault(ing.key, {"name": ing.name, "units": {}})
                    u = clean_unit(ing.unit)
                    slot["units"][u] = slot["units"].get(u, 0) + 1
        out = []
        for key, slot in by_key.items():
            unit = CANONICAL_UNITS.get(key) or max(slot["units"], key=slot["units"].get)
            out.append({"key": key, "name": slot["name"], "unit": unit})
        out.sort(key=lambda x: x["name"])
        return out

    def _ing_amount(self, ing, mult):
        u = clean_unit(ing.unit)
        if ing.key in CANONICAL_UNITS and u in _BAD_COUNT_UNITS:
            return "適量"
        return _fmt_qty(ing.qty * mult, u)

    def _brief(self, r, mult=1.0):
        if not r:
            return None
        return {
            "id": r.id, "name": r.name, "cuisine": r.cuisine, "protein": r.protein,
            "cook": r.cook_time_min, "servings": r.base_servings, "mult": round(mult, 2),
            "steps": r.steps,
            "ings": [{"name": i.name, "amount": self._ing_amount(i, mult),
                      "seasoning": i.category in ("seasoning", "staple")}
                     for i in r.ingredients],
        }

    # ---- 初期化／復元／永続化 ----
    def init_default(self, week_data):
        wk = week_data or {}
        inv = [{"name": n, "qty": q} for n, q in (wk.get("inventory") or {}).items()]
        self.set_week(dinner=wk.get("dinner", "all"), bento=wk.get("bento", "weekday"),
                      month=int(wk.get("month", 6)), inventory=inv,
                      missing=wk.get("missing_staples", []), regen=True)

    def restore(self, d):
        self.session = PlanSession.from_dict(d, self.recipes, self.profile)
        self.inv_names = dict(d.get("inventory_names", {}))
        self.session.regenerate()

    def dump(self):
        d = self.session.to_dict()
        d["inventory_names"] = self.inv_names
        return d

    # ---- 週条件 ----
    def set_week(self, dinner=None, bento=None, month=None, inventory=None,
                 missing=None, regen=True):
        if self.session is None:
            req = WeekRequest([True] * 7, [False] * 7, {}, [], month or 6)
            self.session = PlanSession(self.recipes, self.profile, req, Mods())
        req = self.session.request
        if dinner is not None:
            req.dinner_days = _parse_days(dinner)
        if bento is not None:
            req.bento_days = _parse_days(bento)
        if month is not None:
            req.current_month = int(month)
        if inventory is not None:
            inv = {}
            self.inv_names = {}
            for it in inventory:
                name = str(it.get("name", "")).strip()
                key = it.get("key") or (normalize_key(name)[0] if name else None)
                if not key:
                    continue
                try:
                    q = float(it.get("qty", 0) or 0)
                except (TypeError, ValueError):
                    q = 0.0
                inv[key] = inv.get(key, 0) + q
                self.inv_names[key] = name or key
            req.inventory = inv
        if missing is not None:
            req.missing_staples = [normalize_key(n)[0] for n in missing]
        if regen:
            self.session.regenerate()

    # ---- 状態（state_dict 相当） ----
    def state(self):
        s = self.session
        plan = s.plan
        dates = _week_dates()
        days = []
        if not plan.metrics.get("error"):
            for d in range(7):
                if not plan.dinner_days[d]:
                    continue
                main = plan.dinner_mains[d]
                side = plan.dinner_sides[d]
                soup = plan.dinner_soups[d]
                main_mult = 1.0
                if main:
                    portions = s.profile.dinner_servings
                    if plan.carried_main(d) is main:
                        portions += s.profile.bento_servings
                    main_mult = max(1.0, portions / main.base_servings)
                days.append({
                    "idx": d, "weekday": WEEKDAYS[d], "date": dates[d],
                    "main": self._brief(main, main_mult), "side": self._brief(side),
                    "soup": self._brief(soup), "pinned": d in s.mods.pins,
                })
        sl = build_shopping_list(plan, s.profile, s.request)
        shopping = [{
            "section": sec,
            "items": [{"name": it.name, "qty": _fmt_qty(it.qty, it.unit),
                       "reused": it.reused, "dishes": list(dict.fromkeys(it.dishes))}
                      for it in items],
        } for sec, items in sl.ordered()]
        m = plan.metrics
        return {
            "profile": {"dinner": s.profile.dinner_servings, "bento": s.profile.bento_servings},
            "week": {
                "dinner_days": s.request.dinner_days, "bento_days": s.request.bento_days,
                "month": s.request.current_month,
                "inventory": [{"key": k, "name": self.catalog_name.get(k) or self.inv_names.get(k, k),
                               "qty": q, "unit": self.catalog_unit.get(k, "")}
                              for k, q in s.request.inventory.items()],
            },
            "catalog": self.catalog,
            "days": days,
            "shopping": shopping,
            "shopping_excluded": sl.excluded_pantry,
            "metrics": {
                "washoku": int(m.get("washoku_ratio", 0) * 100),
                "violations": m.get("violations", []),
                "inventory_unused": [self.catalog_name.get(k, k) for k in m.get("inventory_unused", [])],
                "error": m.get("error"),
            },
            "mods": {
                "include_side": s.mods.include_side, "include_soup": s.mods.include_soup,
                "washoku_target": s.mods.washoku_target,
                "time_override": s.mods.weekday_time_override,
                "protein_delta": s.mods.protein_delta,
            },
        }

    # ---- §7 コマンド ----
    def command(self, body):
        s = self.session
        if s is None or s.plan is None:
            return {"error": "not ready"}
        cmd = body.get("cmd")
        if cmd == "swap":
            s.swap(int(body["day"]))
        elif cmd == "protein":
            s.set_protein(int(body["day"]), str(body["group"]))
        elif cmd == "cuisine":
            s.set_cuisine(int(body["day"]), str(body["cuisine"]))
        elif cmd == "unpin":
            s.unpin(int(body["day"]))
        elif cmd == "pick":
            s.pick(int(body["day"]), str(body["id"]))
        elif cmd == "more":
            s.category(str(body["group"]), +1)
        elif cmd == "less":
            s.category(str(body["group"]), -1)
        elif cmd == "useup":
            key, _ = normalize_key(str(body["food"]))
            s.useup(key)
        elif cmd == "time":
            s.set_time(int(body["minutes"]))
        elif cmd == "shuffle":
            s.shuffle()
        elif cmd == "reset":
            s.reset()
        elif cmd == "config":
            if "include_side" in body:
                s.mods.include_side = bool(body["include_side"])
            if "include_soup" in body:
                s.mods.include_soup = bool(body["include_soup"])
            if "washoku_target" in body:
                wt = body["washoku_target"]
                s.mods.washoku_target = None if wt is None else float(wt)
            s.regenerate()
        else:
            return {"error": f"unknown command: {cmd}"}
        return self.state()

    def week(self, body):
        self.set_week(dinner=body.get("dinner"), bento=body.get("bento"),
                      month=body.get("month"), inventory=body.get("inventory"),
                      missing=body.get("missing"))
        return self.state()

    def candidates(self, body):
        s = self.session
        if s is None or s.plan is None:
            return {"candidates": []}
        try:
            cands = s.candidates(int(body["day"]), body.get("cuisine") or None,
                                 body.get("protein") or None)
        except (KeyError, ValueError, TypeError):
            return {"candidates": []}
        return {"candidates": cands}

    def recipe(self, rid):
        r = self.by_id.get(rid)
        if not r:
            return {"error": "not found"}
        return self._brief(r, 1.0)

    def record(self):
        plan = self.session.plan
        if plan.metrics.get("error"):
            return {"error": "記録できる献立がありません"}
        mon = _next_monday()
        cal = {}
        n = 0
        for d in range(7):
            if not plan.dinner_days[d] or not plan.dinner_mains[d]:
                continue
            iso = (mon + timedelta(days=d)).isoformat()
            cal[iso] = {
                "main": plan.dinner_mains[d].name, "main_id": plan.dinner_mains[d].id,
                "side": plan.dinner_sides[d].name if plan.dinner_sides[d] else None,
                "soup": plan.dinner_soups[d].name if plan.dinner_soups[d] else None,
            }
            n += 1
        return {"recorded": n, "entries": cal}
'''


def main() -> int:
    parts = ["from __future__ import annotations", ""]
    for src in SOURCES:
        parts.append(f"# ===== {src.relative_to(ROOT)} =====")
        parts.append(strip_source(src.read_text(encoding="utf-8")))
        parts.append("")
    parts.append(GLUE)
    bundle = "\n".join(parts)
    out = WEB / "kondate_bundle.py"
    out.write_text(bundle, encoding="utf-8")
    print(f"bundle: {out}  ({len(bundle):,} bytes / {bundle.count(chr(10))} lines)")

    # 検証: exec して Core を初期化＋state（デスクトップPythonで動くか）
    import json
    ns = {}
    exec(compile(bundle, str(out), "exec"), ns)
    recipes = json.loads((ROOT / "data" / "recipes.json").read_text(encoding="utf-8"))
    profile = json.loads((ROOT / "data" / "profile.json").read_text(encoding="utf-8"))
    week = json.loads((ROOT / "data" / "week.json").read_text(encoding="utf-8"))
    core = ns["Core"](recipes, profile)
    core.init_default(week)
    st = core.state()
    print("検証 state(): days=", len(st["days"]), "/ error=", st["metrics"]["error"],
          "/ catalog=", len(st["catalog"]))
    core.command({"cmd": "cuisine", "day": st["days"][0]["idx"], "cuisine": "洋"})
    print("検証 cuisine: day0 =", core.state()["days"][0]["main"]["name"],
          core.state()["days"][0]["main"]["cuisine"])
    print("OK バンドル検証通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
