#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Готує карту навчання до публікації як власної сторінки учня (артефакту).

Бере зібрану сторінку {project-root}/study-map/study-map.html (її збирає
study-map/build-map.py з шаблону й уроків). Інструмент Artifact сам обгортає
сторінку в <!doctype html><html><head>...<body>, тож зовнішню обгортку тут
прибираємо. Результат іде в особисту теку учня, а не в репозиторій:
    {project-root}/_memory/learners/<learner-slug>/map/study-map.html

Використання:
    python shared/scripts/build-map-artifact.py <project-root> <learner-slug>

Друкує шлях до готового файлу (path:) і версію карти (map_version:).
"""

import re
import sys
from pathlib import Path

WRAPPER_LINES = {
    "<!doctype html>",
    '<html lang="uk">',
    "<head>",
    '<meta charset="utf-8">',
    '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">',
    "</head>",
    "<body>",
    "</body>",
    "</html>",
}
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    if len(sys.argv) != 3:
        print("Використання: python build-map-artifact.py <project-root> <learner-slug>")
        sys.exit(1)
    root = Path(sys.argv[1]).resolve()
    slug = sys.argv[2]
    if not SLUG.match(slug):
        print(f"Недійсний learner-slug {slug!r}: лише малі латинські літери, цифри й дефіс (напр. «marta-k»).")
        sys.exit(1)

    source = root / "study-map" / "study-map.html"
    if not source.exists():
        print(f"Карту не знайдено: {source}")
        print("Збери її: python study-map/build-map.py")
        sys.exit(1)
    text = source.read_text(encoding="utf-8")
    if "/*@@CONTENT@@*/" in text:
        print("Сторінка не зібрана (є маркер /*@@CONTENT@@*/). Збери її: python study-map/build-map.py")
        sys.exit(1)

    # Попередити, якщо шаблон або уроки новіші за зібрану сторінку.
    built = source.stat().st_mtime
    inputs = [root / "study-map" / "map-template.html", *(root / "study-map" / "content").rglob("*.json")]
    if any(p.exists() and p.stat().st_mtime > built + 1 for p in inputs):
        print("увага: шаблон або уроки новіші за study-map.html — можливо, варто спершу запустити python study-map/build-map.py")

    kept = [line for line in text.splitlines() if line.strip() not in WRAPPER_LINES]
    text = "\n".join(kept) + "\n"
    match = re.search(r'const MAP_VERSION = "([^"]+)"', text)
    version = match.group(1) if match else "unknown"

    out = root / "_memory" / "learners" / slug / "map" / "study-map.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"path: {out}")
    print(f"map_version: {version}")


if __name__ == "__main__":
    main()
