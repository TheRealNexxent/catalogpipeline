"""Wave 1 GPU model steps. Each model is loaded once per process and kept warm.

    vad                   Silero VAD                 (MIT)
    classify.content.gpu  EfficientAT mn10_as        (MIT; AudioSet-trained, dataset flag)
    events.tagging        same EfficientAT pass, top non-speech/music AudioSet labels
    mos.speech            UTMOSv2                    (MIT)
    lid                   SpeechBrain VoxLingua107   (Apache-2.0)
    ai_detect             AASIST                     (MIT; ASVspoof2019 LA, ODC-By)

Every step reads the shared decoded audio from ctx; nothing re-opens the file.
Weights are cached under audio_refinery/models_cache.
"""
from __future__ import annotations
import json, os, sys, time
from pathlib import Path
import numpy as np
from scipy.signal import resample_poly

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / 'models_cache'
os.environ.setdefault('HF_HOME', str(CACHE / 'hf'))
os.environ.setdefault('TORCH_HOME', str(CACHE / 'torch'))
import torch  # noqa: E402

# The TorchScript GPU fuser generates CUDA code that fails to compile under CUDA 12.8 + this driver
# (GLiNER's DeBERTa, on its second call). Scripted models run unfused instead.
torch._C._jit_set_texpr_fuser_enabled(False)
torch._C._jit_override_can_fuse_on_gpu(False)

DEVICE = 'cuda' if torch.cuda.is_available() else 'cpu'
STEP_VERSION = 'gpu-wave1-v1'
_MODELS = {}
LOAD_SECONDS = {}


GPU_BUDGET_BYTES = float(os.environ.get('REFINERY_GPU_BUDGET_GB', '6.5')) * 1e9


def _load(name, fn):
    """Load once and keep warm; past the GPU budget, the least recently used models are evicted (reloaded on demand)."""
    if name in _MODELS:
        _MODELS[name] = _MODELS.pop(name)  # mark as most recently used
        return _MODELS[name]
    t = time.perf_counter()
    _MODELS[name] = fn()
    if DEVICE == 'cuda':
        torch.cuda.synchronize()
        while torch.cuda.memory_allocated() > GPU_BUDGET_BYTES and len(_MODELS) > 1:
            oldest = next(iter(_MODELS))
            del _MODELS[oldest]
            EVICTIONS.append(oldest)
            import gc
            gc.collect()
            torch.cuda.empty_cache()
    LOAD_SECONDS[name] = round(LOAD_SECONDS.get(name, 0) + time.perf_counter() - t, 2)
    return _MODELS[name]


EVICTIONS = []


def _windows(n, size, count):
    """`count` evenly spread windows of `size` samples (whole signal if shorter)."""
    if n <= size:
        return [(0, n)]
    starts = np.linspace(0, n - size, min(count, max(1, n // size))).astype(int)
    return [(int(s), int(s) + size) for s in starts]


def _speech_or_all(ctx):
    """16 kHz audio restricted to detected speech, when VAD has run (speech-only principle)."""
    x, segs = ctx['x16'], ctx.get('speech_segments')
    if segs:
        parts = [x[int(a * 16000):int(b * 16000)] for a, b in segs]
        joined = np.concatenate(parts) if parts else x
        if len(joined) >= 16000:
            return joined
    return x


# ---------- Silero VAD ----------
def _silero():
    from silero_vad import load_silero_vad
    return load_silero_vad()


def vad(ctx, params=None):
    from silero_vad import get_speech_timestamps
    model = _load('silero_vad', _silero)
    wav = torch.from_numpy(np.ascontiguousarray(ctx['x16']))
    segs = get_speech_timestamps(wav, model, sampling_rate=16000, return_seconds=True)
    segments = [(round(s['start'], 2), round(s['end'], 2)) for s in segs]
    ctx['speech_segments'] = segments
    total = len(ctx['x16']) / 16000 or 1e-9
    speech = sum(b - a for a, b in segments)
    return {'speech_s': round(speech, 2), 'speech_ratio_pct': round(100 * speech / total, 1),
            'speech_segment_count': len(segments), 'vad_model': 'silero-vad', 'speech_segments': segments}


# ---------- EfficientAT (content type + event tags) ----------
SPEECH_LABELS = {'Speech', 'Male speech, man speaking', 'Female speech, woman speaking', 'Child speech, kid speaking',
                 'Conversation', 'Narration, monologue', 'Speech synthesizer', 'Babbling'}


def _efficientat():
    sys.path.insert(0, str(ROOT / 'vendor' / 'EfficientAT'))
    cwd = os.getcwd()
    os.chdir(ROOT / 'vendor' / 'EfficientAT')  # the repo resolves resources/ and metadata/ relative to cwd
    try:
        from models.mn.model import get_model
        from models.preprocess import AugmentMelSTFT
        from helpers.utils import NAME_TO_WIDTH, labels
        model = get_model(width_mult=NAME_TO_WIDTH('mn10_as'), pretrained_name='mn10_as').to(DEVICE).eval()
        mel = AugmentMelSTFT(n_mels=128, sr=32000, win_length=800, hopsize=320).to(DEVICE).eval()
    finally:
        os.chdir(cwd)
    labels = list(labels)
    speech_idx = [i for i, l in enumerate(labels) if l in SPEECH_LABELS]
    return {'model': model, 'mel': mel, 'labels': labels, 'speech_idx': speech_idx, 'music_idx': labels.index('Music')}


def _tag_windows(ctx):
    if 'effat_preds' in ctx:
        return ctx['effat_preds']
    m = _load('efficientat_mn10', _efficientat)
    sr = ctx['sample_rate']
    mono = ctx['mono']
    g = np.gcd(sr, 32000)
    x32 = resample_poly(mono, 32000 // g, sr // g).astype(np.float32)
    wins = [(a, b) for a, b in _windows(len(x32), 320000, 10_000)]  # every 10 s window (whole file)
    batch = [np.pad(x32[a:b], (0, 320000 - (b - a))) if b - a < 320000 else x32[a:b] for a, b in wins]
    rms = [float(np.sqrt(np.mean(x32[a:b] ** 2) + 1e-12)) for a, b in wins]
    preds = []
    with torch.no_grad(), torch.autocast(device_type=DEVICE, enabled=DEVICE == 'cuda'):
        for i in range(0, len(batch), 16):
            wav = torch.from_numpy(np.stack(batch[i:i + 16])).to(DEVICE)
            spec = m['mel'](wav)
            out, _ = m['model'](spec.unsqueeze(1))
            preds.append(torch.sigmoid(out.float()).cpu().numpy())
    p = np.concatenate(preds)
    ctx['effat_preds'] = (p, rms, m)
    return ctx['effat_preds']


def classify_content_gpu(ctx, params=None):
    p, rms, m = _tag_windows(ctx)
    labels = []
    for row, level in zip(p, rms):
        sp, mu = float(row[m['speech_idx']].max()), float(row[m['music_idx']])
        if level < 10 ** (-55 / 20):
            labels.append('silence')
        elif sp >= 0.5 and mu >= 0.5:
            labels.append('mixed')
        elif sp >= 0.5:
            labels.append('speech')
        elif mu >= 0.5:
            labels.append('music')
        else:
            labels.append('noise_or_ambient')
    voiced = [l for l in labels if l != 'silence'] or labels
    counts = {k: voiced.count(k) / len(voiced) for k in set(voiced)}
    top, share = max(counts.items(), key=lambda kv: kv[1])
    label = top if share >= 0.6 else 'mixed'
    return {'content_class': label, 'content_confidence': round(share, 2), 'content_method': 'efficientat_mn10',
            'content_windows': {k: round(v, 2) for k, v in counts.items()},
            'p_speech_max': round(float(p[:, m['speech_idx']].max()), 3), 'p_music_max': round(float(p[:, m['music_idx']].max()), 3)}


def events_tagging(ctx, params=None):
    p, _, m = _tag_windows(ctx)
    mean = p.mean(axis=0)
    skip = set(m['speech_idx']) | {m['music_idx']}
    order = [i for i in np.argsort(mean)[::-1] if i not in skip][:5]
    return {'events_top5': [(m['labels'][i], round(float(mean[i]), 3)) for i in order],
            'events_top': m['labels'][order[0]] if order and mean[order[0]] >= 0.2 else None}


# ---------- UTMOSv2 ----------
def _utmos():
    import utmosv2
    # UTMOSv2 cannot parse a bare 'cuda' string and silently stays on CPU; pass an explicit device.
    return utmosv2.create_model(pretrained=True, device=torch.device('cuda:0' if DEVICE == 'cuda' else 'cpu'))


def mos_speech(ctx, params=None):
    model = _load('utmosv2', _utmos)
    x = _speech_or_all(ctx)
    clip = x[: 16000 * 60]  # first minute of speech is enough for a file-level score
    score = model.predict(data=torch.from_numpy(np.ascontiguousarray(clip)), sr=16000,
                          device=torch.device('cuda:0' if DEVICE == 'cuda' else 'cpu'),
                          num_repetitions=1, num_workers=0, verbose=False)
    value = float(np.asarray(score).reshape(-1)[0])
    return {'mos_utmos': round(value, 3), 'mos_model': 'utmosv2-fusion_stage3', 'mos_coverage_s': round(len(clip) / 16000, 1)}


# ---------- VoxLingua107 language ID ----------
def _voxlingua():
    from speechbrain.inference.classifiers import EncoderClassifier
    from speechbrain.utils.fetching import LocalStrategy
    return EncoderClassifier.from_hparams(source='speechbrain/lang-id-voxlingua107-ecapa',
                                          savedir=str(CACHE / 'voxlingua107'), run_opts={'device': DEVICE},
                                          local_strategy=LocalStrategy.COPY)


def lid(ctx, params=None):
    model = _load('voxlingua107', _voxlingua)
    x = _speech_or_all(ctx)
    count = (params or {}).get('windows', 3)
    wins = _windows(len(x), 16000 * 10, count)
    votes, probs = [], []
    with torch.no_grad():
        for a, b in wins:
            out_prob, _, index, text = model.classify_batch(torch.from_numpy(np.ascontiguousarray(x[a:b]))[None].to(DEVICE))
            prob = float(torch.softmax(out_prob[0], -1).max()) if out_prob[0].max() <= 0 else float(out_prob[0].max())
            votes.append(text[0].split(':')[0])
            probs.append(prob)
    lang = max(set(votes), key=votes.count)
    conf = float(np.mean([p for v, p in zip(votes, probs) if v == lang]))
    return {'language': lang, 'language_confidence': round(conf, 3), 'language_windows': len(wins),
            'code_switch_suspected': len(set(votes)) > 1}


# ---------- AASIST anti-spoofing ----------
def _aasist():
    sys.path.insert(0, str(ROOT / 'vendor' / 'aasist'))
    from models.AASIST import Model
    conf = json.loads((ROOT / 'vendor' / 'aasist' / 'config' / 'AASIST.conf').read_text())
    model = Model(conf['model_config']).to(DEVICE).eval()
    model.load_state_dict(torch.load(ROOT / 'vendor' / 'aasist' / 'models' / 'weights' / 'AASIST.pth', map_location=DEVICE))
    return model


def ai_detect(ctx, params=None):
    model = _load('aasist', _aasist)
    x = _speech_or_all(ctx)
    size = 64600  # ~4 s, the AASIST input length
    wins = _windows(len(x), size, (params or {}).get('windows', 8))
    batch = np.stack([np.pad(x[a:b], (0, size - (b - a))) for a, b in wins]).astype(np.float32)
    with torch.no_grad():
        _, out = model(torch.from_numpy(batch).to(DEVICE))
        p_spoof = torch.softmax(out.float(), -1)[:, 0].cpu().numpy()
    score = float(p_spoof.mean())
    return {'ai_generated_score': round(score, 3),
            'ai_generated_flag': 'likely' if score >= 0.8 else 'possible' if score >= 0.5 else None,
            'ai_detect_windows': len(wins), 'ai_detect_model': 'aasist-la'}


def warm():
    """Load every wave 1 model once, so per-file timings measure steady-state speed."""
    for name, fn in (('silero_vad', _silero), ('efficientat_mn10', _efficientat), ('utmosv2', _utmos),
                     ('voxlingua107', _voxlingua), ('aasist', _aasist)):
        _load(name, fn)
    return dict(LOAD_SECONDS)
