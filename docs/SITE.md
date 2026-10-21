# Portfolio Website Documentation

Moved out of the root CLAUDE.md on 2026-09-10 so client sessions do not load it. Read this file before touching `index.html`, `js/`, `css/`, `scripts/`, `data/`, `videos/`, `images/` or `.github/workflows/`. The subtree files `scripts/CLAUDE.md`, `js/CLAUDE.md`, `css/CLAUDE.md`, `.github/CLAUDE.md` and `.claude/CLAUDE.md` load on their own when files in those folders are read.

## Video Sources Must Be 1080p (HARD RULE)

Every **local source** (`videos/source/<id>.mp4`, played fullscreen in the lightbox, `localSource: true`) MUST be pulled at the **highest quality the platform serves, targeting 1080p (short edge 1080: 1080x1920 vertical, 1920x1080 horizontal)**. A low-res copy in a client-facing portfolio is unacceptable and must never ship.

- **1080p is also the CEILING.** Never pull 4K. It is invisible on a 9:16 card and the published site has a hard **1 GB GitHub Pages limit** (check with the editor's asset audit). The variant picker in `editor-server.py` enforces this: it takes the best H.264 variant at or below `SOURCE_MAX_SHORT_EDGE = 1080`.
- **Hover previews (`videos/previews/<id>.mp4`) stay 720p on purpose.** They are muted 15-30s clips rendered in a small grid tile; 1080p there is invisible and doubles the bytes for nothing. This is a deliberate exception, not an oversight.
- **When the platform cannot serve 1080p, that is acceptable and expected** (most Instagram posts top out at 720p). What is NOT acceptable is a low pull when better was available. The distinction matters: flag, investigate, then accept or re-pull.
- **Two acceptable methods; the only thing that matters is the output resolution.**
  1. **no-SNI path** (`scripts/yt_hls_manifest.py` HLS, or the no-SNI InnerTube adaptive video+audio muxed with ffmpeg `-c copy`), what `_ensure_curated_local_sources()` uses. Immune to rate-limits, no cookies. But a flagged IP can get SABR-gated: persistent 0-byte media and `NO_HLS` even on a cold retry. When that happens do NOT hammer or wait it out; switch to method 2.
  2. **A CURRENT yt-dlp, sorting by resolution (NOT filtering by height):** `python -m yt_dlp -S "res:1080,vcodec:h264,acodec:aac" --merge-output-format mp4`. Use `-S res:1080`, never `-f "...[height<=1080]"`: yt-dlp's `res` is the **smallest dimension**, so it caps a vertical 1080x1920 correctly, whereas a `height<=1080` filter would *reject* every vertical 1080p short (height 1920) and silently hand you a 608x1080 or worse. Keep yt-dlp updated (`python -m pip install -U yt-dlp`); the bare `yt-dlp` command on PATH may be a STALE separate install, so invoke `python -m yt_dlp`.
- **NEVER trust a bare/default download.** The 2026-07 360p disaster was a stale yt-dlp with no explicit format, which defaults to format 18 (360x640 muxed). Always pass an explicit format, and force `avc1`+`m4a` (not AV1/Opus) for Safari/iOS compatibility.
- **Verification is now automatic.** The editor's "Download missing assets" job ffprobes every source in its `verifying` phase and reports anything under 1080p as `low_res` (`_video_short_edge()` in `editor-server.py`). Check that list before publishing; a short that plays soft on click has failed this rule.
- Full context, the incident, and codec reasoning: vault note "YouTube Short Full-Resolution Source Rule and no-SNI Flakiness".

## Sections Are Config-Driven (since 2026-10-21; replaces the old "section ids are load-bearing" rule)

`data/site-config.json` v2 is one ordered list of sections, each `{id, title, layout}` plus `video_ids` (wide / tall) or `groups` (hero: `{label, shorts_label, video_ids}`, one ordered list of both shapes per row; the earlier `long_form_id` + `short_form_ids` row shape is folded into it on read by `normalize_hero_group`). `sync_from_sheet.py` resolves it into the `const sections` global in `js/projects.js`; `main.js` `renderSections()` draws them in order and `initMobileTabs()` builds a phone tab per rendered section. `index.html` only carries the empty `#mobile-tabs` and `#sections-root`.

- **Layouts:** `hero` (rows of both shapes; a row lays itself out by counting its long-forms: none = full-width shorts row under the row header, six across, `.shorts-only`; one = the big tile with the shorts beside it, `.lead`; two or more = the long-forms side by side on top with the shorts beneath, `.tiers`, stacked full width on the phone), `wide` (16:9 grid, `.grid.grid-wide`), `tall` (9:16 grid, `.grid.grid-tall`).
- **Headers (2026-10-21 evening):** three levels, all from the config: the section title (20px/500 white with a hairline under it), the row header `.featured-eyebrow` (`label`, else the first long-form's channel; 13px/500 uppercase white with a bar before it) and the shorts label `.featured-shorts-label` (`shorts_label`, else "Related shorts"; 11px grey). Nothing is hard-coded in the renderer.
- **Titles are free text** and double as the phone tab label. Ids are slugs for the DOM only.
- **Playback never depends on the section.** Each item keeps its own `category` from the library, so `localSource` and the lightbox route follow the video, not where it sits. Renaming or re-laying-out a section cannot blank a grid or break short playback any more. Empty sections are kept in the config but not drawn.
- **v1 configs migrate automatically** (`migrate_site_config` in `sync_from_sheet.py`; the editor and the server call it too): the old `featured` list becomes a hero section titled "Featured", the old `short-form` section a tall grid, everything else a wide grid. `.tmp/site-config.v1.backup.json` holds the last v1 file.
- **Grids have a shape, strictly; hero rows take both.** Wide grids take horizontal (long-form) videos only and tall grids vertical (short-form) only; a hero row takes both shapes in one ordered list. The editor refuses wrong-shape drops into grids (and fades the wrong zones while dragging), only offers layout switches that fit every video in the section (others are disabled, never a "will be dropped" warning), and the server's `validate_site_config` rejects a grid mismatch on save or publish.

## Hosted Copies and Subtitle Tracks (since 2026-10-21)

A video can play from a **self-hosted copy with a subtitle track** instead of the YouTube embed. Built for Portuguese long-forms that need English subtitles: the embed cannot carry our own track, and a subtitle layer drawn over it would vanish in fullscreen on iPhone (Safari still cannot fullscreen a non-video element), whereas a native `<track>` on our own `<video>` survives every fullscreen mode.

- **Manifest:** `data/media.json` (tracked) maps a video id to `{src, subtitles, subtitlesLang, subtitlesLabel}`. `sync_from_sheet.py` reads it and emits `videoSrc` + `subtitles*` fields into `projects.js` (only when present; a `.vtt` missing from disk, or a track with no player of our own, is dropped with a warning).
- **The mp4 lives on the GitHub release tagged `media`**, never in the repo: the repo is ~730 MB of the 1 GB Pages limit. `gh release upload media <id>.mp4 --clobber`; URL `https://github.com/daniaparecido/danis-office/releases/download/media/<id>.mp4`. Pull it with the same 1080p rule as sources (`-S "res:1080,vcodec:h264,acodec:aac"`); yt-dlp's merge already writes faststart (check `ftyp, moov, ..., mdat` order). Release downloads support range requests, so seeking works.
- **Subtitles:** `videos/subs/<id>.<lang>.vtt`, tracked. `python scripts/srt_to_vtt.py in.srt out.vtt` converts and refuses em/en dashes (customer-facing text).
- **Front end:** `openHostedLightbox(project)` in `main.js` builds `<video class="hosted-player">` with a `<track default>` inside the 16:9 `.video-container.hosted-video`, forces the track to `showing`, falls back to the YouTube embed if the hosted file errors, and shows the usual "Watch on YouTube" pill. Cards with a track get an `.subs-badge` ("EN subtitles"). A YouTube short with `localSource` also gets the track if the manifest has one.
- First video: `TZfM1yfkFn4` ("Adeus Windows! Bem-vindo Linux!", Coisa de Nerd), 155 MB at YouTube 1080p, 215 English cues.

## Project Overview

A portfolio website for Daniel Aparecido (Video Editor and Motion Designer) showcasing video work from YouTube, Instagram, and TikTok.

## Tech Stack

- **Frontend**: Vanilla HTML/CSS/JavaScript
- **Backend**: Static site (no server)
- **Data Source**: Google Sheets (synced via Python script)
- **Hosting**: GitHub Pages (auto-deploys on push to main)
- **CI/CD**: GitHub Actions, **three** workflows chained daily: `update-tracker-stats.yml` (09:00 UTC cron, populates the Sheets, commits nothing here) → on completion `update-videos.yml` (mirror, commits derived files) → which dispatches `deploy.yml` (Pages). The dispatch is required because a push made with `GITHUB_TOKEN` never triggers `deploy.yml`'s `on: push`; without it the live site froze on 2026-08-21 data until 2026-10-21. Details in `.github/CLAUDE.md`.

## Project Structure

```
Dani's Office/
├── index.html              # The only live page
├── about.html              # ORPHANED: nothing links to it, but still tracked + served
├── js/
│   ├── projects.js         # AUTO-GENERATED, never hand-edit
│   └── main.js             # Grid, lightbox, hover previews, odometer
├── css/styles.css          # All styling (flat, no token layer)
├── data/                   # THE PIPELINE'S CORE
│   ├── library.json        # GENERATED mirror of both sheets (all items)
│   ├── site-config.json    # HAND-CURATED (via the editor): featured + sections
│   └── site-config.schema.json
├── scripts/                # Mostly gitignored; only sync_from_sheet.py is tracked
│   ├── sync_from_sheet.py  # MIRROR ONLY (sheets -> library.json -> projects.js)
│   ├── editor-server.py    # Local editor backend (save/publish/assets/quality gate)
│   ├── process_previews.py # Hover previews via the no-SNI HLS path (LIVE path)
│   ├── yt_hls_manifest.py  # no-SNI InnerTube manifest extractor
│   ├── fetch_thumbnails.py # Re-pull IG/TikTok thumbs whose signed URLs expired
│   └── process-videos.ps1  # SUPERSEDED, kept only for its manual -Url mode
├── editor.html             # Local curation UI (gitignored)
├── electron/               # Desktop wrapper for the editor (gitignored)
├── tracker/                # Populates the Google Sheets; tracked because CI runs it
├── videos/
│   ├── source/             # Lightbox mp4s. ALL gitignored by default; publish
│   │                       #   force-adds the ones projects.js references
│   └── previews/           # 720p muted hover clips
├── images/thumbnails/      # IG/TikTok card thumbs (YouTube uses the CDN)
├── docs/SITE.md            # This file
├── .github/workflows/
│   ├── deploy.yml              # Pages deploy on push to main
│   ├── update-videos.yml       # Daily: mirror sheets -> commits library/projects
│   └── update-tracker-stats.yml # Daily: populate the sheets (commits nothing here)
└── .claude/                # settings, agents, project skills (orahi, team-liquid, orahi-meeting-notes, update-docs)
```

## Workflow

### Launching the editor

Start menu: **Dani's Office Editor** (pin it to the taskbar from there). The app writes that shortcut itself on every launch (`ensureStartMenuShortcut()` in `electron/main.js`), so it survives a moved repo or an Electron update. `scripts/editor-app.bat` still works (it keeps a console window open). Only one editor runs at a time: a second launch focuses the open window, and the server refuses to start twice.

### Adding New Videos (editor v2, since 2026-10-21)

1. Add the video URL to the correct Google Sheet tab (**Long-form** / **Short-form** on the YouTube sheet, **Instagram** / **TikTok** on the socials sheet).
2. In the editor (`scripts/editor-app.bat`), click **Populate new videos**. That dispatches the `update-tracker-stats.yml` workflow, which fills in metadata upstream in the sheets, then mirrors locally (GitHub also mirrors and redeploys on its own when the workflow finishes).
3. Drag the video into a section (a grid, or a hero row, which takes both shapes in order and shows a hint line saying how the row will lay out). **Its assets are fetched the moment it lands**: the card shows a pill going `queued` → `thumbnail` / `source` / `preview` → `ready`. Drag between sections to move; the library greys out what is already on the site; a drop into the wrong category is refused. `+ Add, Section` creates a named section with a layout (hero rows / wide grid / tall grid); a hero section's `+ Row` adds a row; each row has two editable headers (row name, shorts label) next to its videos.
4. To subtitle a video, **drop an `.srt` on its card** (or click `CC`). The server converts it to WebVTT, and for a YouTube long-form pulls the 1080p copy, uploads it to the `media` release and writes `data/media.json`; shorts, Instagram and TikTok attach the track to their local source. Progress shows in the same pill.
5. **Save & Publish**. It pulls, regenerates, and **refuses to ship while any placed video still misses a required asset** (dialog with the list, "Fetch missing now" or "Publish anyway"), then bumps the cache-buster, commits, pushes.

**Top bar: three controls, every one with a hover tooltip.** `+ Add` (Video by link, Section), `Data` (sheet freshness per platform and the nightly run's result; Refresh the videos on the site; Fetch new sheet rows; **Sync everything**), `Save` with a dropdown (Save & Publish, Discard changes).

**Sync everything** (the master button, bottom of Data) brings every source in line in one go: pushes the login cookies to GitHub (platforms whose local jar is logged in), force-queues an asset check for every placed video, and runs the tracker in `full` mode per platform (populate new rows, then refresh every row's stats), then reloads the library and shows one summary dialog. Replaced the separate Refresh everything / Re-check assets / Push login cookies items on 2026-10-21; "Reload from disk" became "Discard changes" under Save.

**Data runs the tracker locally.** The Data actions run `tracker/<platform>/main.py` on this PC as background jobs (`/api/tracker/run`, status in `/api/tracker/status`, progress in the top badge), with `tracker/.env` and the local cookie jars, then re-mirror the sheets. "Refresh the videos on the site" passes `--only <placed ids>` (33 videos in about 90 s; YouTube alone in 10 s). "Video by link" appends the URL to the right tab (`/api/tracker/add-url`, duplicate-checked against the library and the tab) and runs populate; the video appears in the library about 17 s later. "Push login cookies" uploads only the platform's own cookie lines to the GitHub secret (the local jars also hold Google session cookies, which must never leave the machine) and refuses a jar without a login session. The nightly GitHub workflow is unchanged and remains the unattended fallback.

"Re-check assets" re-queues every placed video that lacks something; it is a safety net, not a step. The editor runs one server-side operation at a time, writes every file temp-then-rename, and refuses POSTs from any origin but itself. Backend: `scripts/editor-server.py` (gitignored), endpoints `/api/assets/ensure`, `/api/assets/status`, `/api/media/subtitles`, `/api/media/remove`, `/api/publish` (`{config, force}`), `/api/state`, `/api/ping`. The Electron wrapper picks a free port and pairs with its own server via `EDITOR_TOKEN`.

`scripts/update-portfolio.bat` is **misleading**: its flags are no-ops, so it is now identical to `sync-videos.bat` and does NOT download anything or make previews.

### Platform Behavior

| Platform  | Thumbnail Source | Hover Preview | Click Action | Lightbox Content |
|-----------|------------------|---------------|--------------|------------------|
| YouTube   | YouTube CDN      | Local .mp4    | Lightbox | YouTube embed + "Watch on YouTube" button |
| Instagram | Local file       | Local .mp4    | Lightbox | Local full video + "Watch on Instagram" button |
| TikTok    | Local file       | Local .mp4    | Lightbox | Local full video + "Watch on TikTok" button |

All platforms open in the lightbox with full playback (YouTube: embed, Instagram/TikTok: local source), a "Watch on [Platform]" pill button top-right, and clean HTML5 controls for local videos.

### Automated Stats Refresh

GitHub Actions runs daily from the 9:00 AM UTC tracker cron (GitHub often starts it hours late): the tracker fetches view counts (YouTube API / yt-dlp with `curl_cffi` impersonation for TikTok) and updates the Google Sheets; its completion triggers the mirror, which regenerates `library.json` + `projects.js`, commits, and dispatches the Pages deploy.

## Environment Variables

Two separate files, same variable names, different consumers:

- **root `.env`**: read by `scripts/sync_from_sheet.py`. Only `GOOGLE_SERVICE_ACCOUNT_FILE` (or `GOOGLE_SERVICE_ACCOUNT_JSON` in CI) actually matters. **`GOOGLE_SHEET_ID` is dead here**: both sheet IDs are hardcoded constants (`YOUTUBE_LIBRARY_ID`, `IGTT_LIBRARY_ID`).
- **`tracker/.env`**: read by the tracker scripts, which DO use `GOOGLE_SHEET_ID`, `SOCIAL_SHEET_ID` and `YOUTUBE_API_KEY`.

```
YOUTUBE_API_KEY=...              # tracker only
GOOGLE_SHEET_ID=...              # tracker only
GOOGLE_SERVICE_ACCOUNT_FILE=path/to/credentials.json
```

## Google Sheet Structure

**Two spreadsheets**, four tabs (defined in `SOURCES` in `scripts/sync_from_sheet.py`; the old `WORKSHEET_CONFIG` no longer exists):

| Spreadsheet | Tab | Category | Platform |
|---|---|---|---|
| YouTube library | **Long-form** | long-form | youtube |
| YouTube library | **Short-form** | short-form | youtube |
| Socials library | **Instagram** | short-form | instagram |
| Socials library | **TikTok** | short-form | tiktok |

There is **no Motion Design tab**. The `motion-design` section exists in `site-config.json` and the editor lets you curate into it, but `index.html` has no such grid and `main.js` filters only `long-form` / `short-form`, so anything put there is silently dropped by the front end.

## Project Skills

- `/orahi` and `/team-liquid`: client packs (see the root CLAUDE.md, Clients).
- `/orahi-meeting-notes`: find, read and bank Orahi Labs Gemini meeting notes and transcripts; also reads `dani@orahilabs.com` mail (project-local).
- `/update-docs`: update all CLAUDE.md files to reflect the current codebase (global).

There is no `/sync-videos` skill; `sync-videos.bat` is the script.

## Subtree Memory Files

- `scripts/CLAUDE.md`: script parameters and workflow
- `js/CLAUDE.md`: JavaScript functions and behavior
- `css/CLAUDE.md`: design system and components
- `.github/CLAUDE.md`: GitHub Actions configuration
- `.claude/CLAUDE.md`: skills and agents

Run `/update-docs` to refresh all memory files after significant changes.
