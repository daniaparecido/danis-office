"""Main script to fetch Instagram video/reel data and update Google Sheets."""

import os
import sys
import logging
import argparse

# Add parent directory to path for shared modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from instagram_client import InstagramClient
from sheets_client import SheetsClient, HEADERS_INSTAGRAM, is_stale, find_duplicate_rows, filter_rows_to_ids, parse_only

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

WORKSHEET_NAME = "Instagram"


def load_config() -> dict:
    """Load configuration from environment variables."""
    load_dotenv()

    config = {
        "google_sheet_id": os.getenv("SOCIAL_SHEET_ID"),
        "credentials_file": os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE"),
        "credentials_json": os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON"),
    }

    if not config["google_sheet_id"]:
        logger.error("SOCIAL_SHEET_ID environment variable is required")
        sys.exit(1)

    if not config["credentials_file"] and not config["credentials_json"]:
        logger.error("Either GOOGLE_SERVICE_ACCOUNT_FILE or GOOGLE_SERVICE_ACCOUNT_JSON is required")
        sys.exit(1)

    return config


def populate_new_videos(client: InstagramClient, sheets: SheetsClient):
    """Populate ALL data for new videos only (rows without Video ID)."""
    logger.info("Mode: POPULATE NEW VIDEOS")
    logger.info("-" * 50)

    rows = sheets.get_all_rows()
    logger.info(f"Found {len(rows)} URLs in sheet")

    if not rows:
        logger.info("No URLs to process. Add Instagram reel/video URLs to column A.")
        return

    # Targets: brand-new rows (no Video ID) AND half-filled rows (have an id but
    # never got metadata) so a stalled row can self-heal instead of being skipped
    # forever. Duplicate-id rows are dropped (keep first occurrence) and flagged.
    dup_rows = find_duplicate_rows(rows, client.extract_post_id)
    targets = [r for r in rows if (not r["has_data"]) or r.get("incomplete")]
    skipped_dups = [r for r in targets if r["row_num"] in dup_rows]
    for r in skipped_dups:
        logger.warning(f"Row {r['row_num']}: duplicate post id '{dup_rows[r['row_num']]}' "
                       f"already in sheet ({r['url']}); skipping populate")
    targets = [r for r in targets if r["row_num"] not in dup_rows]
    new_count = sum(1 for r in targets if not r["has_data"])
    heal_count = len(targets) - new_count
    logger.info(f"Found {len(targets)} URLs to populate ({new_count} new, {heal_count} incomplete); "
                f"skipped {len(skipped_dups)} duplicates")

    if not targets:
        logger.info("All videos already have data. Nothing to populate.")
        return

    # Build URL to row mapping
    url_to_row = {}
    for row in targets:
        post_id = client.extract_post_id(row["url"])
        if post_id:
            url_to_row[row["url"]] = (row["row_num"], post_id)
        else:
            logger.warning(f"Row {row['row_num']}: Could not extract post ID from URL")

    if not url_to_row:
        logger.warning("No valid Instagram URLs found")
        return

    # Fetch video details
    urls = list(url_to_row.keys())
    logger.info(f"Fetching data for {len(urls)} videos...")
    video_data = client.get_video_details(urls)

    # Loud failure: if several URLs were attempted and none came back, the cookie
    # jar is almost certainly expired/blocked. Fail the job so it does not end
    # green with 0 updates (which is how Instagram silently froze for a month).
    if len(urls) >= 3 and not video_data:
        msg = "Instagram: all %d metadata fetches failed - cookies likely expired or blocked." % len(urls)
        logger.error(msg)
        print(f"::error::{msg}")
        sys.exit(1)

    # Update sheet rows
    updates = []
    for url, (row_num, post_id) in url_to_row.items():
        if post_id in video_data:
            updates.append((row_num, url, video_data[post_id]))

    if updates:
        sheets.batch_update_rows(updates)

    logger.info(f"Populated {len(updates)} new videos")


def refresh_stats(client: InstagramClient, sheets: SheetsClient, max_age_days: int = 0, only=None):
    """Refresh only Views, Likes, Comments for existing videos.

    max_age_days > 0 skips rows whose "Last Updated" stamp is newer than N days,
    so a refresh doesn't have to hit every row at once (anti rate-limiting).
    `only` restricts the pass to those post ids (the editor's targeted refresh).
    """
    logger.info("Mode: REFRESH STATS")
    logger.info("-" * 50)

    rows = sheets.get_all_rows()
    logger.info(f"Found {len(rows)} URLs in sheet")

    # Filter to only existing rows (have Video ID)
    existing_rows = [r for r in rows if r["has_data"]]
    if only:
        existing_rows = filter_rows_to_ids(existing_rows, only, client.extract_post_id)
        logger.info(f"--only: {len(existing_rows)} of the requested ids are in this tab")
    logger.info(f"Found {len(existing_rows)} existing videos")

    if max_age_days > 0 and not only:
        before = len(existing_rows)
        existing_rows = [r for r in existing_rows if is_stale(r.get("last_updated", ""), max_age_days)]
        logger.info(f"Staleness filter (>{max_age_days}d): refreshing {len(existing_rows)}, "
                    f"skipping {before - len(existing_rows)} recently updated")

    if not existing_rows:
        logger.info("No existing videos to refresh.")
        return

    # Build URL to row mapping
    url_to_row = {}
    for row in existing_rows:
        post_id = client.extract_post_id(row["url"])
        if post_id:
            url_to_row[row["url"]] = (row["row_num"], post_id)

    if not url_to_row:
        return

    # Fetch video stats
    urls = list(url_to_row.keys())
    logger.info(f"Fetching stats for {len(urls)} videos...")
    video_data = client.get_video_stats(urls)

    # Loud failure on a total wipeout (expired/blocked cookies), so a freeze is
    # caught instead of silently leaving every stat stale.
    if len(urls) >= 3 and not video_data:
        msg = "Instagram: all %d stat fetches failed - cookies likely expired or blocked." % len(urls)
        logger.error(msg)
        print(f"::error::{msg}")
        sys.exit(1)

    # Update only stats columns
    updates = []
    for url, (row_num, post_id) in url_to_row.items():
        if post_id in video_data:
            updates.append((row_num, video_data[post_id]))

    if updates:
        sheets.batch_update_stats(updates)

    logger.info(f"Refreshed stats for {len(updates)} videos")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Instagram Video Tracker")
    parser.add_argument("--refresh-stats", action="store_true",
                        help="Only refresh Views, Likes, Comments for existing videos")
    parser.add_argument("--max-age-days", type=int, default=0,
                        help="With --refresh-stats: only refresh rows older than N days (0 = refresh all)")
    parser.add_argument("--browser", type=str, default=None,
                        help="Browser to get cookies from (firefox recommended)")
    parser.add_argument("--cookies", type=str, default=None,
                        help="Path to cookies.txt file (Netscape format)")
    parser.add_argument("--only", default="",
                        help="With --refresh-stats: comma-separated post ids to refresh (default: every row)")
    args = parser.parse_args()

    logger.info("=" * 50)
    logger.info("Instagram Video Tracker")
    logger.info("=" * 50)

    config = load_config()

    client = InstagramClient(cookies_from_browser=args.browser, cookies_file=args.cookies)

    sheets = SheetsClient(
        sheet_id=config["google_sheet_id"],
        worksheet_name=WORKSHEET_NAME,
        credentials_file=config["credentials_file"],
        credentials_json=config["credentials_json"],
        headers=HEADERS_INSTAGRAM
    )

    sheets.ensure_headers()

    if args.refresh_stats:
        refresh_stats(client, sheets, max_age_days=args.max_age_days, only=parse_only(args.only))
    else:
        populate_new_videos(client, sheets)

    # Summary
    logger.info("")
    logger.info("=" * 50)
    logger.info("COMPLETE")
    logger.info(f"  Requests: {client.request_count}")
    logger.info("=" * 50)


if __name__ == "__main__":
    main()
