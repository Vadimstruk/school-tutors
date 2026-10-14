#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Збирає карту навчання з шаблону й уроків.

Читає study-map/content/subjects.json (перелік предметів) і файли розділів, які
він називає, перевіряє схему, вставляє дані в study-map/map-template.html
замість рядка /*@@CONTENT@@*/ і записує study-map/study-map.html — готову
сторінку, яку можна відкрити в браузері подвійним кліком.

MAP_VERSION живе в шаблоні; скрипт його не змінює. Змінив уроки чи сторінку —
підніми MAP_VERSION у шаблоні, щоб репетитор оновив опубліковані копії учнів.

Використання:
    python study-map/build-map.py                 # з будь-якої теки
    python study-map/build-map.py --content DIR   # уроки з іншої теки (для перевірки)
    python study-map/build-map.py --check         # лише перевірити, нічого не писати
    python study-map/build-map.py --out FILE      # записати в інший файл

Код виходу 1, якщо є помилки схеми (попередження збірку не зупиняють).
"""

import argparse
import json
import math
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MARKER = "/*@@CONTENT@@*/"
ALLOWED_TAGS = {"b", "i", "sub", "sup"}
SUBJECT_ID = re.compile(r"^[a-z][a-z0-9-]{0,39}$")
SECTION_ID = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,9}$")
STATUSES = {"ready", "planned"}

SUBJECT_KEYS = {"id", "name", "grade", "tutor", "tutorCall", "icon", "files"}
SECTION_KEYS = {"id", "subject", "name", "what", "topics"}
TOPIC_KEYS = {"id", "name", "what", "subtopics"}
SUBTOPIC_KEYS = {"id", "name", "status", "programmeRef", "lesson"}
LESSON_KEYS = {"what", "ideas", "rules", "examples", "mistakes", "check", "fig"}
CHECK_KEYS = {"q", "a", "options", "correct", "accept", "fig"}


class Report:
    def __init__(self):
        self.errors, self.warnings = [], []
        self.figs, self.fig_checks = 0, 0

    def err(self, where, msg):
        self.errors.append(f"ПОМИЛКА  {where}: {msg}")

    def warn(self, where, msg):
        self.warnings.append(f"увага    {where}: {msg}")


def check_html(rep, where, s):
    for tag in sorted({t.lower() for t in re.findall(r"</?\s*([a-zA-Z][a-zA-Z0-9]*)[^>]*>", s)}):
        if tag not in ALLOWED_TAGS:
            rep.err(where, f"недозволений тег <{tag}> (можна лише b, i, sub, sup)")
    for m in re.finditer(r"<\s*(b|i|sub|sup)\s+[^>]*>", s, re.I):
        rep.err(where, f"тег {m.group(0)} з атрибутами — можна лише простий <{m.group(1)}>")
    if re.search(r"\*\*|__|`", s):
        rep.warn(where, "схоже на markdown (** __ `) — на сторінці воно покажеться як є")


def need_str(rep, where, obj, key, required=True):
    v = obj.get(key)
    if v is None and not required:
        return ""
    if not isinstance(v, str) or not v.strip():
        rep.err(where, f"«{key}» має бути непорожнім рядком")
        return ""
    check_html(rep, f"{where}.{key}", v)
    return v


def need_str_list(rep, where, obj, key, required=True):
    items = obj.get(key)
    if items is None and not required:
        return
    if not isinstance(items, list) or (required and not items):
        rep.err(where, f"«{key}» має бути непорожнім списком рядків")
        return
    for i, s in enumerate(items):
        if not isinstance(s, str) or not s.strip():
            rep.err(where, f"{key}[{i}] має бути непорожнім рядком")
        else:
            check_html(rep, f"{where}.{key}[{i}]", s)


def extra_keys(rep, where, obj, allowed):
    extra = set(obj) - allowed
    if extra:
        rep.warn(where, f"невідомі поля (на сторінці їх не видно): {', '.join(sorted(extra))}")


# ---------- Малюнки (fig): схема і геометрія. Контракт — study-map/FIGURES.md ----------
FIG_KEYS = {"caption", "view", "points", "hide", "lp", "axes", "items", "check"}
FIG_STYLES = {"hl", "hl2", "dash", "faint"}
FIG_LP = {"n", "ne", "e", "se", "s", "sw", "w", "nw"}
ITEM_FIELDS = {
    "seg": ({"p"}, {"ticks"}),
    "ray": ({"p"}, set()),
    "line": ({"p"}, set()),
    "poly": ({"p"}, {"fill"}),
    "circle": ({"c"}, {"r", "through"}),
    "angle": ({"p"}, {"label", "arcs", "r"}),
    "right": ({"p"}, set()),
    "label": ({"at", "text"}, set()),
    "fn": ({"k", "b"}, {"label"}),
    "vline": ({"x"}, {"label"}),
    "plot": ({"pts"}, set()),
}
POINT_COUNT = {"seg": 2, "ray": 2, "line": 2, "angle": 3, "right": 3}
CHECK_FORMS = {"col", "mid", "eq", "len", "ang", "perp", "par", "onc", "on"}
ANGLE_LABEL = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*°\s*$")
REL = 1e-2


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def fmt(v):
    return f"{v:.3f}".rstrip("0").rstrip(".")


def dist(a, b):
    return math.hypot(b[0] - a[0], b[1] - a[1])


def angle_deg(a, o, b):
    """Менший кут AOB у градусах (0–180)."""
    ux, uy, vx, vy = a[0] - o[0], a[1] - o[1], b[0] - o[0], b[1] - o[1]
    lu, lv = math.hypot(ux, uy), math.hypot(vx, vy)
    if lu == 0 or lv == 0:
        return None
    return math.degrees(math.atan2(abs(ux * vy - uy * vx), ux * vx + uy * vy))


def fig_text(rep, where, v, key, required=True):
    if v is None and not required:
        return
    if not isinstance(v, str) or not v.strip():
        rep.err(where, f"«{key}» має бути непорожнім рядком")
    elif "<" in v or ">" in v:
        rep.err(where, f"«{key}» — простий текст без тегів")


def validate_fig(rep, where, fig):
    """Перевіряє схему й геометрію малюнка. Повертає множину id елементів (для hl) або None, якщо малюнок зламаний."""
    rep.figs += 1
    before = len(rep.errors)
    if not isinstance(fig, dict):
        rep.err(where, "«fig» має бути об'єктом")
        return None
    extra = set(fig) - FIG_KEYS
    if extra:
        rep.err(where, f"невідомі поля малюнка: {', '.join(sorted(extra))}")
    fig_text(rep, where, fig.get("caption"), "caption")
    view = fig.get("view")
    if not (isinstance(view, list) and len(view) == 4 and all(is_num(x) for x in view) and view[0] < view[2] and view[1] < view[3]):
        rep.err(where, f"«view» має бути [xmin, ymin, xmax, ymax] з xmin < xmax і ymin < ymax, а не {view!r}")
    pts = fig.get("points", {})
    P = {}
    if not isinstance(pts, dict):
        rep.err(where, "«points» має бути об'єктом {\"A\": [x, y], …}")
    else:
        for name, p in pts.items():
            if not re.fullmatch(r"[A-Za-zА-Яа-яІіЇїЄєҐґ][A-Za-zА-Яа-яІіЇїЄєҐґ0-9'′]*", name):
                rep.err(where, f"ім'я точки {name!r}: літера, далі літери, цифри або штрих")
            if isinstance(p, list) and len(p) == 2 and all(is_num(x) for x in p):
                P[name] = (float(p[0]), float(p[1]))
            else:
                rep.err(where, f"точка {name}: потрібно [x, y] з числами, а не {p!r}")

    def ref(n, ctx):
        if isinstance(n, str) and n in P:
            return P[n]
        rep.err(where, f"{ctx}: точки {n!r} немає в «points»")
        return None

    hide = fig.get("hide", [])
    if not isinstance(hide, list):
        rep.err(where, "«hide» має бути списком імен точок")
    else:
        for n in hide:
            ref(n, "hide")
    lp = fig.get("lp", {})
    if not isinstance(lp, dict):
        rep.err(where, "«lp» має бути об'єктом {\"A\": \"ne\", …}")
    else:
        for n, d in lp.items():
            ref(n, "lp")
            if d not in FIG_LP:
                rep.err(where, f"lp.{n} = {d!r}: можна {', '.join(sorted(FIG_LP))}")
    if "axes" in fig:
        ax = fig["axes"]
        if not isinstance(ax, dict) or set(ax) - {"step", "every"}:
            rep.err(where, "«axes» має бути {\"step\": число, \"every\": ціле}")
        else:
            if not (is_num(ax.get("step", 1)) and ax.get("step", 1) > 0):
                rep.err(where, f"axes.step має бути додатним числом, а не {ax.get('step')!r}")
            e = ax.get("every", 1)
            if not (isinstance(e, int) and not isinstance(e, bool) and e >= 1):
                rep.err(where, f"axes.every має бути цілим ≥ 1, а не {e!r}")

    items = fig.get("items")
    ids, segs_by_ticks, angs_by_arcs = set(), {}, {}
    if not isinstance(items, list) or not items:
        rep.err(where, "«items» має бути непорожнім списком елементів")
        items = []
    for i, it in enumerate(items):
        wi = f"{where} › items[{i}]"
        if not isinstance(it, dict):
            rep.err(wi, "елемент має бути об'єктом")
            continue
        t = it.get("t")
        if t not in ITEM_FIELDS:
            rep.err(wi, f"невідомий тип t={t!r} (можна {', '.join(ITEM_FIELDS)})")
            continue
        wi = f"{where} › items[{i}] ({t}{' ' + str(it['id']) if 'id' in it else ''})"
        req, opt = ITEM_FIELDS[t]
        miss = req - set(it)
        if miss:
            rep.err(wi, f"бракує полів: {', '.join(sorted(miss))}")
        extra = set(it) - req - opt - {"t", "id", "s"}
        if extra:
            rep.err(wi, f"невідомі поля: {', '.join(sorted(extra))}")
        if "id" in it:
            if not isinstance(it["id"], str) or not it["id"].strip():
                rep.err(wi, "«id» має бути непорожнім рядком")
            elif it["id"] in ids:
                rep.err(wi, f"id «{it['id']}» уже є в цьому малюнку")
            else:
                ids.add(it["id"])
        if "s" in it:
            toks = it["s"].split() if isinstance(it["s"], str) else None
            if toks is None or set(toks) - FIG_STYLES:
                rep.err(wi, f"стиль s={it['s']!r}: можна \"\" або hl, hl2, dash, faint (через пробіл)")
        pp = None
        if "p" in it:
            p = it["p"]
            n = POINT_COUNT.get(t)
            if not isinstance(p, list) or (n and len(p) != n) or (not n and len(p) < 3):
                rep.err(wi, f"«p» має бути списком з {n if n else 'щонайменше 3'} імен точок")
            else:
                pp = [ref(x, f"items[{i}]") for x in p]
                if any(q is None for q in pp):
                    pp = None
        if t in ("ray", "line", "seg") and pp and pp[0] == pp[1]:
            rep.err(wi, "дві точки збігаються")
        if t == "seg" and "ticks" in it:
            k = it["ticks"]
            if not (isinstance(k, int) and not isinstance(k, bool) and 1 <= k <= 3):
                rep.err(wi, f"ticks має бути 1–3, а не {k!r}")
            elif pp:
                segs_by_ticks.setdefault(k, []).append((it["p"], dist(*pp)))
        if t == "poly" and "fill" in it and not isinstance(it["fill"], bool):
            rep.err(wi, "fill має бути true або false")
        if t == "circle":
            ref(it.get("c"), f"items[{i}].c")
            if ("r" in it) == ("through" in it):
                rep.err(wi, "потрібне рівно одне: «r» (число) або «through» (точка)")
            elif "r" in it and not (is_num(it["r"]) and it["r"] > 0):
                rep.err(wi, f"r має бути додатним числом, а не {it['r']!r}")
            elif "through" in it:
                ref(it["through"], f"items[{i}].through")
        if t == "angle":
            if "label" in it:
                fig_text(rep, wi, it["label"], "label")
            if "r" in it and not (is_num(it["r"]) and 10 <= it["r"] <= 120):
                rep.err(wi, f"r — радіус дуги в ПІКСЕЛЯХ (10–120), а не {it['r']!r}; "
                            "краще не задавати r зовсім — карта підбере радіус сама")
            arcs = it.get("arcs")
            if arcs is not None and not (isinstance(arcs, int) and not isinstance(arcs, bool) and 1 <= arcs <= 3):
                rep.err(wi, f"arcs має бути 1–3, а не {arcs!r}")
                arcs = None
            if pp:
                m = angle_deg(*pp)
                if m is None:
                    rep.err(wi, "кут з нульовою стороною (вершина збігається з іншою точкою)")
                else:
                    rep.fig_checks += 1
                    lab = it.get("label")
                    mm = ANGLE_LABEL.match(lab) if isinstance(lab, str) else None
                    if mm:
                        want = float(mm.group(1).replace(",", "."))
                        if abs(m - want) > 0.5:
                            rep.err(wi, f"кут ∠{''.join(it['p'])} підписано «{lab}», а на малюнку {fmt(m)}° (допуск 0,5°)")
                    if arcs is not None:
                        angs_by_arcs.setdefault(arcs, []).append((it["p"], m))
        if t == "right" and pp:
            m = angle_deg(*pp)
            rep.fig_checks += 1
            if m is None or abs(m - 90) > 0.5:
                rep.err(wi, f"позначка прямого кута при {it['p'][1]}, а ∠{''.join(it['p'])} = {fmt(m) if m is not None else '?'}° (потрібно 90° ± 0,5°)")
        if t == "label":
            at = it.get("at")
            if not (isinstance(at, list) and len(at) == 2 and all(is_num(x) for x in at)):
                ref(at, f"items[{i}].at")
            fig_text(rep, wi, it.get("text"), "text")
        if t == "fn":
            for key in ("k", "b"):
                if key in it and not is_num(it[key]):
                    rep.err(wi, f"«{key}» має бути числом")
            if "label" in it:
                fig_text(rep, wi, it["label"], "label")
        if t == "vline":
            if "x" in it and not is_num(it["x"]):
                rep.err(wi, "«x» має бути числом")
            if "label" in it:
                fig_text(rep, wi, it["label"], "label")
        if t == "plot":
            pl = it.get("pts")
            if not (isinstance(pl, list) and len(pl) >= 2 and all(isinstance(q, list) and len(q) == 2 and all(is_num(x) for x in q) for q in pl)):
                rep.err(wi, "«pts» має бути списком щонайменше двох пар [x, y]")

    for k, group in segs_by_ticks.items():
        if len(group) > 1:
            rep.fig_checks += 1
            lo, hi = min(g[1] for g in group), max(g[1] for g in group)
            if hi - lo > 0.005 * hi:
                desc = ", ".join(f"{''.join(p)} = {fmt(L)}" for p, L in group)
                rep.err(where, f"відрізки з {k} рисоч{'кою' if k == 1 else 'ками'} мають бути рівні (±0,5 %), а вони: {desc}")
    for k, group in angs_by_arcs.items():
        if len(group) > 1:
            rep.fig_checks += 1
            lo, hi = min(g[1] for g in group), max(g[1] for g in group)
            if hi - lo > 0.5:
                desc = ", ".join(f"∠{''.join(p)} = {fmt(m)}°" for p, m in group)
                rep.err(where, f"кути з {k} дуг{'ою' if k == 1 else 'ами'} мають бути рівні (±0,5°), а вони: {desc}")

    checks = fig.get("check", [])
    if not isinstance(checks, list):
        rep.err(where, "«check» малюнка має бути списком умов")
        checks = []
    for i, c in enumerate(checks):
        wc = f"{where} › check[{i}]"
        if not isinstance(c, dict) or len(c) != 1 or next(iter(c)) not in CHECK_FORMS:
            rep.err(wc, f"умова має бути об'єктом з одним ключем ({', '.join(sorted(CHECK_FORMS))}), а не {c!r}")
            continue
        kind, a = next(iter(c.items()))
        rep.fig_checks += 1
        try:
            fail = fig_assert(kind, a, P)
        except (TypeError, ValueError, KeyError, IndexError) as e:
            rep.err(wc, f"{kind}: погано записана умова {a!r} ({e})")
            continue
        if fail:
            rep.err(wc, f"{kind} {json.dumps(a, ensure_ascii=False)}: {fail}")
    return ids


def fig_assert(kind, a, P):
    """Повертає опис невдачі або None."""
    def pt(n):
        if not isinstance(n, str) or n not in P:
            raise KeyError(f"точки {n!r} немає в points")
        return P[n]

    def seg(s):
        if not (isinstance(s, list) and len(s) == 2):
            raise ValueError("відрізок — це [A, B]")
        return pt(s[0]), pt(s[1])

    def num(x):
        if not is_num(x):
            raise ValueError(f"{x!r} — не число")
        return float(x)

    if kind == "col":
        if not (isinstance(a, list) and len(a) == 3):
            raise ValueError("потрібно [A, B, C]")
        A, B, C = map(pt, a)
        L = max(dist(A, B), dist(A, C), dist(B, C))
        cross = (B[0] - A[0]) * (C[1] - A[1]) - (B[1] - A[1]) * (C[0] - A[0])
        dev = abs(cross) / L if L else 0.0  # подвоєна площа / найдовша сторона ≈ 2·висота
        return None if dev <= REL * L else f"точки не на одній прямій: відхилення {fmt(dev / 2)} при довжині {fmt(L)}"
    if kind == "mid":
        if not (isinstance(a, list) and len(a) == 3):
            raise ValueError("потрібно [M, A, B]")
        M, A, B = map(pt, a)
        mid = ((A[0] + B[0]) / 2, (A[1] + B[1]) / 2)
        d = dist(M, mid)
        return None if d <= REL * dist(A, B) else f"середина {a[1]}{a[2]} — ({fmt(mid[0])}; {fmt(mid[1])}), а {a[0]} = ({fmt(M[0])}; {fmt(M[1])})"
    if kind == "eq":
        if not (isinstance(a, list) and len(a) == 2):
            raise ValueError("потрібно [[A, B], [C, D]]")
        l1, l2 = dist(*seg(a[0])), dist(*seg(a[1]))
        return None if abs(l1 - l2) <= REL * max(l1, l2) else f"{''.join(a[0])} = {fmt(l1)}, а {''.join(a[1])} = {fmt(l2)}"
    if kind == "len":
        if not (isinstance(a, list) and len(a) == 2):
            raise ValueError("потрібно [[A, B], число]")
        L, want = dist(*seg(a[0])), num(a[1])
        return None if abs(L - want) <= REL * max(abs(want), 1e-9) else f"{''.join(a[0])} = {fmt(L)}, а має бути {fmt(want)}"
    if kind == "ang":
        if not (isinstance(a, list) and len(a) == 2 and isinstance(a[0], list) and len(a[0]) == 3):
            raise ValueError("потрібно [[A, O, B], градуси]")
        m, want = angle_deg(*map(pt, a[0])), num(a[1])
        if m is None:
            return "кут з нульовою стороною"
        return None if abs(m - want) <= 0.5 else f"∠{''.join(a[0])} = {fmt(m)}°, а має бути {fmt(want)}° (допуск 0,5°)"
    if kind in ("perp", "par"):
        if not (isinstance(a, list) and len(a) == 2):
            raise ValueError("потрібно [[A, B], [C, D]]")
        (A, B), (C, D) = seg(a[0]), seg(a[1])
        u, v = (B[0] - A[0], B[1] - A[1]), (D[0] - C[0], D[1] - C[1])
        lu, lv = math.hypot(*u), math.hypot(*v)
        if not lu or not lv:
            return "відрізок нульової довжини"
        between = math.degrees(math.atan2(abs(u[0] * v[1] - u[1] * v[0]), u[0] * v[0] + u[1] * v[1]))
        if kind == "perp":
            cos = abs(u[0] * v[0] + u[1] * v[1]) / (lu * lv)
            return None if cos <= REL else f"кут між {''.join(a[0])} і {''.join(a[1])} — {fmt(between)}°, а не 90°"
        sin = abs(u[0] * v[1] - u[1] * v[0]) / (lu * lv)
        return None if sin <= REL else f"кут між {''.join(a[0])} і {''.join(a[1])} — {fmt(min(between, 180 - between))}°, а не 0° (не паралельні)"
    if kind == "onc":
        if not (isinstance(a, list) and len(a) == 3):
            raise ValueError("потрібно [P, O, r]")
        Pp, O, r = pt(a[0]), pt(a[1]), num(a[2])
        d = dist(Pp, O)
        return None if abs(d - r) <= REL * r else f"{a[0]}{a[1]} = {fmt(d)}, а радіус {fmt(r)}"
    if kind == "on":
        if not (isinstance(a, list) and len(a) == 3):
            raise ValueError("потрібно [P, k, b]")
        Pp, k, b = pt(a[0]), num(a[1]), num(a[2])
        want = k * Pp[0] + b
        return None if abs(Pp[1] - want) <= REL * max(1.0, abs(want)) else f"для x = {fmt(Pp[0])} на прямій y = {fmt(want)}, а в точки {a[0]} y = {fmt(Pp[1])}"
    return None


def validate_lesson(rep, where, lesson):
    if not isinstance(lesson, dict):
        rep.err(where, "«lesson» має бути об'єктом")
        return
    extra_keys(rep, f"{where}.lesson", lesson, LESSON_KEYS | {"example"})
    w = f"{where}.lesson"
    need_str(rep, w, lesson, "what")
    need_str_list(rep, w, lesson, "ideas")
    if "fig" in lesson:
        validate_fig(rep, f"{where} › lesson.fig", lesson["fig"])
    rules = lesson.get("rules", [])
    if not isinstance(rules, list):
        rep.err(w, "«rules» має бути списком об'єктів {f, means}")
    else:
        for i, r in enumerate(rules):
            if not isinstance(r, dict):
                rep.err(w, f"rules[{i}] має бути об'єктом {{f, means}}")
                continue
            need_str(rep, f"{w}.rules[{i}]", r, "f")
            need_str(rep, f"{w}.rules[{i}]", r, "means")
    if "example" in lesson:
        rep.err(w, "застарілий ключ example — використовуй examples")
    exs = lesson.get("examples")
    if not isinstance(exs, list) or not 2 <= len(exs) <= 3:
        rep.err(w, "«examples» має бути списком з 2–3 прикладів {task, steps, answer} (від легшого до складнішого)")
        exs = exs if isinstance(exs, list) else []
    for k, ex in enumerate(exs):
        we = f"{w}.examples[{k}]"
        if not isinstance(ex, dict):
            rep.err(we, "приклад має бути об'єктом {task, steps, answer}")
            continue
        extra_keys(rep, we, ex, {"task", "steps", "answer", "fig"})
        fig_ids = validate_fig(rep, f"{where} › приклад {k + 1}.fig", ex["fig"]) if "fig" in ex else None
        need_str(rep, we, ex, "task")
        need_str(rep, we, ex, "answer")
        steps = ex.get("steps")
        if not isinstance(steps, list) or not steps:
            rep.err(we, "«steps» має бути непорожнім списком {do, why}")
            continue
        for i, s in enumerate(steps):
            if not isinstance(s, dict):
                rep.err(we, f"steps[{i}] має бути об'єктом {{do, why}}")
                continue
            ws = f"{where} › приклад {k + 1} › крок {i + 1}"
            extra_keys(rep, ws, s, {"do", "why", "hl"})
            need_str(rep, f"{we}.steps[{i}]", s, "do")
            need_str(rep, f"{we}.steps[{i}]", s, "why")
            if "hl" in s:
                hl = s["hl"]
                if "fig" not in ex:
                    rep.err(ws, "«hl» є, а в прикладу немає малюнка «fig»")
                elif not isinstance(hl, list) or not all(isinstance(x, str) for x in hl):
                    rep.err(ws, "«hl» має бути списком id елементів малюнка")
                elif fig_ids is not None:
                    missing = [x for x in hl if x not in fig_ids]
                    if missing:
                        rep.err(ws, f"«hl» називає id, яких немає серед items малюнка прикладу: {', '.join(missing)}")
    need_str_list(rep, w, lesson, "mistakes")
    checks = lesson.get("check")
    if not isinstance(checks, list) or not checks:
        rep.err(w, "«check» має бути непорожнім списком запитань")
        return
    for i, c in enumerate(checks):
        wc = f"{w}.check[{i}]"
        if not isinstance(c, dict):
            rep.err(wc, "запитання має бути об'єктом {q, a, options+correct або accept}")
            continue
        extra_keys(rep, wc, c, CHECK_KEYS)
        need_str(rep, wc, c, "q")
        need_str(rep, wc, c, "a")
        if "fig" in c:
            validate_fig(rep, f"{where} › запитання {i + 1}.fig", c["fig"])
        has_opts, has_acc = "options" in c, "accept" in c
        if has_opts == has_acc:
            rep.err(wc, "потрібне рівно одне з двох: «options» + «correct» (вибір варіанта) або «accept» (введення відповіді)")
            continue
        if has_opts:
            opts = c.get("options")
            if not isinstance(opts, list) or not 2 <= len(opts) <= 4 or not all(isinstance(o, str) and o.strip() for o in opts):
                rep.err(wc, "«options» — від 2 до 4 непорожніх рядків")
            else:
                for j, o in enumerate(opts):
                    check_html(rep, f"{wc}.options[{j}]", o)
                if len(set(opts)) != len(opts):
                    rep.err(wc, "варіанти в «options» повторюються")
                k = c.get("correct")
                if not isinstance(k, int) or isinstance(k, bool) or not 0 <= k < len(opts):
                    rep.err(wc, f"«correct» має бути номером правильного варіанта від 0 до {len(opts) - 1}, а не {k!r}")
        else:
            if "correct" in c:
                rep.err(wc, "«correct» потрібен лише разом з «options»")
            acc = c.get("accept")
            if not isinstance(acc, list) or not acc or not all(isinstance(a, str) and a.strip() for a in acc):
                rep.err(wc, "«accept» має бути непорожнім списком непорожніх рядків (правильні відповіді)")


def validate_section(rep, where, data, subject_id, seen_ids):
    if not isinstance(data, dict):
        rep.err(where, "очікувався об'єкт JSON")
        return False
    before = len(rep.errors)
    extra_keys(rep, where, data, SECTION_KEYS)
    sid = data.get("id")
    if not isinstance(sid, str) or not SECTION_ID.match(sid):
        rep.err(where, f"«id» розділу має бути на кшталт «A1» (латинські літери й цифри), а не {sid!r}")
        return False
    w = f"{where} › {sid}"
    if sid in seen_ids:
        rep.err(w, f"ID «{sid}» уже є в іншому місці (ID мають бути унікальні в усіх предметах)")
    seen_ids.add(sid)
    if data.get("subject") != subject_id:
        rep.err(w, f"«subject» = {data.get('subject')!r}, а файл належить предмету «{subject_id}»")
    need_str(rep, w, data, "name")
    need_str(rep, w, data, "what", required=False)
    topics = data.get("topics")
    if not isinstance(topics, list) or not topics:
        rep.err(w, "«topics» має бути непорожнім списком")
        return False
    for t in topics:
        if not isinstance(t, dict):
            rep.err(w, "кожна тема має бути об'єктом")
            continue
        tid = t.get("id")
        if not isinstance(tid, str) or not re.fullmatch(re.escape(sid) + r"\.[1-9]\d*", tid):
            rep.err(w, f"ID теми {tid!r} має бути «{sid}.N» (наприклад {sid}.1)")
            continue
        wt = f"{where} › {tid}"
        if tid in seen_ids:
            rep.err(wt, "такий ID уже є")
        seen_ids.add(tid)
        extra_keys(rep, wt, t, TOPIC_KEYS)
        need_str(rep, wt, t, "name")
        need_str(rep, wt, t, "what", required=False)
        subs = t.get("subtopics")
        if not isinstance(subs, list) or not subs:
            rep.err(wt, "«subtopics» має бути непорожнім списком")
            continue
        for st in subs:
            if not isinstance(st, dict):
                rep.err(wt, "кожна підтема має бути об'єктом")
                continue
            stid = st.get("id")
            if not isinstance(stid, str) or not re.fullmatch(re.escape(tid) + r"\.[1-9]\d*", stid):
                rep.err(wt, f"ID підтеми {stid!r} має бути «{tid}.N» (наприклад {tid}.1)")
                continue
            ws = f"{where} › {stid}"
            if stid in seen_ids:
                rep.err(ws, "такий ID уже є")
            seen_ids.add(stid)
            extra_keys(rep, ws, st, SUBTOPIC_KEYS)
            need_str(rep, ws, st, "name")
            need_str(rep, ws, st, "programmeRef")
            status = st.get("status")
            if status not in STATUSES:
                rep.err(ws, f"«status» має бути \"ready\" або \"planned\", а не {status!r}")
                continue
            if status == "ready":
                if "lesson" not in st:
                    rep.err(ws, "підтема зі статусом \"ready\" мусить мати «lesson»")
                else:
                    validate_lesson(rep, ws, st["lesson"])
            elif "lesson" in st:
                rep.warn(ws, "у підтеми \"planned\" є «lesson» — його не покажуть, доки статус не стане \"ready\"")
    return len(rep.errors) == before


def validate_subject(rep, i, s, seen_subjects):
    where = f"subjects.json › subjects[{i}]"
    if not isinstance(s, dict):
        rep.err(where, "предмет має бути об'єктом")
        return False
    before = len(rep.errors)
    sid = s.get("id")
    if not isinstance(sid, str) or not SUBJECT_ID.match(sid):
        rep.err(where, f"«id» предмета має бути коротким латинськими малими літерами (напр. «algebra»), а не {sid!r}")
        return False
    where = f"subjects.json › {sid}"
    if sid in seen_subjects:
        rep.err(where, "предмет з таким id уже є")
    seen_subjects.add(sid)
    extra_keys(rep, where, s, SUBJECT_KEYS)
    for key in ("name", "tutor", "tutorCall", "icon"):
        v = s.get(key)
        if not isinstance(v, str) or not v.strip():
            rep.err(where, f"«{key}» має бути непорожнім рядком")
        elif re.search(r"[<>]", v):
            rep.err(where, f"«{key}» — простий текст без тегів")
    g = s.get("grade")
    if not isinstance(g, int) or isinstance(g, bool) or not 1 <= g <= 12:
        rep.err(where, f"«grade» має бути числом 1–12, а не {g!r}")
    files = s.get("files")
    if not isinstance(files, list) or not all(isinstance(f, str) and f.strip() for f in files):
        rep.err(where, "«files» має бути списком шляхів до файлів розділів (може бути порожнім)")
    return len(rep.errors) == before


def build_content(content_dir: Path, rep: Report) -> dict:
    manifest_path = content_dir / "subjects.json"
    if not manifest_path.is_file():
        rep.err(str(manifest_path), "файлу немає")
        return {"subjects": []}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        rep.err("subjects.json", f"не читається як JSON UTF-8: {e}")
        return {"subjects": []}
    if not isinstance(manifest, dict) or not isinstance(manifest.get("subjects"), list):
        rep.err("subjects.json", "очікувався об'єкт {\"subjects\": [...]}")
        return {"subjects": []}
    extra_keys(rep, "subjects.json", manifest, {"subjects"})

    root = content_dir.resolve()
    out, seen_subjects, seen_ids, used_files = [], set(), set(), set()
    for i, s in enumerate(manifest["subjects"]):
        if not validate_subject(rep, i, s, seen_subjects):
            continue
        sections = []
        for rel in s["files"]:
            where = rel
            p = (content_dir / rel).resolve()
            if Path(rel).is_absolute() or root not in p.parents:
                rep.err(f"subjects.json › {s['id']}", f"шлях «{rel}» має бути всередині теки content")
                continue
            if p in used_files:
                rep.err(f"subjects.json › {s['id']}", f"файл «{rel}» указано двічі")
                continue
            used_files.add(p)
            if not p.is_file():
                rep.err(f"subjects.json › {s['id']}", f"файлу «{rel}» немає")
                continue
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                rep.err(where, f"не читається як JSON UTF-8: {e}")
                continue
            if validate_section(rep, where, data, s["id"], seen_ids):
                sections.append(data)
        subj = {k: s[k] for k in ("id", "name", "grade", "tutor", "tutorCall", "icon")}
        subj["sections"] = sections
        out.append(subj)

    for p in sorted(content_dir.rglob("*.json")):
        if p.resolve() != manifest_path.resolve() and p.resolve() not in used_files:
            rep.warn(str(p.relative_to(content_dir)), "файл не згадано в subjects.json — його не буде на карті")
    return {"subjects": out}


def js(value) -> str:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return text.replace("</", "<\\/").replace("<!--", "<\\!--").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="Зібрати study-map/study-map.html")
    ap.add_argument("--content", type=Path, default=HERE / "content", help="тека з subjects.json і файлами розділів")
    ap.add_argument("--out", type=Path, default=HERE / "study-map.html", help="куди записати сторінку")
    ap.add_argument("--check", action="store_true", help="лише перевірити зміст, нічого не писати")
    args = ap.parse_args()

    rep = Report()
    content = build_content(args.content, rep)
    for line in rep.warnings + rep.errors:
        print(line)
    subs = [st for s in content["subjects"] for sec in s["sections"] for t in sec["topics"] for st in t["subtopics"]]
    ready = sum(1 for st in subs if st.get("status") == "ready")
    print(f"малюнків перевірено {rep.figs}, геометричних перевірок {rep.fig_checks}")
    print(f"предметів {len(content['subjects'])}, підтем {len(subs)}, з них готових уроків {ready}; "
          f"помилок {len(rep.errors)}, попереджень {len(rep.warnings)}")
    if rep.errors:
        sys.exit(1)
    if args.check:
        return

    template = (HERE / "map-template.html").read_text(encoding="utf-8")
    if template.count(MARKER) != 1:
        print(f"ПОМИЛКА: у шаблоні має бути рівно один рядок {MARKER}")
        sys.exit(1)
    page = template.replace(MARKER, f"const CONTENT = {js(content)};")
    version = re.search(r'const MAP_VERSION = "([^"]+)"', page)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(page, encoding="utf-8")
    print(f"path: {args.out}")
    print(f"map_version: {version.group(1) if version else 'unknown'}")


if __name__ == "__main__":
    main()
