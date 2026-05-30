"""Optimize supplement images: resize + convert to WebP.

Shrinks backend/static/images/supplements/ by ~80% while preserving display
quality. Idempotent — already-optimized files are skipped.

Strategy
--------
- Long edge capped at 1200px (Retina-safe for any view in the app).
- WebP @ quality 82, method 6 (slow encode, smaller output — fine, runs once).
- Strip EXIF / metadata.
- Auto-rotate per EXIF before resize so portrait shots don't end up sideways.
- JPEG / PNG / JPG → re-encoded as .webp with the same basename. Renames are
  recorded in a manifest JSON so DB columns can be migrated in one query.
- Existing .webp files: only re-encoded if oversized (>200 KB or >1200 px).
- SVG: untouched (vector — already optimal).

Safety
------
- Dry-run mode (`--dry-run`) prints actions without writing.
- Each file is encoded to a temp path, then atomically replaced.
- On any per-file error, the original is left intact and we move on.
- Backup recommended before running for real (already done at
  /Users/apple/Downloads/HealthMatrix-images-backup-2026-05-06/ for this repo).

Usage
-----
    cd backend
    ./venv/bin/python scripts/optimize_images.py --dry-run --limit 20
    ./venv/bin/python scripts/optimize_images.py --dry-run         # full run preview
    ./venv/bin/python scripts/optimize_images.py                   # for real

Outputs
-------
- Rewrites images in place under static/images/supplements/.
- Writes scripts/optimize_images_manifest.json:
      { "old_filename.jpeg": "old_filename.webp", ... }
  Use it (or the printed SQL) to update supplements.image_path and
  supplement_images.image_path.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PIL import Image, ImageOps, UnidentifiedImageError

# Resolve paths relative to this script so it works from any cwd.
SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
IMAGES_DIR = BACKEND_DIR / "static" / "images" / "supplements"
MANIFEST_PATH = SCRIPT_DIR / "optimize_images_manifest.json"

# Tuning knobs.
MAX_EDGE = 1200          # px — long-edge cap
WEBP_QUALITY = 82        # 80–85 is the sweet spot for product photos
WEBP_METHOD = 6          # 0=fast/big, 6=slow/small. We run once, take the win.
EXISTING_WEBP_REENCODE_THRESHOLD = 200 * 1024  # bytes — re-encode if larger

# Source formats we convert. Order matters only for human-readable output.
CONVERT_EXTS = {".jpeg", ".jpg", ".png"}
KEEP_AS_IS_EXTS = {".svg"}


@dataclass
class Stats:
    scanned: int = 0
    converted: int = 0          # JPEG/PNG → WebP
    recompressed: int = 0       # WebP → smaller WebP
    skipped_already_small: int = 0
    skipped_unsupported: int = 0
    errors: int = 0
    bytes_before: int = 0
    bytes_after: int = 0
    renames: dict[str, str] = field(default_factory=dict)


def _human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _open_oriented(path: Path) -> Image.Image:
    """Open an image and apply EXIF orientation. Caller is responsible for closing."""
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)
    return img


def _resize_in_place(img: Image.Image) -> Image.Image:
    """Downscale so the long edge is at most MAX_EDGE. Upscaling never happens."""
    w, h = img.size
    long_edge = max(w, h)
    if long_edge <= MAX_EDGE:
        return img
    scale = MAX_EDGE / long_edge
    new_size = (round(w * scale), round(h * scale))
    return img.resize(new_size, Image.LANCZOS)


def _encode_webp(img: Image.Image, dest: Path) -> int:
    """Save `img` as WebP to `dest` (overwrites). Returns final byte size.

    Uses a temp file + atomic rename so a crashed encode can't half-write
    over an existing image."""
    # WebP doesn't support paletted ("P") images directly — flatten to RGB(A).
    if img.mode in ("P", "1"):
        img = img.convert("RGBA" if img.mode == "P" and "transparency" in img.info else "RGB")
    elif img.mode == "CMYK":
        img = img.convert("RGB")

    tmp = dest.with_suffix(dest.suffix + ".tmp")
    save_kwargs = {
        "format": "WEBP",
        "quality": WEBP_QUALITY,
        "method": WEBP_METHOD,
    }
    img.save(tmp, **save_kwargs)
    os.replace(tmp, dest)
    return dest.stat().st_size


def _process_file(path: Path, stats: Stats, dry_run: bool) -> None:
    ext = path.suffix.lower()
    stats.scanned += 1
    before = path.stat().st_size

    if ext in KEEP_AS_IS_EXTS:
        stats.skipped_unsupported += 1
        return

    if ext not in CONVERT_EXTS and ext != ".webp":
        # Unrecognized — skip but warn so we don't silently miss things.
        print(f"  [skip] {path.name} — unrecognized extension")
        stats.skipped_unsupported += 1
        return

    # Quick path: existing WebP that's already small + within size cap → leave alone.
    if ext == ".webp" and before <= EXISTING_WEBP_REENCODE_THRESHOLD:
        try:
            with Image.open(path) as probe:
                w, h = probe.size
            if max(w, h) <= MAX_EDGE:
                stats.skipped_already_small += 1
                stats.bytes_before += before
                stats.bytes_after += before
                return
        except (UnidentifiedImageError, OSError) as e:
            print(f"  [warn] could not probe {path.name}: {e}")

    # Decide destination filename.
    # JPEG/PNG → swap extension to .webp. Existing .webp stays in place.
    if ext in CONVERT_EXTS:
        dest = path.with_suffix(".webp")
        stats.renames[path.name] = dest.name
        # Edge case: a .webp with the same basename already exists.
        # Keep behavior loud — we'd rather refuse than silently overwrite.
        if dest.exists() and dest != path:
            print(f"  [skip] {path.name} — {dest.name} already exists, refusing to overwrite")
            stats.errors += 1
            return
    else:
        dest = path

    if dry_run:
        # Just log what would happen.
        try:
            with Image.open(path) as probe:
                w, h = probe.size
            target_w, target_h = w, h
            if max(w, h) > MAX_EDGE:
                scale = MAX_EDGE / max(w, h)
                target_w, target_h = round(w * scale), round(h * scale)
            print(f"  [dry] {path.name} ({w}x{h}, {_human_bytes(before)}) "
                  f"→ {dest.name} ({target_w}x{target_h}, est. WebP q{WEBP_QUALITY})")
        except (UnidentifiedImageError, OSError) as e:
            print(f"  [error] could not read {path.name}: {e}")
            stats.errors += 1
            return
        stats.bytes_before += before
        # Rough estimate: WebP at q82 averages ~30% of resized JPEG, ~20% of resized PNG.
        # Use 35% as a conservative dry-run estimate so users don't over-promise.
        stats.bytes_after += int(before * 0.35)
        if ext == ".webp":
            stats.recompressed += 1
        else:
            stats.converted += 1
        # If we created a rename mapping for a file we're skipping/erroring above,
        # we should not have one — but guard anyway: dry-run keeps it.
        return

    try:
        with _open_oriented(path) as img:
            img = _resize_in_place(img)
            after = _encode_webp(img, dest)
    except (UnidentifiedImageError, OSError) as e:
        print(f"  [error] {path.name}: {e}")
        stats.errors += 1
        # Roll back the rename mapping — we didn't actually convert.
        stats.renames.pop(path.name, None)
        return

    # If we converted (extension changed), remove the original file.
    if ext in CONVERT_EXTS and dest != path:
        try:
            path.unlink()
        except OSError as e:
            print(f"  [warn] could not remove original {path.name}: {e}")

    stats.bytes_before += before
    stats.bytes_after += after
    if ext == ".webp":
        stats.recompressed += 1
    else:
        stats.converted += 1


def _print_summary(stats: Stats, dry_run: bool, elapsed: float) -> None:
    print()
    print("─" * 60)
    print(f"{'DRY RUN — ' if dry_run else ''}Image optimization summary")
    print("─" * 60)
    print(f"  Scanned             : {stats.scanned}")
    print(f"  Converted (→ WebP)  : {stats.converted}")
    print(f"  Recompressed (WebP) : {stats.recompressed}")
    print(f"  Already optimal     : {stats.skipped_already_small}")
    print(f"  Unsupported / SVG   : {stats.skipped_unsupported}")
    print(f"  Errors              : {stats.errors}")
    print(f"  Size before         : {_human_bytes(stats.bytes_before)}")
    print(f"  Size after          : {_human_bytes(stats.bytes_after)}"
          + ("  (estimated)" if dry_run else ""))
    if stats.bytes_before:
        saved = stats.bytes_before - stats.bytes_after
        pct = 100 * saved / stats.bytes_before
        print(f"  Saved               : {_human_bytes(saved)} ({pct:.1f}%)")
    print(f"  Elapsed             : {elapsed:.1f}s")
    print("─" * 60)


def _write_manifest(stats: Stats, dry_run: bool) -> None:
    if not stats.renames:
        return
    if dry_run:
        # Don't write a manifest from a dry-run — would be confusing if the user
        # later runs for real and the file count differs.
        print()
        print(f"  ({len(stats.renames)} files would be renamed — manifest not written in dry-run)")
        return
    MANIFEST_PATH.write_text(json.dumps(stats.renames, indent=2, sort_keys=True))
    print()
    print(f"  Wrote rename manifest → {MANIFEST_PATH.relative_to(BACKEND_DIR)}")


def _print_db_update_sql(stats: Stats) -> None:
    """Emit copy-pasteable SQL to update DB columns to the new filenames.

    Two columns store image filenames: supplements.image_path and
    supplement_images.image_path. Both store the bare filename
    (e.g., 'foo-abc123.jpeg'), so a regex replace is sufficient.
    """
    if not stats.renames:
        return
    print()
    print("─" * 60)
    print("Run this in psql to point DB rows at the new .webp filenames:")
    print("─" * 60)
    print("""
-- Idempotent: only rewrites paths whose extension changed.
UPDATE supplements
SET image_path = regexp_replace(image_path, '\\.(jpeg|jpg|png)$', '.webp')
WHERE image_path ~ '\\.(jpeg|jpg|png)$';

UPDATE supplement_images
SET image_path = regexp_replace(image_path, '\\.(jpeg|jpg|png)$', '.webp')
WHERE image_path ~ '\\.(jpeg|jpg|png)$';
""".strip())
    print()


def main(argv: Optional[list[str]] = None) -> int:
    global WEBP_QUALITY, MAX_EDGE
    parser = argparse.ArgumentParser(
        description="Resize + convert supplement images to WebP. Idempotent.",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Print actions without modifying files.")
    parser.add_argument("--limit", type=int, default=0,
                        help="Process at most N files (for testing). 0 = no limit.")
    parser.add_argument("--quality", type=int, default=WEBP_QUALITY,
                        help=f"WebP quality (default {WEBP_QUALITY}).")
    parser.add_argument("--max-edge", type=int, default=MAX_EDGE,
                        help=f"Max long-edge pixels (default {MAX_EDGE}).")
    parser.add_argument("--progress-every", type=int, default=50,
                        help="Print a heartbeat every N files (default 50).")
    args = parser.parse_args(argv)

    WEBP_QUALITY = args.quality
    MAX_EDGE = args.max_edge

    if not IMAGES_DIR.exists():
        print(f"ERROR: image directory not found: {IMAGES_DIR}", file=sys.stderr)
        return 1

    files = sorted(p for p in IMAGES_DIR.iterdir() if p.is_file())
    if args.limit > 0:
        files = files[: args.limit]

    print(f"Image dir   : {IMAGES_DIR}")
    print(f"Mode        : {'DRY RUN (no writes)' if args.dry_run else 'LIVE (writes enabled)'}")
    print(f"Files queued: {len(files)}")
    print(f"Settings    : long-edge ≤ {MAX_EDGE}px, WebP quality={WEBP_QUALITY}")
    print()

    stats = Stats()
    started = time.time()
    last_heartbeat = started

    for i, path in enumerate(files, 1):
        _process_file(path, stats, dry_run=args.dry_run)
        # Print a heartbeat periodically so long runs feel alive.
        if args.progress_every and i % args.progress_every == 0:
            now = time.time()
            rate = args.progress_every / max(now - last_heartbeat, 0.001)
            last_heartbeat = now
            print(f"  ... {i}/{len(files)} processed ({rate:.1f} files/s, "
                  f"so far: {_human_bytes(stats.bytes_before - stats.bytes_after)} saved)")

    elapsed = time.time() - started
    _print_summary(stats, args.dry_run, elapsed)
    _write_manifest(stats, args.dry_run)
    if stats.renames:
        _print_db_update_sql(stats)

    return 0 if stats.errors == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
