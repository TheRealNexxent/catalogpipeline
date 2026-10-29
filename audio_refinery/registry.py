"""Step registry: every step a preset can name, implemented or still waiting on the bake-off.

A preset that names a pending step still runs; the step is recorded as skipped, which
lowers evidence coverage instead of producing a fake value (Baseline.md P2, section 6.3).
"""
from __future__ import annotations
from steps import decode, gates, dsp, snr, fingerprint, content

try:  # GPU waves need torch; CPU-only installs still run every CPU step
    from steps import gpu, speech, enrich
except ImportError:
    gpu = speech = enrich = None


def _cache_lookup(ctx, params=None):
    index = ctx.get('seen_index')
    key = ctx.get('pcm_sha256')
    hit = index.get(key) if index is not None and key else None
    ctx['stop'] = ctx.get('stop') or bool(hit and (params or {}).get('stop_on_hit', True))
    return {'cache_hit': bool(hit), 'cache_source': hit['file'] if hit else None}


# id -> (function, device, version)
IMPLEMENTED = {
    'decode.probe': (decode.probe, 'cpu', decode.STEP_VERSION),
    'decode.full': (decode.full_decode, 'cpu', decode.STEP_VERSION),
    'gates.basic': (gates.basic, 'cpu', gates.STEP_VERSION),
    'cache.lookup': (_cache_lookup, 'cpu', 'cache-v1'),
    'dsp.levels': (dsp.levels, 'cpu', dsp.STEP_VERSION),
    'dsp.loudness': (dsp.loudness, 'cpu', dsp.STEP_VERSION),
    'dsp.silence': (dsp.silence, 'cpu', dsp.STEP_VERSION),
    'dsp.spectral': (dsp.spectral, 'cpu', dsp.STEP_VERSION),
    'dsp.bit_depth': (dsp.bit_depth, 'cpu', dsp.STEP_VERSION),
    'dsp.hum': (dsp.hum, 'cpu', dsp.STEP_VERSION),
    'dsp.dropouts': (dsp.dropouts, 'cpu', dsp.STEP_VERSION),
    'dsp.stereo': (dsp.stereo, 'cpu', dsp.STEP_VERSION),
    'snr.wada': (snr.wada, 'cpu', snr.STEP_VERSION),
    'snr.energy': (snr.energy, 'cpu', snr.STEP_VERSION),
    'fingerprint.compute': (fingerprint.compute, 'cpu', fingerprint.STEP_VERSION),
    'classify.content.dsp': (content.classify_dsp, 'cpu', content.STEP_VERSION),
    'duplex.stats': (content.duplex_stats, 'cpu', content.STEP_VERSION),
    'duplex.crosstalk': (content.duplex_crosstalk, 'cpu', content.STEP_VERSION),
    'bundle.verify_tracks': (content.verify_track, 'cpu', content.STEP_VERSION),
}
if gpu:
    IMPLEMENTED.update({
        'vad': (gpu.vad, 'gpu', gpu.STEP_VERSION + '/silero'),
        'classify.content.gpu': (gpu.classify_content_gpu, 'gpu', gpu.STEP_VERSION + '/efficientat-mn10'),
        'events.tagging': (gpu.events_tagging, 'gpu', gpu.STEP_VERSION + '/efficientat-mn10'),
        'mos.speech': (gpu.mos_speech, 'gpu', gpu.STEP_VERSION + '/utmosv2'),
        'lid': (gpu.lid, 'gpu', gpu.STEP_VERSION + '/voxlingua107'),
        'ai_detect': (gpu.ai_detect, 'gpu', gpu.STEP_VERSION + '/aasist'),
        'asr': (speech.asr, 'gpu', speech.STEP_VERSION + '/whisper-large-v3-turbo'),
        'align.words': (speech.align_words, 'gpu', speech.STEP_VERSION + '/whisper-words'),
        'pii.detect': (speech.pii_detect, 'gpu', speech.STEP_VERSION + '/presidio+gliner-pii'),
        'pii.medical': (speech.pii_detect, 'gpu', speech.STEP_VERSION + '/presidio+gliner-pii'),
        'pii.redact': (speech.pii_redact, 'gpu', speech.STEP_VERSION + '/mute+asr-verify'),
        'speaker.embed': (speech.speaker_embed, 'gpu', speech.STEP_VERSION + '/ecapa'),
        'diarize': (speech.diarize, 'gpu', speech.STEP_VERSION + '/ecapa-agglomerative'),
        'separate.vocals': (speech.separate_vocals, 'gpu', speech.STEP_VERSION + '/htdemucs'),
        'quality.general': (speech.quality_general, 'gpu', speech.STEP_VERSION + '/audiobox-aesthetics'),
        'music.analysis': (enrich.music_analysis, 'gpu', enrich.STEP_VERSION + '/librosa+clap'),
        'emotion': (enrich.emotion, 'gpu', enrich.STEP_VERSION + '/clap-zero-shot'),
        'bioacoustic': (enrich.bioacoustic, 'gpu', enrich.STEP_VERSION + '/efficientat-animals'),
        'text.enrich': (enrich.text_enrich, 'gpu', enrich.STEP_VERSION + '/qwen2.5-1.5b'),
    })

# id -> candidate models to benchmark (primary first). Commercial-licence audit decides the final list.
PENDING = {
    'snr_c50': ['Brouhaha (needs a Python <=3.12 environment; runs on the DGX)'],
    'demographics': ['own head on ECAPA/WavLM embeddings; blocked until commercially licensed age/gender/accent labels are available'],
}


def describe(step_id):
    if step_id in IMPLEMENTED:
        return {'id': step_id, 'status': 'implemented', 'device': IMPLEMENTED[step_id][1], 'version': IMPLEMENTED[step_id][2]}
    if step_id in PENDING:
        return {'id': step_id, 'status': 'pending_benchmark', 'device': 'gpu', 'candidates': PENDING[step_id]}
    raise KeyError(f'Unknown step: {step_id}')
