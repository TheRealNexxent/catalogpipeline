"""Layer 2 signal-quality metrics (Baseline.md M201-M212). CPU only, whole file.

All functions read the shared decoded context; none of them re-open the file.
"""
from __future__ import annotations
import numpy as np
from scipy.signal import welch, resample_poly, lfilter

STEP_VERSION = 'dsp-v1'
EPS = 1e-12


def _db(power):
    return float(10 * np.log10(max(power, EPS)))


def _frames_rms(x, sr, win_s=0.05):
    n = max(1, int(sr * win_s))
    usable = len(x) // n * n
    if not usable:
        return np.array([np.sqrt(np.mean(x ** 2) + EPS)])
    return np.sqrt(np.mean(x[:usable].reshape(-1, n) ** 2, axis=1) + EPS)


def _runs(mask):
    """Start/length of True runs in a boolean array."""
    if not mask.any():
        return np.zeros(0, int), np.zeros(0, int)
    d = np.diff(np.concatenate(([0], mask.astype(np.int8), [0])))
    starts, ends = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
    return starts, ends - starts


def levels(ctx, params=None):
    """M201 peak/true peak, M202 RMS/noise floor, M204 clipping, M205 DC offset."""
    x, sr = ctx['x'], ctx['sample_rate']
    peak = float(np.max(np.abs(x)))
    oversampled = resample_poly(x[: sr * 600], 4, 1, axis=0)  # first 10 min is enough for true peak
    true_peak = float(np.max(np.abs(oversampled)))
    mono = x.mean(axis=1)
    rms = _frames_rms(mono, sr)
    active = rms[rms > 10 ** (-90 / 20)]
    hot = np.abs(x) >= 10 ** (-0.1 / 20)
    clipped = 0
    longest = 0
    for c in range(x.shape[1]):
        _, lengths = _runs(hot[:, c])
        clipped += int(lengths[lengths >= 3].sum())
        longest = max(longest, int(lengths.max()) if len(lengths) else 0)
    return {
        'peak_dbfs': round(_db(peak ** 2), 2), 'true_peak_dbtp': round(_db(true_peak ** 2), 2),
        'rms_dbfs': round(_db(np.mean(mono ** 2)), 2),
        'noise_floor_dbfs': round(_db(np.percentile(active, 5) ** 2), 2) if len(active) else -120.0,
        'clipping_pct': round(100 * clipped / x.size, 4), 'clipping_longest_run': longest,
        'dc_offset': [round(float(v), 5) for v in x.mean(axis=0)],
    }


def _k_weight(x, sr):
    """ITU-R BS.1770 K-weighting: high-shelf pre-filter then RLB high-pass."""
    def shelf(G, Q, fc):
        A, w0 = 10 ** (G / 40), 2 * np.pi * fc / sr
        alpha, cw = np.sin(w0) / (2 * Q), np.cos(w0)
        b = [A * ((A + 1) + (A - 1) * cw + 2 * np.sqrt(A) * alpha), -2 * A * ((A - 1) + (A + 1) * cw),
             A * ((A + 1) + (A - 1) * cw - 2 * np.sqrt(A) * alpha)]
        a = [(A + 1) - (A - 1) * cw + 2 * np.sqrt(A) * alpha, 2 * ((A - 1) - (A + 1) * cw),
             (A + 1) - (A - 1) * cw - 2 * np.sqrt(A) * alpha]
        return np.array(b) / a[0], np.array(a) / a[0]

    def highpass(Q, fc):
        w0 = 2 * np.pi * fc / sr
        alpha, cw = np.sin(w0) / (2 * Q), np.cos(w0)
        b = [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2]
        a = [1 + alpha, -2 * cw, 1 - alpha]
        return np.array(b) / a[0], np.array(a) / a[0]

    b1, a1 = shelf(4.0, 1 / np.sqrt(2), 1500.0)
    b2, a2 = highpass(0.5, 38.0)
    return lfilter(b2, a2, lfilter(b1, a1, x, axis=0), axis=0)


def loudness(ctx, params=None):
    """M203 integrated loudness (LUFS) with BS.1770 gating, and loudness range (simplified)."""
    x, sr = ctx['x'], ctx['sample_rate']
    y = _k_weight(x.astype(np.float64), sr)
    block, hop = int(0.4 * sr), int(0.1 * sr)
    if len(y) < block:
        return {'integrated_lufs': None, 'loudness_range_lu': None}
    starts = range(0, len(y) - block + 1, hop)
    z = np.array([np.mean(y[s:s + block] ** 2, axis=0).sum() for s in starts])
    lk = -0.691 + 10 * np.log10(z + EPS)
    gated = z[lk > -70]
    if not len(gated):
        return {'integrated_lufs': None, 'loudness_range_lu': None}
    rel = -0.691 + 10 * np.log10(gated.mean()) - 10
    final = gated[(-0.691 + 10 * np.log10(gated + EPS)) > rel]
    integrated = -0.691 + 10 * np.log10(final.mean())
    short = lk[lk > -70]
    lra = float(np.percentile(short, 95) - np.percentile(short, 10)) if len(short) > 2 else 0.0
    return {'integrated_lufs': round(float(integrated), 2), 'loudness_range_lu': round(lra, 2)}


def silence(ctx, params=None):
    """M206 share of 50 ms frames below the threshold, plus leading/trailing silence."""
    threshold = (params or {}).get('threshold_dbfs', -50)
    rms = _frames_rms(ctx['x'].mean(axis=1), ctx['sample_rate'])
    quiet = rms < 10 ** (threshold / 20)
    loud = np.flatnonzero(~quiet)
    lead = (loud[0] if len(loud) else len(quiet)) * 0.05
    trail = (len(quiet) - 1 - loud[-1] if len(loud) else len(quiet)) * 0.05
    return {'silence_pct': round(100 * float(quiet.mean()), 2), 'leading_silence_s': round(lead, 2),
            'trailing_silence_s': round(trail, 2)}


STANDARD_NYQUISTS = (4000, 5512.5, 8000, 11025, 12000, 16000, 22050, 24000)


def spectral(ctx, params=None):
    """M207 effective bandwidth and M208 lossy-origin / upsampling evidence."""
    sr = ctx['sample_rate']
    mono = ctx['x'].mean(axis=1)[: sr * 300].astype(np.float64)
    f, p = welch(mono, sr, nperseg=4096)
    pdb = 10 * np.log10(p + 1e-30)
    k = max(1, int(200 / (f[1] - f[0])))
    smooth = np.convolve(np.pad(pdb, k, mode='edge'), np.ones(k) / k, mode='same')[k:-k]
    bits = min(ctx.get('effective_bit_depth') or ctx.get('declared_bit_depth') or 24, 24)
    quant_psd_db = 10 * np.log10((2.0 ** -(bits - 1)) ** 2 / 12 / (sr / 2))
    nyq = sr / 2
    # Cutoff = lowest frequency above which (almost) everything sits at the digital noise floor.
    # A 90th-percentile test tolerates the faint resampler images that a single-bin test trips on.
    cutoff = nyq
    for c in np.arange(0.15 * nyq, 0.97 * nyq, 50.0):
        if np.percentile(smooth[f >= c], 90) < quant_psd_db + 20:
            cutoff = float(c)
            break
    below = smooth[(f >= cutoff - 1000) & (f < cutoff)]
    after = smooth[(f >= cutoff) & (f < cutoff + 1000)]
    cliff = float(np.median(below) - np.median(after)) if cutoff < nyq * 0.97 and len(below) and len(after) else 0.0
    ratio = cutoff / nyq if nyq else 0
    verdict, confidence = 'full_band', 0.0
    if ratio < 0.92:
        # Everything above the cutoff is at the digital floor, so the content was band-limited digitally.
        # The original Nyquist sits at or just below the measured cutoff (resamplers roll off before it).
        near = [n for n in STANDARD_NYQUISTS if n < nyq * 0.97 and n <= cutoff <= n * 1.08][-1:]
        confidence = round(min(1.0, 0.6 + max(cliff, 0) / 50), 2)
        if near and near[0] != 16000:
            verdict = f'upsampled_from_{int(near[0] * 2)}hz'
        elif 15000 <= cutoff <= 21500:
            verdict = 'lossy_origin_suspected'
        elif near:
            verdict = 'lossy_or_upsampled'
        else:
            verdict = 'band_limited'
    return {'effective_bandwidth_hz': round(cutoff), 'bandwidth_ratio': round(ratio, 3),
            'cutoff_cliff_db': round(cliff, 1), 'spectral_verdict': verdict, 'spectral_confidence': confidence}


def bit_depth(ctx, params=None):
    """M209 effective bit depth from the lowest always-zero bits."""
    ints = ctx['ints']
    nz = ints[ints != 0].astype(np.int64)
    if not len(nz):
        return {'effective_bit_depth': 0}
    combined = int(np.bitwise_or.reduce(np.abs(nz[:5_000_000])))
    tz = (combined & -combined).bit_length() - 1
    effective = 32 - tz
    declared = ctx.get('declared_bit_depth')
    return {'effective_bit_depth': int(effective),
            'bit_depth_padded': bool(declared and declared not in (32,) and effective < declared and ctx.get('lossless'))}


def hum(ctx, params=None):
    """M211 mains hum: peak excess at 50/60 Hz and harmonics, at 1 Hz resolution."""
    sr = ctx['sample_rate']
    mono = ctx['x'].mean(axis=1)[: sr * 120].astype(np.float64)
    if len(mono) < sr:
        return {'hum_hz': None, 'hum_excess_db': 0.0}
    f, p = welch(mono, sr, nperseg=min(len(mono), 4 * sr))
    pdb = 10 * np.log10(p + 1e-30)
    best = (None, 0.0)
    step = f[1] - f[0]
    for base in (50, 60):
        excess = []
        for h in range(1, 5):
            c = int(round(base * h / step))
            w = int(round(3 / step))
            neighbours = np.r_[pdb[c - 4 * w:c - w], pdb[c + w + 1:c + 4 * w + 1]]
            excess.append(pdb[c - 1:c + 2].max() - np.median(neighbours))
        score = float(np.mean(sorted(excess)[-3:]))
        if score > best[1]:
            best = (base, score)
    return {'hum_hz': best[0] if best[1] > 6 else None, 'hum_excess_db': round(best[1], 1)}


def dropouts(ctx, params=None):
    """M210 digital drop-outs (exact-zero gaps inside active audio) and stuck samples, per hour."""
    x, sr = ctx['x'], ctx['sample_rate']
    mono = x.mean(axis=1)
    rms = _frames_rms(mono, sr)
    gaps = 0
    starts, lengths = _runs(mono == 0)
    edge = int(0.05 * sr)
    for s, n in zip(starts, lengths):
        if n < int(0.005 * sr) or s == 0 or s + n >= len(mono):
            continue
        before = mono[max(0, s - edge):s]
        after = mono[s + n:s + n + edge]
        if np.sqrt(np.mean(before ** 2)) > 0.003 and np.sqrt(np.mean(after ** 2)) > 0.003:
            gaps += 1
    same = np.r_[False, np.diff(mono) == 0] & (mono != 0)
    _, runs = _runs(same)
    stuck = int((runs >= 10).sum())
    hours = max(len(mono) / sr / 3600, 1e-9)
    return {'dropout_count': gaps, 'stuck_runs': stuck, 'dropouts_per_hour': round((gaps + stuck) / hours, 1)}


def stereo(ctx, params=None):
    """M212 channel correlation, imbalance, fake stereo, phase inversion, dead channel."""
    x = ctx['x']
    if x.shape[1] != 2:
        return {'stereo_verdict': 'mono' if x.shape[1] == 1 else 'multichannel'}
    l, r = x[:, 0].astype(np.float64), x[:, 1].astype(np.float64)
    pl, pr = np.mean(l ** 2), np.mean(r ** 2)
    corr = float(np.corrcoef(l, r)[0, 1]) if pl > EPS and pr > EPS else 0.0
    imbalance = _db(pl) - _db(pr)
    if min(pl, pr) < 10 ** (-90 / 10) and max(pl, pr) > 10 ** (-60 / 10):
        verdict = 'dead_channel'
    elif corr > 0.999 and abs(imbalance) < 0.1:
        verdict = 'dual_mono'
    elif corr < -0.9:
        verdict = 'phase_inverted'
    elif corr < 0.3:
        verdict = 'independent_channels'
    else:
        verdict = 'stereo'
    return {'channel_correlation': round(corr, 4), 'channel_imbalance_db': round(imbalance, 2), 'stereo_verdict': verdict}
