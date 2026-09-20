#!/usr/bin/env python3
"""Count the thumbs-up on each published profile's submission, for the scores.

Reads which issue belongs to which profile from the registry's own files and
asks the GitHub API for that issue's reactions through the `gh` tool.  The
self-vote of whoever submitted the profile is not counted.
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def thumbs_up(repository, issue, author):
    done = subprocess.run(
        ["gh", "api", "--paginate", f"repos/{repository}/issues/{int(issue)}/reactions",
         "--jq", '.[] | select(.content == "+1") | .user.login'],
        capture_output=True, text=True, timeout=60)
    if done.returncode != 0:
        return None
    return len({login for login in done.stdout.split() if login and login != author})


def main():
    repository, out = sys.argv[1], Path(sys.argv[2])
    votes = {}
    for meta_path in sorted((ROOT / "profiles").glob("*/*/*.meta.json")):
        try:
            meta = json.loads(meta_path.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(meta.get("issue"), int):
            continue
        counted = thumbs_up(repository, meta["issue"], meta.get("submitted_by"))
        if counted is not None:
            votes[meta_path.name[:-len(".meta.json")]] = counted
    out.write_text(json.dumps(votes, indent=1, sort_keys=True) + "\n")
    print(f"counted votes for {len(votes)} profile(s)")


if __name__ == "__main__":
    main()
