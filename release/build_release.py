#!/usr/bin/env python3
"""Build a deterministic versioned ZIP after release checks pass."""

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from check_release import check_release


def build(root, output=None, force=False):
    root = Path(root).resolve()
    report = check_release(root)
    if not report["passed"]:
        raise ValueError("Source release checks failed: %s" % report["findings"])
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    manifest = json.loads((root / "release" / "manifest.json").read_text(encoding="utf-8"))
    skill_name = manifest["skill_name"]
    skill_root = root / manifest["skill_directory"]
    output_path = Path(output).resolve() if output else root / ("%s-skill-v%s.zip" % (skill_name, version))
    if output_path.exists() and not force:
        raise ValueError("Output already exists; use --force to replace it: %s" % output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    files = sorted(path for path in skill_root.rglob("*") if path.is_file() and path.suffix != ".pyc" and "__pycache__" not in path.parts)
    with zipfile.ZipFile(str(output_path), "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            relative = path.relative_to(skill_root).as_posix()
            info = zipfile.ZipInfo("%s/%s" % (skill_name, relative), date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())
    digest = hashlib.sha256(output_path.read_bytes()).hexdigest()
    sidecar = output_path.with_suffix(output_path.suffix + ".sha256")
    sidecar.write_text("%s  %s\n" % (digest, output_path.name), encoding="utf-8")
    archive_report = check_release(root, archive=output_path)
    if not archive_report["passed"]:
        raise ValueError("Built archive failed validation: %s" % archive_report["findings"])
    return {"archive": str(output_path), "sha256": digest, "files": len(files), "version": version}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--output")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = build(args.root, args.output, args.force)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print("Release build error: %s" % exc, file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
