#!/usr/bin/env python3
"""The comment that answers a submission, from the ingest result.  Prints markdown."""

import json
import re
import sys


def plain(value, limit=200):
    """Text for a comment: nothing that markdown or HTML would act on."""
    return re.sub(r"[^A-Za-z0-9 .,:;()'/+#·=→-]", "", str(value))[:limit]


PARTS = (("microphone", "the microphone used"), ("repeatability", "how repeatable the measurement was"),
         ("predicted_improvement", "the improvement the measurement predicts"),
         ("checked", "the check made with the plugin"), ("measured_improvement", "the improvement the check measured"),
         ("warnings", "warnings on the measurement"), ("votes", "thumbs-up from others"))


def score_lines(parts):
    """The score part by part, so that nobody has to ask where a number came from."""
    if not isinstance(parts, dict):
        return []
    shown = [f"{words} {float(parts[key]):+.1f}" for key, words in PARTS
             if isinstance(parts.get(key), (int, float)) and parts[key]]
    return ["  - " + plain("; ".join(shown), 400)] if shown else []


def main():
    result = json.loads(open(sys.argv[1]).read())
    repository = sys.argv[2]
    if result.get("ok"):
        page = f"https://github.com/{repository}/blob/main/{result['page']}"
        lines = [f"Published as `{plain(result['id'], 80)}` for **{plain(result['name'], 120)}**.", "",
                 f"- Score: **{int(result['score'])}** of 100" + (f" ({plain(result['words'], 80)})"
                                                                   if result.get("words") else "") + ".",
                 *score_lines(result.get("score_parts")),
                 "- A thumbs-up on this issue from someone it works for adds to the score."
                 + ("" if (result.get("score_parts") or {}).get("checked") else
                    " Checking the calibration in the panel and sharing it again adds more, because a check is proof."),
                 f"- It is listed with its graph on [the page for this machine]({page}), and the Omarchy Speaker "
                 "Calibrator now offers it on matching hardware."]
        if result.get("replaced"):
            lines.append("- It takes the place of your earlier upload for this machine and kind of microphone: "
                         + ", ".join(f"`{plain(item, 80)}`" for item in result["replaced"]) + ".")
        lines += ["", "Thank you for sharing it. To withdraw it, comment here and a maintainer removes it."]
    else:
        lines = ["This could not be published: " + plain(result.get("reason"), 400) + ".", "",
                 "Nothing was stored. If the file came straight from the panel's Share button, please say so "
                 "here, because then this is a bug."]
    print("\n".join(lines))


if __name__ == "__main__":
    main()
