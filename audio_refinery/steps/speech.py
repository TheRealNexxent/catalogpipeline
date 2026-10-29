"""Wave 2 model steps: speech depth.

    asr               Whisper large-v3-turbo (MIT) with word timestamps
    align.words       word timeline from the ASR pass (no extra model)
    pii.detect        Presidio + regex recognisers (MIT) UNION GLiNER-PII (Apache-2.0); recall over precision
    pii.redact        muted derivative of the original + ASR re-check of every muted span
    speaker.embed     SpeechBrain ECAPA (Apache-2.0) on sampled windows -> speaker-count hint for the router
    diarize           ECAPA embeddings on speech windows + agglomerative clustering
    separate.vocals   Demucs htdemucs (MIT; MUSDB training-data flag) -> vocals derivative
    quality.general   Meta Audiobox Aesthetics (CC-BY-4.0): production quality, complexity, enjoyment, usefulness

Originals are never modified; every derivative is written under audio_refinery/derivatives/.
"""
from __future__ import annotations
import re
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly
from scipy.cluster.hierarchy import fcluster, linkage

from steps.gpu import CACHE, DEVICE, ROOT, _load, _speech_or_all, _windows, torch

STEP_VERSION = 'gpu-wave2-v1'
DERIVATIVES = ROOT / 'derivatives'
GLINER_LABELS = {'person': 'PERSON', 'phone number': 'PHONE_NUMBER', 'email': 'EMAIL_ADDRESS', 'address': 'LOCATION',
                 'date of birth': 'DATE_TIME', 'credit card number': 'CREDIT_CARD', 'medication': 'MEDICAL',
                 'medical condition': 'MEDICAL', 'social security number': 'US_SSN', 'bank account number': 'BANK_ACCOUNT'}
MUTE_AT = 0.85  # Baseline.md section 9: >= 0.85 -> mute; 0.50-0.85 -> human review; below -> ignored
# Generic DATE_TIME is left out on purpose: 'next spring' is not personal data. Dates of birth come from GLiNER.
PRESIDIO_KEEP = {'PERSON', 'PHONE_NUMBER', 'EMAIL_ADDRESS', 'LOCATION', 'CREDIT_CARD', 'US_SSN',
                 'IBAN_CODE', 'IP_ADDRESS', 'US_BANK_NUMBER', 'MEDICAL_LICENSE', 'NRP'}


# ---------- ASR ----------
def _whisper():
    from transformers import pipeline
    return pipeline('automatic-speech-recognition', model='openai/whisper-large-v3-turbo',
                    dtype=torch.float16 if DEVICE == 'cuda' else torch.float32, device=0 if DEVICE == 'cuda' else -1)


def _transcribe(audio16, language=None):
    pipe = _load('whisper_turbo', _whisper)
    kwargs = {'task': 'transcribe'}
    if language and language != 'und':
        kwargs['language'] = language
    out = pipe({'raw': np.ascontiguousarray(audio16, dtype=np.float32), 'sampling_rate': 16000},
               return_timestamps='word', chunk_length_s=30, batch_size=8, generate_kwargs=kwargs)
    words = [(c['text'].strip(), c['timestamp'][0], c['timestamp'][1]) for c in out.get('chunks', []) if c['text'].strip()]
    return out['text'].strip(), [(w, float(a or 0.0), float(b if b is not None else (a or 0.0))) for w, a, b in words]


def asr(ctx, params=None):
    lang = (params or {}).get('language') or (ctx.get('declared_language') or '')[:2] or ctx.get('language')
    text, words = _transcribe(ctx['x16'], lang)
    ctx['words'] = words
    ctx['transcript'] = text
    return {'transcript': text, 'word_count': len(words), 'asr_model': 'whisper-large-v3-turbo',
            'asr_language': lang or 'auto', 'asr_coverage_s': round(len(ctx['x16']) / 16000, 1)}


def align_words(ctx, params=None):
    words = ctx.get('words') or []
    if not words:
        return {'aligned_words': 0}
    spoken = sum(b - a for _, a, b in words)
    return {'aligned_words': len(words), 'aligned_speech_s': round(spoken, 2), 'align_method': 'whisper-word-timestamps'}


# ---------- PII ----------
def _presidio():
    from presidio_analyzer import AnalyzerEngine
    from presidio_analyzer.nlp_engine import NlpEngineProvider
    nlp = NlpEngineProvider(nlp_configuration={'nlp_engine_name': 'spacy',
                                               'models': [{'lang_code': 'en', 'model_name': 'en_core_web_sm'}]}).create_engine()
    return AnalyzerEngine(nlp_engine=nlp, supported_languages=['en'])


def _gliner():
    from gliner import GLiNER
    return GLiNER.from_pretrained('urchade/gliner_multi_pii-v1', cache_dir=str(CACHE / 'hf')).to(DEVICE)


def _spoken_to_written(text):
    """ASR often writes spoken digits and 'dot'/'at' as words; normalise so the recognisers can see them."""
    digits = {'zero': '0', 'oh': '0', 'one': '1', 'two': '2', 'three': '3', 'four': '4', 'five': '5', 'six': '6',
              'seven': '7', 'eight': '8', 'nine': '9'}
    t = re.sub(r'\b(' + '|'.join(digits) + r')\b', lambda m: digits[m.group(1).lower()], text, flags=re.I)
    t = re.sub(r'(?<=\d)[\s,.-]+(?=\d)', '', t)
    t = re.sub(r'\s+dot\s+', '.', t, flags=re.I)
    return re.sub(r'\s+at\s+(?=[\w-]+\.(com|org|net|io|co))', '@', t, flags=re.I)


def _word_spans(words):
    """Character span of each ASR word inside ' '.join(words)."""
    spans, pos = [], 0
    for w, a, b in words:
        spans.append((pos, pos + len(w), a, b))
        pos += len(w) + 1
    return spans


def pii_detect(ctx, params=None):
    words = ctx.get('words') or []
    text = ' '.join(w for w, _, _ in words)
    if not text:
        ctx['pii'] = []
        return {'pii_count': 0, 'pii_types': [], 'pii_sources': {}}
    found = []
    for r in _load('presidio', _presidio).analyze(text=text, language='en'):
        if r.entity_type in PRESIDIO_KEEP and r.score >= 0.5:
            found.append({'type': r.entity_type, 'start': r.start, 'end': r.end, 'score': round(r.score, 2), 'source': 'presidio'})
    for e in _load('gliner_pii', _gliner).predict_entities(text, list(GLINER_LABELS), threshold=0.5):
        found.append({'type': GLINER_LABELS[e['label']], 'start': e['start'], 'end': e['end'],
                      'score': round(float(e['score']), 2), 'source': 'gliner'})
    # Spoken numbers and e-mails: run Presidio again on a normalised copy and map hits back by word overlap.
    norm = _spoken_to_written(text)
    if norm != text:
        for r in _load('presidio', _presidio).analyze(text=norm, language='en', entities=['PHONE_NUMBER', 'EMAIL_ADDRESS', 'CREDIT_CARD', 'US_SSN']):
            if r.score >= 0.4:
                hit = norm[r.start:r.end].lower().replace('@', ' at ').replace('.', ' dot ')
                anchor = next((m.start() for tok in re.findall(r'[a-z]{3,}', hit) for m in [re.search(re.escape(tok), text.lower())] if m), None)
                if anchor is not None:
                    found.append({'type': r.entity_type, 'start': anchor, 'end': min(len(text), anchor + max(len(hit), 20)),
                                  'score': round(r.score, 2), 'source': 'presidio-normalised'})
                elif r.entity_type == 'PHONE_NUMBER':
                    first = re.search(r'\b(zero|one|two|three|four|five|six|seven|eight|nine)\b', text, flags=re.I)
                    if first:
                        found.append({'type': r.entity_type, 'start': first.start(), 'end': min(len(text), first.start() + 60),
                                      'score': round(r.score, 2), 'source': 'presidio-normalised'})
    spans = _word_spans(words)
    entities = []
    for f in found:
        hit = [(a, b) for s, e, a, b in spans if s < f['end'] and e > f['start']]
        if hit:
            entities.append({**f, 'text': text[f['start']:f['end']], 't0': round(min(a for a, _ in hit), 2), 't1': round(max(b for _, b in hit), 2)})
    presidio_spans = [(e['start'], e['end']) for e in entities if e['source'].startswith('presidio') and e['type'] == 'PERSON']
    for e in entities:
        e['action'] = 'mute' if e['score'] >= MUTE_AT else 'review'
        if e['type'] == 'PERSON' and e['source'] == 'gliner' and e['action'] == 'mute' and e['score'] < 0.95:
            # GLiNER alone tags role nouns ("building manager") as people; a name needs a capitalised word that does
            # not merely start a sentence, or Presidio's agreement.
            mid_caps = any(w[:1].isupper() and m.start() > 0 and text[max(0, m.start() - 2):m.start()].strip() not in ('.', '?', '!')
                           for m in re.finditer(r"[A-Za-z']+", e['text']) for w in [m.group(0)])
            agreed = any(a < e['end'] and b > e['start'] for a, b in presidio_spans)
            if not (mid_caps or agreed):
                e['action'] = 'review'
    ctx['pii'] = [e for e in entities if e['action'] == 'mute']
    by_source = {}
    for e in entities:
        by_source.setdefault(e['source'].split('-')[0], set()).add(e['type'])
    return {'pii_count': len(ctx['pii']), 'pii_review_count': sum(e['action'] == 'review' for e in entities),
            'pii_types': sorted({e['type'] for e in ctx['pii']}),
            'pii_sources': {k: sorted(v) for k, v in by_source.items()},
            'pii_entities': [{k: e[k] for k in ('type', 'source', 'score', 't0', 't1', 'action')} for e in entities]}


def pii_redact(ctx, params=None):
    """Mute every PII span (+0.15 s padding) in a copy of the original, then re-run ASR over each span."""
    ents = ctx.get('pii') or []
    if not ents:
        return {'pii_redacted': False, 'pii_verified': None}
    pad = (params or {}).get('pad_s', 0.15)
    sr = ctx['sample_rate']
    spans = sorted((max(0.0, e['t0'] - pad), e['t1'] + pad) for e in ents)
    merged = []
    for a, b in spans:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    y = ctx['x'].copy()
    for a, b in merged:
        y[int(a * sr):int(b * sr)] = 0
    DERIVATIVES.mkdir(exist_ok=True)
    out = DERIVATIVES / f"{ctx['pcm_sha256'][:16]}_pii_muted.wav"
    sf.write(out, y, sr, subtype='PCM_16')
    # Verification: what does ASR hear in each muted window (with 1 s of context either side)?
    mono = y.mean(axis=1)
    g = np.gcd(sr, 16000)
    y16 = resample_poly(mono, 16000 // g, sr // g).astype(np.float32)
    leaked = []
    for e in ents:
        a, b = max(0, int((e['t0'] - 1) * 16000)), int((e['t1'] + 1) * 16000)
        heard, _ = _transcribe(y16[a:b], ctx.get('language'))
        tokens = [t for t in re.findall(r'[a-z0-9]{3,}', e['text'].lower())]
        if tokens and any(t in heard.lower() for t in tokens):
            leaked.append(e['type'])
    return {'pii_redacted': True, 'pii_derivative': str(out.relative_to(ROOT)), 'pii_muted_s': round(sum(b - a for a, b in merged), 2),
            'pii_verified': not leaked, 'pii_leaked_types': sorted(set(leaked))}


# ---------- speakers ----------
def _ecapa():
    from speechbrain.inference.speaker import EncoderClassifier
    from speechbrain.utils.fetching import LocalStrategy
    return EncoderClassifier.from_hparams(source='speechbrain/spkrec-ecapa-voxceleb', savedir=str(CACHE / 'ecapa'),
                                          run_opts={'device': DEVICE}, local_strategy=LocalStrategy.COPY)


def _embed(chunks):
    model = _load('ecapa', _ecapa)
    out = []
    with torch.no_grad():
        for i in range(0, len(chunks), 32):
            batch = torch.from_numpy(np.stack(chunks[i:i + 32])).to(DEVICE)
            e = model.encode_batch(batch).squeeze(1).float().cpu().numpy()
            out.append(e / (np.linalg.norm(e, axis=1, keepdims=True) + 1e-9))
    return np.concatenate(out) if out else np.zeros((0, 192))


def _cluster(emb, threshold):
    if len(emb) < 2:
        return np.ones(len(emb), int)
    return fcluster(linkage(emb, 'average', metric='cosine'), t=threshold, criterion='distance')


def speaker_embed(ctx, params=None):
    """Cheap speaker-count hint on sampled windows; feeds the router's multi-speaker trigger."""
    x = _speech_or_all(ctx)
    size = 16000 * 2
    wins = _windows(len(x), size, (params or {}).get('windows', 10))
    chunks = [np.pad(x[a:b], (0, size - (b - a))).astype(np.float32) for a, b in wins]
    emb = _embed(chunks)
    labels = _cluster(emb, (params or {}).get('threshold', 0.6))
    main = emb[labels == np.bincount(labels).argmax()]
    centroid = main.mean(axis=0)
    centroid /= np.linalg.norm(centroid) + 1e-9
    return {'speakers_hint': int(len(set(labels))), 'speaker_consistency': round(float((main @ centroid).mean()), 3),
            'speaker_windows': len(wins)}


def diarize(ctx, params=None):
    segs = ctx.get('speech_segments') or [(0.0, len(ctx['x16']) / 16000)]
    win, hop = 1.5, 0.75
    starts = [t for a, b in segs for t in np.arange(a, max(a + 1e-3, b - win * 0.5), hop)]
    chunks = [np.pad(ctx['x16'][int(t * 16000):int((t + win) * 16000)], (0, max(0, int(win * 16000) - len(ctx['x16'][int(t * 16000):int((t + win) * 16000)])))).astype(np.float32)
              for t in starts]
    if not chunks:
        return {'speakers': 0, 'speaker_turns': []}
    labels = _cluster(_embed(chunks), (params or {}).get('threshold', 0.6))
    turns = []
    for t, lab in zip(starts, labels):
        a, b = round(float(t), 2), round(float(t + hop), 2)
        if turns and turns[-1][0] == int(lab) and a - turns[-1][2] <= hop + 0.01:
            turns[-1][2] = b
        else:
            turns.append([int(lab), a, b])
    ctx['speaker_turns'] = turns
    return {'speakers': int(len(set(labels))), 'speaker_turns': turns, 'diarize_method': 'ecapa-agglomerative'}


# ---------- separation ----------
def _demucs():
    from demucs.pretrained import get_model
    return get_model('htdemucs').to(DEVICE).eval()


def separate_vocals(ctx, params=None):
    from demucs.apply import apply_model
    model = _load('demucs_htdemucs', _demucs)
    sr, x = ctx['sample_rate'], ctx['x']
    stereo = x if x.shape[1] == 2 else np.repeat(x[:, :1], 2, axis=1)
    g = np.gcd(sr, model.samplerate)
    y = resample_poly(stereo, model.samplerate // g, sr // g, axis=0).T.astype(np.float32)
    wav = torch.from_numpy(y)
    ref = wav.mean(0)
    mean, std = ref.mean(), ref.std() + 1e-8
    with torch.no_grad():
        sources = apply_model(model, ((wav - mean) / std)[None], device=DEVICE, split=True, overlap=0.25, progress=False)[0]
    vocals = (sources[model.sources.index('vocals')] * std + mean).cpu().numpy().T
    DERIVATIVES.mkdir(exist_ok=True)
    out = DERIVATIVES / f"{ctx['pcm_sha256'][:16]}_vocals.wav"
    sf.write(out, vocals, model.samplerate, subtype='PCM_16')
    ratio = float(np.mean(vocals ** 2) / (np.mean(y.T ** 2) + 1e-12))
    return {'vocals_derivative': str(out.relative_to(ROOT)), 'vocal_energy_share': round(ratio, 3), 'separation_model': 'htdemucs'}


# ---------- general quality ----------
def _aesthetics():
    from audiobox_aesthetics.infer import initialize_predictor
    return initialize_predictor()


def quality_general(ctx, params=None):
    pred = _load('audiobox_aesthetics', _aesthetics)
    sr = ctx['sample_rate']
    clip = ctx['x'][: sr * 60].T.astype(np.float32)
    out = pred.forward([{'path': torch.from_numpy(np.ascontiguousarray(clip)), 'sample_rate': sr}])[0]
    return {'aes_production_quality': round(float(out['PQ']), 2), 'aes_production_complexity': round(float(out['PC']), 2),
            'aes_enjoyment': round(float(out['CE']), 2), 'aes_usefulness': round(float(out['CU']), 2),
            'quality_general_model': 'audiobox-aesthetics'}
