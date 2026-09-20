#!/usr/bin/env python3
"""Tests for the registry's tools.  PLUGIN_DIR names a checkout of the plugin."""

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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


CHECKED = {"usable": [True] * POINTS, "verdict": "pass", "model_error_db": {"rms": 0.8},
           "target_error_db": {"before": 5.5, "planned": 1.5, "measured": 1.8}}
METRICS = {"bass_group_delay_swing_ms": 0.7, "limiter_headroom_db": 0.4, "peak_dbfs": -1.4,
           "dynamic_range_delta_lu": 0.0, "signal": "pink noise, 20 s, peaks at -0.1 dBFS"}


def submission(checked=None, **options):
    public = share.public_payload(shared(**options), checked)
    return "### Profile\n\n```text\n" + share.encode_submission(public) + "\n```\n"


class RegistryTestCase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        root = Path(self.folder.name)
        self.saved = (registry.ROOT, registry.PROFILES, registry.INDEX, registry.VOTES)
        tunings = mock.patch.multiple(registry, TUNINGS=root / "tunings", PLUGIN_COMMIT=root / "PLUGIN_COMMIT")
        tunings.start()
        self.addCleanup(tunings.stop)
        # The four figures of a tuning cost twenty seconds of simulated audio; the plugin tests them.
        figures = mock.patch.object(helper, "vendor_metrics", return_value=dict(METRICS))
        figures.start()
        self.addCleanup(figures.stop)
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


class VendorTuningTests(RegistryTestCase):
    MODEL = "slimbook/executive-14-uc2"

    def index(self):
        return json.loads((self.root / f"index/{self.MODEL}.json").read_text())

    def test_an_unchecked_calibration_is_published_and_gets_no_tuning(self):
        self.ingest(submission())
        self.assertIsNone(self.index()["tuning"]["profile"])
        self.assertIn("it has not been checked", self.index()["tuning"]["why_not"])
        self.assertEqual([item.name for item in (self.root / "tunings").iterdir()], ["README.md"])
        self.assertIn("**Vendor tuning:** none yet", (self.root / f"profiles/{self.MODEL}/README.md").read_text())

    def test_a_checked_calibration_becomes_the_machine_s_tuning_and_bash_sources_it(self):
        result = self.ingest(submission(CHECKED))
        tuning = self.index()["tuning"]
        self.assertEqual((tuning["profile"], tuning["path"]), (result["id"], f"tunings/{self.MODEL}"))
        folder = self.root / tuning["path"]
        self.assertEqual(sorted(item.name for item in folder.iterdir()),
                         ["README.md", "filter-chain.conf", "source.json", "tuning.conf"])
        self.assertIn(result["id"], (folder / "tuning.conf").read_text())
        self.assertIn('validated_by=""', (folder / "tuning.conf").read_text())
        proc = subprocess.run(["/usr/bin/bash", "-euc", 'source "$1"; printf "%s" "$sink_pattern"', "x",
                               str(folder / "tuning.conf")], capture_output=True, text=True, timeout=20)
        self.assertEqual((proc.returncode, proc.stdout), (0, "^alsa_output.pci-0000_00_1f.3.analog-stereo$"))
        self.assertIn("rendered for Omarchy", (self.root / f"profiles/{self.MODEL}/README.md").read_text())
        self.assertIn("default/audio/tunings/slimbook-executive-14-uc2/", (folder / "README.md").read_text())

    def test_a_tuning_is_only_rendered_again_when_something_changed(self):
        self.ingest(submission(CHECKED))
        before = (self.root / f"tunings/{self.MODEL}/tuning.conf").read_text()
        with mock.patch.object(helper, "render_registry_tuning", side_effect=AssertionError("rendered again")):
            registry.rebuild(share, helper)
        self.assertEqual((self.root / f"tunings/{self.MODEL}/tuning.conf").read_text(), before)
        (self.root / "PLUGIN_COMMIT").write_text("0" * 40 + "\n")             # a new plugin renders everything again
        with mock.patch.object(helper, "render_registry_tuning", side_effect=ImportError("no numpy here")) as render:
            registry.rebuild(share, helper)
        self.assertEqual(render.call_count, 1)
        # A runner that cannot render must not cost the machine the tuning it has.
        self.assertEqual((self.root / f"tunings/{self.MODEL}/tuning.conf").read_text(), before)
        self.assertEqual(self.index()["tuning"]["path"], f"tunings/{self.MODEL}")

    def test_the_tuning_follows_the_best_calibration_and_goes_when_the_profiles_go(self):
        first = self.ingest(submission(CHECKED, internal=True), author="one")
        self.assertEqual(self.index()["tuning"]["profile"], first["id"])
        second = self.ingest(submission(CHECKED, gain=-7.0), issue=2, author="two")      # an external microphone
        self.assertEqual(self.index()["tuning"]["profile"], second["id"])
        self.assertIn(second["id"], (self.root / f"tunings/{self.MODEL}/tuning.conf").read_text())
        for item in (self.root / f"profiles/{self.MODEL}").glob("*"):
            item.unlink()
        registry.rebuild(share, helper)
        self.assertFalse((self.root / "tunings/slimbook").exists())
        self.assertIn("none yet", (self.root / "tunings/README.md").read_text())

    def test_a_calibration_for_another_output_never_becomes_a_tuning(self):
        body = shared()
        body["hardware"]["speaker"] = "alsa_output.usb-Some_Dock-00.analog-stereo"
        public = share.public_payload(body, CHECKED)
        self.ingest("### Profile\n\n```text\n" + share.encode_submission(public) + "\n```\n")
        self.assertIsNone(self.index()["tuning"]["profile"])
        # The name of a USB output carries a serial number and does not travel at all.
        self.assertIn("does not name the speakers", self.index()["tuning"]["why_not"])
        self.assertFalse((self.root / "tunings/slimbook").exists())
        stored = next((self.root / "profiles/slimbook/executive-14-uc2").glob("*-*.json"))
        self.assertNotIn("Some_Dock", stored.read_text())


if __name__ == "__main__":
    unittest.main()
