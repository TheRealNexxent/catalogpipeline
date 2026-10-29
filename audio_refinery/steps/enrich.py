"""Wave 3 enrichment steps (optional; run when a profile asks for enrichment).

    music.analysis   tempo + key (librosa, ISC) and zero-shot genre / mood tags (LAION-CLAP, Apache-2.0)
    emotion          LAION-CLAP zero-shot over emotion prompts. PLACEHOLDER: untrained, low trust; a head trained
                     on commercially usable labels (e.g. CREMA-D, ODbL) replaces it
    bioacoustic      animal classes from the EfficientAT pass already made in triage; species-level Perch runs on the DGX
    text.enrich      topic, one-line summary, sentiment, keywords from the transcript (Qwen2.5-1.5B-Instruct, Apache-2.0)
    demographics     not implemented: no commercial-safe model exists and the training labels need licence terms accepted

Raw transcripts are inputs here; only the derived labels are returned.
"""
from __future__ import annotations
import json, re
import numpy as np
from scipy.signal import resample_poly

from steps.gpu import DEVICE, _load, _speech_or_all, _tag_windows, _windows, torch

STEP_VERSION = 'gpu-wave3-v1'
GENRES = ['ambient', 'classical', 'electronic', 'hip hop', 'jazz', 'pop', 'rock', 'folk', 'cinematic score', 'world music']
MOODS = ['calm', 'happy', 'sad', 'energetic', 'tense', 'dark']
EMOTIONS = ['neutral', 'happy', 'sad', 'angry', 'fearful', 'surprised']
ANIMAL_WORDS = ('Animal', 'Bird', 'Dog', 'Cat', 'Insect', 'Frog', 'Cattle', 'Horse', 'Pig', 'Sheep', 'Goat', 'Fowl',
                'Owl', 'Crow', 'Pigeon', 'Duck', 'Goose', 'Whale', 'Bat', 'Cricket', 'Mosquito', 'Bee', 'Roar', 'Howl', 'Chirp')
KEYS = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def _mono_at(ctx, rate):
    sr = ctx['sample_rate']
    g = np.gcd(sr, rate)
    return resample_poly(ctx['mono'], rate // g, sr // g).astype(np.float32)


# ---------- CLAP zero-shot ----------
def _clap():
    from transformers import ClapModel, ClapProcessor
    return {'model': ClapModel.from_pretrained('laion/clap-htsat-unfused').to(DEVICE).eval(),
            'proc': ClapProcessor.from_pretrained('laion/clap-htsat-unfused')}


def _zero_shot(audio48, prompts, count=3):
    c = _load('laion_clap', _clap)
    wins = _windows(len(audio48), 48000 * 10, count)
    clips = [audio48[a:b] for a, b in wins]
    with torch.no_grad():
        inputs = c['proc'](text=prompts, audios=clips, sampling_rate=48000, return_tensors='pt', padding=True)
        inputs = {k: v.to(DEVICE) for k, v in inputs.items()}
        probs = c['model'](**inputs).logits_per_audio.softmax(-1).mean(0).cpu().numpy()
    return probs


def music_analysis(ctx, params=None):
    import librosa
    y = _mono_at(ctx, 22050)[: 22050 * 120]
    tempo, _ = librosa.beat.beat_track(y=y, sr=22050)
    chroma = librosa.feature.chroma_cqt(y=y, sr=22050).mean(axis=1)
    scores = [(np.corrcoef(np.roll(MAJOR, k), chroma)[0, 1], f'{KEYS[k]} major') for k in range(12)]
    scores += [(np.corrcoef(np.roll(MINOR, k), chroma)[0, 1], f'{KEYS[k]} minor') for k in range(12)]
    best = sorted(scores, reverse=True)
    audio48 = _mono_at(ctx, 48000)
    g = _zero_shot(audio48, [f'{x} music' for x in GENRES])
    m = _zero_shot(audio48, [f'{x} music' for x in MOODS])
    return {'tempo_bpm': round(float(np.atleast_1d(tempo)[0]), 1), 'key': best[0][1], 'key_confidence': round(float(best[0][0]), 2),
            'genre_top': GENRES[int(g.argmax())], 'genre_score': round(float(g.max()), 2),
            'mood_top': MOODS[int(m.argmax())], 'mood_score': round(float(m.max()), 2), 'music_method': 'librosa + laion-clap zero-shot'}


def emotion(ctx, params=None):
    x = _speech_or_all(ctx)
    g = np.gcd(16000, 48000)
    audio48 = resample_poly(x, 48000 // g, 16000 // g).astype(np.float32)
    p = _zero_shot(audio48, [f'a person speaking in a {e} voice' for e in EMOTIONS])
    return {'emotion': EMOTIONS[int(p.argmax())], 'emotion_score': round(float(p.max()), 2),
            'emotion_method': 'laion-clap zero-shot (placeholder, untrained)'}


def bioacoustic(ctx, params=None):
    p, _, m = _tag_windows(ctx)
    mean = p.mean(axis=0)
    idx = [i for i, l in enumerate(m['labels']) if any(w in l for w in ANIMAL_WORDS)]
    top = sorted(idx, key=lambda i: -mean[i])[:5]
    present = [(m['labels'][i], round(float(mean[i]), 3)) for i in top if mean[i] >= 0.1]
    return {'animal_sounds': present, 'animal_present': bool(present),
            'bioacoustic_method': 'efficientat audioset classes (species-level Perch: DGX)'}


# ---------- transcript enrichment ----------
def _llm():
    from transformers import AutoModelForCausalLM, AutoTokenizer
    name = 'Qwen/Qwen2.5-1.5B-Instruct'
    return {'tok': AutoTokenizer.from_pretrained(name),
            'model': AutoModelForCausalLM.from_pretrained(name, dtype=torch.float16 if DEVICE == 'cuda' else torch.float32).to(DEVICE).eval()}


def text_enrich(ctx, params=None):
    text = (ctx.get('transcript') or '').strip()
    if len(text.split()) < 5:
        return {'topic': None, 'summary': None, 'sentiment': None, 'keywords': []}
    llm = _load('qwen2_5_1_5b', _llm)
    prompt = ('Read this transcript and reply with JSON only, keys: "topic" (2-4 words), "summary" (one sentence, '
              'no names, numbers or other personal details), "sentiment" (positive, neutral or negative), '
              '"keywords" (3 short phrases, no personal details).\n\nTranscript:\n' + text[:6000])
    msgs = [{'role': 'user', 'content': prompt}]
    ids = llm['tok'].apply_chat_template(msgs, add_generation_prompt=True, return_tensors='pt').to(DEVICE)
    with torch.no_grad():
        out = llm['model'].generate(ids, max_new_tokens=160, do_sample=False)
    reply = llm['tok'].decode(out[0, ids.shape[1]:], skip_special_tokens=True)
    match = re.search(r'\{.*\}', reply, flags=re.S)
    try:
        data = json.loads(match.group(0)) if match else {}
    except json.JSONDecodeError:
        data = {}
    return {'topic': data.get('topic'), 'summary': data.get('summary'), 'sentiment': data.get('sentiment'),
            'keywords': data.get('keywords') or [], 'text_model': 'qwen2.5-1.5b-instruct', 'text_parsed': bool(data)}
