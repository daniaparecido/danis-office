#!/usr/bin/env python3
"""
Sync video library from the two source Google Sheets to local JSON.

Mirror mode (the only mode after the 2026-05-11 redesign): the script reads the
IG/TikTok library sheet and the YouTube library sheet, builds the full library
of edited videos as data/library.json, and regenerates the legacy js/projects.js
filtered down to whichever video IDs are listed in data/site-config.json
(sections + their ordered video_ids).

The two source sheets are populated and refreshed by other tooling (the daily
GitHub Actions runner is purely a mirror here, no API calls, no yt-dlp). The
data/site-config.json file is the canonical curation layer, edited via the
visual editor (editor.html) and read by both this script and the front-end.

Usage:
    python scripts/sync_from_sheet.py           # default: regenerate JSON + projects.js
    python scripts/sync_from_sheet.py --dry-run # show what would change, write nothing

Legacy flags (--populate, --refresh, --generate, --download, --fetch-thumbnails)
are accepted for backward compatibility with .bat wrappers and the /sync-videos
skill, but they no longer change behavior. Population and refresh happen in the
source sheets, not here.
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
import gspread


# ============================================
# Configuration
# ============================================

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]

ROOT_DIR = Path(__file__).parent.parent
DATA_DIR = ROOT_DIR / "data"
LIBRARY_FILE = DATA_DIR / "library.json"
SITE_CONFIG_FILE = DATA_DIR / "site-config.json"
PROJECTS_FILE = ROOT_DIR / "js" / "projects.js"
THUMBS_DIR = ROOT_DIR / "images" / "thumbnails"
PREVIEWS_DIR = ROOT_DIR / "videos" / "previews"
SOURCE_DIR = ROOT_DIR / "videos" / "source"
# Self-hosted copies + subtitle tracks (see load_media_manifest).
MEDIA_FILE = DATA_DIR / "media.json"

YOUTUBE_LIBRARY_ID = "157LkGyuY_jMWwTWKu2w4Sh9lw0qHCURXKUufFfgOgqg"
IGTT_LIBRARY_ID = "1jVd2XMhOI1MVqV9YtaBMVtXWU7IzkdZNuLYdkI5ZKdQ"

# Per source-tab metadata. category drives which section the video belongs to
# on the live site; platform is the inferred default for the rows in that tab
# (validated per-row against the URL, since the IG/TT tab is single-platform too).
SOURCES = [
    {"sheet_id": YOUTUBE_LIBRARY_ID, "tab": "Long-form",  "platform": "youtube",   "category": "long-form"},
    {"sheet_id": YOUTUBE_LIBRARY_ID, "tab": "Short-form", "platform": "youtube",   "category": "short-form"},
    {"sheet_id": IGTT_LIBRARY_ID,    "tab": "Instagram",  "platform": "instagram", "category": "short-form"},
    {"sheet_id": IGTT_LIBRARY_ID,    "tab": "TikTok",     "platform": "tiktok",    "category": "short-form"},
]

GMT_MINUS_3 = timezone(timedelta(hours=-3))


# ============================================
# Parsers
# ============================================

def parse_count(s):
    """Parse '4,5 M' / '36 k' / '229' / '' into an int or None.

    Comma is the decimal separator (Brazilian formatting). 'k' = 1e3, 'M' = 1e6.
    Empty / unparseable returns None so the front-end can distinguish "missing"
    from "zero" (notably Instagram has no Views column at all).
    """
    if s is None:
        return None
    s = str(s).strip().lower()
    if not s:
        return None
    plain = s.replace(",", "").replace(".", "").replace(" ", "")
    if plain.isdigit():
        return int(plain)
    match = re.match(r"([\d.,]+)\s*([kmb])?", s)
    if not match:
        return None
    try:
        num = float(match.group(1).replace(",", "."))
    except ValueError:
        return None
    suffix = match.group(2) or ""
    return int(num * {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}.get(suffix, 1))


def parse_duration(s):
    """Parse 'MM:SS' or 'HH:MM:SS' into total seconds. Empty returns None."""
    if not s:
        return None
    parts = str(s).strip().split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    if len(nums) == 2:
        return nums[0] * 60 + nums[1]
    if len(nums) == 3:
        return nums[0] * 3600 + nums[1] * 60 + nums[2]
    return None


def parse_published(s):
    """Parse a published date into ISO 'YYYY-MM-DD'.

    Accepts the sheet's Brazilian 'DD/MM/YYYY' (what the column renders) and a
    bare ISO 'YYYY-MM-DD' (in case a cell still holds ISO text), so neither shape
    silently becomes a null published date in library.json."""
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def extract_video_id(url, platform):
    """Pull the canonical platform-specific ID out of a URL."""
    if platform == "youtube":
        patterns = [
            r"(?:v=|/v/|youtu\.be/|/embed/|/shorts/)([a-zA-Z0-9_-]{11})",
            r"^([a-zA-Z0-9_-]{11})$",
        ]
    elif platform == "instagram":
        patterns = [r"/reel/([A-Za-z0-9_-]+)", r"/p/([A-Za-z0-9_-]+)", r"/reels/([A-Za-z0-9_-]+)"]
    elif platform == "tiktok":
        patterns = [r"/video/(\d+)", r"/v/(\d+)"]
    else:
        return None
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def get_timestamp():
    return datetime.now(GMT_MINUS_3).strftime("%Y-%m-%d %H:%M")


# ============================================
# Auth + sheet reading
# ============================================

def authorize():
    load_dotenv(ROOT_DIR / ".env")
    creds_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    creds_file = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE")
    if creds_file and not os.path.isabs(creds_file):
        creds_file = str(ROOT_DIR / creds_file)
    if creds_json:
        creds = Credentials.from_service_account_info(json.loads(creds_json), scopes=SCOPES)
    elif creds_file and os.path.exists(creds_file):
        creds = Credentials.from_service_account_file(creds_file, scopes=SCOPES)
    else:
        sys.exit("ERROR: set GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_SERVICE_ACCOUNT_FILE in .env")
    return gspread.authorize(creds)


def read_source(client, source):
    """Read one (sheet, tab) and yield library item dicts."""
    spreadsheet = client.open_by_key(source["sheet_id"])
    ws = spreadsheet.worksheet(source["tab"])
    rows = ws.get_all_values()
    if not rows:
        return []
    header = [h.strip() for h in rows[0]]

    def col(name):
        try:
            return header.index(name)
        except ValueError:
            return None

    idx = {k: col(k) for k in ["URL", "Video ID", "Title", "Channel", "Duration",
                                "Views", "Likes", "Comments", "Published",
                                "Thumbnail", "Last Updated"]}

    def cell(row, key):
        i = idx.get(key)
        if i is None or i >= len(row):
            return ""
        return row[i].strip()

    items = []
    for row in rows[1:]:
        url = cell(row, "URL")
        if not url:
            continue
        platform = source["platform"]
        video_id = cell(row, "Video ID") or extract_video_id(url, platform)
        if not video_id:
            continue

        # Prefer a local thumbnail if one is on disk; only IG/TT bother
        # downloading these locally (YouTube uses the stable CDN URL directly).
        local_thumb = THUMBS_DIR / f"{video_id}.jpg"
        if platform == "youtube":
            thumbnail = f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg"
        elif local_thumb.exists():
            thumbnail = f"images/thumbnails/{video_id}.jpg"
        else:
            thumbnail = cell(row, "Thumbnail") or None

        items.append({
            "id": video_id,
            "platform": platform,
            "category": source["category"],
            "url": url,
            "title": cell(row, "Title"),
            "channel": cell(row, "Channel"),
            "duration_sec": parse_duration(cell(row, "Duration")),
            "views": parse_count(cell(row, "Views")) if idx.get("Views") is not None else None,
            "likes": parse_count(cell(row, "Likes")),
            "comments": parse_count(cell(row, "Comments")),
            "published": parse_published(cell(row, "Published")),
            "thumbnail": thumbnail,
            "last_updated": cell(row, "Last Updated") or None,
        })
    return items


def build_library(client):
    """Read every source and return a deduped library list."""
    seen_ids = {}
    library = []
    for source in SOURCES:
        label = f"{source['platform']}/{source['tab']}"
        try:
            items = read_source(client, source)
        except Exception as e:
            print(f"  WARNING: failed to read {label}: {e}")
            continue
        print(f"  {label}: {len(items)} items")
        for item in items:
            key = item["id"]
            if key in seen_ids:
                # Collision = same video listed in two tabs. Keep the first,
                # report so the source sheet can be cleaned up.
                print(f"    duplicate id {key} ({label}); keeping first occurrence")
                continue
            seen_ids[key] = True
            library.append(item)
    return library


# ============================================
# Output: library.json + projects.js
# ============================================

def write_library_json(library, dry_run=False):
    payload = {
        "generated_at": datetime.now(GMT_MINUS_3).isoformat(timespec="seconds"),
        "count": len(library),
        "items": library,
    }
    if dry_run:
        print(f"[DRY RUN] Would write {len(library)} items to {LIBRARY_FILE}")
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_text(LIBRARY_FILE, json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"Wrote {len(library)} items to {LIBRARY_FILE}")


def atomic_write_text(path, text):
    """Temp file in the same directory, then rename: a reader (the editor, a
    browser tab) never sees a half-written library.json or projects.js."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def load_library_json():
    """The items of the existing data/library.json (for --offline)."""
    if not LIBRARY_FILE.exists():
        raise SystemExit(f"ERROR: {LIBRARY_FILE} missing; run without --offline first")
    return json.loads(LIBRARY_FILE.read_text(encoding="utf-8")).get("items", [])


def format_count_display(count, label="views"):
    if count is None:
        return ""
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M {label}"
    if count >= 1_000:
        return f"{count / 1_000:.0f}K {label}"
    return f"{count} {label}"


def escape_js(s):
    return (s or "").replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


_MEDIA_ITEMS = None


def load_media_manifest():
    """data/media.json: videos that play from a self-hosted copy instead of the
    YouTube embed, usually because they carry a subtitle track the embed cannot
    show. {id: {"src": <absolute mp4 URL>, "subtitles": <repo-relative .vtt>,
    "subtitlesLang": "en", "subtitlesLabel": "English"}}. The mp4s live on the
    GitHub release tagged `media` (the repo is near the 1 GB Pages limit); the
    .vtt files are tracked in videos/subs/. Missing file means no hosted media."""
    global _MEDIA_ITEMS
    if _MEDIA_ITEMS is None:
        if MEDIA_FILE.exists():
            _MEDIA_ITEMS = json.loads(MEDIA_FILE.read_text(encoding="utf-8")).get("items", {})
        else:
            _MEDIA_ITEMS = {}
    return _MEDIA_ITEMS


def hosted_media(item, local_source):
    """Fields a hosted copy / subtitle track adds to a project object, or {}.
    Only emits what the front end can actually use: a .vtt that is not on disk is
    dropped, and a track without any player of our own (no hosted copy, no local
    source) is dropped too, since the YouTube iframe cannot carry it."""
    media = load_media_manifest().get(item["id"])
    if not media:
        return {}
    out = {}
    src = media.get("src") or ""
    if src:
        out["videoSrc"] = src
    subs = media.get("subtitles") or ""
    if subs and not (ROOT_DIR / subs).exists():
        print(f"  WARNING: media.json subtitles for {item['id']} not on disk ({subs}); dropping track")
        subs = ""
    if subs and not (src or local_source):
        print(f"  WARNING: media.json subtitles for {item['id']} need a hosted copy or a local source; "
              f"the YouTube embed cannot show them; dropping track")
        subs = ""
    if subs:
        out["subtitles"] = subs
        out["subtitlesLang"] = media.get("subtitlesLang") or "en"
        out["subtitlesLabel"] = media.get("subtitlesLabel") or "English"
    return out


def project_obj(category, item):
    """Legacy-shaped project dict for one library item (used by both the flat
    `projects` array and the resolved `featured` groups)."""
    platform = item["platform"]
    if platform == "instagram":
        display = format_count_display(item.get("likes"), "likes")
    else:
        display = format_count_display(item.get("views"), "views")
    thumbnail = "" if platform == "youtube" else (item.get("thumbnail") or "")
    preview_rel = f"videos/previews/{item['id']}.mp4"
    has_preview = (PREVIEWS_DIR / f"{item['id']}.mp4").exists()
    # YouTube short-form gets the IG/TikTok lightbox treatment when a local mp4
    # exists: the embed pillarboxes a 9:16 short inside a 16:9 box and shows YT
    # chrome, so we'd rather play the local source. Long-form YouTube keeps the
    # embed (16:9 is the right shape for that container).
    local_source = (
        platform == "youtube"
        and category == "short-form"
        and (SOURCE_DIR / f"{item['id']}.mp4").exists()
    )
    obj = {
        "title": item.get("title", ""),
        "category": category,
        "videoId": item["id"],
        "platform": platform,
        "channelName": item.get("channel", ""),
        "viewCount": display,
        "thumbnail": thumbnail,
        "url": item.get("url", ""),
        "previewVideo": preview_rel if has_preview else "",
        "localSource": local_source,
    }
    # videoSrc / subtitles / subtitlesLang / subtitlesLabel, only when present,
    # so items without hosted media serialise exactly as before.
    obj.update(hosted_media(item, local_source))
    return obj


def resolve_featured(by_id, site_config):
    """Resolve site-config.json `featured` groups into full project objects.

    Each output group is {longForm: <project>, shortForm: [<project>, ...]}.
    Missing IDs are skipped with a warning; a group with no resolvable long-form
    is dropped entirely (nothing to anchor it on)."""
    out = []
    for group in site_config.get("featured", []):
        lf_id = group.get("long_form_id")
        lf = by_id.get(lf_id)
        if lf is None:
            print(f"  WARNING: featured long_form_id {lf_id!r} not found in library; skipping group")
            continue
        shorts = []
        for sid in group.get("short_form_ids", []):
            s = by_id.get(sid)
            if s is None:
                print(f"  WARNING: featured short_form_id {sid!r} not found in library; skipping")
                continue
            shorts.append(project_obj(s.get("category", "short-form"), s))
        out.append({
            "longForm": project_obj(lf.get("category", "long-form"), lf),
            "shortForm": shorts,
        })
    return out


def generate_projects_js(library, site_config, totals):
    """Build js/projects.js: a legacy-shaped `projects` array (the flat grids)
    plus a resolved `featured` array (the curated hero groups), both filtered to
    whatever data/site-config.json marks as visible.

    Iterates sections in order; within each section, iterates video_ids in
    order. `featured` groups are resolved from site-config.json directly so the
    front-end gets full video objects without fetching the big library.json.
    """
    by_id = {item["id"]: item for item in library}
    ordered = []
    missing = []
    for section in site_config.get("sections", []):
        category = section["id"]
        for vid in section.get("video_ids", []):
            item = by_id.get(vid)
            if item is None:
                missing.append((category, vid))
                continue
            ordered.append((category, item))
    if missing:
        for category, vid in missing:
            print(f"  WARNING: site-config id {vid} ({category}) not found in library")

    featured = resolve_featured(by_id, site_config)

    lines = [
        "/**",
        " * ============================================",
        " * PROJECT DATA - AUTO-GENERATED FROM GOOGLE SHEETS",
        " * ============================================",
        " *",
        " * Source: data/library.json (full library) filtered by data/site-config.json.",
        " * To regenerate, run: python scripts/sync_from_sheet.py",
        f" * Last updated: {get_timestamp()}",
        " */",
        "",
        f"const totalYouTubeViews = {totals['views']};",
        f"const totalYouTubeVideos = {totals['videos']};",
        # Count across every source sheet (YouTube long-form + Shorts, Instagram,
        # TikTok). The hero "published videos" stat uses this; cross-posts of the
        # same edit count once per platform on purpose.
        f"const totalVideos = {len(library)};",
        "",
        "const projects = [",
    ]
    for category, item in ordered:
        obj = project_obj(category, item)
        entry = [
            "    {",
            f'        title: "{escape_js(obj["title"])}",',
            f'        category: "{obj["category"]}",',
            f'        videoId: "{obj["videoId"]}",',
            f'        platform: "{obj["platform"]}",',
            f'        channelName: "{escape_js(obj["channelName"])}",',
            f'        viewCount: "{obj["viewCount"]}",',
            f'        thumbnail: "{obj["thumbnail"]}",',
            f'        url: "{obj["url"]}",',
            f'        previewVideo: "{obj["previewVideo"]}"',
        ]
        # Optional fields, emitted only when set (keeps diffs small).
        extras = []
        if obj.get("localSource"):
            extras.append('        localSource: true')
        if obj.get("videoSrc"):
            extras.append(f'        videoSrc: "{escape_js(obj["videoSrc"])}"')
        if obj.get("subtitles"):
            extras.append(f'        subtitles: "{escape_js(obj["subtitles"])}"')
            extras.append(f'        subtitlesLang: "{escape_js(obj["subtitlesLang"])}"')
            extras.append(f'        subtitlesLabel: "{escape_js(obj["subtitlesLabel"])}"')
        if extras:
            entry[-1] += ","
            entry.append(",\n".join(extras))
        entry.append("    },")
        lines += entry
    lines += ["];", ""]
    lines += [
        "// Curated hero groups: one big long-form video + companion shorts each.",
        "// Resolved from data/site-config.json at sync time.",
        "const featured = " + json.dumps(featured, ensure_ascii=False, indent=2) + ";",
        "",
    ]
    return "\n".join(lines)


def compute_youtube_totals(library):
    """Total YouTube views + count across the full library (both Long-form and
    Short-form). Matches the meaning of the existing totalYouTubeViews global."""
    yt = [item for item in library if item["platform"] == "youtube"]
    total_views = sum(item["views"] for item in yt if item.get("views"))
    return {"views": total_views, "videos": len(yt)}


def load_site_config():
    if not SITE_CONFIG_FILE.exists():
        print(f"  site-config.json not found at {SITE_CONFIG_FILE}; projects.js will be empty")
        return {"version": 1, "featured": [], "sections": []}
    return json.loads(SITE_CONFIG_FILE.read_text(encoding="utf-8"))


# ============================================
# Main
# ============================================

def main():
    parser = argparse.ArgumentParser(description="Sync videos from library Google Sheets")
    # Legacy flags kept for back-compat with .bat wrappers and the /sync-videos
    # skill. They no longer change behavior.
    parser.add_argument("--populate", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--refresh",  action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--generate", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--download", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--fetch-thumbnails", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--dry-run", action="store_true", help="Print what would change, write nothing")
    parser.add_argument("--offline", action="store_true",
                        help="Skip the sheets: regenerate js/projects.js from the existing data/library.json "
                             "(the editor uses this after fetching assets, so previewVideo/localSource/subtitles update without a sheet read)")
    args = parser.parse_args()

    print("=" * 50)
    print("SYNC LIBRARY (offline: regenerate from data/library.json)" if args.offline else "SYNC LIBRARY (mirror mode)")
    print("=" * 50)

    if args.offline:
        library = load_library_json()
        print(f"\nLibrary total: {len(library)} items (from disk)")
    else:
        client = authorize()
        print("\nReading source sheets:")
        library = build_library(client)
        library.sort(key=lambda it: (it["category"], it["platform"], -(it.get("views") or 0)))
        print(f"\nLibrary total: {len(library)} items")
        write_library_json(library, dry_run=args.dry_run)

    totals = compute_youtube_totals(library)
    print(f"YouTube totals: {totals['videos']} videos, {totals['views']:,} views")

    site_config = load_site_config()
    js_content = generate_projects_js(library, site_config, totals)
    visible_count = sum(len(s.get("video_ids", [])) for s in site_config.get("sections", []))
    if args.dry_run:
        print(f"[DRY RUN] Would write {visible_count} entries to {PROJECTS_FILE}")
    else:
        atomic_write_text(PROJECTS_FILE, js_content)
        print(f"Wrote {visible_count} entries to {PROJECTS_FILE}")


if __name__ == "__main__":
    main()
