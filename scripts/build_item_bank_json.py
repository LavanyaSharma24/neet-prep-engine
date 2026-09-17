"""Builds web/public/item_bank.json from item_bank/<subject>/*.jsonl source files.

Each source .jsonl file holds one verified item per line, shaped per
item_bank/schema.json. This script concatenates every subject folder into a
single JSON array for the web app to fetch, and adds one derived field not
present in schema.json: "subject", taken from the source folder name (e.g.
"biology", "chemistry"), so the client can group/filter by subject.

Also copies item_bank/diagrams/*.svg to web/public/diagrams/ — the SVGs an
item's optional "diagram" field (schema.json) can reference. item_bank/ is
the committed source of truth (diagrams reviewed alongside the items they
illustrate); web/public/diagrams/ is a gitignored build artifact, exactly
like web/public/item_bank.json.

Run from anywhere; paths are resolved relative to the repo root.
"""
import json
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_GLOBS = [
    "item_bank/biology/*.jsonl",
    "item_bank/chemistry/*.jsonl",
]
OUTPUT_PATH = REPO_ROOT / "web" / "public" / "item_bank.json"
DIAGRAMS_SOURCE_DIR = REPO_ROOT / "item_bank" / "diagrams"
DIAGRAMS_OUTPUT_DIR = REPO_ROOT / "web" / "public" / "diagrams"


def load_source_files(root: Path = REPO_ROOT, globs=SOURCE_GLOBS) -> list[dict]:
    """Load every item across all subject globs, tagging each with its subject.

    Missing subject folders (e.g. chemistry not seeded yet) are skipped
    silently — glob() just returns nothing for a pattern with no matches.
    """
    items = []
    for pattern in globs:
        subject = pattern.split("/")[1]
        for path in sorted(root.glob(pattern)):
            with path.open(encoding="utf-8") as f:
                for line_no, line in enumerate(f, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise ValueError(f"{path}:{line_no}: invalid JSON — {exc}") from exc
                    item["subject"] = subject
                    items.append(item)
    return items


def copy_diagrams(
    source_dir: Path = DIAGRAMS_SOURCE_DIR, output_dir: Path = DIAGRAMS_OUTPUT_DIR
) -> int:
    """Copies every SVG from source_dir to output_dir. Missing source_dir
    (no diagrams authored yet) is not an error — same "skip silently"
    behavior as load_source_files has for a missing subject folder."""
    if not source_dir.is_dir():
        return 0
    output_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for svg_path in sorted(source_dir.glob("*.svg")):
        shutil.copyfile(svg_path, output_dir / svg_path.name)
        count += 1
    return count


def build(output_path: Path = OUTPUT_PATH) -> list[dict]:
    items = load_source_files()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return items


if __name__ == "__main__":
    built = build()
    by_subject: dict[str, int] = {}
    for item in built:
        by_subject[item["subject"]] = by_subject.get(item["subject"], 0) + 1
    print(f"Wrote {len(built)} items to {OUTPUT_PATH}")
    for subject, count in sorted(by_subject.items()):
        print(f"  {subject}: {count}")

    diagram_count = copy_diagrams()
    print(f"Copied {diagram_count} diagram(s) to {DIAGRAMS_OUTPUT_DIR}")
