# Vendor tuning: LENOVO 82Y5

Generated. Do not edit by hand: it is rendered again when a better calibration arrives.

An [Omarchy](https://github.com/omacom/omarchy) speaker tuning rendered from the best checked calibration shared for this machine, [`2026-11-24-external-b17e862cba`](../../../profiles/lenovo/82y5/2026-11-24-external-b17e862cba.json): **good**, score **71**, external microphone.

- 6 filter sections and a lookahead limiter, with deep bass made from built-in nodes
- bass group delay swing 0.7 ms, limiter headroom 0.5 dB on pink noise, 20 s, peaks at -0.1 dBFS

## Offering it to Omarchy

1. Copy `tuning.conf` and `filter-chain.conf` into a checkout of Omarchy as `default/audio/tunings/lenovo-82y5/`.
2. Listen to it on the hardware it names. This step is the point: nobody has, until you do.
3. Fill in `validated_by` in `tuning.conf` with your name, and open a pull request.

Omarchy's `docs/audio-tuning.md` describes what a tuning must report. The files are CC0 like everything generated here.
