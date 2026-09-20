#!/usr/bin/env python3
"""Publish submitted speaker calibrations and keep the registry's indexes.

Everything a submission contains is untrusted.  It is unpacked with bounds,
held to the plugin's own import rules (the same function that guards loading
a shared file on someone's laptop), and then copied field by field into the
public form by the plugin's own code, so what is stored is never what was
uploaded: it is what the plugin would have written for that calibration.
The graph is drawn here from the stored numbers and never taken from anyone.

The plugin's modules are imported from a checkout pinned in PLUGIN_COMMIT.

  registry.py ingest  --plugin DIR --body-file FILE --issue N --author LOGIN
  registry.py rebuild --plugin DIR
  registry.py votes   --plugin DIR --votes-file FILE
"""

import argparse
import copy
import datetime as dt
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "profiles"
INDEX = ROOT / "index"
VOTES = ROOT / "votes.json"
LOGIN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?(\[bot\])?")
MODEL_LIMIT = 200          # profiles kept per machine model


class Refused(Exception):
    """A submission that will not be published, with the reason to tell its author."""


def load_plugin(directory):
    directory = Path(directory).resolve()
    sys.path.insert(0, str(directory))
    sys.dont_write_bytecode = True
    import calibration_share as share
    spec = importlib.util.spec_from_file_location("speaker_calibrate", directory / "speaker-calibrate.py")
    helper = importlib.util.module_from_spec(spec)
    argv, sys.argv = sys.argv, ["speaker-calibrate.py"]
    try:
        spec.loader.exec_module(helper)
    finally:
        sys.argv = argv
    return share, helper


def normalised(share, helper, body):
    """The public profile inside a submission, rebuilt by the plugin's own code."""
    try:
        uploaded = share.decode_submission(body)
    except share.NotAPublicProfile as error:
        raise Refused(str(error))
    try:
        helper.valid_shared_payload(copy.deepcopy(uploaded))
    except ValueError as error:
        raise Refused(f"it is not a calibration the plugin would load: {error}")
    except (RecursionError, OverflowError, TypeError, AttributeError, KeyError):
        raise Refused("it is not a calibration the plugin would load")
    claimed = (uploaded.get("public") or {}).get("verification") if isinstance(uploaded.get("public"), dict) else None
    verification = None
    if isinstance(claimed, dict):
        verification = {"usable": True, "verdict": claimed.get("verdict"),
                        "model_error_db": claimed.get("model_error_db"),
                        "target_error_db": {"before": claimed.get("target_error_before_db"),
                                            "after": claimed.get("target_error_after_db")}}
    try:
        public = share.public_payload(uploaded, verification)
    except share.NotAPublicProfile as error:
        raise Refused(str(error))
    if public["profile"]["quality"]["accepted"] is not True:
        raise Refused("the measurement did not pass its own quality checks")
    return public


def model_directory(share, hardware):
    vendor, product = share.hardware_key(hardware)
    return PROFILES / vendor / product


def read_json(path, fallback):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return fallback


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=1, sort_keys=True) + "\n")


def ingest(share, helper, body, issue, author):
    if not LOGIN.fullmatch(author or ""):
        raise Refused("the submitting account's name is not one GitHub would give")
    public = normalised(share, helper, body)
    identifier = share.profile_id(public)
    directory = model_directory(share, public["hardware"])
    target = directory / f"{identifier}.json"
    if target.exists():
        raise Refused(f"this exact calibration is already published as `{identifier}`")
    replaced = []
    # One account, one machine model, one kind of microphone: a new upload takes the old one's place.
    for meta_path in sorted(directory.glob("*.meta.json")):
        meta = read_json(meta_path, {})
        if meta.get("submitted_by") == author and meta.get("microphone_kind") == public["public"]["microphone_kind"]:
            stem = meta_path.name[:-len(".meta.json")]
            for suffix in (".json", ".svg", ".meta.json"):
                (directory / f"{stem}{suffix}").unlink(missing_ok=True)
            replaced.append(stem)
    if len(list(directory.glob("*.meta.json"))) >= MODEL_LIMIT:
        raise Refused("this machine model already has as many calibrations as the registry keeps")
    write_json(target, public)
    (directory / f"{identifier}.svg").write_text(share.render_svg(public))
    write_json(directory / f"{identifier}.meta.json", {
        "issue": int(issue), "submitted_by": author,
        "microphone_kind": public["public"]["microphone_kind"],
        "published_on": dt.date.today().isoformat(),
    })
    rebuild(share)
    vendor, product = share.hardware_key(public["hardware"])
    return {"id": identifier, "name": public["name"], "model": f"{vendor}/{product}",
            "score": share.objective_score(public), "replaced": replaced,
            "page": f"profiles/{vendor}/{product}/README.md"}


def rebuild(share):
    """Every index and every model page, from the stored profiles alone."""
    votes = read_json(VOTES, {})
    models = {}
    for path in sorted(PROFILES.glob("*/*/*.json")):
        if path.name.endswith(".meta.json"):
            continue
        public = read_json(path, None)
        meta = read_json(path.with_name(path.stem + ".meta.json"), {})
        if not isinstance(public, dict) or "hardware" not in public:
            continue
        identifier = path.stem
        row = share.index_entry(public, identifier=identifier, path=str(path.relative_to(ROOT)),
                                issue=meta.get("issue"), submitted_by=meta.get("submitted_by"),
                                votes=int(votes.get(identifier, 0)) if isinstance(votes, dict) else 0)
        row["published_on"] = meta.get("published_on")
        models.setdefault(path.parent, []).append(row)
    for stale in INDEX.glob("*/*.json"):
        stale.unlink()
    overview = []
    for directory, rows in sorted(models.items()):
        rows.sort(key=lambda row: row["created_at"], reverse=True)       # newest first among equals
        rows.sort(key=lambda row: -row["score"])
        vendor, product = directory.parent.name, directory.name
        write_json(INDEX / vendor / f"{product}.json", {"format": "omarchy-speaker-profiles-index/1", "profiles": rows})
        (directory / "README.md").write_text(model_page(rows))
        overview.append({"vendor": vendor, "product": product, "label": rows[0]["hardware"]["label"],
                         "profiles": len(rows), "best_score": rows[0]["score"]})
    write_json(INDEX / "all.json", {"format": "omarchy-speaker-profiles-overview/1", "models": overview})
    (ROOT / "MODELS.md").write_text(overview_page(overview))
    return overview


def model_page(rows):
    label = rows[0]["hardware"]["label"]
    lines = [f"# {label}", "",
             f"{len(rows)} shared calibration{'s' if len(rows) != 1 else ''} for this machine, best first. "
             "The Omarchy Speaker Calibrator finds these by itself on a matching machine.", ""]
    for row in rows:
        checked = row.get("verification") or {}
        facts = [f"score **{row['score']}**", row["microphone_kind"], f"measured {row['created_at']}",
                 f"plugin {row['plugin_version']}"]
        if checked.get("verdict"):
            facts.append(f"checked: {checked['verdict']}"
                         + (f", {checked['target_error_before_db']:.1f} → {checked['target_error_after_db']:.1f} dB from target"
                            if isinstance(checked.get("target_error_before_db"), (int, float))
                            and isinstance(checked.get("target_error_after_db"), (int, float)) else ""))
        else:
            facts.append("not checked")
        if row.get("votes"):
            facts.append(f"{row['votes']} 👍")
        if row.get("issue"):
            facts.append(f"[#{row['issue']}](../../../../../issues/{row['issue']})")
        lines += [f"## `{row['id']}`", "", " · ".join(facts), "", f"![response]({row['id']}.svg)", ""]
    return "\n".join(lines)


def overview_page(overview):
    lines = ["# Machines with shared calibrations", "",
             "Generated from the profiles in this repository. Do not edit by hand.", "",
             "| Machine | Calibrations | Best score |", "| --- | ---: | ---: |"]
    for item in sorted(overview, key=lambda item: item["label"].lower()):
        lines.append(f"| [{item['label']}](profiles/{item['vendor']}/{item['product']}/README.md) "
                     f"| {item['profiles']} | {item['best_score']} |")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("ingest", "rebuild", "votes"):
        command = sub.add_parser(name)
        command.add_argument("--plugin", required=True)
        if name == "ingest":
            command.add_argument("--body-file", required=True)
            command.add_argument("--issue", required=True, type=int)
            command.add_argument("--author", required=True)
        if name == "votes":
            command.add_argument("--votes-file", required=True)
    args = parser.parse_args()
    share, helper = load_plugin(args.plugin)
    if args.command == "ingest":
        body = Path(args.body_file).read_text(errors="replace")[:400_000]
        try:
            result = {"ok": True, **ingest(share, helper, body, args.issue, args.author)}
        except Refused as refusal:
            result = {"ok": False, "reason": str(refusal)[:400]}
        print(json.dumps(result))
    elif args.command == "votes":
        counted = read_json(Path(args.votes_file), {})
        known = {path.stem for path in PROFILES.glob("*/*/*.json") if not path.name.endswith(".meta.json")}
        write_json(VOTES, {key: max(0, min(100000, int(value))) for key, value in counted.items()
                           if key in known and isinstance(value, int) and not isinstance(value, bool)})
        rebuild(share)
        print(json.dumps({"ok": True}))
    else:
        print(json.dumps({"ok": True, "models": len(rebuild(share))}))


if __name__ == "__main__":
    main()
