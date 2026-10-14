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
LESSON_KEYS = {"what", "ideas", "rules", "examples", "mistakes", "check"}
CHECK_KEYS = {"q", "a", "options", "correct", "accept"}


class Report:
    def __init__(self):
        self.errors, self.warnings = [], []

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


def validate_lesson(rep, where, lesson):
    if not isinstance(lesson, dict):
        rep.err(where, "«lesson» має бути об'єктом")
        return
    extra_keys(rep, f"{where}.lesson", lesson, LESSON_KEYS | {"example"})
    w = f"{where}.lesson"
    need_str(rep, w, lesson, "what")
    need_str_list(rep, w, lesson, "ideas")
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
        extra_keys(rep, we, ex, {"task", "steps", "answer"})
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
            need_str(rep, f"{we}.steps[{i}]", s, "do")
            need_str(rep, f"{we}.steps[{i}]", s, "why")
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
