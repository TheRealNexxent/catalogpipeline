# Model licence and platform audit (2026-10-29)

**Rule:** a model is eligible only when its code **and** weights both allow commercial use.
**Hardware:** DGX Spark (ARM64 + GB10) and the Windows RTX 3070 box.

Sources were the Hugging Face model cards, the GitHub licence API, and each repo's LICENSE file. **This is an engineering pre-screen, not legal advice:** counsel signs off before release.

## Platform findings

- **PyTorch:** official aarch64 CUDA wheels exist (cu128–cu130), and so does the NGC `nvcr.io/nvidia/pytorch` container. Any pure-PyTorch model therefore has an ARM64 path.
- **onnxruntime-gpu:** aarch64 wheels exist. GB10 (sm_121) kernels are unconfirmed, so test on the DGX.
- **CTranslate2 / faster-whisper:** the aarch64 wheel is **CPU-only**, so GPU use on the DGX needs a source build. On Windows x86, the pip install works on GPU.
- **NeMo** (Parakeet, Canary, Sortformer, TitaNet): use the NGC container on the DGX, and WSL2 or Docker on Windows.
- **Essentia:** no aarch64 wheels; it would need a source build.

## Eligible (commercial OK)

| Task | Model | Code / weights licence | Notes |
|---|---|---|---|
| Fingerprint | Chromaprint | MIT (+ LGPL FFmpeg parts) | CPU |
| Tagging / embeddings | LAION-CLAP | CC0 / Apache-2.0 | AudioSet-derived training data |
| Tagging / embeddings | Microsoft CLAP | MIT / MS-PL | |
| Tagging | EfficientAT mn10/mn40 | MIT / MIT | 4.9M–68M parameters; AudioSet-derived |
| VAD | Silero VAD | MIT / MIT | ~2 MB; ONNX option |
| Segmentation / diarization | pyannote 3.0 / 3.1 / community-1 | MIT / MIT, CC-BY-4.0 | **Gated:** needs an HF token |
| SNR + C50 + VAD | Brouhaha | MIT / MIT | |
| Speech quality | UTMOS / UTMOSv2 | MIT / MIT | Trained on BVCC |
| General quality | Audiobox Aesthetics | CC-BY-4.0 | |
| Language ID | SpeechBrain VoxLingua107 ECAPA | Apache-2.0 | |
| ASR | Whisper large-v3 / turbo | MIT / Apache-2.0, MIT | |
| ASR | Parakeet-TDT v2/v3, Canary-1b-flash / v2 | Apache-2.0 / CC-BY-4.0 | The original `canary-1b` is non-commercial; avoid it |
| ASR (Indic) | IndicConformer | MIT / MIT, CC-BY-4.0 | Gated |
| ASR (long tail) | Omnilingual ASR | Apache-2.0 | 300M–7B parameters |
| PII | Presidio; GLiNER-PII models | MIT; Apache-2.0 / NVIDIA Open Model License | |
| Diarization | Sortformer streaming v2 / v2.1 | Apache-2.0 / CC-BY-4.0, NVIDIA OML | v1 is non-commercial |
| Speaker embeddings | TitaNet, SpeechBrain ECAPA, WeSpeaker | CC-BY-4.0 / Apache-2.0 | |
| Anti-spoofing | AASIST (clovaai) | MIT / MIT | Trained on ASVspoof2019 (ODC-By) |
| Separation | Demucs htdemucs | MIT / MIT | **Dataset flag:** MUSDB18 is research-only |
| Bioacoustics | Google Perch 2.0 | Apache-2.0 | Training data includes NC-licensed recordings |

## Excluded (non-commercial)

NISQA weights · MMS-LID and MMS-1B-all · Sortformer v1 · original canary-1b · AASIST3 · audeering age-gender · MERT · Essentia TF models · BirdNET

## Needs legal review

- **emotion2vec / emotion2vec+:** the licence includes "for reference and learning purposes only" wording.
- **Weights with no explicit licence:** DNSMOS ONNX files, BEATs, WavLM (which also inherits GigaSpeech's terms), SSL-AASIST.
- **BS-RoFormer and MDX-Net:** community checkpoints.
- **Essentia core:** AGPL-3.0, or buy UPF's commercial licence.
- **Dataset-derived risk:** Demucs, Perch, UTMOS, EfficientAT, BEATs and CLAP have permissive weights, but training data that is not commercially licensed.

## Gaps with no eligible model

- **Age / gender:** train a small head on ECAPA or WavLM embeddings, using commercially licensed labels such as Common Voice (CC0).
- **Emotion:** if emotion2vec isn't cleared, train our own head as well.
- **Music tagging:** use LAION-CLAP music checkpoints, or license Essentia models from UPF.
