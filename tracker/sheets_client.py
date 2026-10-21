"""Google Sheets client for reading URLs and writing video data."""

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional
import gspread
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

HEADERS = ["URL", "Video ID", "Title", "Channel", "Duration", "Views", "Likes", "Comments", "Published", "Thumbnail", "Last Updated"]

# Instagram headers (no Views column)
HEADERS_INSTAGRAM = ["URL", "Video ID", "Title", "Channel", "Duration", "Likes", "Comments", "Published", "Thumbnail", "Last Updated"]

# Worksheet names for different video types
WORKSHEETS = ["Long-form", "Short-form"]

GMT_MINUS_3 = timezone(timedelta(hours=-3))


def get_timestamp() -> str:
    """Get current timestamp in GMT-3."""
    return datetime.now(GMT_MINUS_3).strftime("%Y-%m-%d %H:%M")


def is_stale(last_updated: str, max_age_days: int) -> bool:
    """True if a row's "Last Updated" stamp is older than max_age_days, or absent/unparseable.

    max_age_days <= 0 disables the filter (every row counts as stale, i.e. refresh all).
    Blank or malformed timestamps are treated as stale so they always get refreshed.
    """
    if max_age_days <= 0:
        return True
    last_updated = (last_updated or "").strip()
    if not last_updated:
        return True
    try:
        ts = datetime.strptime(last_updated, "%Y-%m-%d %H:%M").replace(tzinfo=GMT_MINUS_3)
    except ValueError:
        return True
    return datetime.now(GMT_MINUS_3) - ts > timedelta(days=max_age_days)


def _text(value) -> str:
    """Prefix with apostrophe to force Google Sheets to treat as text, not number/date/time.

    Used for Video ID only: we want the literal id preserved (leading-zero safe),
    never coerced into a number. Duration and Published deliberately do NOT use
    this, so the column's TIME / DATE format can render them (see _duration_cell /
    _date_cell).
    """
    return f"'{value}" if value else ""


def _duration_cell(value) -> str:
    """Duration as an HH:MM:SS string that USER_ENTERED parses into a real time
    value, so the column's TIME format ([>=0.0416667]h:mm:ss;mm:ss) renders it
    consistently. Returns "" for unknown/zero durations (photos/carousels) so the
    cell stays blank instead of showing a fake 00:00.

    The platform clients already emit HH:MM:SS, which is unambiguous to Sheets
    (a 2-part MM:SS like "1:02" would be misread as 1h02m, so we keep 3 parts)."""
    v = str(value or "").strip().lstrip("'")
    if not v or v == "00:00:00":
        return ""
    return v


def _date_cell(value) -> str:
    """Published date as a DD/MM/YYYY string that USER_ENTERED parses into a real
    date under the sheets' pt_BR locale, so the column's dd/MM/yyyy format renders
    it. Accepts ISO YYYY-MM-DD (what the clients emit) or an already-DD/MM/YYYY
    string; returns "" when unknown. Writing in the sheet locale avoids the
    day/month ambiguity that a bare ISO string can hit on some locales."""
    v = str(value or "").strip().lstrip("'")
    if not v:
        return ""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", v)
    if m:
        return f"{m.group(3)}/{m.group(2)}/{m.group(1)}"
    return v


def extract_video_id_generic(url: str) -> Optional[str]:
    """Canonical platform-agnostic video/post id for duplicate detection.

    Mirrors the per-platform extractors so the dedup guard can key on the same id
    the site (sync_from_sheet.py) dedupes by, regardless of URL variant
    (watch?v= vs youtu.be vs ?feature=share, /reel/ vs /p/, etc.)."""
    if not url:
        return None
    patterns = [
        r"(?:v=|/v/|youtu\.be/|/embed/|/shorts/)([A-Za-z0-9_-]{11})",  # YouTube
        r"/(?:reel|reels|p)/([A-Za-z0-9_-]+)",                         # Instagram
        r"/video/(\d+)",                                               # TikTok
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def find_duplicate_rows(rows: list[dict], extract_id=extract_video_id_generic) -> dict:
    """Map row_num -> the video id it duplicates, for every row that is NOT the
    first occurrence of its id. Keeps the first occurrence; later rows with the
    same id are flagged. Used by the populate guard to avoid (re)populating a
    duplicate of a video that already lives in another row."""
    first_seen = {}
    dups = {}
    for r in rows:
        vid = extract_id(r["url"])
        if not vid:
            continue
        if vid in first_seen:
            dups[r["row_num"]] = vid
        else:
            first_seen[vid] = r["row_num"]
    return dups


def filter_rows_to_ids(rows: list[dict], ids, extract_id) -> list[dict]:
    """Keep only the rows whose canonical id is in `ids` (the --only flag: the
    editor refreshes just the videos that are on the site). Matches on the id
    extracted from the URL, falling back to the Video ID cell."""
    wanted = {str(i).strip() for i in ids if str(i).strip()}
    if not wanted:
        return rows
    out = []
    for r in rows:
        vid = extract_id(r["url"]) or (r.get("video_id") or "").lstrip("'")
        if vid in wanted:
            out.append(r)
    return out


def parse_only(value: str) -> list[str]:
    """'id1,id2, id3' -> ['id1', 'id2', 'id3']; '' -> []."""
    return [s.strip() for s in (value or "").split(",") if s.strip()]


class SheetsClient:
    """Client for interacting with Google Sheets."""

    def __init__(self, sheet_id: str, worksheet_name: str = "Long-form",
                 credentials_file: Optional[str] = None,
                 credentials_json: Optional[str] = None,
                 headers: list[str] = None):
        """Initialize with either a credentials file path or JSON string."""
        if credentials_json:
            creds_dict = json.loads(credentials_json)
            credentials = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        elif credentials_file:
            credentials = Credentials.from_service_account_file(credentials_file, scopes=SCOPES)
        else:
            raise ValueError("Either credentials_file or credentials_json must be provided")

        self.headers = headers if headers else HEADERS
        self.has_views = "Views" in self.headers
        self.client = gspread.authorize(credentials)
        self.spreadsheet = self.client.open_by_key(sheet_id)
        self.worksheet_name = worksheet_name
        self.worksheet = self._get_or_create_worksheet()
        logger.info(f"Connected to spreadsheet: {self.spreadsheet.title} [{worksheet_name}]")

    def _get_or_create_worksheet(self) -> gspread.Worksheet:
        """Get worksheet by name or create it with headers."""
        try:
            worksheet = self.spreadsheet.worksheet(self.worksheet_name)
            logger.info(f"Found existing {self.worksheet_name} worksheet")
        except gspread.WorksheetNotFound:
            worksheet = self.spreadsheet.add_worksheet(title=self.worksheet_name, rows=1000, cols=len(self.headers))
            worksheet.update("A1", [self.headers])
            logger.info(f"Created {self.worksheet_name} worksheet with headers")
        return worksheet

    def ensure_headers(self):
        """Ensure the worksheet has correct headers.

        Compares only the known A:.. prefix so extra helper columns to the right
        (e.g. the in-sheet "Extracted ID" / "Dup?" duplicate-detection columns)
        don't trigger a needless A1 rewrite on every run."""
        current_headers = self.worksheet.row_values(1)
        if current_headers[:len(self.headers)] != self.headers:
            self.worksheet.update("A1", [self.headers])
            logger.info("Updated headers")

    def get_all_rows(self) -> list[dict]:
        """Get all rows with their URLs, row numbers, ids, and "Last Updated" stamps.

        `has_data` is True when the Video ID cell is filled. `incomplete` is True
        when the row has a Video ID but Title AND Channel are both blank, i.e. it
        was never successfully populated (a successful fetch always sets at least
        the channel). The populate pass treats incomplete rows as work to do so a
        half-filled row can self-heal, instead of being skipped forever because it
        already has an id.
        """
        all_values = self.worksheet.get_all_values()
        last_col_idx = len(self.headers) - 1  # "Last Updated" is always the final column

        def hidx(name):
            try:
                return self.headers.index(name)
            except ValueError:
                return None

        title_idx = hidx("Title")
        channel_idx = hidx("Channel")

        rows = []
        for idx, row in enumerate(all_values[1:], start=2):  # Skip header, rows start at 2
            url = row[0] if row else ""
            if not url.strip():
                continue

            def cell(i):
                return row[i].strip() if (i is not None and i < len(row)) else ""

            video_id = cell(1)  # Column B
            has_data = video_id != ""
            title = cell(title_idx)
            channel = cell(channel_idx)
            last_updated = row[last_col_idx].strip() if len(row) > last_col_idx else ""
            rows.append({
                "row_num": idx,
                "url": url.strip(),
                "video_id": video_id,
                "has_data": has_data,
                "incomplete": has_data and not title and not channel,
                "last_updated": last_updated,
            })

        return rows

    def existing_urls(self) -> list[str]:
        """Column A below the header (cheap duplicate check before appending)."""
        return [u.strip() for u in self.worksheet.col_values(1)[1:] if u and u.strip()]

    def append_url(self, url: str) -> int:
        """Append a bare URL in column A so the next populate pass fills the row
        (what the editor's "Add video by URL" does). Returns the new row number."""
        self.worksheet.append_row([url], value_input_option="USER_ENTERED", table_range="A1")
        return len(self.worksheet.col_values(1))

    def update_row(self, row_num: int, url: str, video_data: dict):
        """Update a single row with video data."""
        timestamp = get_timestamp()

        if self.has_views:
            row_values = [
                url,
                _text(video_data.get("video_id", "")),
                video_data.get("title", ""),
                video_data.get("channel", ""),
                _duration_cell(video_data.get("duration", "")),
                video_data.get("views", 0),
                video_data.get("likes", 0),
                video_data.get("comments", 0),
                _date_cell(video_data.get("published", "")),
                video_data.get("thumbnail", ""),
                timestamp
            ]
            end_col = "K"
        else:
            row_values = [
                url,
                _text(video_data.get("video_id", "")),
                video_data.get("title", ""),
                video_data.get("channel", ""),
                _duration_cell(video_data.get("duration", "")),
                video_data.get("likes", 0),
                video_data.get("comments", 0),
                _date_cell(video_data.get("published", "")),
                video_data.get("thumbnail", ""),
                timestamp
            ]
            end_col = "J"

        self.worksheet.update(f"A{row_num}:{end_col}{row_num}", [row_values], value_input_option='USER_ENTERED')

    def batch_update_rows(self, updates: list[tuple[int, str, dict]]):
        """Batch update multiple rows. Each tuple is (row_num, url, video_data)."""
        timestamp = get_timestamp()
        end_col = "K" if self.has_views else "J"

        batch_data = []
        for row_num, url, video_data in updates:
            if self.has_views:
                row_values = [
                    url,
                    _text(video_data.get("video_id", "")),
                    video_data.get("title", ""),
                    video_data.get("channel", ""),
                    _duration_cell(video_data.get("duration", "")),
                    video_data.get("views", 0),
                    video_data.get("likes", 0),
                    video_data.get("comments", 0),
                    _date_cell(video_data.get("published", "")),
                    video_data.get("thumbnail", ""),
                    timestamp
                ]
            else:
                row_values = [
                    url,
                    _text(video_data.get("video_id", "")),
                    video_data.get("title", ""),
                    video_data.get("channel", ""),
                    _duration_cell(video_data.get("duration", "")),
                    video_data.get("likes", 0),
                    video_data.get("comments", 0),
                    _date_cell(video_data.get("published", "")),
                    video_data.get("thumbnail", ""),
                    timestamp
                ]
            batch_data.append({
                "range": f"A{row_num}:{end_col}{row_num}",
                "values": [row_values]
            })

        if batch_data:
            self.worksheet.batch_update(batch_data, value_input_option='USER_ENTERED')

        logger.info(f"Updated {len(updates)} rows")

    def batch_update_stats(self, updates: list[tuple[int, dict]]):
        """Update only stats and Last Updated. Each tuple is (row_num, stats)."""
        timestamp = get_timestamp()

        # Prepare batch updates
        batch_data = []
        for row_num, stats in updates:
            if self.has_views:
                # Stats columns F:H (Views, Likes, Comments), Last Updated K
                batch_data.append({
                    "range": f"F{row_num}:H{row_num}",
                    "values": [[
                        stats.get("views", 0),
                        stats.get("likes", 0),
                        stats.get("comments", 0),
                    ]]
                })
                batch_data.append({
                    "range": f"K{row_num}",
                    "values": [[timestamp]]
                })
            else:
                # Stats columns F:G (Likes, Comments), Last Updated J
                batch_data.append({
                    "range": f"F{row_num}:G{row_num}",
                    "values": [[
                        stats.get("likes", 0),
                        stats.get("comments", 0),
                    ]]
                })
                batch_data.append({
                    "range": f"J{row_num}",
                    "values": [[timestamp]]
                })

        # Execute batch update
        self.worksheet.batch_update(batch_data, value_input_option='USER_ENTERED')
        logger.info(f"Updated stats for {len(updates)} rows")
