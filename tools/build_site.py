#!/usr/bin/env python3
"""Package the browser application and verify its local entry-point assets."""
from __future__ import annotations

import json
import shutil
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
FILES = ("index.html", "styles.css", "data.js", "render.js", "picker-tree.js", "events.js")
DIRECTORIES = ("assets", "data")


class LocalReferences(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths: set[str] = set()

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name not in {"href", "src"} or not value:
                continue
            url = urlsplit(value)
            if not url.scheme and not url.netloc and url.path:
                self.paths.add(unquote(url.path))


def main() -> None:
    if DIST.is_symlink():
        raise RuntimeError("The generated output directory must not be a symbolic link")
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()
    for name in FILES:
        shutil.copy2(ROOT / name, DIST / name)
    for name in DIRECTORIES:
        shutil.copytree(ROOT / name, DIST / name)
    (DIST / ".nojekyll").touch()
    parser = LocalReferences()
    parser.feed((DIST / "index.html").read_text(encoding="utf-8"))
    for relative in parser.paths:
        destination = (DIST / relative).resolve()
        if not destination.is_relative_to(DIST) or not destination.is_file():
            raise RuntimeError(f"Missing or invalid application asset: {relative}")
    catalog = json.loads((DIST / "data/pals.verified.json").read_text(encoding="utf-8"))
    for pal in catalog["pals"]:
        icon = (DIST / pal["icon"]).resolve()
        if not icon.is_relative_to(DIST / "assets") or not icon.is_file():
            raise RuntimeError(f"Missing Pal icon: {pal['id']}")
    paths = [p for p in DIST.rglob("*") if p.is_file()]
    print(f"Built dist/: {len(paths)} files, {sum(p.stat().st_size for p in paths):,} bytes; all entry-point assets and Pal icons present")


if __name__ == "__main__":
    main()
