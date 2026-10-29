# Bake-off run — DESKTOP-TQKLFGI

GPU: NVIDIA GeForce RTX 3070 Laptop GPU, 8192 MiB, 610.62 · CPUs: 16 · Windows 11 AMD64

**116 files, 28.8 min of audio, processed in 30.8 s → 56.1× realtime** (CPU steps only)

## Task accuracy against ground truth

| Task | Passed | Accuracy |
|---|---|---|
| gates | 106/107 | 99.1% |
| spectral (fake hi-res / lossy origin) | 1/4 | 25.0% |
| bit depth | 3/3 | 100.0% |
| stereo checks | 5/5 | 100.0% |
| content class (DSP baseline) | 48/77 | 62.3% |
| clipping | 1/1 | 100.0% |
| hum | 2/2 | 100.0% |
| dc offset | 1/1 | 100.0% |
| dropouts | 1/1 | 100.0% |
| silence padding | 1/1 | 100.0% |
| routing | 11/12 | 91.7% |
| extension mismatch | 1/1 | 100.0% |
| duplicates | 6/7 | 85.7% |

## SNR estimator candidates (speech + white/pink/babble noise, 0–30 dB)

| Candidate | Files | Mean abs error | Within ±3 dB | MAE white / pink / babble | Speed |
|---|---|---|---|---|---|
| snr.wada | 72 | 3.88 dB | 61.1% | 1.17 / 1.18 / 9.3 dB | 2074.6× |
| snr.energy | 72 | 5.04 dB | 50.0% | 2.01 / 2.93 / 10.18 dB | 16633.3× |

## Step speed

| Step | Calls | Total ms | Realtime × |
|---|---|---|---|
| decode.probe | 116 | 6742 | 256.5 |
| decode.full | 116 | 6504 | 265.9 |
| fingerprint.compute | 105 | 3741 | 434.8 |
| dsp.hum | 105 | 3305 | 492.1 |
| dsp.levels | 105 | 2761 | 589.1 |
| classify.content | 105 | 2252 | 722.3 |
| dsp.spectral | 105 | 2234 | 728.1 |
| dsp.loudness | 105 | 1113 | 1461.0 |
| snr.wada | 105 | 784 | 2074.6 |
| dsp.dropouts | 105 | 735 | 2211.5 |
| dsp.bit_depth | 105 | 251 | 6473.1 |
| dsp.silence | 105 | 161 | 10133.8 |
| snr.energy | 105 | 98 | 16633.3 |
| dsp.stereo | 105 | 50 | 32434.1 |
| gates.basic | 116 | 31 | 54931.1 |
| duplex.stats | 1 | 12 | 2289.4 |
| cache.lookup | 109 | 0 | 168315100.0 |

## Routes chosen

R00: 7, R01: 4, R02: 2, R03: 50, R04: 1, R05: 1, R07: 5, R08: 1, R09: 1, R10: 44

## Pending model steps (skipped, lower coverage)

vad (100), bundle.verify_tracks (2), mos.speech (55), asr (54), pii.detect (54), ai_detect (54), music.analysis (2), lid (53), classify.content.gpu (44), events.tagging (46), snr_c50 (52), align.words (52), quality.general (2), duplex.crosstalk (1), separate.vocals (1)

## Failures

- **gates** · `gates/truncated.wav` — expected ['G4'] got ['G3']
- **spectral (fake hi-res / lossy origin)** · `defects/fake_hires_from16k.wav` — expected upsampled_from_16000hz got full_band (cutoff 24000 Hz, cliff 0.0 dB)
- **spectral (fake hi-res / lossy origin)** · `defects/fake_hires_from22k.wav` — expected upsampled_from_22050hz got full_band (cutoff 22050 Hz, cliff 0.0 dB)
- **spectral (fake hi-res / lossy origin)** · `defects/mp3_in_wav.wav` — expected lossy_origin_suspected got full_band (cutoff 24000 Hz, cliff 0.0 dB)
- **content class (DSP baseline)** · `quality/clean_48k.wav` — expected speech got mixed (syllabic 0.385, flatness 0.168)
- **content class (DSP baseline)** · `snr/v0t0_babble_00db.wav` — expected speech got mixed (syllabic 0.362, flatness 0.169)
- **content class (DSP baseline)** · `snr/v0t0_babble_05db.wav` — expected speech got mixed (syllabic 0.382, flatness 0.17)
- **content class (DSP baseline)** · `snr/v0t0_babble_30db.wav` — expected speech got mixed (syllabic 0.387, flatness 0.167)
- **content class (DSP baseline)** · `snr/v0t1_white_30db.wav` — expected speech got mixed (syllabic 0.345, flatness 0.146)
- **content class (DSP baseline)** · `snr/v0t1_pink_30db.wav` — expected speech got mixed (syllabic 0.337, flatness 0.144)
- **content class (DSP baseline)** · `snr/v0t1_babble_00db.wav` — expected speech got mixed (syllabic 0.318, flatness 0.152)
- **content class (DSP baseline)** · `snr/v0t1_babble_05db.wav` — expected speech got mixed (syllabic 0.318, flatness 0.149)
- **content class (DSP baseline)** · `snr/v0t1_babble_10db.wav` — expected speech got mixed (syllabic 0.316, flatness 0.147)
- **content class (DSP baseline)** · `snr/v0t1_babble_15db.wav` — expected speech got mixed (syllabic 0.309, flatness 0.145)
- **content class (DSP baseline)** · `snr/v0t1_babble_20db.wav` — expected speech got mixed (syllabic 0.298, flatness 0.144)
- **content class (DSP baseline)** · `snr/v0t1_babble_30db.wav` — expected speech got mixed (syllabic 0.264, flatness 0.143)
- **content class (DSP baseline)** · `snr/v1t0_white_30db.wav` — expected speech got mixed (syllabic 0.382, flatness 0.089)
- **content class (DSP baseline)** · `snr/v1t0_pink_30db.wav` — expected speech got mixed (syllabic 0.378, flatness 0.087)
- **content class (DSP baseline)** · `snr/v1t0_babble_00db.wav` — expected speech got mixed (syllabic 0.298, flatness 0.113)
- **content class (DSP baseline)** · `snr/v1t0_babble_05db.wav` — expected speech got mixed (syllabic 0.295, flatness 0.101)
- **content class (DSP baseline)** · `snr/v1t0_babble_10db.wav` — expected speech got mixed (syllabic 0.291, flatness 0.092)
- **content class (DSP baseline)** · `snr/v1t0_babble_15db.wav` — expected speech got mixed (syllabic 0.286, flatness 0.088)
- **content class (DSP baseline)** · `snr/v1t0_babble_20db.wav` — expected speech got mixed (syllabic 0.281, flatness 0.087)
- **content class (DSP baseline)** · `snr/v1t0_babble_30db.wav` — expected speech got mixed (syllabic 0.265, flatness 0.086)
- **content class (DSP baseline)** · `snr/v1t1_white_30db.wav` — expected speech got mixed (syllabic 0.354, flatness 0.078)
- **content class (DSP baseline)** · `snr/v1t1_pink_30db.wav` — expected speech got mixed (syllabic 0.355, flatness 0.075)
- **content class (DSP baseline)** · `snr/v1t1_babble_00db.wav` — expected speech got mixed (syllabic 0.296, flatness 0.108)
- **content class (DSP baseline)** · `snr/v1t1_babble_05db.wav` — expected speech got mixed (syllabic 0.291, flatness 0.092)
- **content class (DSP baseline)** · `snr/v1t1_babble_10db.wav` — expected speech got mixed (syllabic 0.287, flatness 0.082)
- **content class (DSP baseline)** · `snr/v1t1_babble_15db.wav` — expected speech got mixed (syllabic 0.281, flatness 0.076)
- **content class (DSP baseline)** · `snr/v1t1_babble_20db.wav` — expected speech got mixed (syllabic 0.274, flatness 0.074)
- **content class (DSP baseline)** · `snr/v1t1_babble_30db.wav` — expected speech got mixed (syllabic 0.255, flatness 0.074)
- **content class (DSP baseline)** · `routes/podcast.mp3` — expected speech got mixed (syllabic 0.385, flatness 0.168)
- **routing** · `routes/podcast.mp3` — expected R03 got R10
- **duplicates** · `dups/clip_8s.wav` — expected containment got unrelated (sim 0.586, overlap 0.552/1.0)
- **bundle** `bundle_001`: 2 valid of 3 speaker tracks, 3 declared → INCOMPLETE (capped at Silver, E14 review)
