"""Source of truth for the preset pipelines. `python presets_catalog.py` writes presets/*.json.

Each preset is self-contained (it lists every step it needs, including the shared triage
steps), so any single JSON file can be imported into another tool on its own. The top-level
shape follows the Refinery preset convention: name, version, profile, steps, plus
preserve_originals / privacy_required / automatic.

Conditions (`trigger`, step `when`) are AND-lists of [fact, op, value]; ops: == != < <= > >= in.
"""
from __future__ import annotations
import json
from pathlib import Path

TRIAGE = ['decode.probe', 'decode.full', 'gates.basic', 'cache.lookup',
          'dsp.levels', 'dsp.loudness', 'dsp.silence', 'dsp.bit_depth', 'dsp.spectral',
          'dsp.hum', 'dsp.dropouts', 'dsp.stereo', 'snr.wada', 'fingerprint.compute', 'classify.content.gpu',
          {'id': 'speaker.embed', 'when': [['content_class', '==', 'speech']]}]
SPEECH_CORE = ['vad', 'snr_c50', 'quality.general', {'id': 'mos.speech', 'when': [['profile_tts', '==', True]]},
               'lid', 'asr', 'align.words', 'pii.detect', 'pii.redact', 'ai_detect']
ENRICH = [{'id': 'emotion', 'when': [['enrich', '==', True]]}, {'id': 'text.enrich', 'when': [['enrich', '==', True]]},
          {'id': 'demographics', 'when': [['enrich', '==', True]]}]


def step(sid, when=None, **params):
    if isinstance(sid, dict):
        return {**sid, **({'params': params} if params else {})}
    s = {'id': sid}
    if when:
        s['when'] = when
    if params:
        s['params'] = params
    return s


def route(rid, name, description, trigger, steps, skips, priority, profile='Balanced'):
    return {'name': name, 'version': 1, 'kind': 'route', 'route_id': rid, 'priority': priority,
            'description': description, 'profile': profile, 'trigger': trigger,
            'steps': [step(s) if not isinstance(s, dict) else s for s in steps], 'skips': skips,
            'preserve_originals': True, 'privacy_required': True, 'automatic': True}


ROUTES = [
    route('R00', 'Audio · Gate failure', 'File failed a hard gate (empty, unreadable, truncated, silent, too short). Nothing else runs.',
          [['gates_failed', '!=', []]], ['decode.probe', 'decode.full', 'gates.basic'], ['all analysis'], 0),
    route('R01', 'Audio · Already processed', 'Decoded audio identical to a file already processed; results are copied.',
          [['cache_hit', '==', True]], ['decode.probe', 'decode.full', 'gates.basic', 'cache.lookup'], ['all analysis'], 1),
    route('R02', 'Audio · Silent or near-empty', 'Almost no content; signal checks only.',
          [['silence_pct', '>=', 95]], TRIAGE, ['all GPU models'], 2),
    route('R13', 'Audio · Declared synthetic', 'Partner declares TTS/synthetic speech; AI-detect still runs, default decision keep-with-label.',
          [['declared_synthetic', '==', True]], TRIAGE + SPEECH_CORE + ENRICH, ['diarize', 'separate.vocals'], 3),
    route('R07', 'Audio · Bundle with stems or speaker tracks', 'Uses the supplied vocals stem and speaker tracks instead of separation and diarization.',
          [['bundle_role', 'in', ['source', 'vocals', 'accompaniment', 'speaker']]],
          TRIAGE + [step('bundle.verify_tracks', [['bundle_role', '==', 'speaker']]),
                    step('vad', [['bundle_role', 'in', ['source', 'vocals', 'speaker']]]),
                    step('quality.general', [['bundle_role', 'in', ['source', 'vocals', 'speaker']]]),
                    step('lid', [['bundle_role', '==', 'vocals']]),
                    step('asr', [['bundle_role', '==', 'speaker']]),
                    step('pii.detect', [['bundle_role', '==', 'speaker']]),
                    step('pii.redact', [['bundle_role', '==', 'speaker']]),
                    step('ai_detect', [['bundle_role', '==', 'speaker']]),
                    step('music.analysis', [['bundle_role', '==', 'accompaniment']])],
          ['separate.vocals', 'diarize'], 4),
    route('R04', 'Audio · Telephony speech', 'Narrowband (8 kHz) or telephone codec. Telephony-suited quality model; bandwidth check off.',
          [['sample_rate', '<=', 8000]],
          TRIAGE + [step(s, **({'model_hint': 'telephony'} if s in ('quality.general', 'asr') else {})) for s in SPEECH_CORE] + ENRICH,
          ['dsp.spectral verdicts', 'diarize unless >1 speaker'], 5),
    route('R05', 'Audio · Duplex conversation', 'Two independent channels, one speaker each. Channels analysed separately; no diarization.',
          [['channels', '==', 2], ['stereo_verdict', '==', 'independent_channels']],
          TRIAGE + ['duplex.stats', 'duplex.crosstalk'] + SPEECH_CORE + ENRICH,
          ['diarize', 'separate.vocals'], 6),
    route('R11', 'Audio · Long-form recording', 'Over one hour. Chunked streaming; heavy models within a per-run budget.',
          [['decoded_duration_s', '>', 3600]],
          TRIAGE + SPEECH_CORE + ['diarize'] + ENRICH,
          ['full-length heavy models unless strict-PII modifier'], 7),
    route('R06', 'Audio · Multi-speaker speech', 'Several speakers in one channel. Separation only if speech SNR is low with music or crowd.',
          [['content_class', '==', 'speech'], ['speakers_hint', '>', 1]],
          TRIAGE + SPEECH_CORE + ['diarize', step('separate.vocals', [['snr_wada_db', '<', 10]])] + ENRICH,
          ['separation on clean speech'], 8),
    route('R03', 'Audio · Clean single speaker', 'Mostly speech, one channel or fake stereo. The standard speech chain.',
          [['content_class', '==', 'speech']], TRIAGE + SPEECH_CORE + ENRICH, ['diarize', 'separate.vocals'], 9),
    route('R08', 'Audio · Music', 'Mostly music. Music quality, tags, tempo/key; ASR on vocals only if a profile needs lyrics.',
          [['content_class', '==', 'music']],
          TRIAGE + ['quality.general', 'music.analysis', 'events.tagging', step('separate.vocals', [['p_speech_max', '>=', 0.5]])],
          ['speech models'], 10),
    route('R09', 'Audio · Environmental / SFX / animals / machines', 'Non-speech events. Event tagging; bioacoustic model only if animals are detected.',
          [['content_class', '==', 'noise_or_ambient']],
          TRIAGE + ['events.tagging', 'quality.general', 'bioacoustic'],
          ['speech models', 'music models'], 11),
    route('R10', 'Audio · Mixed or uncertain', 'No dominant class on sampled windows. Whole-file segment classification, then each segment is re-routed.',
          [['content_class', 'in', ['mixed', None]]],
          TRIAGE + ['classify.content.gpu', 'vad', 'events.tagging'], ['nothing heavy until segments are routed'], 12),
    route('R12', 'Audio · Long-tail language', 'Language without a specialised ASR model. Broad multilingual ASR; PII coverage flagged as limited.',
          [['lid_has_specialised_asr', '==', False]],
          TRIAGE + SPEECH_CORE + ENRICH,
          ['specialised ASR'], 13),
]

MODIFIERS = [
    {'name': 'Modifier · Strict PII domain', 'kind': 'modifier', 'version': 1,
     'description': 'Pharma/medical, legal, finance, children. Forces full-coverage ASR, PII and verification; unresolved PII rejects.',
     'trigger': [['domain', 'in', ['pharma', 'medical', 'legal', 'finance', 'children']]],
     'add_steps': ['asr', 'align.words', 'pii.detect', 'pii.medical', 'pii.redact'],
     'policy': {'unresolved_pii': 'reject'}},
    {'name': 'Modifier · Children\'s speech', 'kind': 'modifier', 'version': 1,
     'description': 'Adds the age model and strict PII.', 'trigger': [['domain', '==', 'children']],
     'add_steps': ['demographics', 'pii.detect'], 'policy': {'consent_flag_required': True}},
    {'name': 'Modifier · Declared language', 'kind': 'modifier', 'version': 1,
     'description': 'Partner declared the language: LID only confirms it on one sample instead of several windows.',
     'trigger': [['declared_language', '!=', None]], 'force_params': {'lid': {'windows': 1}}},
    {'name': 'Modifier · Supplied transcript', 'kind': 'modifier', 'version': 1,
     'description': 'Transcript provided: align it and spot-check word error rate instead of running full ASR (unless strict PII).',
     'trigger': [['has_transcript', '==', True]], 'replace_steps': {'asr': 'align.words'}},
]


def write(out=Path(__file__).parent / 'presets'):
    out.mkdir(exist_ok=True)
    for p in ROUTES:
        slug = p['name'].split('·')[1].strip().lower().replace(' / ', '_').replace(' ', '_').replace("'", '')
        (out / f"{p['route_id']}_{slug}.json").write_text(json.dumps(p, indent=2), encoding='utf-8')
    for i, m in enumerate(MODIFIERS, 1):
        slug = m['name'].split('·')[1].strip().lower().replace(' ', '_').replace("'", '')
        (out / f'M{i:02d}_{slug}.json').write_text(json.dumps(m, indent=2), encoding='utf-8')
    return out


if __name__ == '__main__':
    print('wrote', write())
