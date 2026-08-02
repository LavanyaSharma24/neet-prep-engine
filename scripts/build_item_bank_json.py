"""Builds web/public/item_bank.json from item_bank/<subject>/*.jsonl source files.

Each source .jsonl file holds one verified item per line, shaped per
item_bank/schema.json. This script concatenates every subject folder into a
single JSON array for the web app to fetch, and adds one derived field not
present in schema.json: "subject", taken from the source folder name (e.g.
"biology", "chemistry"), so the client can group/filter by subject.

Run from anywhere; paths are resolved relative to the repo root.
"""
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_GLOBS = [
    "item_bank/biology/*.jsonl",
    "item_bank/chemistry/*.jsonl",
]
OUTPUT_PATH = REPO_ROOT / "web" / "public" / "item_bank.json"


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
