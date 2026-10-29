"""Cheap content-type and duplex checks on the 16 kHz copy.

classify_dsp is the CPU *baseline* candidate for classify.content (M301). It exists so the
router can work before the GPU classifiers are benchmarked; EfficientAT / BEATs are expected
to beat it. duplex_stats covers the per-channel parts of route R05 that need no model.
"""
from __future__ import annotations
import numpy as np
from scipy.signal import welch

STEP_VERSION = 'content-dsp-v1'


def _env(x, sr, hop_s=0.01):
    n = int(sr * hop_s)
    usable = len(x) // n * n
    return np.sqrt(np.mean(x[:usable].reshape(-1, n) ** 2, axis=1) + 1e-12)


def classify_dsp(ctx, params=None):
    x = ctx['x16'].astype(np.float64)
    env = _env(x, 16000)
    active = env > max(np.percentile(env, 95) * 10 ** (-40 / 20), 10 ** (-60 / 20))
    if active.mean() < 0.05:
        return {'content_class_dsp': 'silence'}
    e = np.log(env + 1e-6)
    e -= e.mean()
    f, p = welch(e, 100, nperseg=min(len(e), 512))
    syllabic = float(p[(f >= 2) & (f <= 8)].sum() / (p[(f > 0.5) & (f <= 30)].sum() + 1e-12))
    f2, p2 = welch(x, 16000, nperseg=1024)
    band = (f2 > 100) & (f2 < 6000)
    flatness = float(np.exp(np.mean(np.log(p2[band] + 1e-20))) / (np.mean(p2[band]) + 1e-20))
    if flatness > 0.35 and syllabic < 0.45:
        label, conf = 'noise_or_ambient', min(1.0, flatness)
    elif syllabic >= 0.40:
        label, conf = 'speech', min(1.0, 0.5 + syllabic / 2)
    elif syllabic < 0.25 and flatness < 0.05:
        label, conf = 'music', min(1.0, 0.5 + (0.4 - syllabic))
    else:
        label, conf = 'mixed', 0.5
    return {'content_class_dsp': label, 'content_confidence_dsp': round(conf, 2),
            'syllabic_modulation': round(syllabic, 3), 'spectral_flatness': round(flatness, 3)}


def duplex_crosstalk(ctx, params=None):
    """Level of each channel while ONLY the other one is talking = bleed between the two microphones."""
    x, sr = ctx['x'], ctx['sample_rate']
    if x.shape[1] != 2:
        return {}
    envs = [_env(x[:, c].astype(np.float64), sr, 0.05) for c in range(2)]
    acts = [e > max(np.percentile(e, 95) * 10 ** (-35 / 20), 10 ** (-60 / 20)) for e in envs]
    out = []
    for a, b in ((0, 1), (1, 0)):
        only = acts[a] & ~acts[b]
        if only.sum() < 10:
            out.append(None)
            continue
        out.append(round(float(20 * np.log10(np.median(envs[b][only]) / np.median(envs[a][only]))), 1))
    worst = max([v for v in out if v is not None], default=None)
    return {'crosstalk_db': out, 'crosstalk_worst_db': worst,
            'crosstalk_flag': bool(worst is not None and worst > -20)}


def verify_track(ctx, params=None):
    """A supplied speaker track must actually contain speech-level activity (bundle completeness, Baseline section 5)."""
    env = _env(ctx['x16'].astype(np.float64), 16000, 0.05)
    active = env > 10 ** (-45 / 20)
    return {'track_active_pct': round(100 * float(active.mean()), 1), 'track_usable': bool(active.mean() > 0.01)}


def duplex_stats(ctx, params=None):
    """Per-channel speech activity, overlap and speaker balance for two-channel conversations."""
    x, sr = ctx['x'], ctx['sample_rate']
    if x.shape[1] != 2:
        return {}
    envs = [_env(x[:, c].astype(np.float64), sr, 0.05) for c in range(2)]
    acts = [e > max(np.percentile(e, 95) * 10 ** (-35 / 20), 10 ** (-60 / 20)) for e in envs]
    a, b = acts
    share = [float(v.mean()) for v in acts]
    return {'channel_active_pct': [round(100 * s, 1) for s in share],
            'overlap_pct': round(100 * float((a & b).mean()), 1),
            'speaker_balance': round(min(share) / max(share), 3) if max(share) else 0.0}
