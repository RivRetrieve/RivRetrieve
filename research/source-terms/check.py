"""Check the source-terms forms: complete, recorded, and quoting the page they cite.

Research apparatus for the source-terms survey. Not library code and not shipped.

Usage:

    python research/source-terms/check.py            # every provider
    python research/source-terms/check.py pl_imgw    # one provider

Three things are checked per slot (licence, citation):

1. The form states an address, a recording and a retrieval instant, or declares the
   agency publishes nothing.
2. The named recording exists, and its bytes still hash to what was recorded.
3. **The quoted text actually occurs in the recorded page.** This is the check that
   matters. A plausible address paired with a plausible quotation is exactly what a
   language model produces when the page does not say the thing.

Exit code is 0 only when every checked provider passes.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import unicodedata
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SLOTS = ("licence", "citation")
# Only tags with a real closing tag. A void element such as <meta> or <link> never
# closes, so counting it here would ratchet the skip depth up and swallow the page.
SKIP_TAGS = {"script", "style", "noscript", "template", "svg"}


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in SKIP_TAGS:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP_TAGS and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def normalise(text: str) -> str:
    """Collapse whitespace and unify the punctuation a copy-paste mangles."""
    text = unicodedata.normalize("NFKC", text)
    for fancy, plain in (("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"'),
                         ("–", "-"), ("—", "-"), (" ", " ")):
        text = text.replace(fancy, plain)
    return re.sub(r"\s+", " ", text).strip().casefold()


def page_text(html: bytes) -> str:
    parser = _Text()
    parser.feed(html.decode("utf-8", errors="replace"))
    return normalise("".join(parser.parts))


def read_form(path: Path) -> dict[str, dict[str, str]]:
    """Parse the fixed-heading form into {slot: {field: value}}."""
    body = path.read_text(encoding="utf-8")
    out: dict[str, dict[str, str]] = {}
    for slot in SLOTS:
        section = re.search(rf"^## {slot}\b(.*?)(?=^## |\Z)", body, re.S | re.M | re.I)
        if not section:
            continue
        chunk = section.group(1)
        fields = {k.strip().casefold(): v.strip() for k, v in re.findall(r"^- ([^:]+):(.*)$", chunk, re.M)}
        quote = re.search(r"```text\n(.*?)```", chunk, re.S)
        fields["quote"] = quote.group(1).strip() if quote else ""
        out[slot] = fields
    return out


def check_provider(provider_id: str) -> list[str]:
    problems: list[str] = []
    form = ROOT / provider_id / "finding.md"
    if not form.exists():
        return [f"{provider_id}: no finding.md"]

    for slot, fields in read_form(form).items():
        where = f"{provider_id}/{slot}"
        if fields.get("agency publishes nothing", "").casefold() in {"yes", "true"}:
            if not fields.get("recording"):
                problems.append(f"{where}: claims the agency publishes nothing, with no page recorded showing that")
            continue

        for field in ("page url", "recording"):
            if not fields.get(field):
                problems.append(f"{where}: '{field}' is blank")
        if not fields.get("quote"):
            problems.append(f"{where}: the verbatim quote block is empty")
        if problems and not fields.get("recording"):
            continue

        stem = ROOT / provider_id / "pages" / fields["recording"]
        sidecar = stem.with_suffix(".json")
        meta_early = json.loads(sidecar.read_text(encoding="utf-8")) if sidecar.exists() else {}
        page = stem.parent / meta_early.get("file", f"{stem.name}.html")
        if not sidecar.exists() or not page.exists():
            problems.append(f"{where}: recording '{fields['recording']}' is not in pages/")
            continue

        meta = json.loads(sidecar.read_text(encoding="utf-8"))
        body = page.read_bytes()
        if hashlib.sha256(body).hexdigest() != meta.get("sha256"):
            problems.append(f"{where}: the saved page no longer matches its recorded digest")
            continue
        kind = meta.get("content_type", "").lower()
        if "html" not in kind and "text" not in kind:
            problems.append(
                f"{where}: recording is {meta.get('content_type')!r}, so the quote CANNOT be checked by machine. "
                f"It is on you to have copied it exactly. Say in Notes that this source's terms are not an HTML page."
            )
            continue

        if fields["quote"] and normalise(fields["quote"]) not in page_text(body):
            problems.append(
                f"{where}: THE QUOTE IS NOT ON THE RECORDED PAGE. "
                f"Either it was not copied from {meta['final_url']}, or it was reworded. Copy it again, character for character."
            )
    return problems


def main() -> int:
    wanted = sys.argv[1:]
    providers = sorted(p.name for p in ROOT.iterdir() if p.is_dir() and (p / "finding.md").exists())
    if wanted:
        providers = [p for p in providers if p in wanted]
    else:
        # Folders starting with "_" are worked examples, not one of the thirteen.
        providers = [p for p in providers if not p.startswith("_")]
        if not providers:
            print(f"no such provider form: {' '.join(wanted)}")
            return 2

    failed = 0
    for provider_id in providers:
        problems = check_provider(provider_id)
        if problems:
            failed += 1
            print(f"FAIL {provider_id}")
            for problem in problems:
                print(f"     {problem}")
        else:
            print(f"ok   {provider_id}")
    print(f"\n{len(providers) - failed}/{len(providers)} providers pass.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
