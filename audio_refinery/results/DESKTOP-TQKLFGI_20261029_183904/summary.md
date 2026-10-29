# Bake-off run — DESKTOP-TQKLFGI

GPU: NVIDIA GeForce RTX 3070 Laptop GPU, 8192 MiB, 610.62 · CPUs: 16 · Windows 11 AMD64

**116 files, 29.6 min of audio, processed in 31.38 s → 56.6× realtime** (CPU steps only)

## Task accuracy against ground truth

| Task | Passed | Accuracy |
|---|---|---|
| gates | 106/107 | 99.1% |
| spectral (fake hi-res / lossy origin) | 0/4 | 0.0% |
| bit depth | 2/3 | 66.7% |
| stereo checks | 4/5 | 80.0% |
| content class (DSP baseline) | 3/77 | 3.9% |
| clipping | 1/1 | 100.0% |
| hum | 0/2 | 0.0% |
| dc offset | 1/1 | 100.0% |
| dropouts | 1/1 | 100.0% |
| silence padding | 0/1 | 0.0% |
| routing | 10/12 | 83.3% |
| extension mismatch | 1/1 | 100.0% |
| duplicates | 5/8 | 62.5% |

## SNR estimator candidates (speech + white/pink/babble noise, 0–30 dB)

| Candidate | Files | Mean abs error | Within ±3 dB | MAE white / pink / babble | Speed |
|---|---|---|---|---|---|
| snr.wada | 72 | 4.93 dB | 55.6% | 1.86 / 1.88 / 11.03 dB | 2037.5× |

## Step speed

| Step | Calls | Total ms | Realtime × |
|---|---|---|---|
| decode.full | 116 | 6650 | 267.2 |
| decode.probe | 116 | 6243 | 284.6 |
| fingerprint.compute | 106 | 4220 | 397.5 |
| dsp.levels | 106 | 3064 | 547.5 |
| classify.content | 106 | 2630 | 637.9 |
| dsp.spectral | 106 | 2613 | 642.0 |
| dsp.hum | 106 | 2443 | 686.8 |
| dsp.loudness | 106 | 1247 | 1345.7 |
| dsp.dropouts | 106 | 838 | 2002.0 |
| snr.wada | 106 | 823 | 2037.5 |
| dsp.bit_depth | 106 | 296 | 5673.0 |
| dsp.silence | 106 | 182 | 9218.1 |
| dsp.stereo | 106 | 61 | 27581.5 |
| gates.basic | 116 | 34 | 52338.6 |
| duplex.stats | 1 | 12 | 2344.6 |
| cache.lookup | 110 | 0 | None |

## Routes chosen

R00: 6, R01: 4, R02: 2, R03: 2, R04: 1, R05: 1, R07: 5, R08: 29, R09: 1, R10: 65

## Pending model steps (skipped, lower coverage)

vad (73), bundle.verify_tracks (2), mos.speech (7), asr (6), pii.detect (6), ai_detect (6), music.analysis (30), lid (5), quality.general (30), events.tagging (95), separate.vocals (29), classify.content.gpu (65), snr_c50 (4), align.words (4), duplex.crosstalk (1)

## Failures

- **gates** · `gates/truncated.wav` — expected ['G4'] got []
- **spectral (fake hi-res / lossy origin)** · `quality/clean_48k.wav` — expected full_band got None (cutoff None Hz, cliff None dB)
- **spectral (fake hi-res / lossy origin)** · `defects/fake_hires_from16k.wav` — expected upsampled_from_16000hz got full_band (cutoff 24000 Hz, cliff 0.0 dB)
- **spectral (fake hi-res / lossy origin)** · `defects/fake_hires_from22k.wav` — expected upsampled_from_22050hz got full_band (cutoff 22050 Hz, cliff 0.0 dB)
- **spectral (fake hi-res / lossy origin)** · `defects/mp3_in_wav.wav` — expected lossy_origin_suspected got full_band (cutoff 24000 Hz, cliff 0.0 dB)
- **bit depth** · `quality/clean_48k.wav` — expected 16/padded=False got None/padded=None
- **stereo checks** · `quality/clean_48k.wav` — expected mono got None
- **content class (DSP baseline)** · `quality/clean_48k.wav` — expected speech got None (syllabic None, flatness None)
- **content class (DSP baseline)** · `snr/v0t0_white_00db.wav` — expected speech got mixed (syllabic 0.663, flatness 0.766)
- **content class (DSP baseline)** · `snr/v0t0_white_05db.wav` — expected speech got mixed (syllabic 0.645, flatness 0.529)
- **content class (DSP baseline)** · `snr/v0t0_white_10db.wav` — expected speech got mixed (syllabic 0.624, flatness 0.34)
- **content class (DSP baseline)** · `snr/v0t0_white_15db.wav` — expected speech got mixed (syllabic 0.586, flatness 0.238)
- **content class (DSP baseline)** · `snr/v0t0_white_20db.wav` — expected speech got mixed (syllabic 0.551, flatness 0.193)
- **content class (DSP baseline)** · `snr/v0t0_white_30db.wav` — expected speech got mixed (syllabic 0.472, flatness 0.17)
- **content class (DSP baseline)** · `snr/v0t0_pink_00db.wav` — expected speech got mixed (syllabic 0.467, flatness 0.399)
- **content class (DSP baseline)** · `snr/v0t0_pink_05db.wav` — expected speech got mixed (syllabic 0.596, flatness 0.292)
- **content class (DSP baseline)** · `snr/v0t0_pink_10db.wav` — expected speech got mixed (syllabic 0.604, flatness 0.222)
- **content class (DSP baseline)** · `snr/v0t0_pink_15db.wav` — expected speech got mixed (syllabic 0.589, flatness 0.187)
- **content class (DSP baseline)** · `snr/v0t0_pink_20db.wav` — expected speech got mixed (syllabic 0.539, flatness 0.174)
- **content class (DSP baseline)** · `snr/v0t0_pink_30db.wav` — expected speech got mixed (syllabic 0.468, flatness 0.168)
- **content class (DSP baseline)** · `snr/v0t0_babble_00db.wav` — expected speech got music (syllabic 0.384, flatness 0.171)
- **content class (DSP baseline)** · `snr/v0t0_babble_05db.wav` — expected speech got mixed (syllabic 0.407, flatness 0.172)
- **content class (DSP baseline)** · `snr/v0t0_babble_10db.wav` — expected speech got mixed (syllabic 0.428, flatness 0.17)
- **content class (DSP baseline)** · `snr/v0t0_babble_15db.wav` — expected speech got mixed (syllabic 0.44, flatness 0.168)
- **content class (DSP baseline)** · `snr/v0t0_babble_20db.wav` — expected speech got mixed (syllabic 0.441, flatness 0.168)
- **content class (DSP baseline)** · `snr/v0t1_white_00db.wav` — expected speech got mixed (syllabic 0.548, flatness 0.757)
- **content class (DSP baseline)** · `snr/v0t1_white_05db.wav` — expected speech got mixed (syllabic 0.538, flatness 0.513)
- **content class (DSP baseline)** · `snr/v0t1_white_10db.wav` — expected speech got mixed (syllabic 0.507, flatness 0.321)
- **content class (DSP baseline)** · `snr/v0t1_white_15db.wav` — expected speech got mixed (syllabic 0.461, flatness 0.216)
- **content class (DSP baseline)** · `snr/v0t1_white_20db.wav` — expected speech got mixed (syllabic 0.415, flatness 0.171)
- **content class (DSP baseline)** · `snr/v0t1_white_30db.wav` — expected speech got music (syllabic 0.33, flatness 0.146)
- **content class (DSP baseline)** · `snr/v0t1_pink_00db.wav` — expected speech got mixed (syllabic 0.454, flatness 0.389)
- **content class (DSP baseline)** · `snr/v0t1_pink_05db.wav` — expected speech got mixed (syllabic 0.533, flatness 0.271)
- **content class (DSP baseline)** · `snr/v0t1_pink_10db.wav` — expected speech got mixed (syllabic 0.478, flatness 0.195)
- **content class (DSP baseline)** · `snr/v0t1_pink_15db.wav` — expected speech got mixed (syllabic 0.442, flatness 0.163)
- **content class (DSP baseline)** · `snr/v0t1_pink_20db.wav` — expected speech got mixed (syllabic 0.413, flatness 0.15)
- **content class (DSP baseline)** · `snr/v0t1_pink_30db.wav` — expected speech got music (syllabic 0.326, flatness 0.144)
- **content class (DSP baseline)** · `snr/v0t1_babble_00db.wav` — expected speech got music (syllabic 0.318, flatness 0.156)
- **content class (DSP baseline)** · `snr/v0t1_babble_05db.wav` — expected speech got music (syllabic 0.315, flatness 0.152)
- **content class (DSP baseline)** · `snr/v0t1_babble_10db.wav` — expected speech got music (syllabic 0.31, flatness 0.148)
- **content class (DSP baseline)** · `snr/v0t1_babble_15db.wav` — expected speech got music (syllabic 0.304, flatness 0.146)
- **content class (DSP baseline)** · `snr/v0t1_babble_20db.wav` — expected speech got music (syllabic 0.292, flatness 0.144)
- **content class (DSP baseline)** · `snr/v0t1_babble_30db.wav` — expected speech got music (syllabic 0.258, flatness 0.144)
- **content class (DSP baseline)** · `snr/v1t0_white_00db.wav` — expected speech got mixed (syllabic 0.538, flatness 0.693)
- **content class (DSP baseline)** · `snr/v1t0_white_05db.wav` — expected speech got mixed (syllabic 0.532, flatness 0.436)
- **content class (DSP baseline)** · `snr/v1t0_white_10db.wav` — expected speech got mixed (syllabic 0.516, flatness 0.249)
- **content class (DSP baseline)** · `snr/v1t0_white_15db.wav` — expected speech got mixed (syllabic 0.489, flatness 0.154)
- **content class (DSP baseline)** · `snr/v1t0_white_20db.wav` — expected speech got mixed (syllabic 0.457, flatness 0.112)
- **content class (DSP baseline)** · `snr/v1t0_white_30db.wav` — expected speech got music (syllabic 0.39, flatness 0.089)
- **content class (DSP baseline)** · `snr/v1t0_pink_00db.wav` — expected speech got mixed (syllabic 0.446, flatness 0.338)
- **content class (DSP baseline)** · `snr/v1t0_pink_05db.wav` — expected speech got mixed (syllabic 0.47, flatness 0.219)
- **content class (DSP baseline)** · `snr/v1t0_pink_10db.wav` — expected speech got mixed (syllabic 0.517, flatness 0.141)
- **content class (DSP baseline)** · `snr/v1t0_pink_15db.wav` — expected speech got mixed (syllabic 0.488, flatness 0.106)
- **content class (DSP baseline)** · `snr/v1t0_pink_20db.wav` — expected speech got mixed (syllabic 0.449, flatness 0.093)
- **content class (DSP baseline)** · `snr/v1t0_pink_30db.wav` — expected speech got music (syllabic 0.386, flatness 0.086)
- **content class (DSP baseline)** · `snr/v1t0_babble_00db.wav` — expected speech got music (syllabic 0.315, flatness 0.118)
- **content class (DSP baseline)** · `snr/v1t0_babble_05db.wav` — expected speech got music (syllabic 0.31, flatness 0.104)
- **content class (DSP baseline)** · `snr/v1t0_babble_10db.wav` — expected speech got music (syllabic 0.305, flatness 0.094)
- **content class (DSP baseline)** · `snr/v1t0_babble_15db.wav` — expected speech got music (syllabic 0.299, flatness 0.089)
- **content class (DSP baseline)** · `snr/v1t0_babble_20db.wav` — expected speech got music (syllabic 0.293, flatness 0.087)
- **content class (DSP baseline)** · `snr/v1t0_babble_30db.wav` — expected speech got music (syllabic 0.274, flatness 0.086)
- **content class (DSP baseline)** · `snr/v1t1_white_00db.wav` — expected speech got mixed (syllabic 0.529, flatness 0.696)
- **content class (DSP baseline)** · `snr/v1t1_white_05db.wav` — expected speech got mixed (syllabic 0.512, flatness 0.434)
- **content class (DSP baseline)** · `snr/v1t1_white_10db.wav` — expected speech got mixed (syllabic 0.485, flatness 0.245)
- **content class (DSP baseline)** · `snr/v1t1_white_15db.wav` — expected speech got mixed (syllabic 0.443, flatness 0.147)
- **content class (DSP baseline)** · `snr/v1t1_white_20db.wav` — expected speech got mixed (syllabic 0.405, flatness 0.104)
- **content class (DSP baseline)** · `snr/v1t1_white_30db.wav` — expected speech got music (syllabic 0.33, flatness 0.078)
- **content class (DSP baseline)** · `snr/v1t1_pink_00db.wav` — expected speech got mixed (syllabic 0.431, flatness 0.34)
- **content class (DSP baseline)** · `snr/v1t1_pink_05db.wav` — expected speech got mixed (syllabic 0.495, flatness 0.213)
- **content class (DSP baseline)** · `snr/v1t1_pink_10db.wav` — expected speech got mixed (syllabic 0.475, flatness 0.133)
- **content class (DSP baseline)** · `snr/v1t1_pink_15db.wav` — expected speech got mixed (syllabic 0.435, flatness 0.097)
- **content class (DSP baseline)** · `snr/v1t1_pink_20db.wav` — expected speech got music (syllabic 0.395, flatness 0.082)
- **content class (DSP baseline)** · `snr/v1t1_pink_30db.wav` — expected speech got music (syllabic 0.326, flatness 0.075)
- **content class (DSP baseline)** · `snr/v1t1_babble_00db.wav` — expected speech got music (syllabic 0.313, flatness 0.113)
- **content class (DSP baseline)** · `snr/v1t1_babble_05db.wav` — expected speech got music (syllabic 0.308, flatness 0.097)
- **content class (DSP baseline)** · `snr/v1t1_babble_10db.wav` — expected speech got music (syllabic 0.303, flatness 0.085)
- **content class (DSP baseline)** · `snr/v1t1_babble_15db.wav` — expected speech got music (syllabic 0.295, flatness 0.078)
- **content class (DSP baseline)** · `snr/v1t1_babble_20db.wav` — expected speech got music (syllabic 0.286, flatness 0.075)
- **content class (DSP baseline)** · `snr/v1t1_babble_30db.wav` — expected speech got music (syllabic 0.259, flatness 0.074)
- **content class (DSP baseline)** · `routes/podcast.mp3` — expected speech got mixed (syllabic 0.396, flatness 0.167)
- **content class (DSP baseline)** · `routes/mixed_music_speech.wav` — expected mixed got music (syllabic 0.336, flatness 0.035)
- **hum** · `defects/hum_50hz.wav` — expected 50 got None (9.5 dB)
- **hum** · `defects/hum_60hz.wav` — expected 60 got None (9.9 dB)
- **silence padding** · `defects/silence_padded.wav` — lead 8.1 s, trail 8.75 s
- **routing** · `routes/podcast.mp3` — expected R03 got R10
- **routing** · `routes/mixed_music_speech.wav` — expected R10 got R08
- **duplicates** · `dups/clip_8s.wav` — expected containment got unrelated (sim 0.586, overlap 0.519/1.0)
- **duplicates** · `dups/call_A_with_ivr.wav` — expected shared_segment got unrelated (sim 0.0, overlap 0.0/0.0)
- **duplicates** · `dups/call_B_with_ivr.wav` — expected shared_segment got partial_overlap (sim 0.97, overlap 0.439/0.439)
- **bundle** `bundle_001`: 2 valid of 3 speaker tracks, 3 declared → INCOMPLETE (capped at Silver, E14 review)
