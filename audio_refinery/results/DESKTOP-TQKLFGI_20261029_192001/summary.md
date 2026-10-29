# Bake-off run — DESKTOP-TQKLFGI

GPU: NVIDIA GeForce RTX 3070 Laptop GPU, 8192 MiB, 610.62 · CPUs: 16 · Windows 11 AMD64

**116 files, 28.8 min of audio, processed in 178.14 s → 9.7× realtime** (CPU steps only)

## Task accuracy against ground truth

| Task | Passed | Accuracy |
|---|---|---|
| gates | 107/107 | 100.0% |
| spectral (fake hi-res / lossy origin) | 4/4 | 100.0% |
| bit depth | 3/3 | 100.0% |
| stereo checks | 5/5 | 100.0% |
| content class: EfficientAT (GPU) | 76/77 | 98.7% |
| content class: DSP baseline (CPU) | 48/77 | 62.3% |
| language ID: VoxLingua107 | 73/73 | 100.0% |
| AI-speech flag on known-synthetic speech: AASIST | 73/73 | 100.0% |
| clipping | 1/1 | 100.0% |
| hum | 2/2 | 100.0% |
| dc offset | 1/1 | 100.0% |
| dropouts | 1/1 | 100.0% |
| silence padding | 1/1 | 100.0% |
| routing | 11/12 | 91.7% |
| extension mismatch | 1/1 | 100.0% |
| duplicates | 7/7 | 100.0% |

## SNR estimator candidates (speech + white/pink/babble noise, 0–30 dB)

| Candidate | Files | Mean abs error | Within ±3 dB | MAE white / pink / babble | Speed |
|---|---|---|---|---|---|
| snr.wada | 72 | 3.88 dB | 61.1% | 1.17 / 1.18 / 9.3 dB | 14807.2× |
| snr.energy | 72 | 5.04 dB | 50.0% | 2.01 / 2.93 / 10.18 dB | 11731.5× |

GPU: cuda · peak allocated 2486 MB · one-time model load (s): silero_vad 0.25, efficientat_mn10 2.83, utmosv2 12.98, voxlingua107 1.35, aasist 0.17

## Speech detection: Silero VAD (frame F1 against the true speech timeline)

Mean F1 **0.946** over 73 files

| SNR (dB) | 0 | 5 | 10 | 15 | 20 | 30 | 35 |
|---|---|---|---|---|---|---|---|
| F1 | 0.931 | 0.938 | 0.942 | 0.943 | 0.951 | 0.966 | 0.977 |

By noise type: white 0.964, pink 0.965, babble 0.907

## Speech quality: UTMOSv2 (no human MOS labels, so a sanity check only)

Rank correlation with true SNR, averaged over 12 noise series: **0.343** (1.0 = score always drops as noise rises)

| SNR (dB) | 0 | 5 | 10 | 15 | 20 | 30 |
|---|---|---|---|---|---|---|
| mean MOS | 1.91 | 1.81 | 1.91 | 2.01 | 2.13 | 2.31 |

## Step speed

| Step | Calls | Total ms | Realtime × |
|---|---|---|---|
| mos.speech | 98 | 105415 | 13.7 |
| vad | 99 | 20634 | 71.5 |
| classify.content.gpu | 105 | 11375 | 143.0 |
| decode.probe | 116 | 7489 | 230.9 |
| decode.full | 116 | 6997 | 247.2 |
| fingerprint.compute | 105 | 4725 | 344.2 |
| dsp.hum | 105 | 3971 | 409.6 |
| dsp.spectral | 105 | 3911 | 415.9 |
| dsp.levels | 105 | 3108 | 523.3 |
| ai_detect | 97 | 2725 | 521.1 |
| classify.content.dsp | 105 | 2679 | 607.1 |
| lid | 96 | 1960 | 710.4 |
| dsp.loudness | 105 | 1286 | 1264.7 |
| dsp.dropouts | 105 | 942 | 1726.3 |
| dsp.bit_depth | 105 | 322 | 5045.0 |
| dsp.silence | 105 | 202 | 8064.7 |
| snr.energy | 105 | 139 | 11731.5 |
| snr.wada | 105 | 110 | 14807.2 |
| dsp.stereo | 105 | 63 | 25794.0 |
| gates.basic | 116 | 33 | 51835.4 |
| duplex.stats | 1 | 13 | 2094.4 |
| events.tagging | 3 | 0 | 187500.0 |
| cache.lookup | 109 | 0 | 28052516.7 |

## Routes chosen

R00: 7, R01: 4, R02: 2, R03: 93, R04: 1, R05: 1, R07: 5, R08: 2, R09: 1

## Pending model steps (skipped, lower coverage)

bundle.verify_tracks (2), asr (97), pii.detect (97), music.analysis (3), snr_c50 (95), align.words (95), quality.general (3), duplex.crosstalk (1), separate.vocals (2)

## Failures

- **content class: EfficientAT (GPU)** · `routes/mixed_music_speech.wav` — expected mixed got music (windows {'speech': 0.33, 'music': 0.67})
- **content class: DSP baseline (CPU)** · `quality/clean_48k.wav` — expected speech got mixed
- **content class: DSP baseline (CPU)** · `snr/v0t0_babble_00db.wav` — expected speech got mixed
- **content class: DSP baseline (CPU)** · `snr/v0t0_babble_05db.wav` — expected speech got mixed
- **content class: DSP baseline (CPU)** · `snr/v0t0_babble_30db.wav` — expected speech got mixed
- **content class: DSP baseline (CPU)** · `snr/v0t1_white_30db.wav` — expected speech got mixed
- **content class: DSP baseline (CPU)** · `snr/v0t1_pink_30db.wav` — expected speech got mixed
- **content class: DSP baseline (CPU)** · `snr/v0t1_babble_00db.wav` — expected speech got mixed
- **content class: DSP baseline (CPU)** · `snr/v0t1_babble_05db.wav` — expected speech got mixed
- **content class: DSP baseline (CPU)** · `snr/v0t1_babble_10db.wav` — expected speech got mixed
- **content class: DSP baseline (CPU)** · `snr/v0t1_babble_15db.wav` — expected speech got mixed
- **content class: DSP baseline (CPU)** · `snr/v0t1_babble_20db.wav` — expected speech got mixed
- **content class: DSP baseline (CPU)** · `snr/v0t1_babble_30db.wav` — expected speech got mixed
- **content class: DSP baseline (CPU)** · `snr/v1t0_white_30db.wav` — expected speech got mixed
- **content class: DSP baseline (CPU)** · `snr/v1t0_pink_30db.wav` — expected speech got mixed
- **content class: DSP baseline (CPU)** · `snr/v1t0_babble_00db.wav` — expected speech got mixed
- **content class: DSP baseline (CPU)** · `snr/v1t0_babble_05db.wav` — expected speech got mixed
- **content class: DSP baseline (CPU)** · `snr/v1t0_babble_10db.wav` — expected speech got mixed
- **content class: DSP baseline (CPU)** · `snr/v1t0_babble_15db.wav` — expected speech got mixed
- **content class: DSP baseline (CPU)** · `snr/v1t0_babble_20db.wav` — expected speech got mixed
- **content class: DSP baseline (CPU)** · `snr/v1t0_babble_30db.wav` — expected speech got mixed
- **content class: DSP baseline (CPU)** · `snr/v1t1_white_30db.wav` — expected speech got mixed
- **content class: DSP baseline (CPU)** · `snr/v1t1_pink_30db.wav` — expected speech got mixed
- **content class: DSP baseline (CPU)** · `snr/v1t1_babble_00db.wav` — expected speech got mixed
- **content class: DSP baseline (CPU)** · `snr/v1t1_babble_05db.wav` — expected speech got mixed
- **content class: DSP baseline (CPU)** · `snr/v1t1_babble_10db.wav` — expected speech got mixed
- **content class: DSP baseline (CPU)** · `snr/v1t1_babble_15db.wav` — expected speech got mixed
- **content class: DSP baseline (CPU)** · `snr/v1t1_babble_20db.wav` — expected speech got mixed
- **content class: DSP baseline (CPU)** · `snr/v1t1_babble_30db.wav` — expected speech got mixed
- **content class: DSP baseline (CPU)** · `routes/podcast.mp3` — expected speech got mixed
- **routing** · `routes/mixed_music_speech.wav` — expected R10 got R08
- **bundle** `bundle_001`: 2 valid of 3 speaker tracks, 3 declared → INCOMPLETE (capped at Silver, E14 review)
