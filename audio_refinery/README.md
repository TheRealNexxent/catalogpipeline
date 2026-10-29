# Audio Refinery: preset pipelines, Postgres catalogue and bake-off

This project provides preset pipelines for categorising, checking, cleaning and packaging audio. **Each preset can be lifted into another tool on its own.** A Postgres layer stages every observation in Table 1 and promotes only approved rows into Table 2, with immutable releases. A bake-off harness measures the steps for accuracy and speed.

## Using it (Windows, RTX 3070)

The Python environment is at `C:\Users\Nexxent\.venvs\ar`. It's kept at a short path because some Windows libraries fail on long paths. Postgres runs in the Docker container `audio-refinery-pg` (localhost:55432 only); its credentials are in `.env`.

```bash
# one file: triage, route, run its preset, print every measurement
C:/Users/Nexxent/.venvs/ar/Scripts/python runner.py path/to/file.wav

# a partner folder into Table 1 (add --enrich for emotion / topic / summary, --domain pharma for strict PII)
C:/Users/Nexxent/.venvs/ar/Scripts/python refinery_db.py ingest path/to/folder --partner "Partner A"

# propose -> review -> approve -> Table 2 -> release
C:/Users/Nexxent/.venvs/ar/Scripts/python refinery_db.py propose --profile asr --partner "Partner A"
C:/Users/Nexxent/.venvs/ar/Scripts/python refinery_db.py show 1
C:/Users/Nexxent/.venvs/ar/Scripts/python refinery_db.py decide 1 --accept-defaults     # or --item ID --accept / --reject
C:/Users/Nexxent/.venvs/ar/Scripts/python refinery_db.py apply 1 --release
C:/Users/Nexxent/.venvs/ar/Scripts/python refinery_db.py status
```

**Profiles:** `asr`, `tts`, `full_duplex`, `speaker_id`, `emotion`, `wake_word`, `audio_llm`, `music_gen`, `sound_events`, `speech_enhancement_clean`. They are defined in `scoring.py`; the telephony and far-field overlays apply automatically.

## Layout

| Path | What it is |
|---|---|
| `presets/R*.json` | **14 route presets**, each self-contained (every step it needs, including the shared triage) |
| `presets/M*.json` | **4 modifiers** (strict-PII domain, children's speech, declared language, supplied transcript) |
| `presets_catalog.py` | Source of truth for the presets; `python presets_catalog.py` regenerates the JSON |
| `steps/decode.py`, `gates.py`, `dsp.py`, `snr.py`, `fingerprint.py`, `content.py` | CPU steps: one decode, gates G1–G6, signal checks, SNR, fingerprints, duplex and speaker-track checks |
| `steps/gpu.py` | Wave 1: content type and events (EfficientAT), speech detection (Silero), language (VoxLingua107), AI speech (AASIST), UTMOSv2 (TTS profile only). Holds the shared model loader with a GPU memory budget |
| `steps/speech.py` | Wave 2: Whisper large-v3-turbo with word timestamps; PII (Presidio + GLiNER) with muting and re-transcription check; ECAPA speaker hint and diarization; Demucs vocals; Audiobox Aesthetics quality |
| `steps/enrich.py` | Wave 3: tempo, key, genre and mood (librosa + LAION-CLAP); emotion (CLAP zero-shot placeholder); animal sounds; topic, summary, sentiment (Qwen2.5-1.5B) |
| `registry.py` | Maps every step id to its function and version; lists the 2 pending steps |
| `runner.py` | Triage, routing, preset execution |
| `scoring.py` | Baseline §6 scoring: quality, coverage, tiers, caps, penalties, overlays, 10 profiles |
| `refinery_db.py`, `db/schema.sql` | Postgres: Table 1 `audio_catalog`, changesets, Table 2 `audio_curated`, releases |
| `derivatives/`, `releases/` | PII-muted and vocal copies (originals never change), release manifests |
| `model_registry.json`, `docs/licence_audit.md` | Model choices, measured results, licence status |
| `bakeoff/` | Fixture builder, benchmark harness, end-to-end database test (`db_e2e.py`) |

## Preset format (matches the Refinery `presets` table)

```json
{
  "name": "Audio · Telephony speech", "version": 1, "kind": "route", "route_id": "R04", "priority": 5,
  "profile": "Balanced", "preserve_originals": true, "privacy_required": true, "automatic": true,
  "trigger": [["sample_rate", "<=", 8000]],
  "steps": [{"id": "decode.probe"}, {"id": "asr", "params": {"model_hint": "telephony"}}, {"id": "emotion", "when": [["enrich", "==", true]]}, "..."],
  "skips": ["dsp.spectral verdicts", "diarize unless >1 speaker"]
}
```

- **Conditions** (`trigger`, a step's `when`) are AND-lists of `[fact, op, value]`; operators are `== != < <= > >= in`. They're plain data, so nothing is executed on import.
- **Router:** triage facts are matched against route triggers in `priority` order. The first match wins; R10 (mixed/uncertain) is the fallback.
- **Pending steps:** two remain, `snr_c50` (Brouhaha) and `demographics`. A preset that names one still runs; the step is recorded as skipped, which lowers evidence coverage.
- **Importing into Refinery:** store each JSON as `config_json` in its `presets` table. Refinery's `workflows.validate()` accepts only its fixed generic stages, so it needs an audio branch that validates these step ids against `registry.py`.

## Installing from scratch

```bash
py -3.13 -m venv C:/Users/Nexxent/.venvs/ar
pip install "torch==2.11.0" "torchaudio==2.11.0" "torchvision==0.26.0" --index-url https://download.pytorch.org/whl/cu128
pip install numpy scipy soundfile silero-vad speechbrain "git+https://github.com/sarulab-speech/UTMOSv2.git" presidio-analyzer gliner demucs jiwer librosa "psycopg[binary]" accelerate audiobox_aesthetics tiktoken sentencepiece protobuf -c audio_refinery/constraints.txt
python -m spacy download en_core_web_sm
git -c core.longpaths=true clone --depth 1 https://github.com/fschmid56/EfficientAT.git audio_refinery/vendor/EfficientAT
git clone --depth 1 https://github.com/clovaai/aasist.git audio_refinery/vendor/aasist
docker run -d --name audio-refinery-pg -p 127.0.0.1:55432:5432 -e POSTGRES_USER=refinery -e POSTGRES_PASSWORD=<from .env> -e POSTGRES_DB=audio_refinery -v audio_refinery_pgdata:/var/lib/postgresql/data postgres:17
python refinery_db.py init
```

- **Always install with `-c constraints.txt`.** It pins CUDA PyTorch and Transformers 4.x: several packages silently swap in a CPU PyTorch, and GLiNER's tokenizer breaks under Transformers 5.
- **UTMOSv2 on Windows:** its downloader calls `wget`. Fetch `fold0_s42_best_model.pth` from the `sarulab-speech/UTMOSv2` Hugging Face repo into `~/.cache/utmosv2/models/fusion_stage3/`.
- **Other models** download on first use into `models_cache/`: Whisper turbo, GLiNER-PII, ECAPA, Demucs, Audiobox Aesthetics, LAION-CLAP and Qwen2.5-1.5B.
- **The TorchScript GPU fuser is disabled** in `steps/gpu.py`, because its generated CUDA code fails to compile on this setup (GLiNER's second call).
- **8 GB GPU:** models over the `REFINERY_GPU_BUDGET_GB` budget (default 6.5) are unloaded and reloaded on demand, which is slow when enrichment runs on every file. The DGX's 128 GB avoids this.
- **Brouhaha** needs Python ≤3.12 (its dependencies require NumPy 1.x), so it runs in its own environment on the DGX.

**DGX Spark (Linux ARM64):** the same steps with `ffmpeg` from apt and NGC PyTorch containers. Copy `fixtures/` from Windows, since fixture generation uses Windows voices.

## Bake-off

```bash
python bakeoff/make_fixtures.py     # 120 test files with ground truth
python bakeoff/harness.py           # scores every step; results/<machine>_<time>/summary.md
python bakeoff/make_deliveries.py   # partner deliveries for the database test (built from the fixtures)
python bakeoff/db_e2e.py --reset    # two deliveries + second partner through Postgres, approval and releases
```
