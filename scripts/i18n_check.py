#!/usr/bin/env python3
"""
i18n validation and template generation for DOCSight.

Usage:
    python scripts/i18n_check.py              # validate all language files
    python scripts/i18n_check.py --validate   # same as above
    python scripts/i18n_check.py --generate   # generate template.json files
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SKIP_FILES = {"en.json", "template.json"}


def find_i18n_dirs():
    """Return a list of (label, i18n_dir) tuples for core and all modules."""
    dirs = []
    core_i18n = ROOT / "app" / "i18n"
    if (core_i18n / "en.json").exists():
        dirs.append(("core", core_i18n))

    modules_dir = ROOT / "app" / "modules"
    if modules_dir.is_dir():
        for mod in sorted(modules_dir.iterdir()):
            i18n_dir = mod / "i18n"
            if i18n_dir.is_dir() and (i18n_dir / "en.json").exists():
                dirs.append((f"module/{mod.name}", i18n_dir))

    return dirs


def load_json(path):
    """Load and return a JSON file as a dict."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON in {path}: {e}", file=sys.stderr)
        sys.exit(1)


def make_template(source):
    """Build a template dict from a source (en.json) dict.

    Rules:
        - String values become ""
        - List values become []
        - Dict values recurse into empty-string templates
        - The _meta object becomes {"language_name": "", "flag": ""}
        - Everything else (unexpected) is kept as-is for safety
    """
    template = {}
    for key, value in source.items():
        if key == "_meta" and isinstance(value, dict):
            template[key] = {"language_name": "", "flag": ""}
        elif isinstance(value, dict):
            template[key] = make_template(value)
        elif isinstance(value, str):
            template[key] = ""
        elif isinstance(value, list):
            template[key] = []
        else:
            # Unexpected type -- keep it so nothing is silently lost
            template[key] = value
    return template


def flatten_key_paths(value, prefix=""):
    """Return nested dotted key paths for dict structures."""
    if not isinstance(value, dict):
        return set()

    paths = set()
    for key, child in value.items():
        path = f"{prefix}.{key}" if prefix else key
        paths.add(path)
        paths.update(flatten_key_paths(child, path))
    return paths


def cmd_generate():
    """Generate template.json files from en.json for core and all modules."""
    dirs = find_i18n_dirs()
    generated = 0

    for label, i18n_dir in dirs:
        en_path = i18n_dir / "en.json"
        template_path = i18n_dir / "template.json"

        source = load_json(en_path)
        template = make_template(source)

        with open(template_path, "w", encoding="utf-8") as f:
            json.dump(template, f, indent=2, ensure_ascii=False)
            f.write("\n")

        print(f"  Generated {template_path.relative_to(ROOT)}  ({len(template)} keys)")
        generated += 1

    print(f"\nGenerated {generated} template file(s).")


def cmd_validate():
    """Validate all language files against en.json as source of truth."""
    dirs = find_i18n_dirs()
    total_missing = 0
    total_extra = 0
    files_checked = 0
    problems = []

    for label, i18n_dir in dirs:
        en_path = i18n_dir / "en.json"
        source = load_json(en_path)
        source_keys = flatten_key_paths(source)

        for lang_file in sorted(i18n_dir.glob("*.json")):
            if lang_file.name in SKIP_FILES:
                continue

            lang = load_json(lang_file)
            lang_keys = flatten_key_paths(lang)

            missing = source_keys - lang_keys
            extra = lang_keys - source_keys

            if missing or extra:
                rel = lang_file.relative_to(ROOT)
                entry = {"file": str(rel), "missing": sorted(missing), "extra": sorted(extra)}
                problems.append(entry)
                total_missing += len(missing)
                total_extra += len(extra)

            files_checked += 1

    # Print results
    if not problems:
        print(f"All {files_checked} language file(s) are in sync with en.json.")
    else:
        for p in problems:
            print(f"\n  {p['file']}:")
            if p["missing"]:
                print(f"    Missing ({len(p['missing'])}): {', '.join(p['missing'])}")
            if p["extra"]:
                print(f"    Extra   ({len(p['extra'])}): {', '.join(p['extra'])}")

        print(f"\nSummary: {total_missing} missing key(s), {total_extra} extra key(s) "
              f"across {len(problems)} file(s)  ({files_checked} checked).")

    # Always exit 0 -- this is warning-only, does not block CI
    return 0


def main():
    parser = argparse.ArgumentParser(description="DOCSight i18n checker")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--generate", action="store_true",
                       help="Generate template.json files from en.json")
    group.add_argument("--validate", action="store_true",
                       help="Validate language files against en.json (default)")
    args = parser.parse_args()

    if args.generate:
        cmd_generate()
    else:
        sys.exit(cmd_validate())


if __name__ == "__main__":
    main()
