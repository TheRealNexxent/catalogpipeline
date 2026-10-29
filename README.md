# catalogpipeline

This repo holds an audio data refinery: preset pipelines that catalogue, quality-check, clean and package partner audio for ML datasets, plus a Postgres approval layer that keeps raw and clean data apart.

- [`Baseline.md`](Baseline.md) is the rule set: hard gates, measurements, confidence scoring, profiles, overlays and duplicate handling.
- [`audio_refinery/`](audio_refinery) holds the code: 14 route presets, step modules for three model waves, the Postgres layer and the benchmark harness. See its [README](audio_refinery/README.md) for setup and usage.

Model weights, test audio and the database password are not in the repo. The README explains how to download and regenerate them.
