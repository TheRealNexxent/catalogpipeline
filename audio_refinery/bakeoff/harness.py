"""Bake-off harness: run every fixture through triage + its routed preset, score against truth.

    python bakeoff/harness.py [fixtures_dir]

Results land in results/<host>_<timestamp>/ (records.jsonl, summary.json, summary.md) and are
tagged with the machine, so 3070 and DGX runs can be compared side by side.
"""
from __future__ import annotations
import itertools, json, os, platform, shutil, subprocess, sys, time
import numpy as np
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import runner  # noqa: E402
from steps import fingerprint  # noqa: E402

sys.stdout.reconfigure(encoding='utf-8')
CANDIDATES = ['snr.energy', 'classify.content.dsp']
AUDIO_EXT = {'.wav', '.flac', '.mp3', '.m4a', '.ogg', '.opus', '.aac', '.aiff'}


def machine():
    gpu = None
    if shutil.which('nvidia-smi'):
        q = subprocess.run(['nvidia-smi', '--query-gpu=name,memory.total,driver_version', '--format=csv,noheader'],
                           capture_output=True, text=True)
        gpu = q.stdout.strip() or None
    return {'host': platform.node(), 'os': f'{platform.system()} {platform.release()}', 'arch': platform.machine(),
            'cpu_count': os.cpu_count(), 'python': platform.python_version(), 'gpu': gpu}


def scan(folder):
    """Inventory + bundle detection (known layouts: stems/, speakers/speaker-*, metadata.json)."""
    files, facts = [], {}
    for p in sorted(folder.rglob('*')):
        if p.is_file() and (p.suffix.lower() in AUDIO_EXT or (p.suffix == '' or p.parent.name == 'gates')) and p.name != 'truth.json':
            files.append(p)
    for meta in folder.rglob('metadata.json'):
        bundle = meta.parent
        declared = json.loads(meta.read_text())
        for p in files:
            if bundle in p.parents:
                rel = p.relative_to(bundle).as_posix()
                role = ('speaker' if rel.startswith('speakers/') else
                        'vocals' if rel.endswith('vocals.wav') else
                        'accompaniment' if rel.endswith('accompaniment.wav') else 'source')
                facts[p] = {'bundle_id': declared.get('sample_id', bundle.name), 'bundle_role': role,
                            'declared': declared, 'declared_language': declared.get('language')}
    return files, facts


def near(a, b, tol):
    return a is not None and b is not None and abs(a - b) <= tol


def score(records, truth, root):
    by = {Path(r['file']).relative_to(root).as_posix(): r for r in records}
    m = lambda key, rec: {k: v for d in rec['measurements'].values() for k, v in d.items()}.get(key)
    checks = {}

    def add(task, ok, name, detail):
        checks.setdefault(task, []).append({'file': name, 'ok': bool(ok), 'detail': detail})

    for name, t in truth.items():
        r = by.get(name)
        if not r:
            continue
        g = m('gates_failed', r) or []
        if 'expect_gates' in t:
            add('gates', g == t['expect_gates'], name, f'expected {t["expect_gates"]} got {g}')
        if g:
            continue
        if 'spectral' in t:
            add('spectral (fake hi-res / lossy origin)', m('spectral_verdict', r) == t['spectral'], name,
                f'expected {t["spectral"]} got {m("spectral_verdict", r)} (cutoff {m("effective_bandwidth_hz", r)} Hz, cliff {m("cutoff_cliff_db", r)} dB)')
        if 'bit_depth' in t:
            add('bit depth', m('effective_bit_depth', r) == t['bit_depth'] and m('bit_depth_padded', r) == t.get('bit_depth_padded', False),
                name, f'expected {t["bit_depth"]}/padded={t.get("bit_depth_padded", False)} got {m("effective_bit_depth", r)}/padded={m("bit_depth_padded", r)}')
        if 'stereo' in t:
            add('stereo checks', m('stereo_verdict', r) == t['stereo'], name, f'expected {t["stereo"]} got {m("stereo_verdict", r)}')
        if 'hum_hz' in t:
            add('hum', m('hum_hz', r) == t['hum_hz'], name, f'expected {t["hum_hz"]} got {m("hum_hz", r)} ({m("hum_excess_db", r)} dB)')
        if t.get('clipped'):
            add('clipping', (m('clipping_pct', r) or 0) > 0.1, name, f'clipping {m("clipping_pct", r)}%')
        if t.get('dc_offset'):
            add('dc offset', max(abs(v) for v in m('dc_offset', r)) > 0.01, name, f'dc {m("dc_offset", r)}')
        if 'dropouts' in t:
            add('dropouts', near(m('dropout_count', r), t['dropouts'], 2), name, f'expected {t["dropouts"]} got {m("dropout_count", r)}')
        if 'leading_silence_s' in t:
            add('silence padding', near(m('leading_silence_s', r), t['leading_silence_s'], 0.3)
                and near(m('trailing_silence_s', r), t['trailing_silence_s'], 0.3), name,
                f'lead {m("leading_silence_s", r)} s, trail {m("trailing_silence_s", r)} s')
        if 'extension_matches' in t:
            add('extension mismatch', m('extension_matches', r) == t['extension_matches'], name, f'got {m("extension_matches", r)}')
        if 'content' in t:
            add('content class: EfficientAT (GPU)', m('content_class', r) == t['content'], name,
                f'expected {t["content"]} got {m("content_class", r)} (windows {m("content_windows", r)})')
            add('content class: DSP baseline (CPU)', m('content_class_dsp', r) == t['content'], name,
                f'expected {t["content"]} got {m("content_class_dsp", r)}')
        if 'language' in t and m('language', r):
            add('language ID: VoxLingua107', m('language', r) == t['language'], name,
                f'expected {t["language"]} got {m("language", r)} ({m("language_confidence", r)})')
        if t.get('ai_generated') and m('ai_generated_score', r) is not None:
            add('AI-speech flag on known-synthetic speech: AASIST', m('ai_generated_score', r) >= 0.5, name,
                f'score {m("ai_generated_score", r)}')
        if 'route' in t:
            add('routing', r['route'] == t['route'], name, f'expected {t["route"]} got {r["route"]}')

    snr = {'snr.wada': [], 'snr.energy': []}
    for name, t in truth.items():
        r = by.get(name)
        if r and name.startswith('snr/'):
            for cand, key in (('snr.wada', 'snr_wada_db'), ('snr.energy', 'snr_energy_db')):
                v = m(key, r)
                if v is not None:
                    snr[cand].append({'file': name, 'truth': t['snr_db'], 'noise': t['noise'], 'est': v, 'err': v - t['snr_db']})

    vad_rows = []
    for name, t in truth.items():
        r = by.get(name)
        if r and 'speech_segments' in t and m('speech_segments', r) is not None:
            grid = np.arange(0, r['audio_s'], 0.01)

            def mark(segs):
                out = np.zeros_like(grid, bool)
                for a, b in segs:
                    out |= (grid >= a) & (grid < b)
                return out

            truth_v, est = mark(t['speech_segments']), mark(m('speech_segments', r))
            tp, fp, fn = (truth_v & est).sum(), (~truth_v & est).sum(), (truth_v & ~est).sum()
            vad_rows.append({'file': name, 'snr': t.get('snr_db'), 'noise': t.get('noise'),
                             'f1': round(float(2 * tp / max(1, 2 * tp + fp + fn)), 3)})
    mos_rows = [{'file': n, 'snr': t['snr_db'], 'noise': t['noise'], 'series': n.split('_')[0] + '_' + t['noise'],
                 'mos': m('mos_utmos', by[n])} for n, t in truth.items()
                if n.startswith('snr/') and n in by and m('mos_utmos', by[n]) is not None]
    dup = []
    by_path = {r['file']: r for r in records}
    group = [n for n, t in truth.items() if t.get('dup_group') == 'g1' and n in by]
    base_name = next(n for n in group if by[n].get('_fingerprint') is not None)
    base = by[base_name]
    for name, t in truth.items():
        if not name.startswith('dups/') or name in (base_name, 'dups/call_A_with_ivr.wav') or name not in by:
            continue
        r = by[name]
        if r.get('copied_from'):
            source = by_path[r['copied_from']]
            same_bytes = r['measurements']['decode.probe']['sha256'] == source['measurements']['decode.probe']['sha256']
            got = 'exact' if same_bytes else 'same_audio'
            expected = t.get('dup_kind', 'unrelated')
            if expected == 'unrelated' and name == 'dups/original.wav':
                expected = 'exact'  # original vs its byte-identical copy, whichever is scanned first
            dup.append({'file': name, 'expected': expected, 'got': got, 'similarity': None})
            continue
        other = by['dups/call_A_with_ivr.wav'] if name == 'dups/call_B_with_ivr.wav' else base
        match = fingerprint.compare(other['_fingerprint'], r['_fingerprint'])
        got = fingerprint.classify(match)
        dup.append({'file': name, 'expected': t.get('dup_kind', 'unrelated'), 'got': got, **match})
    for d in dup:
        add('duplicates', d['expected'] == d['got'], d['file'], f'expected {d["expected"]} got {d["got"]} (sim {d.get("similarity")}, '
            f'overlap {d.get("overlap_a")}/{d.get("overlap_b")})')

    bundles = {}
    for r in records:
        if r.get('bundle_role') == 'speaker':
            b = bundles.setdefault(r['bundle_id'], {'declared': r['declared'].get('speakers'), 'valid': 0, 'tracks': 0})
            b['tracks'] += 1
            b['valid'] += not (m('gates_failed', r) or [])
    w23 = score_wave23(by, truth, m, add)
    return checks, snr, dup, bundles, vad_rows, mos_rows, w23


WORDS = {'0': 'zero', '1': 'one', '2': 'two', '3': 'three', '4': 'four', '5': 'five', '6': 'six', '7': 'seven', '8': 'eight', '9': 'nine'}


def _norm_text(t):
    import re
    t = re.sub(r'\d', lambda d: ' ' + WORDS[d.group(0)] + ' ', t.lower())
    return ' '.join(re.findall(r"[a-z']+", t))


def score_wave23(by, truth, m, add):
    import jiwer
    from scipy.stats import spearmanr
    out = {}
    # ASR word error rate on the SNR ladder + clean reference
    rows = []
    for n, t in truth.items():
        r = by.get(n)
        if r and t.get('transcript') and m('transcript', r) and n.startswith(('snr/', 'quality/')):
            rows.append({'snr': t.get('snr_db'), 'noise': t.get('noise', 'white'),
                         'wer': jiwer.wer(_norm_text(t['transcript']), _norm_text(m('transcript', r)))})
    if rows:
        out['asr'] = {'files': len(rows), 'mean_wer': round(float(np.mean([x['wer'] for x in rows])), 3),
                      'wer_by_snr': {s: round(float(np.mean([x['wer'] for x in rows if x['snr'] == s])), 3) for s in sorted({x['snr'] for x in rows})},
                      'wer_by_noise': {k: round(float(np.mean([x['wer'] for x in rows if x['noise'] == k])), 3) for k in ('white', 'pink', 'babble')}}
    # PII: recall per detector on the PII fixtures, false alarms on PII-free speech
    pii = {'files': [], 'false_alarm_files': 0, 'clean_speech_files': 0}
    for n, t in truth.items():
        r = by.get(n)
        if not r:
            continue
        if t.get('pii_entities'):
            ents = m('pii_entities', r) or []
            muted = {e['type'] for e in ents if e.get('action') == 'mute'}
            per = {src: {e['type'] for e in ents if e['source'].startswith(src)} for src in ('presidio', 'gliner')}
            want = set(t['pii_entities'])
            row = {'file': n, 'expected': sorted(want), 'muted': sorted(muted), 'recall': round(len(want & muted) / len(want), 2),
                   'recall_presidio': round(len(want & per['presidio']) / len(want), 2), 'recall_gliner': round(len(want & per['gliner']) / len(want), 2),
                   'verified': m('pii_verified', r)}
            pii['files'].append(row)
            add('PII: every expected type muted (Presidio + GLiNER)', row['recall'] == 1.0, n, f"expected {row['expected']} muted {row['muted']}")
            add('PII: redaction verified by re-transcription', bool(row['verified']), n, f"verified {row['verified']}, leaked {m('pii_leaked_types', r)}")
        elif t.get('transcript') and n.startswith('snr/') and m('pii_count', r) is not None:
            pii['clean_speech_files'] += 1
            pii['false_alarm_files'] += bool(m('pii_count', r))
    if pii['clean_speech_files']:
        pii['false_alarm_rate'] = round(pii['false_alarm_files'] / pii['clean_speech_files'], 3)
    out['pii'] = pii
    # speakers
    t = truth.get('speakers/two_speaker_mono.wav')
    r = by.get('speakers/two_speaker_mono.wav')
    if t and r:
        add('speaker-count hint (ECAPA, sampled)', m('speakers_hint', r) == t['speakers'], 'speakers/two_speaker_mono.wav', f"hint {m('speakers_hint', r)}")
        add('routing', r['route'] == 'R06', 'speakers/two_speaker_mono.wav', f"expected R06 got {r['route']}")
        turns = m('speaker_turns', r) or []
        if turns:
            grid = np.arange(0, r['audio_s'], 0.05)
            truth_lab = np.full(len(grid), '', dtype=object)
            for spk, a, b in t['speaker_turns']:
                truth_lab[(grid >= a) & (grid < b)] = spk
            est = np.full(len(grid), -1)
            for lab, a, b in turns:
                est[(grid >= a) & (grid < b)] = lab
            mask = truth_lab != ''
            best = 0.0
            labs = sorted(set(est[mask]) - {-1})
            for perm in itertools.permutations(['A', 'B'], min(2, len(labs))):
                mapping = dict(zip(labs, perm))
                best = max(best, float(np.mean([mapping.get(e) == tl for e, tl in zip(est[mask], truth_lab[mask])])))
            out['diarization'] = {'speakers_found': m('speakers', r), 'frame_accuracy': round(best, 3)}
            add('diarization: speakers found', m('speakers', r) == t['speakers'], 'speakers/two_speaker_mono.wav', f"found {m('speakers', r)}")
    # tempo
    r = by.get('music/beat_120bpm.wav')
    if r and m('tempo_bpm', r):
        bpm = m('tempo_bpm', r)
        add('tempo within 4% (or half/double)', any(abs(bpm * k - 120) / 120 <= 0.04 for k in (0.5, 1, 2)), 'music/beat_120bpm.wav', f'{bpm} BPM')
    # general quality vs SNR
    q = [(t['snr_db'], m('aes_production_quality', by[n]), n.split('_')[0] + '_' + t['noise']) for n, t in truth.items()
         if n.startswith('snr/') and n in by and m('aes_production_quality', by[n]) is not None]
    if q:
        rhos = []
        for series in sorted({s for _, _, s in q}):
            pts = [(a, b) for a, b, s in q if s == series]
            if len(pts) >= 4:
                rhos.append(float(spearmanr([a for a, _ in pts], [b for _, b in pts]).statistic))
        out['quality_general'] = {'mean_spearman_vs_snr': round(float(np.mean(rhos)), 3),
                                  'mean_pq_by_snr': {s: round(float(np.mean([b for a, b, _ in q if a == s])), 2) for s in sorted({a for a, _, _ in q})}}
    # vocal separation: Demucs on the bundle mixture vs the true vocals stem (signal-to-distortion ratio)
    src, ref = FOLDER / 'bundle_001' / 'source.wav', FOLDER / 'bundle_001' / 'stems' / 'vocals.wav'
    if src.exists() and ref.exists():
        import soundfile as sf
        from scipy.signal import resample_poly
        from steps import decode, speech
        c = {'path': str(src)}
        decode.probe(c); decode.full_decode(c)
        sep = speech.separate_vocals(c)
        est, sr_e = sf.read(ROOT / sep['vocals_derivative'])
        tru, sr_t = sf.read(ref)
        tru = resample_poly(tru, sr_e // np.gcd(sr_e, sr_t), sr_t // np.gcd(sr_e, sr_t), axis=0)
        n = min(len(est), len(tru))
        e, t_ = est[:n].mean(axis=1), (tru[:n].mean(axis=1) if tru.ndim > 1 else tru[:n])
        sdr = 10 * np.log10(np.sum(t_ ** 2) / (np.sum((t_ - e) ** 2) + 1e-12))
        out['separation'] = {'sdr_db': round(float(sdr), 2)}
        add('vocal separation SDR >= 10 dB (Demucs)', sdr >= 10, 'bundle_001/source.wav', f'SDR {sdr:.1f} dB')
    # enrichment outputs for a human to read
    out['enrichment_samples'] = {n: {k: m(k, by[n]) for k in ('topic', 'summary', 'sentiment', 'emotion', 'genre_top', 'mood_top', 'tempo_bpm', 'key')}
                                 for n in ('snr/v0t0_white_30db.wav', 'snr/v0t1_white_30db.wav', 'pii/pharma_pii.wav', 'music/beat_120bpm.wav', 'routes/music_pads.wav')
                                 if n in by}
    emos = [m('emotion', r) for n, r in by.items() if n.startswith('snr/') and m('emotion', r)]
    if emos:
        out['emotion_neutral_share'] = round(emos.count('neutral') / len(emos), 3)
    return out


def summarise(records, checks, snr, bundles, mach):
    audio = sum(r['audio_s'] for r in records)
    wall = sum(r['wall_ms'] for r in records) / 1000
    steps = {}
    for r in records:
        for sid, ms in r['timings_ms'].items():
            s = steps.setdefault(sid, {'ms': 0.0, 'audio_s': 0.0, 'calls': 0})
            s['ms'] += ms; s['audio_s'] += r['audio_s']; s['calls'] += 1
    for s in steps.values():
        s['realtime_x'] = round(s['audio_s'] / (s['ms'] / 1000), 1) if s['ms'] else None
    snr_stats = {}
    for cand, rows in snr.items():
        if rows:
            errs = [abs(x['err']) for x in rows]
            within3 = sum(e <= 3 for e in errs) / len(errs)
            per_noise = {n: round(sum(abs(x['err']) for x in rows if x['noise'] == n) / max(1, sum(x['noise'] == n for x in rows)), 2)
                         for n in ('white', 'pink', 'babble')}
            snr_stats[cand] = {'files': len(rows), 'mae_db': round(sum(errs) / len(errs), 2), 'within_3db_pct': round(100 * within3, 1),
                               'mae_by_noise': per_noise, 'realtime_x': steps.get(cand, {}).get('realtime_x')}
    routes = {}
    for r in records:
        routes[r['route']] = routes.get(r['route'], 0) + 1
    pending = {}
    for r in records:
        for sid in r['skipped_pending']:
            pending[sid] = pending.get(sid, 0) + 1
    return {'machine': mach, 'files': len(records), 'audio_hours': round(audio / 3600, 4), 'wall_s': round(wall, 2),
            'end_to_end_realtime_x': round(audio / wall, 1) if wall else None,
            'task_accuracy': {k: {'passed': sum(c['ok'] for c in v), 'total': len(v), 'pct': round(100 * sum(c['ok'] for c in v) / len(v), 1),
                                  'failures': [c for c in v if not c['ok']]} for k, v in checks.items()},
            'snr_candidates': snr_stats, 'step_speed': steps, 'routes': routes, 'pending_steps_skipped': pending,
            'bundles': bundles}


def markdown(s):
    lines = [f"# Bake-off run — {s['machine']['host']}", '',
             f"GPU: {s['machine']['gpu'] or 'none'} · CPUs: {s['machine']['cpu_count']} · {s['machine']['os']} {s['machine']['arch']}", '',
             f"**{s['files']} files, {s['audio_hours'] * 60:.1f} min of audio, processed in {s['wall_s']} s → {s['end_to_end_realtime_x']}× realtime** (all implemented steps, models already loaded)", '',
             '## Task accuracy against ground truth', '', '| Task | Passed | Accuracy |', '|---|---|---|']
    for k, v in s['task_accuracy'].items():
        lines.append(f"| {k} | {v['passed']}/{v['total']} | {v['pct']}% |")
    lines += ['', '## SNR estimator candidates (speech + white/pink/babble noise, 0–30 dB)', '',
              '| Candidate | Files | Mean abs error | Within ±3 dB | MAE white / pink / babble | Speed |', '|---|---|---|---|---|---|']
    for k, v in s['snr_candidates'].items():
        n = v['mae_by_noise']
        lines.append(f"| {k} | {v['files']} | {v['mae_db']} dB | {v['within_3db_pct']}% | {n['white']} / {n['pink']} / {n['babble']} dB | {v['realtime_x']}× |")
    if s.get('gpu'):
        lines += ['', f"GPU: {s['gpu']['device']} · peak allocated {s['gpu'].get('peak_allocated_mb')} MB · one-time model load (s): "
                  + ', '.join(f'{k} {v}' for k, v in s['gpu']['model_load_s'].items())]
    if s.get('vad'):
        v = s['vad']
        lines += ['', '## Speech detection: Silero VAD (frame F1 against the true speech timeline)', '',
                  f"Mean F1 **{v['mean_f1']}** over {v['files']} files", '',
                  '| SNR (dB) | ' + ' | '.join(str(k) for k in v['f1_by_snr']) + ' |',
                  '|---' * (len(v['f1_by_snr']) + 1) + '|',
                  '| F1 | ' + ' | '.join(str(x) for x in v['f1_by_snr'].values()) + ' |', '',
                  'By noise type: ' + ', '.join(f'{k} {x}' for k, x in v['f1_by_noise'].items())]
    if s.get('mos'):
        q = s['mos']
        lines += ['', '## Speech quality: UTMOSv2 (no human MOS labels, so a sanity check only)', '',
                  f"Rank correlation with true SNR, averaged over {q['series']} noise series: **{q['mean_spearman_vs_snr']}** "
                  "(1.0 = score always drops as noise rises)", '',
                  '| SNR (dB) | ' + ' | '.join(str(k) for k in q['mean_mos_by_snr']) + ' |',
                  '|---' * (len(q['mean_mos_by_snr']) + 1) + '|',
                  '| mean MOS | ' + ' | '.join(str(x) for x in q['mean_mos_by_snr'].values()) + ' |']
    w = s.get('wave23') or {}
    if w.get('asr'):
        a = w['asr']
        lines += ['', '## Transcription: Whisper large-v3-turbo (word error rate vs the known text)', '',
                  f"Mean WER **{a['mean_wer']}** over {a['files']} files", '',
                  '| SNR (dB) | ' + ' | '.join(str(k) for k in a['wer_by_snr']) + ' |', '|---' * (len(a['wer_by_snr']) + 1) + '|',
                  '| WER | ' + ' | '.join(str(x) for x in a['wer_by_snr'].values()) + ' |', '',
                  'By noise type: ' + ', '.join(f'{k} {x}' for k, x in a['wer_by_noise'].items())]
    if w.get('pii'):
        p = w['pii']
        lines += ['', '## PII detection and redaction', '', '| File | Expected | Muted | Recall: union / Presidio / GLiNER | Verified |', '|---|---|---|---|---|']
        for r in p['files']:
            lines.append(f"| {r['file']} | {', '.join(r['expected'])} | {', '.join(r['muted'])} | {r['recall']} / {r['recall_presidio']} / {r['recall_gliner']} | {r['verified']} |")
        lines += ['', f"False alarms on PII-free speech: {p['false_alarm_files']} of {p['clean_speech_files']} files ({p.get('false_alarm_rate')})"]
    if w.get('diarization'):
        pass
    if w.get('separation'):
        lines += ['', f"**Vocal separation (Demucs htdemucs):** SDR {w['separation']['sdr_db']} dB against the true vocals stem"]
    if w.get('diarization'):
        lines += ['', f"**Diarization (ECAPA + clustering):** {w['diarization']['speakers_found']} speakers found, frame accuracy {w['diarization']['frame_accuracy']}"]
    if w.get('quality_general'):
        g = w['quality_general']
        lines += ['', f"**General quality (Audiobox Aesthetics PQ) vs true SNR:** rank correlation {g['mean_spearman_vs_snr']} (UTMOSv2 scored 0.343)", '',
                  '| SNR (dB) | ' + ' | '.join(str(k) for k in g['mean_pq_by_snr']) + ' |', '|---' * (len(g['mean_pq_by_snr']) + 1) + '|',
                  '| mean PQ | ' + ' | '.join(str(x) for x in g['mean_pq_by_snr'].values()) + ' |']
    if w.get('enrichment_samples'):
        lines += ['', '## Enrichment samples (for a human to read)', '']
        for n, v in w['enrichment_samples'].items():
            lines.append(f"- `{n}`: " + ', '.join(f'{k}: {x}' for k, x in v.items() if x not in (None, [], '')))
        if 'emotion_neutral_share' in w:
            lines.append(f"- Emotion placeholder labelled {w['emotion_neutral_share']:.0%} of the (neutral) TTS speech as neutral")
    lines += ['', '## Step speed', '', '| Step | Calls | Total ms | Realtime × |', '|---|---|---|---|']
    for k, v in sorted(s['step_speed'].items(), key=lambda kv: -kv[1]['ms']):
        lines.append(f"| {k} | {v['calls']} | {v['ms']:.0f} | {v['realtime_x']} |")
    lines += ['', '## Routes chosen', '', ', '.join(f'{k}: {v}' for k, v in sorted(s['routes'].items())), '',
              '## Pending model steps (skipped, lower coverage)', '', ', '.join(f'{k} ({v})' for k, v in s['pending_steps_skipped'].items()) or 'none', '',
              '## Failures', '']
    for k, v in s['task_accuracy'].items():
        for f in v['failures']:
            lines.append(f"- **{k}** · `{f['file']}` — {f['detail']}")
    for b, v in s['bundles'].items():
        lines.append(f"- **bundle** `{b}`: {v['valid']} valid of {v['tracks']} speaker tracks, {v['declared']} declared → "
                     f"{'complete' if v['valid'] == v['declared'] else 'INCOMPLETE (capped at Silver, E14 review)'}")
    return '\n'.join(lines) + '\n'


FOLDER = None


def main(folder):
    global FOLDER
    folder = Path(folder).resolve()
    FOLDER = folder
    truth = json.loads((folder / 'truth.json').read_text())
    files, facts = scan(folder)
    routes = runner.load_presets()
    gpu_info = None
    try:
        from steps import gpu
        import torch
        loads = gpu.warm()
        sample = next(p for p in files if p.name == 'clean_48k.wav')
        runner.process(sample, routes=routes)  # warm-up pass (cuDNN autotune etc.), discarded
        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
        gpu_info = {'device': gpu.DEVICE, 'model_load_s': loads}
    except ImportError:
        pass
    seen, records = {}, []
    for p in files:
        rec = runner.process(p, facts={**(facts.get(p) or {}), 'enrich': True}, seen_index=seen, routes=routes, extra_steps=CANDIDATES)
        rec.update({k: v for k, v in (facts.get(p) or {}).items()})
        records.append(rec)
    checks, snr, dup, bundles, vad_rows, mos_rows, w23 = score(records, truth, folder)
    mach = machine()
    if gpu_info and gpu_info['device'] == 'cuda':
        import torch
        gpu_info['peak_allocated_mb'] = round(torch.cuda.max_memory_allocated() / 1e6)
    summary = summarise(records, checks, snr, bundles, mach)
    summary['gpu'] = gpu_info
    summary['wave23'] = w23
    if vad_rows:
        f1 = [v['f1'] for v in vad_rows]
        summary['vad'] = {'files': len(f1), 'mean_f1': round(float(np.mean(f1)), 3),
                          'f1_by_snr': {s: round(float(np.mean([v['f1'] for v in vad_rows if v['snr'] == s])), 3)
                                        for s in sorted({v['snr'] for v in vad_rows if v['snr'] is not None})},
                          'f1_by_noise': {n: round(float(np.mean([v['f1'] for v in vad_rows if v['noise'] == n])), 3)
                                          for n in ('white', 'pink', 'babble')}}
    if mos_rows:
        from scipy.stats import spearmanr
        rhos = []
        for series in sorted({x['series'] for x in mos_rows}):
            pts = [x for x in mos_rows if x['series'] == series]
            if len(pts) >= 4:
                rhos.append(float(spearmanr([x['snr'] for x in pts], [x['mos'] for x in pts]).statistic))
        summary['mos'] = {'series': len(rhos), 'mean_spearman_vs_snr': round(float(np.mean(rhos)), 3),
                          'mean_mos_by_snr': {s: round(float(np.mean([x['mos'] for x in mos_rows if x['snr'] == s])), 2)
                                              for s in sorted({x['snr'] for x in mos_rows})}}
    out = ROOT / 'results' / f"{mach['host']}_{datetime.now():%Y%m%d_%H%M%S}"
    out.mkdir(parents=True)
    with open(out / 'records.jsonl', 'w', encoding='utf-8') as f:
        for r in records:
            r = {k: v for k, v in r.items() if k != '_fingerprint'}
            f.write(json.dumps(r, default=str) + '\n')
    (out / 'snr_rows.json').write_text(json.dumps(snr, indent=1))
    (out / 'summary.json').write_text(json.dumps(summary, indent=2, default=str))
    (out / 'summary.md').write_text(markdown(summary), encoding='utf-8')
    print(markdown(summary))
    print('results in', out)


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else ROOT / 'fixtures')
