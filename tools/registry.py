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
  registry.py rebuild --plugin DIR        (also renders tunings/, one Omarchy vendor tuning per machine)
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
TUNINGS = ROOT / "tunings"
PLUGIN_COMMIT = ROOT / "PLUGIN_COMMIT"
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
    rebuild(share, helper)
    vendor, product = share.hardware_key(public["hardware"])
    return {"id": identifier, "name": public["name"], "model": f"{vendor}/{product}",
            "score": share.objective_score(public), "words": share.score_words(public),
            "band": share.score_band(share.objective_score(public)),
            "score_parts": {key: round(value, 1) for key, value in share.score_parts(public).items()},
            "replaced": replaced,
            "page": f"profiles/{vendor}/{product}/README.md"}


def render_tuning(share, helper, directory, rows):
    """The machine's vendor tuning, from the best calibration that qualifies.  Returns what the pages say.

    Rendering simulates twenty seconds of audio, so a tuning is only made
    again when its source, its score or the plugin that renders it changed.
    Whatever goes wrong, the registry itself still publishes: a machine
    without a tuning is the normal case, not a failure.
    """
    vendor, product = directory.parent.name, directory.name
    target = TUNINGS / vendor / product
    chosen, why_not = None, "no calibration has been shared"
    for row in rows:                                   # best first
        public = read_json(ROOT / row["path"], None)
        if not isinstance(public, dict):
            continue
        eligible, reason = share.vendor_eligible(public, row["score"])
        if eligible:
            chosen = (row, public)
            break
        if row is rows[0]:
            why_not = f"the best calibration cannot become one yet: {reason}"
    commit = PLUGIN_COMMIT.read_text().strip()[:40] if PLUGIN_COMMIT.exists() else ""
    if chosen:
        row, public = chosen
        source = {"profile": row["id"], "score": row["score"], "plugin_commit": commit,
                  "rendered_for": row.get("published_on")}
        if read_json(target / "source.json", None) == source and (target / "tuning.conf").exists():
            return {"profile": row["id"], "score": row["score"], "path": str(target.relative_to(ROOT))}
        day = str(row.get("published_on") or "")[:10]
        try:
            rendered = helper.render_registry_tuning(
                public, identifier=row["id"], score=row["score"],
                today=day if share.DATE.fullmatch(day) else public["profile"]["created_at"])
        except (SystemExit, Exception) as problem:       # noqa: BLE001 - nothing here may stop a publish
            # A runner without numpy must not cost a machine its tuning: what is there stays.
            kept = read_json(target / "source.json", None)
            if isinstance(kept, dict) and (target / "tuning.conf").exists():
                return {"profile": kept.get("profile"), "score": kept.get("score"),
                        "path": str(target.relative_to(ROOT))}
            chosen, why_not = None, "rendering it failed: " + re.sub(r"[^A-Za-z0-9 .,:;()'-]", "", str(problem))[:160]
        else:
            target.mkdir(parents=True, exist_ok=True)
            (target / "tuning.conf").write_text(rendered["tuning"])
            (target / "filter-chain.conf").write_text(rendered["chain"])
            (target / "README.md").write_text(tuning_page(share, row, rendered))
            write_json(target / "source.json", source)
            return {"profile": row["id"], "score": row["score"], "path": str(target.relative_to(ROOT))}
    if target.exists():
        for stale in target.iterdir():
            stale.unlink()
        target.rmdir()
    return {"profile": None, "why_not": why_not}


def tuning_page(share, row, rendered):
    metrics = rendered["metrics"]
    return "\n".join([
        f"# Vendor tuning: {row['hardware']['label']}", "",
        "Generated. Do not edit by hand: it is rendered again when a better calibration arrives.", "",
        f"An [Omarchy](https://github.com/omacom/omarchy) speaker tuning rendered from the best checked calibration "
        f"shared for this machine, [`{row['id']}`](../../../{row['path']}): "
        f"**{share.score_band(row['score'])}**, score **{row['score']}**, {row['microphone_kind']}.", "",
        f"- {rendered['sections']} filter sections and a lookahead limiter, with deep bass made from built-in nodes",
        f"- bass group delay swing {metrics['bass_group_delay_swing_ms']} ms, limiter headroom "
        f"{metrics['limiter_headroom_db']} dB on {metrics['signal']}", "",
        "## Offering it to Omarchy", "",
        f"1. Copy `tuning.conf` and `filter-chain.conf` into a checkout of Omarchy as "
        f"`default/audio/tunings/{rendered['slug']}/`.",
        "2. Listen to it on the hardware it names. This step is the point: nobody has, until you do.",
        "3. Fill in `validated_by` in `tuning.conf` with your name, and open a pull request.", "",
        "Omarchy's `docs/audio-tuning.md` describes what a tuning must report. The files are CC0 like "
        "everything generated here.", ""])


def rebuild(share, helper=None):
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
        tuning = render_tuning(share, helper, directory, rows) if helper is not None else {"profile": None, "why_not": ""}
        write_json(INDEX / vendor / f"{product}.json", {"format": "omarchy-speaker-profiles-index/1", "profiles": rows,
                                                        "tuning": tuning})
        (directory / "README.md").write_text(model_page(share, rows, tuning))
        overview.append({"vendor": vendor, "product": product, "label": rows[0]["hardware"]["label"],
                         "profiles": len(rows), "best_score": rows[0]["score"], "tuning": tuning.get("path")})
    if helper is not None and TUNINGS.exists():
        # A machine whose last profile was removed leaves no tuning behind.
        kept = {(item["vendor"], item["product"]) for item in overview if item.get("tuning")}
        for stale in sorted(TUNINGS.glob("*/*")):
            if stale.is_dir() and (stale.parent.name, stale.name) not in kept:
                for item in stale.iterdir():
                    item.unlink()
                stale.rmdir()
        for empty in sorted(TUNINGS.glob("*")):
            if empty.is_dir() and not any(empty.iterdir()):
                empty.rmdir()
    if helper is not None:
        TUNINGS.mkdir(parents=True, exist_ok=True)
        (TUNINGS / "README.md").write_text(tunings_page(overview))
    write_json(INDEX / "all.json", {"format": "omarchy-speaker-profiles-overview/1", "models": overview})
    (ROOT / "MODELS.md").write_text(overview_page(overview))
    return overview


def model_page(share, rows, tuning=None):
    label = rows[0]["hardware"]["label"]
    lines = [f"# {label}", "",
             f"{len(rows)} shared calibration{'s' if len(rows) != 1 else ''} for this machine, best first. "
             "The Omarchy Speaker Calibrator finds these by itself on a matching machine.", ""]
    tuning = tuning or {}
    if tuning.get("path"):
        lines += [f"**Vendor tuning:** [rendered for Omarchy](../../../{tuning['path']}/README.md) from "
                  f"`{tuning['profile']}`.", ""]
    elif tuning.get("why_not"):
        lines += [f"**Vendor tuning:** none yet, {tuning['why_not']}.", ""]
    for row in rows:
        checked = row.get("verification") or {}
        facts = [f"**{share.score_band(row['score'])}**, score **{row['score']}**", row["microphone_kind"], f"measured {row['created_at']}",
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


def tunings_page(overview):
    lines = ["# Vendor tunings", "",
             "Generated. One [Omarchy](https://github.com/omacom/omarchy) speaker tuning per machine, rendered from "
             "the best calibration shared for it that was checked and rates good. Each folder says how to offer "
             "its tuning to Omarchy; the step nobody can generate is listening to it on the hardware.", "",
             "| Machine | Tuning |", "| --- | --- |"]
    for item in sorted(overview, key=lambda item: item["label"].lower()):
        if item.get("tuning"):
            lines.append(f"| {item['label']} | [{item['vendor']}/{item['product']}]"
                         f"({item['vendor']}/{item['product']}/README.md) |")
    if len(lines) == 6:
        lines.append("| none yet | a calibration has to be checked and rate good first |")
    return "\n".join(lines) + "\n"


def overview_page(overview):
    lines = ["# Machines with shared calibrations", "",
             "Generated from the profiles in this repository. Do not edit by hand.", "",
             "| Machine | Calibrations | Best score | Vendor tuning |", "| --- | ---: | ---: | --- |"]
    for item in sorted(overview, key=lambda item: item["label"].lower()):
        lines.append(f"| [{item['label']}](profiles/{item['vendor']}/{item['product']}/README.md) "
                     f"| {item['profiles']} | {item['best_score']} | "
                     + (f"[rendered]({item['tuning']}/README.md)" if item.get("tuning") else "not yet") + " |")
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
        rebuild(share, helper)
        print(json.dumps({"ok": True}))
    else:
        print(json.dumps({"ok": True, "models": len(rebuild(share, helper))}))


if __name__ == "__main__":
    main()
