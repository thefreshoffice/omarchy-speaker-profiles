#!/usr/bin/env python3
"""A week of the registry in one message, so that nobody has to watch every submission.

  digest.py --repository OWNER/NAME --days 7 [--today YYYY-MM-DD] [--mention "@someone @another"]

Prints a JSON document: {"count": N, "title": "...", "body": "..."}.  With
nothing new in the period the count is 0 and no message should be sent.
Everything in it comes from the index, which holds validated values only.
"""

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index"
REPOSITORY = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}")
MENTION = re.compile(r"@[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?")
BANDS = ((80, "excellent"), (60, "good"), (40, "fair"), (0, "rough"))


def band(score):
    return next(word for floor, word in BANDS if score >= floor)


def plain(value, limit=120):
    """Text for a message: nothing that markdown would act on."""
    return re.sub(r"[^A-Za-z0-9 .,:()/+=-]", "", str(value))[:limit]


def week(today, days):
    """The rows published in the period, by machine, and the machines that have a tuning."""
    since = today - dt.timedelta(days=days)
    found, tunings = {}, []
    for path in sorted(INDEX.glob("*/*.json")):
        try:
            document = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        rows = document.get("profiles") if isinstance(document, dict) else None
        for row in rows if isinstance(rows, list) else []:
            try:
                day = dt.date.fromisoformat(str(row.get("published_on"))[:10])
            except ValueError:
                continue
            if since < day <= today:
                label = plain((row.get("hardware") or {}).get("label") or path.stem)
                found.setdefault((label, f"profiles/{path.parent.name}/{path.stem}/README.md"), []).append(row)
        tuning = document.get("tuning") if isinstance(document, dict) else None
        if isinstance(tuning, dict) and tuning.get("path") and any(
                row.get("id") == tuning.get("profile") for rows_ in found.values() for row in rows_):
            tunings.append((plain(tuning["path"], 200), plain(tuning["profile"], 80)))
    return found, tunings


def message(today, days, mention="", repository=""):
    # Links in an issue are relative to the issue, so files are named in full.
    base = f"https://github.com/{repository}/blob/main/" if REPOSITORY.fullmatch(repository or "") else ""
    found, tunings = week(today, days)
    count = sum(len(rows) for rows in found.values())
    if not count:
        return {"count": 0, "title": "", "body": ""}
    lines = [f"{count} calibration{'s' if count != 1 else ''} published in the {days} days up to {today.isoformat()}, "
             f"for {len(found)} machine{'s' if len(found) != 1 else ''}.", ""]
    for (label, page), rows in sorted(found.items()):
        lines.append(f"### [{label}]({base}{page})")
        for row in sorted(rows, key=lambda row: -int(row.get("score") or 0)):
            score = int(row.get("score") or 0)
            checked = (row.get("verification") or {}).get("verdict")
            issue = row.get("issue")
            lines.append(f"- `{plain(row.get('id'), 80)}`: **{band(score)}**, score {score}, "
                         f"{plain(row.get('microphone_kind'), 40)}, {'checked' if checked else 'not checked'}"
                         + (f", #{int(issue)}" if isinstance(issue, int) and not isinstance(issue, bool) else ""))
        lines.append("")
    if tunings:
        lines.append("### Vendor tunings rendered from this week's calibrations")
        lines += [f"- [{path}]({base}{path}/README.md) from `{profile}`" for path, profile in tunings]
        lines.append("")
    people = " ".join(MENTION.findall(mention or ""))[:400]
    if people:
        lines.append(f"For {people}.")
    return {"count": count, "title": f"Week up to {today.isoformat()}: {count} new calibration{'s' if count != 1 else ''}",
            "body": "\n".join(lines)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--today")
    parser.add_argument("--mention", default="")
    parser.add_argument("--repository", default="")
    args = parser.parse_args()
    today = dt.date.fromisoformat(args.today) if args.today else dt.datetime.now(dt.timezone.utc).date()
    json.dump(message(today, max(1, min(31, args.days)), args.mention, args.repository), sys.stdout)


if __name__ == "__main__":
    main()
