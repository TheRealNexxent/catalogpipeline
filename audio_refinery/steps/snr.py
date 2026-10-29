"""Speech SNR estimators (Baseline.md M303). Two CPU candidates for the bake-off.

wada:    Kim & Stern (2008) waveform-amplitude-distribution analysis. The lookup
         table is generated here by simulation (Gamma-distributed speech, shape 0.4,
         plus Gaussian noise) instead of being copied from a published table.
energy:  frame-energy percentiles: noise = quietest 10% of frames, speech = frames
         at least 6 dB above that.
Both read the shared 16 kHz mono copy.
"""
from __future__ import annotations
from functools import lru_cache
import numpy as np

STEP_VERSION = 'snr-v1'
EPS = 1e-10


def _wada_stat(z):
    a = np.abs(z)
    a = a[a > EPS]
    if not len(a):
        return None
    return float(np.log(a.mean()) - np.log(a).mean())


@lru_cache(maxsize=1)
def _wada_table():
    rng = np.random.default_rng(1234)
    n = 400_000
    speech = rng.gamma(0.4, 1.0, n) * rng.choice((-1.0, 1.0), n)
    speech /= np.sqrt(np.mean(speech ** 2))
    noise = rng.standard_normal(n)
    snrs = np.arange(-20, 101, 1.0)
    stats = np.array([_wada_stat(speech + noise * 10 ** (-s / 20)) for s in snrs])
    return snrs, stats


def wada(ctx, params=None):
    z = ctx['x16']
    g = _wada_stat(z)
    if g is None:
        return {'snr_wada_db': None}
    snrs, stats = _wada_table()
    order = np.argsort(stats)
    value = float(np.interp(g, stats[order], snrs[order]))
    return {'snr_wada_db': round(value, 2)}


def energy(ctx, params=None):
    z = ctx['x16'].astype(np.float64)
    n = 400  # 25 ms at 16 kHz
    usable = len(z) // n * n
    if usable < n * 8:
        return {'snr_energy_db': None}
    p = np.mean(z[:usable].reshape(-1, n) ** 2, axis=1) + EPS
    noise = np.mean(np.sort(p)[: max(1, len(p) // 10)])
    speech = p[p > noise * 4]
    if not len(speech):
        return {'snr_energy_db': 0.0}
    return {'snr_energy_db': round(10 * np.log10(max(speech.mean() - noise, EPS) / noise), 2)}
