#!/usr/bin/env python3
"""Tests for the registry's tools.  PLUGIN_DIR names a checkout of the plugin."""

import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import answer  # noqa: E402
import registry  # noqa: E402

PLUGIN = os.environ.get("PLUGIN_DIR", str(Path(__file__).resolve().parents[1] / ".plugin"))
share, helper = registry.load_plugin(PLUGIN)
POINTS = 64


def shared(vendor="SLIMBOOK", product="Executive-14-UC2", internal=False, day="2026-09-20", gain=-8.5):
    profile = {
        "schema_version": 5, "plugin_version": "1.2.0", "created_at": f"{day}T10:00:00+00:00",
        "microphone": {"description": "x", "channel": 0, "internal": internal, "calibration_file": None},
        "voicing": "neutral", "loudness": "matched", "bass": "full", "channel_trim": "off",
        "quality": {"accepted": True, "verdict": "pass", "warnings": [], "metrics": {"worst_repeatability_db": 0.4}},
        "fit": {"filter_count": 1, "input_gain_linear": 0.8, "weighted_rmse_before_db": 5.4,
                "weighted_rmse_after_db": 1.8,
                "filters": [{"type": "peaking", "frequency_hz": 600.0, "q": 2.6, "gain_db": gain}],
                "measured_smoothed_db": [-30.0] * POINTS, "correction_response_db": [-4.0] * POINTS,
                "predicted_response_db": [-34.0] * POINTS},
        "measurement": {"frequency_hz": [50.0 * (400.0 ** (i / (POINTS - 1))) for i in range(POINTS)],
                        "level_dbfs": [-30.0] * POINTS},
    }
    return {"format": helper.SHARE_FORMAT, "name": "x", "plugin_version": "1.2.0",
            "hardware": {"sys_vendor": vendor, "product_name": product, "product_sku": product,
                         "board_name": product, "speaker": "alsa_output.pci-0000_00_1f.3.analog-stereo"},
            "profile": profile}


def submission(**options):
    return "### Profile\n\n```text\n" + share.encode_submission(share.public_payload(shared(**options))) + "\n```\n"


class RegistryTestCase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        root = Path(self.folder.name)
        self.saved = (registry.ROOT, registry.PROFILES, registry.INDEX, registry.VOTES)
        registry.ROOT, registry.PROFILES = root, root / "profiles"
        registry.INDEX, registry.VOTES = root / "index", root / "votes.json"
        self.addCleanup(lambda: setattr(registry, "ROOT", self.saved[0]))
        self.addCleanup(lambda: setattr(registry, "PROFILES", self.saved[1]))
        self.addCleanup(lambda: setattr(registry, "INDEX", self.saved[2]))
        self.addCleanup(lambda: setattr(registry, "VOTES", self.saved[3]))
        self.root = root

    def ingest(self, body, issue=1, author="someone"):
        return registry.ingest(share, helper, body, issue, author)


class PublishingTests(RegistryTestCase):
    def test_a_submission_becomes_a_profile_a_graph_an_index_row_and_a_page(self):
        result = self.ingest(submission(), issue=7, author="octo-cat")
        self.assertEqual(result["model"], "slimbook/executive-14-uc2")
        directory = self.root / "profiles/slimbook/executive-14-uc2"
        stored = json.loads((directory / f"{result['id']}.json").read_text())
        helper.valid_shared_payload(copy.deepcopy(stored))                       # loadable as it is stored
        self.assertTrue((directory / f"{result['id']}.svg").read_text().startswith("<svg "))
        index = json.loads((self.root / "index/slimbook/executive-14-uc2.json").read_text())
        row = index["profiles"][0]
        self.assertEqual((row["id"], row["issue"], row["submitted_by"]), (result["id"], 7, "octo-cat"))
        self.assertEqual(row["path"], f"profiles/slimbook/executive-14-uc2/{result['id']}.json")
        page = (directory / "README.md").read_text()
        self.assertIn(f"![response]({result['id']}.svg)", page)
        self.assertIn("SLIMBOOK Executive-14-UC2", (self.root / "MODELS.md").read_text())
        overview = json.loads((self.root / "index/all.json").read_text())
        self.assertEqual(overview["models"][0]["profiles"], 1)

    def test_what_is_stored_is_rebuilt_never_what_was_uploaded(self):
        uploaded = share.public_payload(shared())
        uploaded["profile"]["fit"]["optimizer_message"] = "Visit https://example.com"
        uploaded["profile"]["smuggled"] = {"note": "<script>alert(1)</script>"}
        uploaded["hardware"]["label"] = "Totally Different Machine"
        uploaded["name"] = "<b>mine</b>"
        result = self.ingest(share.encode_submission(uploaded))
        text = next((self.root / "profiles").glob("*/*/*.json")).read_text()
        for smuggled in ("example.com", "script", "smuggled", "Totally Different", "<b>"):
            self.assertNotIn(smuggled, text)
        self.assertEqual(result["name"], "SLIMBOOK Executive-14-UC2 · external microphone · 2026-09-20")

    def test_a_new_upload_takes_the_place_of_the_same_author_s_earlier_one(self):
        first = self.ingest(submission(day="2026-09-18"), issue=1, author="octo-cat")
        other = self.ingest(submission(day="2026-09-19"), issue=2, author="someone-else")
        built_in = self.ingest(submission(day="2026-09-19", internal=True), issue=3, author="octo-cat")
        second = self.ingest(submission(day="2026-09-20"), issue=4, author="octo-cat")
        self.assertEqual(second["replaced"], [first["id"]])
        ids = {row["id"] for row in json.loads((self.root / "index/slimbook/executive-14-uc2.json").read_text())["profiles"]}
        self.assertEqual(ids, {other["id"], built_in["id"], second["id"]})
        self.assertFalse(list((self.root / "profiles").glob(f"*/*/{first['id']}*")))

    def test_the_same_calibration_twice_is_said_not_stored(self):
        self.ingest(submission())
        with self.assertRaisesRegex(registry.Refused, "already published"):
            self.ingest(submission(), issue=2, author="another")

    def test_the_best_comes_first_and_votes_count(self):
        built_in = self.ingest(submission(internal=True), issue=1, author="a")
        external = self.ingest(submission(), issue=2, author="b")
        rows = json.loads((self.root / "index/slimbook/executive-14-uc2.json").read_text())["profiles"]
        self.assertEqual([row["id"] for row in rows], [external["id"], built_in["id"]])
        registry.write_json(registry.VOTES, {built_in["id"]: 4, "not-a-profile": 99})
        registry.rebuild(share)
        rows = {row["id"]: row for row in json.loads((self.root / "index/slimbook/executive-14-uc2.json").read_text())["profiles"]}
        self.assertEqual(rows[built_in["id"]]["votes"], 4)
        self.assertEqual(rows[built_in["id"]]["score"], share.objective_score(share.public_payload(shared(internal=True)), 4))


class RefusalTests(RegistryTestCase):
    def test_everything_that_is_not_a_loadable_calibration_is_refused_and_nothing_is_written(self):
        outside = share.public_payload(shared(gain=-40.0))                      # beyond the protective envelope
        rejected = share.public_payload(shared())
        rejected["profile"]["quality"]["accepted"] = False
        nameless = share.public_payload(shared())
        nameless["hardware"]["product_name"] = "<script>"
        for body, reason in (
            ("my speakers sound bad", "no profile found"),
            (share.SUBMISSION_PREFIX + "\nAAAA", "cannot be unpacked"),
            (share.encode_submission(outside), "gain outside"),
            (share.encode_submission(rejected), "quality checks"),
            (share.encode_submission(nameless), "firmware does not name"),
            (share.encode_submission({"format": "something-else/1"}), "not a shared calibration"),
        ):
            with self.assertRaisesRegex(registry.Refused, reason, msg=reason):
                self.ingest(body)
        self.assertFalse(list((self.root).rglob("*.json")))

    def test_a_machine_name_cannot_walk_out_of_the_profiles_folder(self):
        for vendor, product in (("../../etc", "passwd"), ("..", ".."), ("a/b", "c\\d"), ("Dell Inc.", "../../../x")):
            try:
                self.ingest(share.encode_submission({**share.public_payload(shared()),
                                                     "hardware": {"sys_vendor": vendor, "product_name": product}}),
                            issue=9, author="x")
            except registry.Refused:
                pass
        for path in self.root.rglob("*"):
            self.assertTrue(str(path.resolve()).startswith(str(self.root.resolve())))
        self.assertFalse((self.root.parent / "etc").exists())

    def test_an_account_name_github_would_not_give_is_refused(self):
        for author in ("", "-dash", "a b", "x" * 60, "../x", None):
            with self.assertRaises(registry.Refused):
                self.ingest(submission(), author=author)


class AnswerTests(unittest.TestCase):
    def test_nothing_in_an_answer_is_markup_someone_else_chose(self):
        self.assertEqual(answer.plain("<img src=x onerror=1> [link](http://x) `code` @someone"),
                         "img src=x onerror=1 link(http://x) code someone")
        self.assertNotIn("@", answer.plain("@maintainer please"))


if __name__ == "__main__":
    unittest.main()
