"""Check this repository's inline Markdown links, with optional bounded HTTP audit.

Supports the inline-link and ATX-heading syntax used here, including duplicate
GitHub-style anchors. This is not a general Markdown or HACS validator.
"""

import argparse
import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r'!?\[[^\]\n]*\]\(([^)\s]+)(?:\s+"[^"]*")?\)')
HEADING = re.compile(r"^#{1,6}\s+(.+?)(?:\s+#+)?$", re.MULTILINE)
CANONICAL_LICENSE = "https://www.apache.org/licenses/LICENSE-2.0.txt"
EXCLUDED = {".git", ".venv", "__pycache__", ".ruff_cache", "htmlcov", "build", "dist"}


def anchors(text: str) -> set[str]:
    result = set()
    counts = {}
    for heading in HEADING.findall(text):
        slug = re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")
        suffix = counts.get(slug, 0)
        counts[slug] = suffix + 1
        result.add(f"{slug}-{suffix}" if suffix else slug)
    return result


def markdown_files(root: Path) -> list[Path]:
    files = []
    for directory, folders, names in os.walk(root):
        folders[:] = sorted(folder for folder in folders if folder not in EXCLUDED)
        files.extend(Path(directory) / name for name in sorted(names) if name.endswith(".md"))
    return files


def local_links(root: Path) -> tuple[list[str], set[str], int]:
    root = root.resolve()
    errors, external = [], set()
    count = 0
    for source in markdown_files(root):
        for target in LINK.findall(source.read_text()):
            count += 1
            parsed = urlsplit(target)
            if parsed.scheme in {"http", "https"}:
                external.add(target)
                continue
            if parsed.scheme or parsed.netloc:
                errors.append(f"{source.relative_to(root)}: unsupported link {target}")
                continue
            destination = (
                (source.parent / unquote(parsed.path)).resolve() if parsed.path else source
            )
            if not destination.is_relative_to(root) or not destination.is_file():
                errors.append(f"{source.relative_to(root)}: missing/escaping target {target}")
            elif parsed.fragment:
                if destination.suffix != ".md" or unquote(parsed.fragment) not in anchors(
                    destination.read_text()
                ):
                    errors.append(f"{source.relative_to(root)}: missing anchor {target}")
    return errors, external, count


def external_links(root: Path, urls: set[str]) -> list[str]:
    errors = []
    for url in sorted(urls):
        try:
            request = Request(url, headers={"User-Agent": "cloud-intelligence-link-check/0.0"})
            with urlopen(request, timeout=20) as response:
                body = response.read(2_000_000)
                print(f"HTTP {response.status} {url}")
            if url == CANONICAL_LICENSE and body != (root / "LICENSE").read_bytes():
                errors.append("LICENSE differs from the canonical Apache-2.0 text")
        except (OSError, ValueError) as error:
            errors.append(f"External link failed: {url} ({type(error).__name__})")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--external", action="store_true", help="also use bounded HTTP GETs")
    arguments = parser.parse_args()
    errors, external, count = local_links(ROOT)
    if count == 0:
        errors.append("No documentation links were checked")
    if arguments.external:
        errors.extend(external_links(ROOT, external))
    for error in errors:
        print(f"FAIL {error}", file=sys.stderr)
    if errors:
        return 1
    print(
        f"Validated {count} documentation links; {len(external)} distinct external references"
        + (
            " checked over HTTP; canonical LICENSE matched"
            if arguments.external
            else " deferred (offline mode)"
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
