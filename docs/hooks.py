"""MkDocs build hooks for RivRetrieve documentation.

Automatically:
1. Syncs the root README.md into docs/index.md, adjusting internal links.
2. Ensures docs/assets/stations_map.html is up to date with packaged catalogues.
3. Automatically fixes and resolves relative markdown links:
   - External repo files (src/, tests/, maintenance/, .env) become GitHub blob links.
   - Cross-references to README.md become proper relative paths to index.md.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = REPO_ROOT / "docs"
README_PATH = REPO_ROOT / "README.md"
INDEX_MD_PATH = DOCS_DIR / "index.md"
STATIONS_MAP_PATH = DOCS_DIR / "assets" / "stations_map.html"
GITHUB_REPO_BLOB = "https://github.com/RivRetrieve/RivRetrieve/blob/main"


def on_pre_build(config: dict) -> None:
    """Invoked before building the docs site."""
    # 1. Sync README.md to docs/index.md
    if README_PATH.is_file():
        content = README_PATH.read_text(encoding="utf-8")

        # Replace links pointing to docs/ subpaths: (docs/foo.md) -> (foo.md)
        content = re.sub(r"\((?:\./)?docs/([^)#\s]+)", r"(\1", content)

        # Replace LICENSE link
        content = re.sub(
            r"\[LICENSE\]\(LICENSE\)",
            f"[LICENSE]({GITHUB_REPO_BLOB}/LICENSE)",
            content,
        )

        # Add link to interactive map in coverage map section
        map_note = (
            '\n\n!!! tip "Interactive Station Explorer"\n'
            "    Looking for specific gauges? Explore all 78,000+ stations worldwide on our "
            "[**Interactive Station Map**](map.md).\n"
        )
        content = content.replace(
            "![Countries with implemented providers in solid green and countries coming soon in orange stripes; implemented providers are listed in the table below.](assets/coverage-map.png)",
            "![Countries with implemented providers in solid green and countries coming soon in orange stripes; implemented providers are listed in the table below.](assets/coverage-map.png)"
            + map_note,
        )

        INDEX_MD_PATH.write_text(content, encoding="utf-8")

    # 2. Generate stations_map.html if missing
    if not STATIONS_MAP_PATH.is_file():
        generator = DOCS_DIR / "scripts" / "generate_station_map.py"
        if generator.is_file():
            print("Generating stations_map.html for documentation build...")
            subprocess.run([sys.executable, str(generator)], check=True)

    # 3. Synchronize API reference directly from Python docstrings & domain contracts
    ref_generator = REPO_ROOT / "scripts" / "generate_reference.py"
    if ref_generator.is_file():
        subprocess.run([sys.executable, str(ref_generator)], check=True)


def on_page_markdown(markdown: str, page, config: dict, files) -> str:
    """Rewrite relative markdown links on each page."""
    page_src_path = page.file.src_path
    current_doc_path = DOCS_DIR / page_src_path
    current_dir = current_doc_path.parent

    def replacer(match: re.Match) -> str:
        text = match.group(1)
        href = match.group(2).strip()

        # Preserve web links, anchors, mailto, etc.
        if href.startswith(("http://", "https://", "mailto:", "#", "javascript:")):
            return match.group(0)

        url_target, sep, anchor = href.partition("#")
        if not url_target:
            return match.group(0)

        # Strip any formatting/attributes like {:target="_blank"}
        attr = ""
        if "}" in anchor:
            anchor_part, brace, rest = anchor.partition("{")
            anchor = anchor_part.strip()
            attr = "{" + rest

        try:
            resolved = (current_dir / url_target).resolve()
        except Exception:
            return match.group(0)

        # 1. External files outside docs/ or excluded provider_ports directory
        if (resolved.is_relative_to(REPO_ROOT) and not resolved.is_relative_to(DOCS_DIR)) or (
            resolved.is_relative_to(DOCS_DIR / "provider_ports")
        ):
            rel_root = resolved.relative_to(REPO_ROOT).as_posix()
            url_type = "tree" if resolved.is_dir() else "blob"
            new_url = f"https://github.com/RivRetrieve/RivRetrieve/{url_type}/main/{rel_root}"
            if anchor:
                new_url += f"#{anchor}"
            return f"[{text}]({new_url}{attr})"

        # 2. Links to README.md (or docs/README.md) -> target docs/index.md
        if resolved in (REPO_ROOT / "README.md", DOCS_DIR / "README.md"):
            target_path = DOCS_DIR / "index.md"
            rel_path = os.path.relpath(target_path, current_dir).replace("\\", "/")
            if anchor == "providers":
                anchor = "river-data-and-where-to-find-them"
            new_url = rel_path + (f"#{anchor}" if anchor else "")
            return f"[{text}]({new_url}{attr})"

        # 3. If target is inside docs, normalize relative path
        if resolved.is_relative_to(DOCS_DIR):
            rel_path = os.path.relpath(resolved, current_dir).replace("\\", "/")
            new_url = rel_path + (f"#{anchor}" if anchor else "")
            return f"[{text}]({new_url}{attr})"

        return match.group(0)

    # Replace markdown link patterns: [text](href)
    pattern = re.compile(r"\[([^\]]+)\]\(([^)\s]+(?:\s+[^)]+)?)\)")
    return pattern.sub(replacer, markdown)
