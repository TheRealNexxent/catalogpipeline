"""Profile scoring from Baseline.md section 6: quality Q, evidence coverage C, tier, caps and penalties.

Each metric: (name, measurement key, floor, ideal, weight, hard). For lower-is-better metrics the floor
is the maximum allowed value (floor > ideal). A missing measurement lowers coverage, never quality.

`quality` uses Audiobox Aesthetics production quality (1-10). Baseline.md wrote quality floors on a
1-5 MOS scale; they are doubled here as a PROVISIONAL mapping until calibration on rated data.
"""
from __future__ import annotations

TIERS = [('Gold', 80, 90), ('Silver', 60, 70), ('Bronze', 40, 50)]
STRICT_PII_DOMAINS = {'pharma', 'medical', 'legal', 'finance', 'children'}
DECLARED_TOLERANCE = {'snr_db': ('snr_wada_db', 3.0), 'sample_rate': ('sample_rate', 0), 'speakers': ('speakers', 0)}

M = lambda name, key, floor, ideal, weight, hard=True: (name, key, floor, ideal, weight, hard)
PROFILES = {
    'asr': {'version': 1, 'metrics': [
        M('sample_rate_khz', 'sample_rate_khz', 16, 16, 10), M('speech_snr_db', 'snr_wada_db', 5, 20, 20),
        M('quality', 'aes_production_quality', 5.0, 6.6, 20), M('clipping_pct', 'clipping_pct', 1.0, 0.1, 10),
        M('speech_ratio_pct', 'speech_ratio_pct', 30, 70, 10), M('bandwidth_ratio', 'bandwidth_ratio', 0.5, 0.8, 5),
        M('language_confidence', 'language_confidence', 0.70, 0.95, 15), M('dropouts_per_hour', 'dropouts_per_hour', 10, 0, 10)],
        'ai_default': 'keep_with_label'},
    'tts': {'version': 1, 'metrics': [
        M('sample_rate_khz', 'sample_rate_khz', 44.1, 48, 10), M('speech_snr_db', 'snr_wada_db', 30, 40, 20),
        M('quality', 'aes_production_quality', 7.0, 8.0, 25), M('clipping_pct', 'clipping_pct', 0.01, 0, 10),
        M('speech_ratio_pct', 'speech_ratio_pct', 60, 85, 5), M('bandwidth_ratio', 'bandwidth_ratio', 0.9, 0.95, 10),
        M('reverb_c50_db', 'c50_db', 15, 25, 10), M('language_confidence', 'language_confidence', 0.90, 0.98, 5),
        M('dropouts_per_hour', 'dropouts_per_hour', 1, 0, 5)],
        'filters': [('speakers_hint', '==', 1)], 'ai_default': 'exclude'},
    'full_duplex': {'version': 1, 'metrics': [
        M('sample_rate_khz', 'sample_rate_khz', 16, 24, 10), M('speech_snr_db', 'snr_wada_db', 10, 25, 15),
        M('quality', 'aes_production_quality', 5.6, 7.0, 15), M('clipping_pct', 'clipping_pct', 0.5, 0.05, 10),
        M('speech_ratio_pct', 'speech_ratio_pct', 40, 80, 10), M('crosstalk_db', 'crosstalk_worst_db', -10, -30, 15),
        M('speaker_balance', 'speaker_balance', 0.2, 0.5, 5), M('dropouts_per_hour', 'dropouts_per_hour', 5, 0, 5),
        M('language_confidence', 'language_confidence', 0.70, 0.95, 5), M('reverb_c50_db', 'c50_db', 5, 15, 5),
        M('bandwidth_ratio', 'bandwidth_ratio', 0.7, 0.9, 5)],
        'filters': [('stereo_verdict', '==', 'independent_channels')], 'ai_default': 'keep_with_label'},
    'speaker_id': {'version': 1, 'metrics': [
        M('sample_rate_khz', 'sample_rate_khz', 16, 16, 5), M('speech_snr_db', 'snr_wada_db', 10, 25, 20),
        M('quality', 'aes_production_quality', 5.6, 7.0, 15), M('clipping_pct', 'clipping_pct', 0.5, 0.05, 10),
        M('speech_ratio_pct', 'speech_ratio_pct', 40, 80, 10), M('bandwidth_ratio', 'bandwidth_ratio', 0.6, 0.9, 5),
        M('reverb_c50_db', 'c50_db', 5, 15, 5), M('dropouts_per_hour', 'dropouts_per_hour', 5, 0, 5),
        M('speech_per_speaker_s', 'speech_s', 30, 300, 15), M('speaker_consistency', 'speaker_consistency', 0.6, 0.85, 10, False)],
        'ai_default': 'exclude'},
    'emotion': {'version': 1, 'metrics': [
        M('sample_rate_khz', 'sample_rate_khz', 16, 16, 5), M('speech_snr_db', 'snr_wada_db', 10, 25, 15),
        M('quality', 'aes_production_quality', 5.6, 7.0, 15), M('clipping_pct', 'clipping_pct', 0.5, 0.05, 10),
        M('speech_ratio_pct', 'speech_ratio_pct', 40, 80, 10), M('bandwidth_ratio', 'bandwidth_ratio', 0.6, 0.9, 5),
        M('language_confidence', 'language_confidence', 0.70, 0.95, 5), M('dropouts_per_hour', 'dropouts_per_hour', 5, 0, 5),
        M('emotion_confidence', 'emotion_score', 0.5, 0.8, 20, False)], 'ai_default': 'keep_with_label'},
    'wake_word': {'version': 1, 'metrics': [
        M('sample_rate_khz', 'sample_rate_khz', 16, 16, 10), M('speech_snr_db', 'snr_wada_db', 5, 20, 15),
        M('quality', 'aes_production_quality', 5.0, 6.6, 15), M('clipping_pct', 'clipping_pct', 1.0, 0.1, 10),
        M('speech_ratio_pct', 'speech_ratio_pct', 10, 50, 10), M('bandwidth_ratio', 'bandwidth_ratio', 0.5, 0.8, 5),
        M('language_confidence', 'language_confidence', 0.70, 0.95, 5), M('dropouts_per_hour', 'dropouts_per_hour', 10, 0, 5)],
        'ai_default': 'keep_with_label'},
    'audio_llm': {'version': 1, 'metrics': [
        M('sample_rate_khz', 'sample_rate_khz', 16, 44.1, 10), M('speech_snr_db', 'snr_wada_db', 0, 15, 10, False),
        M('quality', 'aes_production_quality', 4.0, 6.0, 10, False), M('clipping_pct', 'clipping_pct', 2.0, 0.1, 10),
        M('bandwidth_ratio', 'bandwidth_ratio', 0.5, 0.9, 10), M('dropouts_per_hour', 'dropouts_per_hour', 20, 0, 10),
        M('content_confidence', 'content_confidence', 0.5, 0.8, 15), M('silence_pct', 'silence_pct', 80, 30, 10)],
        'ai_default': 'keep_with_label'},
    'music_gen': {'version': 1, 'metrics': [
        M('sample_rate_khz', 'sample_rate_khz', 44.1, 48, 15), M('clipping_pct', 'clipping_pct', 0.1, 0, 15),
        M('bandwidth_ratio', 'bandwidth_ratio', 0.9, 0.97, 15), M('lossless_origin', 'lossless_origin', 1, 1, 15),
        M('bit_depth', 'effective_bit_depth', 16, 24, 10), M('dropouts_per_hour', 'dropouts_per_hour', 1, 0, 10),
        M('quality', 'aes_production_quality', 5.0, 7.5, 10), M('silence_pct', 'silence_pct', 20, 5, 10)],
        'filters': [('content_class', '==', 'music')], 'ai_default': 'keep_with_label'},
    'sound_events': {'version': 1, 'metrics': [
        M('sample_rate_khz', 'sample_rate_khz', 16, 44.1, 10), M('clipping_pct', 'clipping_pct', 1.0, 0.1, 10),
        M('bandwidth_ratio', 'bandwidth_ratio', 0.6, 0.9, 10), M('dropouts_per_hour', 'dropouts_per_hour', 10, 0, 10),
        M('content_confidence', 'content_confidence', 0.5, 0.85, 30), M('silence_pct', 'silence_pct', 80, 30, 10),
        M('quality', 'aes_production_quality', 4.0, 6.0, 20, False)],
        'filters': [('content_class', 'in', ['noise_or_ambient', 'mixed'])], 'ai_default': 'keep_with_label'},
    'speech_enhancement_clean': {'version': 1, 'metrics': [
        M('sample_rate_khz', 'sample_rate_khz', 16, 48, 10), M('speech_snr_db', 'snr_wada_db', 35, 45, 25),
        M('quality', 'aes_production_quality', 7.2, 8.2, 20), M('clipping_pct', 'clipping_pct', 0.01, 0, 10),
        M('bandwidth_ratio', 'bandwidth_ratio', 0.9, 0.95, 10), M('lossless_origin', 'lossless_origin', 1, 1, 10),
        M('dropouts_per_hour', 'dropouts_per_hour', 1, 0, 5), M('silence_pct', 'silence_pct', 50, 20, 10)],
        'ai_default': 'keep_with_label'},
}
OPS = {'==': lambda a, b: a == b, 'in': lambda a, b: a in b}


def flatten(measurements):
    """One flat fact dict from a record's per-step measurements, plus derived facts the profiles use."""
    f = {k: v for d in measurements.values() for k, v in (d or {}).items()}
    if f.get('sample_rate'):
        f['sample_rate_khz'] = f['sample_rate'] / 1000
    if f.get('spectral_verdict') is not None:
        f['lossless_origin'] = 1 if f.get('lossless') and f['spectral_verdict'] == 'full_band' else 0
    return f


def _metric_score(value, floor, ideal):
    if floor == ideal:
        return (1.0 if value >= ideal else None)
    s = (value - floor) / (ideal - floor)
    return None if s < 0 else min(1.0, s)


OVERLAYS = {  # Baseline.md section 8.1: recording-setup adjustments, applied automatically from facts
    'telephony': {'when': lambda f: (f.get('sample_rate') or 99999) <= 8000,
                  'set': {'sample_rate_khz': (8, 8)}, 'drop': {'bandwidth_ratio'}, 'shift': {'quality': -0.6}},
    'far_field': {'when': lambda f: (f.get('c50_db') or 99) < 5, 'shift': {'speech_snr_db': -5, 'quality': -0.6}, 'drop': {'reverb_c50_db'}},
}


def _apply_overlays(metrics, facts):
    applied = []
    for name, o in OVERLAYS.items():
        if not o['when'](facts):
            continue
        applied.append(name)
        out = []
        for n, key, floor, ideal, w, hard in metrics:
            if n in o.get('drop', ()):
                continue
            if n in o.get('set', {}):
                floor, ideal = o['set'][n]
            if n in o.get('shift', {}):
                floor += o['shift'][n]
            out.append((n, key, floor, ideal, w, hard))
        metrics = out
    return metrics, applied


def score(facts, profile_name, declared=None, domain=None, bundle_complete=True):
    p = PROFILES[profile_name]
    metrics, overlays = _apply_overlays(p['metrics'], facts)
    total_w = sum(m[4] for m in metrics)
    q_sum = cov = 0.0
    failed, breakdown = [], []
    for name, key, floor, ideal, w, hard in metrics:
        v = facts.get(key)
        if v is None:
            breakdown.append((name, None, None))
            continue
        cov += w
        s = _metric_score(float(v), floor, ideal)
        if s is None:
            if hard:
                failed.append(f'{name}={v} below floor {floor}')
            s = 0.0
        q_sum += w * s
        breakdown.append((name, v, round(s, 2)))
    for key, op, val in p.get('filters', []):
        if not OPS[op](facts.get(key), val):
            failed.append(f'filter {key} {op} {val} (got {facts.get(key)})')
    q = 100 * q_sum / cov if cov else 0.0
    penalties = []
    for dkey, (mkey, tol) in DECLARED_TOLERANCE.items():
        if declared and dkey in declared and facts.get(mkey) is not None and abs(float(declared[dkey]) - float(facts[mkey])) > tol:
            penalties.append(f'declared {dkey}={declared[dkey]} vs measured {facts[mkey]}')
    q = max(0.0, q - min(20, 5 * len(penalties)))
    c = 100 * cov / total_w
    tier = 'Review'
    for name, qmin, cmin in TIERS:
        if q >= qmin and c >= cmin:
            tier = name
            break
    caps = []
    if not bundle_complete and tier == 'Gold':
        tier, caps = 'Silver', caps + ['incomplete bundle']
    pii_open = bool(facts.get('pii_count')) and not facts.get('pii_verified')
    if pii_open:
        caps.append('unresolved PII')
        tier = 'Reject' if domain in STRICT_PII_DOMAINS else ('Review' if tier != 'Reject' else tier)
    if failed:
        tier = 'Reject'
    return {'profile': profile_name, 'profile_version': p['version'], 'quality': round(q, 1), 'coverage': round(c, 1),
            'tier': tier, 'failed': failed, 'penalties': penalties, 'caps': caps, 'overlays': overlays, 'breakdown': breakdown}
