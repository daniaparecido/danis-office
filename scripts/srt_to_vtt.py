#!/usr/bin/env python3
"""Convert a SubRip (.srt) file to WebVTT (.vtt) for the portfolio lightbox.

Usage: python scripts/srt_to_vtt.py <input.srt> <output.vtt>

WebVTT is SubRip with a `WEBVTT` header, `.` instead of `,` in timestamps, and
the three HTML-sensitive characters escaped in cue text. Cue numbers are dropped
(WebVTT allows them but they only add noise). The script refuses em and en
dashes in cue text: the subtitles are customer-facing text on the live site.
"""

import re
import sys
from pathlib import Path

TIMING_RE = re.compile(
    r"^(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})\s*$"
)
FORBIDDEN = {"—": "em dash", "–": "en dash"}


def _ts(h, m, s, ms):
    return f"{int(h):02d}:{m}:{s}.{ms}"


def _escape(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def srt_to_vtt(srt_text):
    """Return the WebVTT text for `srt_text`. Raises ValueError on a malformed
    cue or on an em/en dash in cue text."""
    blocks = re.split(r"\n\s*\n", srt_text.replace("\r\n", "\n").replace("\r", "\n").strip())
    out = ["WEBVTT", ""]
    count = 0
    for block in blocks:
        lines = [ln for ln in block.split("\n") if ln.strip() != ""]
        if not lines:
            continue
        # Optional cue number line, then the timing line, then text.
        if TIMING_RE.match(lines[0]) is None:
            lines = lines[1:]
        if not lines or TIMING_RE.match(lines[0]) is None:
            raise ValueError(f"cue without a timing line: {block[:80]!r}")
        m = TIMING_RE.match(lines[0])
        start = _ts(*m.groups()[:4])
        end = _ts(*m.groups()[4:])
        text_lines = lines[1:]
        for ln in text_lines:
            for ch, name in FORBIDDEN.items():
                if ch in ln:
                    raise ValueError(f"{name} in cue text: {ln!r}")
        out.append(f"{start} --> {end}")
        out.extend(_escape(ln) for ln in text_lines)
        out.append("")
        count += 1
    if count == 0:
        raise ValueError("no cues found")
    return "\n".join(out), count


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 2
    src, dst = Path(argv[1]), Path(argv[2])
    vtt, count = srt_to_vtt(src.read_text(encoding="utf-8-sig"))
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(vtt, encoding="utf-8", newline="\n")
    print(f"Wrote {count} cues to {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
