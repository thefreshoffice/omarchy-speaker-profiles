# Omarchy speaker profiles

Speaker calibrations that people measured on their own laptops with the
[Omarchy Speaker Calibrator](https://github.com/thefreshoffice/omarchy-speaker-calibrator),
shared so that someone with the same machine can use one without measuring.

Browse them by machine in [MODELS.md](MODELS.md). Each machine has a page with
every calibration for it, its graph and its score.

## Using one

You do not need this page. On a machine whose model has calibrations here, the
plugin's panel says so and loads one with a press. It plays as a preview first,
level matched against what you had, and you keep it or go back.

A calibration from here passes through the same checks as any shared file
before it touches your sound: no cut deeper than 18 dB, no boost above 6 dB,
no high-pass above 400 Hz, at most twelve filters, and a measurement that passed
its own quality checks. A profile never chooses your speaker output.

## Sharing yours

In the panel: **Advanced → Share with everyone**. With the GitHub command line
tool installed and signed in (`gh auth login`), that is one press. Without it,
the panel copies the profile and opens the form here for you to paste it into.

What is uploaded: the filters, the measured and corrected curves, how the
measurement went, and your machine's model as its firmware names it (vendor,
product, SKU, board). What is not: your user name, any path, any device name or
serial, the recordings, free text of any kind. It is published under your GitHub
account, because that is how GitHub works, and under
[CC0](LICENSE): anyone may use it for anything.

A new upload for the same machine and the same kind of microphone replaces your
earlier one. To withdraw one, comment on its submission.

## How a submission becomes a profile

1. A submission is an issue whose body carries the packed profile.
2. A workflow unpacks it with size limits at every step, holds it to the plugin's
   own import rules, and then **rebuilds** the public profile field by field with
   the plugin's own code, from a commit of the plugin pinned in
   [`PLUGIN_COMMIT`](PLUGIN_COMMIT). What is stored is never what was uploaded:
   it is what the plugin would have written for that calibration.
3. It draws the graph from the stored numbers, files the profile under
   `profiles/<vendor>/<product>/`, rebuilds that machine's index under `index/`
   and its page, answers the submission and closes it.

The plugin reads `index/<vendor>/<product>.json` for its own machine, and
nothing else, over HTTPS from this repository.

## The score

0 to 100, computed from the file, the same way for everyone:

| | points |
| --- | ---: |
| calibrated measuring microphone / external microphone / built-in microphone | 40 / 30 / 15 |
| the result was checked with the plugin and passed / passed with warnings | 25 / 12 |
| how much closer to the target the check found it, as a share of the error before | up to 15 |
| repeatability of the measurement within 0.5 / 1 / 2 dB | 10 / 6 / 3 |
| each warning on the measurement | −2, at most −10 |
| each 👍 on the submission from someone other than its author | +2, at most +10 |

A built-in microphone measures the sound at its own position, inches from one
speaker, which is why it scores lowest: such a calibration is a real improvement
and still only an estimate.

## Maintaining

- Setting the repository variable `PUBLISHING_PAUSED` to `true` stops automatic
  publishing; submissions then get the `pending` label and wait.
- To remove a profile, delete its `.json`, `.svg` and `.meta.json` and run
  `python3 tools/registry.py rebuild --plugin <plugin checkout>`.
- Tools: MIT. Profiles and everything generated from them: CC0.
