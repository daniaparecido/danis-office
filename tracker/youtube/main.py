"""Main script to fetch YouTube video data and update Google Sheets."""

import os
import sys
import logging
import argparse

# Add parent directory to path for shared modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from youtube_client import YouTubeClient
from sheets_client import SheetsClient, WORKSHEETS, find_duplicate_rows, filter_rows_to_ids, parse_only

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


def load_config() -> dict:
    """Load configuration from environment variables."""
    load_dotenv()

    config = {
        "youtube_api_key": os.getenv("YOUTUBE_API_KEY"),
        "google_sheet_id": os.getenv("GOOGLE_SHEET_ID"),
        "credentials_file": os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE"),
        "credentials_json": os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON"),
    }

    if not config["youtube_api_key"]:
        logger.error("YOUTUBE_API_KEY environment variable is required")
        sys.exit(1)

    if not config["google_sheet_id"]:
        logger.error("GOOGLE_SHEET_ID environment variable is required")
        sys.exit(1)

    if not config["credentials_file"] and not config["credentials_json"]:
        logger.error("Either GOOGLE_SERVICE_ACCOUNT_FILE or GOOGLE_SERVICE_ACCOUNT_JSON is required")
        sys.exit(1)

    return config


def populate_new_videos(youtube: YouTubeClient, sheets: SheetsClient):
    """Populate ALL data for new videos only (rows without Video ID)."""
    logger.info("Mode: POPULATE NEW VIDEOS")
    logger.info("-" * 50)

    rows = sheets.get_all_rows()
    logger.info(f"Found {len(rows)} URLs in sheet")

    if not rows:
        logger.info("No URLs to process. Add YouTube video URLs to column A.")
        return

    # Targets: brand-new rows (no Video ID) AND half-filled rows (have an id but
    # never got metadata) so a stalled row can self-heal instead of being skipped
    # forever. Duplicate-id rows are dropped (keep first occurrence) and flagged.
    dup_rows = find_duplicate_rows(rows, youtube.extract_video_id)
    targets = [r for r in rows if (not r["has_data"]) or r.get("incomplete")]
    skipped_dups = [r for r in targets if r["row_num"] in dup_rows]
    for r in skipped_dups:
        logger.warning(f"Row {r['row_num']}: duplicate video id '{dup_rows[r['row_num']]}' "
                       f"already in sheet ({r['url']}); skipping populate")
    targets = [r for r in targets if r["row_num"] not in dup_rows]
    new_count = sum(1 for r in targets if not r["has_data"])
    heal_count = len(targets) - new_count
    logger.info(f"Found {len(targets)} URLs to populate ({new_count} new, {heal_count} incomplete); "
                f"skipped {len(skipped_dups)} duplicates")

    if not targets:
        logger.info("All videos already have data. Nothing to populate.")
        return

    # Extract video IDs from URLs
    url_to_row = {}
    for row in targets:
        video_id = youtube.extract_video_id(row["url"])
        if video_id:
            url_to_row[video_id] = (row["row_num"], row["url"])
        else:
            logger.warning(f"Row {row['row_num']}: Could not extract video ID from URL")

    if not url_to_row:
        logger.warning("No valid YouTube URLs found")
        return

    # Fetch video details from YouTube
    video_ids = list(url_to_row.keys())
    logger.info(f"Fetching data for {len(video_ids)} videos...")
    video_data = youtube.get_video_details(video_ids)

    if len(video_ids) >= 3 and not video_data:
        msg = "YouTube: all %d metadata fetches returned nothing - check YOUTUBE_API_KEY / quota." % len(video_ids)
        logger.error(msg)
        print(f"::error::{msg}")
        sys.exit(1)

    # Update sheet rows
    updates = []
    for video_id, data in video_data.items():
        row_num, url = url_to_row[video_id]
        updates.append((row_num, url, data))

    if updates:
        sheets.batch_update_rows(updates)

    logger.info(f"Populated {len(updates)} new videos")


def refresh_stats(youtube: YouTubeClient, sheets: SheetsClient, only=None):
    """Refresh only Views, Likes, Comments for existing videos. `only` restricts
    the pass to those video ids (the editor's "refresh the videos on the site")."""
    logger.info("Mode: REFRESH STATS")
    logger.info("-" * 50)

    rows = sheets.get_all_rows()
    logger.info(f"Found {len(rows)} URLs in sheet")

    # Filter to only existing rows (have Video ID)
    existing_rows = [r for r in rows if r["has_data"]]
    if only:
        existing_rows = filter_rows_to_ids(existing_rows, only, youtube.extract_video_id)
        logger.info(f"--only: {len(existing_rows)} of the requested ids are in this tab")
    logger.info(f"Found {len(existing_rows)} existing videos to refresh")

    if not existing_rows:
        logger.info("No existing videos to refresh.")
        return

    # Extract video IDs from URLs
    url_to_row = {}
    for row in existing_rows:
        video_id = youtube.extract_video_id(row["url"])
        if video_id:
            url_to_row[video_id] = row["row_num"]

    if not url_to_row:
        return

    # Fetch video stats from YouTube
    video_ids = list(url_to_row.keys())
    logger.info(f"Fetching stats for {len(video_ids)} videos...")
    video_data = youtube.get_video_stats(video_ids)

    if len(video_ids) >= 3 and not video_data:
        msg = "YouTube: all %d stat fetches returned nothing - check YOUTUBE_API_KEY / quota." % len(video_ids)
        logger.error(msg)
        print(f"::error::{msg}")
        sys.exit(1)

    # Update only stats columns
    updates = []
    for video_id, stats in video_data.items():
        row_num = url_to_row[video_id]
        updates.append((row_num, stats))

    if updates:
        sheets.batch_update_stats(updates)

    logger.info(f"Refreshed stats for {len(updates)} videos")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="YouTube Video Tracker")
    parser.add_argument("--refresh-stats", action="store_true",
                        help="Only refresh Views, Likes, Comments for existing videos")
    parser.add_argument("--only", default="",
                        help="With --refresh-stats: comma-separated video ids to refresh (default: every row)")
    args = parser.parse_args()
    only = parse_only(args.only)

    logger.info("=" * 50)
    logger.info("YouTube Video Tracker")
    logger.info("=" * 50)

    config = load_config()

    youtube = YouTubeClient(config["youtube_api_key"])

    # Process each worksheet (Long-form, Short-form)
    for worksheet_name in WORKSHEETS:
        logger.info("")
        logger.info(f"Processing: {worksheet_name}")
        logger.info("-" * 50)

        sheets = SheetsClient(
            sheet_id=config["google_sheet_id"],
            worksheet_name=worksheet_name,
            credentials_file=config["credentials_file"],
            credentials_json=config["credentials_json"]
        )

        sheets.ensure_headers()

        if args.refresh_stats:
            refresh_stats(youtube, sheets, only=only)
        else:
            populate_new_videos(youtube, sheets)

    # Summary
    logger.info("")
    logger.info("=" * 50)
    logger.info("COMPLETE")
    logger.info(f"  API requests: {youtube.request_count}")
    logger.info("=" * 50)


if __name__ == "__main__":
    main()
