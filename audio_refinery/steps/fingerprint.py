"""Robust audio fingerprint (Haitsma & Kalker style) for near-duplicate checks (M103).

This is the in-house CPU candidate; Chromaprint is its bake-off competitor.
One 32-bit sub-fingerprint per ~12.8 ms frame, from energy differences between
33 log-spaced bands (300-2000 Hz). Differences make it insensitive to gain changes.
"""
from __future__ import annotations
import numpy as np
from scipy.signal import resample_poly

STEP_VERSION = 'fp-philips-v1'
FS, FRAME, HOP = 5000, 2048, 64
FRAME_S = HOP / FS


def compute(ctx, params=None):
    x = resample_poly(ctx['x16'].astype(np.float64), 5, 16)
    if len(x) < FRAME * 2:
        ctx['fingerprint'] = np.zeros(0, np.uint32)
        return {'fingerprint_frames': 0}
    idx = np.arange(FRAME)[None, :] + HOP * np.arange((len(x) - FRAME) // HOP)[:, None]
    spec = np.abs(np.fft.rfft(x[idx] * np.hanning(FRAME), axis=1)) ** 2
    freqs = np.fft.rfftfreq(FRAME, 1 / FS)
    edges = np.geomspace(300, 2000, 34)
    bands = np.stack([spec[:, (freqs >= lo) & (freqs < hi)].sum(axis=1) for lo, hi in zip(edges[:-1], edges[1:])], 1)
    d = bands[:, :-1] - bands[:, 1:]
    bits = (d[1:] - d[:-1]) > 0
    fp = (bits.astype(np.uint64) << np.arange(32, dtype=np.uint64)).sum(axis=1).astype(np.uint32)
    ctx['fingerprint'] = fp
    return {'fingerprint_frames': int(len(fp))}


def compare(a, b, min_match_s=3.0):
    """Best alignment of two fingerprints: similarity = 1 - bit error rate (0.5 random, 1 identical) and overlap shares."""
    if not len(a) or not len(b):
        return {'similarity': 0.0, 'overlap_a': 0.0, 'overlap_b': 0.0, 'offset_s': None}
    win = 78  # ~1 s smoothing
    best = (0, None, None)
    for off in range(-(len(b) - win), len(a) - win):
        a0, b0 = max(off, 0), max(-off, 0)
        n = min(len(a) - a0, len(b) - b0)
        if n < win:
            continue
        err = np.bitwise_count(a[a0:a0 + n] ^ b[b0:b0 + n]).astype(np.float64) / 32
        smooth = np.convolve(err, np.ones(win) / win, mode='same')
        matched = smooth < 0.30
        count = int(matched.sum())
        if count > best[0]:
            best = (count, off, float(err[matched].mean()) if count else 0.5)
    count, off, ber = best
    if count * FRAME_S < min_match_s:
        return {'similarity': 0.0, 'overlap_a': 0.0, 'overlap_b': 0.0, 'offset_s': None}
    return {'similarity': round(1 - ber, 3), 'bit_error_rate': round(ber, 3), 'overlap_a': round(count / len(a), 3),
            'overlap_b': round(count / len(b), 3), 'offset_s': round(off * FRAME_S, 2)}


def classify(match, threshold=0.65):
    """Baseline.md section 10.1 overlap rules. Default threshold = BER 0.35, the match level Haitsma & Kalker report."""
    if match['similarity'] < threshold:
        return 'unrelated'
    oa, ob = match['overlap_a'], match['overlap_b']
    if oa >= 0.9 and ob >= 0.9:
        return 'duplicate'
    if oa >= 0.9 or ob >= 0.9:
        return 'containment'
    if oa < 0.3 and ob < 0.3:
        return 'shared_segment'
    return 'partial_overlap'
