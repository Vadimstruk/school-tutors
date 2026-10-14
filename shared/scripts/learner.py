#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Профілі учнів для шкільних репетиторів.

Кожен учень має власну теку в _memory/learners/<slug>/:
    PROFILE.md            — спільний для всіх репетиторів (ім'я, клас, як навчається)
    <subject>/            — окремо для кожного предмета (прогрес, історія задач, помилки)
        PROGRESS.md HISTORY.md MISTAKES.md NOTES.md sessions/ tasks/
    map/                  — підготовлена сторінка карти навчання

Використання:
    python3 learner.py list <project-root>
    python3 learner.py new <project-root> "<Ім'я>" [--grade 7]
    python3 learner.py add-subject <project-root> <slug> <subject>

`new` друкує `slug: ...` — назву теки учня. Якщо учень з таким ім'ям уже є,
скрипт нічого не перезаписує, а додає до назви номер (kateryna-2): двоє учнів
з однаковим ім'ям на одному комп'ютері — не рідкість. Спершу перевір `list`.
`add-subject` не перезаписує наявних файлів, лише створює відсутні.
"""

import argparse
import re
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATES = HERE.parent / "templates"

SUBJECT_TEMPLATES = ["PROGRESS", "HISTORY", "MISTAKES", "NOTES"]

TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "h", "ґ": "g", "д": "d", "е": "e", "є": "ie",
    "ж": "zh", "з": "z", "и": "y", "і": "i", "ї": "i", "й": "i", "к": "k", "л": "l",
    "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch", "ь": "",
    "ю": "iu", "я": "ia", "'": "", "’": "", "ʼ": "",
}


def slugify(name: str) -> str:
    out = "".join(TRANSLIT.get(ch, ch) for ch in name.strip().lower())
    out = re.sub(r"[^a-z0-9]+", "-", out).strip("-")
    return out or "learner"


def learners_dir(root: Path) -> Path:
    return root / "_memory" / "learners"


def read_field(text: str, field: str) -> str:
    m = re.search(rf"^- \*\*{re.escape(field)}:\*\*\s*(.*)$", text, re.M)
    return m.group(1).strip() if m else ""


def fill(template: str, values: dict) -> str:
    for key, val in values.items():
        template = template.replace("{" + key + "}", val)
    return template


def write_index(root: Path) -> None:
    rows = []
    for d in sorted(learners_dir(root).glob("*/PROFILE.md")):
        text = d.read_text(encoding="utf-8")
        subjects = sorted(p.name for p in d.parent.iterdir()
                          if p.is_dir() and (p / "PROGRESS.md").exists())
        rows.append(f"| {read_field(text, 'Ім’я')} | `{d.parent.name}` | "
                    f"{read_field(text, 'Клас')} | {', '.join(subjects) or '—'} |")
    index = root / "_memory" / "LEARNERS.md"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text(
        "# Учні на цьому комп'ютері\n\n"
        "_Оновлює `shared/scripts/learner.py`. Не редагуй вручну._\n\n"
        "| Ім'я | Тека | Клас | Предмети |\n|---|---|---|---|\n" + "\n".join(rows) + "\n",
        encoding="utf-8")


def cmd_list(root: Path) -> int:
    found = False
    for d in sorted(learners_dir(root).glob("*/PROFILE.md")):
        text = d.read_text(encoding="utf-8")
        subjects = sorted(p.name for p in d.parent.iterdir()
                          if p.is_dir() and (p / "PROGRESS.md").exists())
        print(f"{d.parent.name}\t{read_field(text, 'Ім’я')}\t{read_field(text, 'Клас')}\t"
              f"{','.join(subjects)}")
        found = True
    if not found:
        print("(учнів ще немає)")
    return 0


def cmd_new(root: Path, name: str, grade: str) -> int:
    base = slugify(name)
    slug, n = base, 2
    while (learners_dir(root) / slug).exists():
        slug, n = f"{base}-{n}", n + 1
    folder = learners_dir(root) / slug
    folder.mkdir(parents=True)
    today = date.today().isoformat()
    tpl = (TEMPLATES / "PROFILE-template.md").read_text(encoding="utf-8")
    (folder / "PROFILE.md").write_text(
        fill(tpl, {"name": name.strip(), "grade": grade, "slug": slug, "date": today}),
        encoding="utf-8")
    write_index(root)
    print(f"slug: {slug}")
    print(f"profile: {folder / 'PROFILE.md'}")
    return 0


def cmd_add_subject(root: Path, slug: str, subject: str) -> int:
    folder = learners_dir(root) / slug
    if not (folder / "PROFILE.md").exists():
        print(f"Немає учня з текою «{slug}». Спершу: learner.py new", file=sys.stderr)
        return 1
    if not re.fullmatch(r"[a-z][a-z0-9-]*", subject):
        print("Назва предмета — латиницею, напр. math", file=sys.stderr)
        return 1
    sub = folder / subject
    (sub / "sessions").mkdir(parents=True, exist_ok=True)
    (sub / "tasks").mkdir(exist_ok=True)
    name = read_field((folder / "PROFILE.md").read_text(encoding="utf-8"), "Ім’я")
    today = date.today().isoformat()
    created = []
    for t in SUBJECT_TEMPLATES:
        dest = sub / f"{t}.md"
        if dest.exists():
            continue
        tpl = (TEMPLATES / "subject" / f"{t}-template.md").read_text(encoding="utf-8")
        dest.write_text(fill(tpl, {"name": name, "subject": subject, "date": today}),
                        encoding="utf-8")
        created.append(dest.name)
    write_index(root)
    print(f"subject: {sub}")
    print("created: " + (", ".join(created) or "нічого — усе вже було"))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("list"); p.add_argument("root")
    p = sp.add_parser("new"); p.add_argument("root"); p.add_argument("name"); p.add_argument("--grade", default="7")
    p = sp.add_parser("add-subject"); p.add_argument("root"); p.add_argument("slug"); p.add_argument("subject")
    a = ap.parse_args()
    root = Path(a.root).resolve()
    if a.cmd == "list":
        return cmd_list(root)
    if a.cmd == "new":
        return cmd_new(root, a.name, a.grade)
    return cmd_add_subject(root, a.slug, a.subject)


if __name__ == "__main__":
    sys.exit(main())
