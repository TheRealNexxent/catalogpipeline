# Audio Data Refinery — Baseline v1.0

| | |
|---|---|
| **Scope** | Audio only (cataloguing, quality baseline, cleanup, packaging) |
| **Status** | Draft. All numeric thresholds are starting values to be calibrated on real data (see §14) |
| **Date** | 2026-10-29 |
| **Deployment** | Pipeline, Postgres, UI and rclone on the DGX Spark; Windows is browser-only |

This document defines the rules every audio file passes through: what is measured, what blocks a file outright, how a confidence percentage is calculated, which thresholds apply to which kind of audio, and which situations require human approval before anything reaches the curated table.

---

## Contents

1. [Core principles](#1-core-principles)
2. [Where the baseline applies](#2-where-the-baseline-applies)
3. [Hard gates](#3-hard-gates)
4. [Measurement catalogue](#4-measurement-catalogue)
5. [Role-specific rules](#5-role-specific-rules)
6. [Confidence scoring](#6-confidence-scoring)
7. [Base profiles (by intended use)](#7-base-profiles-by-intended-use)
8. [Overlays (recording setup and content domain)](#8-overlays)
9. [Detector confidence thresholds](#9-detector-confidence-thresholds)
10. [Duplicates and approval edge cases](#10-duplicates-and-approval-edge-cases)
11. [AI-generated speech](#11-ai-generated-speech)
12. [PII and privacy](#12-pii-and-privacy)
13. [Rescans, versions and releases](#13-rescans-versions-and-releases)
14. [Calibration plan](#14-calibration-plan)
15. [Glossary](#15-glossary)

---

## 1. Core principles

| # | Principle |
|---|---|
| P1 | **Phase 1 measures; it does not judge.** The only judgement in Phase 1 is the hard gates (§3). Everything else is stored as a raw value. |
| P2 | **Every measurement records four things:** the value, the method and its version, the coverage (whole file or sampled windows, in seconds), and the partner's declared value if one exists. |
| P3 | **Declared and measured values are never merged.** Partner-supplied values (e.g. an `audio-quality.json` saying SNR 8.1 dB) sit next to our own. A disagreement is a finding, not something resolved silently. |
| P4 | **Durations stay separate:** declared, container header, decoded, speech, and usable duration are five different numbers. |
| P5 | **Two analysis copies.** The native file is used for format and fidelity checks. A standard 16 kHz mono copy feeds the ML models. Each value records which copy it came from. |
| P6 | **Checks depend on the file's role:** source, stem, speaker track, loose file, or sidecar (§5). |
| P7 | **Confidence belongs to a profile, not to a file.** The same recording can be Gold for ASR and a Reject for TTS. |
| P8 | **Originals are never modified or deleted.** Cleaned audio is always a separate, linked derivative file. Excluded files stay in Table 1. |
| P9 | **Nothing reaches Table 2 without approval.** Every promotion is a reviewed changeset (§10). |
| P10 | **Detectors are evidence, not verdicts.** ML outputs such as language, AI-generated or PII carry a confidence and route uncertain cases to review. |

---

## 2. Where the baseline applies

```
 Source (local / rclone)
        │
        ▼
 ┌─────────────── PHASE 1 ─────────────────┐
 │ Inventory → Gates (§3) → Measure (§4)    │──▶ TABLE 1  audio_catalog
 │ Layers 0–3 every file, Layer 4 optional  │     (every observation, raw)
 └──────────────────────────────────────────┘
        │  user picks a profile (§7, §8) + manual ticks
        ▼
 ┌──────────── PROMOTION ───────────────────┐
 │ Score + tier per profile (§6)            │
 │ Cross-file checks / duplicates (§10)     │──▶ CHANGESET  (pending review)
 │ AI-generated (§11), PII (§12) flags      │
 └──────────────────────────────────────────┘
        │  human approval
        ▼
 TABLE 2  audio_curated  ──▶  RELEASE vN (immutable snapshot, §13)
```

---

## 3. Hard gates

Failing **any** gate makes a file ineligible for every profile. The file stays in Table 1 with a plain-language reason. Gates run on the **whole file**.

| ID | Gate | Rule | On failure |
|---|---|---|---|
| G1 | Not empty | `size_bytes > 0` | Reject: "This file contains zero bytes." |
| G2 | Has an audio stream | ffprobe finds ≥ 1 audio stream | Reject: "No audio stream found." |
| G3 | Decodes | Full ffmpeg decode reports no errors | Reject, with the decoder error and the time position where it failed |
| G4 | Not truncated | Decoded duration ≥ **98%** of the header duration, or within 1 s for files under 50 s | Reject, and propose a derivative that keeps the readable portion (requires approval) |
| G5 | Not all digital silence | At least one non-zero sample | Reject. For a speaker track this also breaks the bundle's completeness check. |
| G6 | Minimum length | Decoded duration ≥ **0.1 s** | Reject |

---

## 4. Measurement catalogue

**Coverage** says how much of the file a metric covers. **Whole** means the entire file is analysed. **Speech** means only the regions where speech was detected. **Budget** means the whole file, up to a per-run GPU time limit; anything beyond the limit is recorded as partial coverage.

### Layer 1: Identity and technical facts (CPU, every file)

| ID | Metric | Unit | Method | Coverage |
|---|---|---|---|---|
| M101 | File hash | SHA-256 | Hash of the file bytes | Whole |
| M102 | Decoded-audio hash | SHA-256 | Hash of the decoded audio samples (catches the same audio in a different container) | Whole |
| M103 | Audio fingerprint | Chromaprint | `fpcalc`, full length | Whole |
| M104 | Container / codec / lossless flag | label | ffprobe | Header |
| M105 | Bitrate, CBR/VBR | kbps | ffprobe | Header |
| M106 | Sample rate | Hz | ffprobe | Header |
| M107 | Bit depth (declared) | bits | ffprobe | Header |
| M108 | Channels and layout | count / label | ffprobe | Header |
| M109 | Extension matches real format | bool | Magic bytes compared with the extension | Header |
| M110 | Declared / header / decoded duration | s | Partner metadata / ffprobe / full decode | Whole |
| M111 | Embedded tags | key/value | ID3, Vorbis comments, BWF/iXML, encoder, creation date | Header |
| M112 | Bundle ID and role | label | Bundle rules (§5) | n/a |

### Layer 2: Signal quality (CPU, every file)

| ID | Metric | Unit | Method | Coverage |
|---|---|---|---|---|
| M201 | Sample peak, **true peak** | dBFS / dBTP | ffmpeg `astats`, `ebur128` | Whole |
| M202 | RMS level, noise floor | dBFS | `astats` (noise floor = lowest RMS window) | Whole |
| M203 | Integrated loudness, loudness range | LUFS / LU | EBU R128 | Whole |
| M204 | **Clipping** | % of samples, longest run (samples) | Samples at ≥ −0.1 dBFS; runs of 3 or more | Whole |
| M205 | DC offset | fraction of full scale | Mean of the signal | Whole |
| M206 | Silence | % of file, leading/trailing s | `silencedetect` at −50 dBFS, minimum 0.5 s | Whole |
| M207 | **Effective bandwidth** | × Nyquist | Highest frequency band still carrying energy above the noise floor | Whole |
| M208 | **Lossy origin** | label + confidence | Characteristic MP3/AAC frequency cutoff patterns inside a WAV or FLAC | Whole |
| M209 | **Effective bit depth** | bits | Whether the lowest bits are always zero | Whole |
| M210 | Dropouts and glitches | count per hour | Sudden jumps between samples, runs of exactly repeated samples | Whole |
| M211 | Mains hum | dB above the local spectrum | Energy at 50/60 Hz and its harmonics | Whole |
| M212 | Stereo checks | correlation, imbalance dB | Correlation between channels, level difference | Whole |

### Layer 3: Content (GPU, every file, 16 kHz mono copy)

| ID | Metric | Unit | Candidate tool | Coverage |
|---|---|---|---|---|
| M301 | Content type: speech / music / noise / silence / mixed | % of duration per class + confidence | PANNs / BEATs / YAMNet | Budget |
| M302 | Speech ratio, speech duration | %, s | Silero VAD | Whole |
| M303 | **Speech SNR** | dB | WADA-SNR on the speech regions from M302 | Speech |
| M304 | **Perceptual quality** | MOS 1–5 (speech, background, overall) | DNSMOS P.835 | Speech |
| M305 | Reverb | C50 dB | Blind C50 estimator | Speech |
| M306 | Language + confidence, code-switching | ISO code, 0–1 | Whisper language ID / MMS-LID, per segment | Speech |
| M307 | Transcript → spoken PII | entities + timestamps | whisper.cpp + Presidio | Speech |
| M308 | Overlapping speech | % of speech | pyannote (ARM64 build to be confirmed) | Speech |
| M309 | **AI-generated speech score** | 0–1 | Anti-spoofing detector (AASIST family or equivalent) | Speech |
| M310 | Speaking rate | words per minute | From M307 timestamps | Speech |

### Layer 4: Enrichment (GPU, on demand, after selection)

Speaker separation and speaker count, per-speaker speech time, speaker consistency (embedding similarity), emotion, age/gender, accent, sentiment, topic, summary, sound events (laughter, applause, music, etc.). Partner-supplied JSON files fill these fields as **declared** values (P3).

### Layer 5: Cross-file checks (at promotion)

Exact duplicates (M101), same audio in a different container (M102), near-duplicates, containment and shared segments (M103), the same content from two partners, bundle completeness, and dataset balance. See §10 and §13.

---

## 5. Role-specific rules

Every file is an asset. A **bundle** is an optional group of assets that belong together. A loose file is a bundle of one.

**Bundle detection (in order).** A guessed grouping becomes a proposal that must be approved.
1. Known layouts: `stems/`, `speaker-*.wav`, `vocals.wav` / `accompaniment.wav`
2. Same name prefix: `call_01.wav` + `call_01.json` / `.srt` / `.txt`
3. Same folder plus a manifest file (`metadata.json`, CSV)

| Role | What changes |
|---|---|
| **Source / mixture** | Scored in full under the selected profile |
| **Vocals stem** | Speech metrics (M303–M306) are measured here and copied to the source when the source contains music or crowd noise |
| **Accompaniment stem** | Speech metrics are disabled; music checks apply |
| **Stem consistency** | Sum of stems vs mixture: residual ≤ **−30 dB** (warning above that) |
| **Speaker track** | Silence metrics (M206) are ignored. Quality metrics are measured on active regions only. Leakage from other speakers ≤ **−20 dB** relative to the active speaker. |
| **Sidecar (JSON, SRT, TXT)** | Not scored as audio. Parsed into declared values and linked to its audio file. |
| **Bundle completeness** | Declared count = valid count (e.g. 10 speakers declared → 10 speaker tracks pass gates). **100%** is required for Gold; below 100% the bundle is capped at Silver. |

---

## 6. Confidence scoring

Each file gets **two percentages per profile**: a quality score and an evidence coverage. The tier is decided by both.

### 6.1 Scoring each metric (0–100%)

Each profile gives each metric a **floor**, an **ideal** and a **weight**.

- **Higher-is-better** (e.g. SNR):  `score = clamp((value − floor) / (ideal − floor), 0, 1)`
- **Lower-is-better** (e.g. clipping): `score = clamp((floor − value) / (floor − ideal), 0, 1)`, where the floor is the maximum allowed value
- **Categorical** (e.g. lossy origin): fixed mapping. Lossless origin = 1.0, lossy at ≥ 192 kbps = 0.5, lossy below 192 kbps = 0.0
- **Hard floor:** a value worse than the floor **fails the profile** (tier = Reject for that profile), unless the profile marks the metric as *soft*. A soft metric just scores 0.

### 6.2 Quality score Q

```
Q = Σ (weight_i × score_i) / Σ weight_i  −  penalties          (shown as %)
```

Only measured metrics count toward Q. **Penalties**, each also logged as a finding:

| Penalty | Amount |
|---|---|
| Declared vs measured disagreement beyond tolerance (§6.5), per field | −5 points |
| Lossy origin detected in a file sold as lossless | −10 points |
| Maximum total penalty | −20 points |

### 6.3 Evidence coverage C

```
C = Σ (weight_i × coverage_i) / Σ weight_i                      (shown as %)
```

`coverage_i` is the fraction of the relevant audio actually analysed: 1.0 for a whole-file measurement, 0.0 for a metric that wasn't measured. **A metric that wasn't measured lowers C; it never counts as a zero quality score.**

### 6.4 Tiers

| Tier | Quality Q | Coverage C | Meaning |
|---|---|---|---|
| 🥇 **Gold** | ≥ **80%** | ≥ **90%** | Ready for premium / client-facing use |
| 🥈 **Silver** | ≥ **60%** | ≥ **70%** | Good for training; minor issues |
| 🥉 **Bronze** | ≥ **40%** | ≥ **50%** | Usable with caveats, or for pretraining only |
| 🔍 **Review** | Passed gates and floors, but below Bronze or C < 50% | | Needs a human decision |
| ⛔ **Reject** | Failed a gate (§3) or a hard floor of this profile | | Not eligible for this profile |

Additional caps: an incomplete bundle caps the tier at **Silver**. Unresolved PII caps it at **Review** (§12).

### 6.5 Declared vs measured tolerances

| Field | Tolerance |
|---|---|
| Duration | ±1% or ±1 s, whichever is larger |
| Sample rate, channels, bit depth | Exact |
| SNR | ±3 dB |
| Speaker count | Exact |
| Language | Same ISO language code |
| Content class | Same dominant class |

### 6.6 Worked example: ACN `en_US-SPRT-60m-019` (source file)

The values marked *assumed* are illustrative until we run the real measurements.

| Metric | Value | ASR floor → ideal | Score | Weight | Points |
|---|---|---|---|---|---|
| Sample rate | 48 kHz | 16 → 16 | 1.00 | 10 | 10.0 |
| Speech SNR | 8.1 dB (declared) | 5 → 20 | 0.21 | 20 | 4.1 |
| Perceptual quality (overall) | 3.1 *assumed* | 2.5 → 3.3 | 0.75 | 20 | 15.0 |
| Clipping | 0% *assumed* | max 1.0 → 0.1 | 1.00 | 10 | 10.0 |
| Speech ratio | 70% *assumed* | 30 → 70 | 1.00 | 10 | 10.0 |
| Effective bandwidth | 0.95 × Nyquist *assumed* | 0.5 → 0.8 | 1.00 | 5 | 5.0 |
| Language ID confidence | 0.97 *assumed* | 0.70 → 0.95 | 1.00 | 15 | 15.0 |
| Dropouts | 0 per hour *assumed* | max 10 → 0 | 1.00 | 10 | 10.0 |
| **Total** | | | | **100** | **Q = 79.1%** |

With C = 100% and the bundle complete, that's **Silver**, just under Gold, held back by the noisy broadcast mix. Under the **TTS / voice clone** profile the same file is **Reject**, because 8.1 dB is below that profile's 30 dB hard floor.

---

## 7. Base profiles (by intended use)

A profile = **a base profile for the intended use** (this section) **+ zero or more overlays** (§8). Cells read **`floor → ideal · weight`**. For lower-is-better metrics the floor is the maximum allowed value. `–` means not scored. The weights in each profile add up to 100.

### 7.1 Speech profiles

| Metric | ASR | TTS / voice clone | Full-duplex dialogue | Speaker ID / diarization | Emotion recognition | Wake word / commands |
|---|---|---|---|---|---|---|
| Sample rate (kHz) | 16 → 16 · 10 | 44.1 → 48 · 10 | 16 → 24 · 10 | 16 → 16 · 5 | 16 → 16 · 5 | 16 → 16 · 10 |
| Speech SNR (dB) | 5 → 20 · 20 | 30 → 40 · 20 | 10 → 25 · 15 | 10 → 25 · 20 | 10 → 25 · 15 | 5 → 20 · 15 |
| Perceptual quality, overall (MOS) | 2.5 → 3.3 · 20 | 3.5 → 4.0 · 25 | 2.8 → 3.5 · 15 | 2.8 → 3.5 · 15 | 2.8 → 3.5 · 15 | 2.5 → 3.3 · 15 |
| Clipping (%) | 1.0 → 0.1 · 10 | 0.01 → 0 · 10 | 0.5 → 0.05 · 10 | 0.5 → 0.05 · 10 | 0.5 → 0.05 · 10 | 1.0 → 0.1 · 10 |
| Speech ratio (%) | 30 → 70 · 10 | 60 → 85 · 5 | 40 → 80 · 10 | 40 → 80 · 10 | 40 → 80 · 10 | 10 → 50 · 10 |
| Effective bandwidth (× Nyquist) | 0.5 → 0.8 · 5 | 0.9 → 0.95 · 10 | 0.7 → 0.9 · 5 | 0.6 → 0.9 · 5 | 0.6 → 0.9 · 5 | 0.5 → 0.8 · 5 |
| Reverb C50 (dB) | – | 15 → 25 · 10 | 5 → 15 · 5 | 5 → 15 · 5 | – | – |
| Language ID confidence | 0.70 → 0.95 · 15 | 0.90 → 0.98 · 5 | 0.70 → 0.95 · 5 | – | 0.70 → 0.95 · 5 | 0.70 → 0.95 · 5 |
| Dropouts (per hour) | 10 → 0 · 10 | 1 → 0 · 5 | 5 → 0 · 5 | 5 → 0 · 5 | 5 → 0 · 5 | 10 → 0 · 5 |
| Channel separation, duplex (dB) | – | – | 10 → 30 · 15 | – | – | – |
| Speaker balance (min/max speech share) | – | – | 0.2 → 0.5 · 5 | – | – | – |
| Speech per speaker, minimum (s) | – | – | – | 30 → 300 · 15 | – | – |
| Overlapping speech (%) | – | – | – | 20 → 5 · 10 | 20 → 5 · 10 | – |
| Emotion evidence confidence | – | – | – | – | 0.5 → 0.8 · 20 | – |
| Keyword match confidence (ASR) | – | – | – | – | – | 0.6 → 0.9 · 25 |
| **Extra hard filters** | | Exactly 1 speaker; speaker consistency ≥ 0.75; no music; AI-generated default *exclude* | Duplex setup required; both channels active | Speaker count known; AI-generated default *exclude* | | |

### 7.2 General and non-speech profiles

| Metric | Audio-LLM / pretraining | Music generation | Sound-event classification | Speech enhancement (clean side) |
|---|---|---|---|---|
| Sample rate (kHz) | 16 → 44.1 · 10 | 44.1 → 48 · 15 | 16 → 44.1 · 10 | 16 → 48 · 10 |
| Speech SNR (dB) | 0 → 15 · 10 (*soft*) | – | – | 35 → 45 · 25 |
| Perceptual quality, overall (MOS) | 2.0 → 3.0 · 10 (*soft*) | – | – | 3.6 → 4.1 · 20 |
| Clipping (%) | 2.0 → 0.1 · 10 | 0.1 → 0 · 15 | 1.0 → 0.1 · 10 | 0.01 → 0 · 10 |
| Effective bandwidth (× Nyquist) | 0.5 → 0.9 · 10 | 0.9 → 0.97 · 15 | 0.6 → 0.9 · 10 | 0.9 → 0.95 · 10 |
| Lossy origin | categorical · 5 (*soft*) | lossless only (hard) · 15 | categorical · 5 (*soft*) | lossless only (hard) · 10 |
| Effective bit depth (bits) | – | 16 → 24 · 10 | – | – |
| Dropouts (per hour) | 20 → 0 · 10 | 1 → 0 · 10 | 10 → 0 · 10 | 1 → 0 · 5 |
| Content-class confidence | 0.5 → 0.8 · 15 | music share 80 → 98% · 10 | event-label confidence 0.5 → 0.85 · 30 | – |
| Silence (%) | 80 → 30 · 10 | 20 → 5 · 10 | 80 → 30 · 10 | 50 → 20 · 10 |
| Near-duplicate cluster size | 5 → 1 · 10 | – | 5 → 1 · 15 | – |
| **Extra hard filters** | | Rights flag required | Event labels present | Paired noisy version present |

---

## 8. Overlays

An overlay adjusts a base profile. Several overlays can apply at once. Recording-setup overlays are mostly **detected automatically** in Phase 1. Domain overlays come from the approved category of the dataset.

When an overlay disables a metric, that metric's weight is **redistributed proportionally** across the remaining metrics.

### 8.1 Recording setup

| Overlay | Detected by | Changes |
|---|---|---|
| **Telephony** (narrowband) | 8 kHz, or G.711 / AMR / GSM codec | Sample-rate floor and ideal → 8 kHz; bandwidth metric disabled; quality-score floor −0.3 |
| **VoIP** (compressed wideband) | Opus / AAC at ≤ 32 kbps | Lossy origin allowed; bandwidth floor → 0.5 |
| **Duplex** (one speaker per channel) | 2 channels, low correlation, alternating speech | Each channel scored separately; **file score = the weaker channel's score**; adds channel separation ≥ 10 dB floor and speaker balance |
| **Far-field / mic array** | Low C50, high noise floor | Speech-SNR floor −5 dB; quality-score floor −0.3; reverb metric disabled |
| **Mono / stereo** | Channel count | Stereo checks (M212) only for stereo: fake stereo (correlation > 0.999) → finding; phase-inverted channels (correlation < −0.9) → finding; one dead channel → finding |
| **Multitrack / stems** | Bundle rules | Role rules from §5; stem-sum residual check |
| **Per-speaker tracks** | Bundle rules | Silence ignored; active-region scoring; leakage ≤ −20 dB |
| **Spatial** (binaural / ambisonic) | Channel layout | Channel count must match the declared format; correlation checks disabled |

### 8.2 Content domain

| Overlay | Changes |
|---|---|
| **Pharma / medical** | **Strict health-data privacy**: patient name, date of birth, medical record number, address, phone, and a medication mentioned together with a condition. **Any unresolved PII → Reject.** ASR coverage of speech must be 100%. Consent flag required for Gold. |
| **Legal / court** | Strict PII. Speaker labels required for Gold. |
| **Finance** | Strict PII, including spoken card and account numbers. |
| **Call-centre** | Telephony overlay usually applies. IVR messages and hold music are treated as shared segments, not duplicates. |
| **Broadcast / sports / podcast** | Speech metrics taken from the vocals stem if one exists; music beds allowed; content class *mixed* accepted; ad breaks and jingles treated as shared segments. |
| **Audiobook / read speech** | Speech-SNR floor +5 dB; single speaker expected per file. |
| **Meetings / lectures** | Far-field overlay usually applies; overlapping speech allowed. |
| **Children's speech** | Guardian-consent flag required; strict PII; age enrichment required. |
| **Accented / non-native** | Language ID is reported, but its weight is halved. |
| **Multilingual / code-switching** | Language ID floor → 0.5; per-segment language recorded; code-switching is a label, not a defect. |
| **Elderly speech** | Age enrichment recommended; speaking-rate outliers are not penalised. |
| **Acted / emotional speech** | Emotion enrichment required. |
| **Whispered / non-verbal** | Perceptual-quality floor −0.5 (speech-quality models under-rate whispers). |
| **Singing / vocals** | Speech-quality metrics disabled; music-style metrics apply. |
| **Music** (tracks, stems, instrument samples) | Speech metrics disabled; rights flag required. |
| **SFX / foley** | Speech metrics disabled; near-duplicate similarity threshold raised to 0.98. |
| **Ambient / environmental** | Speech metrics disabled; silence maximum relaxed to 90%; similarity threshold raised to 0.98. |
| **Animal / nature sounds** | Same as ambient; species label expected if declared. |
| **Industrial / machine sounds** | Speech metrics disabled; constant tones are not counted as hum. |
| **Synthetic speech** (declared) | AI-generated flag expected; default decision *keep with label*. Incompatible with the TTS / voice-clone and speaker-ID profiles. |

### 8.3 Product type (packaging, not quality)

| Field | Values | Effect |
|---|---|---|
| `product_type` | **OTS** (off-the-shelf) / **custom** | OTS releases require **release grade A** (§13.3) and a complete datasheet |
| `delivery_type` | **sample** / **full** | A sample assessment is provisional; it never certifies the full dataset |

---

## 9. Detector confidence thresholds

| Detector | Accept | Review | Below review |
|---|---|---|---|
| Language ID | ≥ **0.90** | 0.70 – 0.90 | < 0.70 → language `und` |
| Content class (dominant class) | Class ≥ **60%** of duration | 40 – 60% | No class ≥ 40% → `mixed` |
| Speech detection (per frame) | Probability ≥ 0.5 | n/a | n/a |
| Spoken PII entity | ≥ **0.85** → mute proposal | 0.50 – 0.85 → review | < 0.50 → logged only |
| AI-generated speech | n/a | ≥ **0.80** "likely", 0.50 – 0.80 "possible" (both go to approval) | < 0.50 → not flagged |
| Lossy origin | ≥ **0.80** → labelled lossy | 0.50 – 0.80 → finding | < 0.50 → not flagged |
| Emotion / age / gender / accent | ≥ 0.70 stored as label | 0.50 – 0.70 stored as "uncertain" | < 0.50 → not stored |

---

## 10. Duplicates and approval edge cases

### 10.1 Near-duplicate detection

Two numbers decide what a match means:
- **Similarity:** how alike the matching parts are, from 0 to 1, using Chromaprint.
- **Overlap:** what % of each file the match covers.

| Content type | Similarity threshold |
|---|---|
| Speech | ≥ **0.90** |
| Music | ≥ **0.95** |
| Ambient / SFX / animal / industrial | ≥ **0.98** (natural sounds are inherently alike) |

Profiles may override these thresholds.

| Overlap pattern | Meaning | Default action |
|---|---|---|
| ≥ 90% of **both** files | Same recording | **Duplicate** → keep the preferred copy (§10.2) and link the others |
| ≥ 90% of one file, < 90% of the other | Containment: one is a clip cut from the other | **Review**, defaulting to keeping the longer file |
| < 30% of **both** files | Shared segment (jingle, IVR message, intro) | **Not a duplicate**; recorded as a shared segment |
| Anything else | Partial overlap | **Review** |

### 10.2 Preferred-copy ranking (for duplicates)

1. Lossless origin over lossy
2. Higher sample rate
3. Higher effective bit depth
4. Higher quality score Q in the active profile
5. Earliest provenance (first delivery)

### 10.3 Approval edge cases

Every promotion from Table 1 to Table 2 builds a **changeset**. Nothing is written to Table 2 until it is approved. Approval can be per row or bulk per category, and one database transaction applies the whole approved changeset.

| ID | Case | Detected by | Default proposal |
|---|---|---|---|
| E1 | Exact duplicate | Same M101 | **Skip** and log the occurrence |
| E2 | Same audio, different container | Same M102 | **Keep the preferred copy** (§10.2) and link the rest |
| E3 | Near-duplicate | §10.1 | **Review** |
| E4 | Containment (clip of a longer file) | §10.1 | **Review**, defaulting to keeping the longer file |
| E5 | Same path, new content (partner re-delivered) | Path matches, hash differs | **Update**: shows the before/after metric diff; the old Table 2 row is marked superseded |
| E6 | Same content from two partners | Same M101/M102, different partner | **Review** (provenance and rights flag) |
| E7 | Same content, conflicting metadata | Same hash, declared fields differ | **Review**, showing both side by side |
| E8 | Stems / speaker tracks of one bundle | Bundle membership | **Never treated as duplicates** |
| E9 | File missing on rescan | Absent from the source | **Flag**; the Table 2 row is kept until removal is approved |
| E10 | New metric version changes a tier | Same hash, different extractor version | **Review** if the tier changes; automatic update otherwise |
| E11 | AI-generated speech flagged | M309 (§11) | **Review**: keep with label, or exclude |
| E12 | Unresolved PII | M307 / M111 (§12) | **Review**: mute derivative, keep held, or exclude |
| E13 | Truncated file with a readable portion | G4 | **Review**: create a trimmed derivative or exclude |
| E14 | Incomplete bundle | §5 | **Review**: promote the valid members or hold the bundle |

---

## 11. AI-generated speech

| Rule | |
|---|---|
| A1 | Every file with speech gets an AI-generated score (M309). |
| A2 | Score ≥ 0.50 → flagged and sent to approval (E11). **It is never removed automatically.** |
| A3 | Two decisions: **Keep with label** (`ai_generated = true` carried into Table 2 and the release manifest) or **Exclude** (stays in Table 1 only). |
| A4 | Default decision by profile: **TTS / voice clone** and **speaker ID** → *exclude*. **Synthetic-speech domain** → *keep*. All others → *keep with label*. |
| A5 | Detectors are unreliable on telephone or compressed audio and on new voice-cloning models. The flag is evidence, not proof, and the UI says so. |

---

## 12. PII and privacy

| Rule | |
|---|---|
| PII1 | **Spoken PII:** ASR (whisper.cpp) + entity recognition (Presidio) → timestamped entities (M307). |
| PII2 | **Metadata PII:** embedded tags (artist, originator, comments, GPS in BWF/iXML) and **filenames** are scanned too. |
| PII3 | **Remediation is non-destructive:** a muted or beeped **derivative** file is created and verified. The original is never altered. |
| PII4 | **Verification:** after muting, ASR runs again on the muted regions of the derivative; the entity must no longer be recognised. |
| PII5 | **Unresolved PII caps the tier at Review.** Under strict-PII domains (pharma, legal, finance, children) it **rejects** the file for that profile. |
| PII6 | **Voices are not altered by default.** A recognisable voice is biometric data, but changing it is a separate, explicit decision. |
| PII7 | **No raw transcripts in the catalogue**, unless the dataset is licensed to include them. Only entity types and timestamps are stored. |
| PII8 | **"Screened" is not "cleared."** A status means the configured detectors ran; it is not a legal anonymisation certificate. |

---

## 13. Rescans, versions and releases

### 13.1 Table 1 (staging)

| Rule | |
|---|---|
| R1 | Rescan of an **unchanged** file (same path, same hash) → only `last_seen` is updated. |
| R2 | **Content changed** at the same path → new Table 1 row; the earlier row is kept. |
| R3 | **Same content at a new path** (moved or copied) → new row linked to the earlier one. |
| R4 | **Metric/extractor version changed** → re-measure and store a new measurement record. A tier change → E10. |
| R5 | **Missing from source** → row marked `missing`, never deleted. |
| R6 | Duplicates across paths, partners or deliveries always get their own rows. Table 1 never deduplicates. |

### 13.2 Table 2 (curated) and releases

| Rule | |
|---|---|
| V1 | Table 2 holds **one current row per piece of content**, only ever written by an approved changeset. |
| V2 | A replaced row is marked **superseded** (with valid-from / valid-to dates), never deleted. |
| V3 | Each approved changeset may produce a **release**: an immutable manifest of asset IDs, hashes, derivative hashes and profile versions. |
| V4 | **Released versions never change.** Any release can be rebuilt exactly. |
| V5 | **Stale guard:** if a source file, derivative or measurement changed after the changeset was built, approval is blocked until it is rebuilt. |

### 13.3 Release grades (dataset level)

| Grade | Requirements |
|---|---|
| **A** | ≥ **90%** of hours Silver or better, **and** ≥ **50%** Gold; 0 unresolved PII; 0 unresolved conflicts; 100% of manifest checksums verified; balance checks pass |
| **B** | ≥ **75%** of hours Silver or better; 0 unresolved PII; 100% of checksums verified |
| **C** | Anything else that passed approval. Internal use only. |

**Balance checks** (speech datasets, reported, and enforced only for grade A):

| Check | Threshold |
|---|---|
| Largest single speaker share of hours (ASR, multi-speaker datasets) | ≤ **5%** |
| Language purity (monolingual datasets) | ≥ **98%** of speech hours in the declared language |
| Content-class purity (single-class datasets) | ≥ **95%** of hours in the declared class |
| Age/gender distribution | Reported only, never enforced |

---

## 14. Calibration plan

All numbers above are starting values. They are tuned on real data before they're relied on.

1. **Golden set:** for each profile actually in use, 200–500 files labelled by a person as *accept*, *borderline* or *reject*.
2. **Targets:**

   | Measure | Target |
   |---|---|
   | False rejects (good files scored Reject) | ≤ **2%** |
   | False accepts (bad files scored Silver or better) | ≤ **5%** |
   | Share of files landing in Review | ≤ **10%** |
   | Near-duplicate false alarms (on a sample) | ≤ **10%** |

3. **Adjust floors first, then weights, then tier cut-offs.** Each change creates a new **profile version**. Old scores stay attached to the version that produced them.
4. **Re-calibrate** whenever a detector model changes, or every quarter.
5. **Per-language benchmarks** for language ID, ASR and PII detection before relying on them for a new language.

---

## 15. Glossary

| Term | Meaning |
|---|---|
| dBFS | Level relative to the loudest possible digital value (0 dBFS = maximum) |
| True peak | Peak level including peaks that occur *between* samples during playback |
| LUFS | Loudness as perceived by people (EBU R128 standard) |
| SNR | Signal-to-noise ratio: how much louder the speech is than the background |
| WADA-SNR | A method for estimating SNR from speech without a clean reference |
| DNSMOS | A model that predicts a human quality rating (1–5) for speech |
| VAD | Voice activity detection: finds where speech occurs |
| C50 | Clarity measure for reverberation; higher means drier and clearer |
| Nyquist | Half the sample rate: the highest frequency a file can hold |
| Effective bandwidth | The highest frequency that actually contains sound |
| Lossy origin | Audio that was once MP3/AAC, even if now stored as WAV or FLAC |
| Chromaprint | An audio fingerprint used to find matching recordings |
| Bundle | A group of files that belong together (source, stems, speaker tracks, sidecars) |
| Changeset | A proposed set of Table 2 changes waiting for approval |
| Release | An immutable snapshot of approved Table 2 content |
| Profile | A versioned set of thresholds and weights for one intended use |
| Overlay | An adjustment to a profile for a recording setup or content domain |
| OTS | Off-the-shelf: a ready-made catalogue dataset (vs a custom collection) |
