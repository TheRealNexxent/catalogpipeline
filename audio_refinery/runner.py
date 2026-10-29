"""Run one preset pipeline on one file, and pick the route preset for a file.

    python runner.py <audio file> [preset.json]

Without a preset the file goes through triage, then the router picks the matching
route preset and runs only the steps that triage has not already done.
"""
from __future__ import annotations
import json, sys, time
from pathlib import Path
import registry

PRESET_DIR = Path(__file__).parent / 'presets'
OPS = {'==': lambda a, b: a == b, '!=': lambda a, b: a != b, '<': lambda a, b: a is not None and a < b,
       '<=': lambda a, b: a is not None and a <= b, '>': lambda a, b: a is not None and a > b,
       '>=': lambda a, b: a is not None and a >= b, 'in': lambda a, b: a in b}


def holds(conditions, facts):
    return all(OPS[op](facts.get(fact), value) for fact, op, value in conditions or [])


def load_presets(kind='route'):
    presets = [json.loads(p.read_text(encoding='utf-8')) for p in sorted(PRESET_DIR.glob('*.json'))]
    return sorted([p for p in presets if p['kind'] == kind], key=lambda p: p.get('priority', 99))


def run_steps(ctx, steps, record):
    for s in steps:
        sid = s['id']
        if sid in ctx['done'] or ctx.get('stop'):
            continue
        if not holds(s.get('when'), ctx):
            record['not_applicable'].append(sid)
            continue
        info = registry.describe(sid)
        if info['status'] != 'implemented':
            record['skipped_pending'].append(sid)
            ctx['done'].add(sid)
            continue
        fn = registry.IMPLEMENTED[sid][0]
        t = time.perf_counter()
        out = fn(ctx, s.get('params')) or {}
        record['timings_ms'][sid] = round((time.perf_counter() - t) * 1000, 2)
        record['measurements'][sid] = out
        ctx.update(out)
        ctx['done'].add(sid)


def route_for(ctx, routes):
    for p in routes:
        if holds(p['trigger'], ctx):
            return p
    return next(p for p in routes if p['route_id'] == 'R10')


def process(path, facts=None, seen_index=None, routes=None, preset=None, extra_steps=()):
    """Triage + routed preset. Returns a JSON-serialisable record."""
    routes = routes or load_presets()
    ctx = {'path': str(path), 'done': set(), 'seen_index': seen_index, **(facts or {})}
    record = {'file': str(path), 'measurements': {}, 'timings_ms': {}, 'skipped_pending': [], 'not_applicable': []}
    triage = next(p for p in routes if p['route_id'] == 'R02')['steps']  # R02 == triage steps only
    t0 = time.perf_counter()
    run_steps(ctx, preset['steps'] if preset else triage, record)
    chosen = preset or route_for(ctx, routes)
    run_steps(ctx, chosen['steps'], record)
    run_steps(ctx, [{'id': s} for s in extra_steps], record)  # bake-off competitors
    record['route'] = chosen['route_id']
    record['route_name'] = chosen['name']
    record['wall_ms'] = round((time.perf_counter() - t0) * 1000, 2)
    record['audio_s'] = ctx.get('decoded_duration_s') or 0
    planned = [s['id'] for s in chosen['steps'] if s['id'] not in record['not_applicable']]
    ran = [sid for sid in planned if sid in record['measurements']]
    record['step_coverage'] = round(len(ran) / len(planned), 3) if planned else 1.0
    if ctx.get('cache_hit'):
        source = seen_index[ctx['pcm_sha256']]
        for sid, out in source['measurements'].items():
            record['measurements'].setdefault(sid, out)
        record['copied_from'] = source['file']
    elif seen_index is not None and ctx.get('pcm_sha256') and not ctx.get('gates_failed'):
        seen_index[ctx['pcm_sha256']] = record
    record['_fingerprint'] = ctx.get('fingerprint')
    return record


if __name__ == '__main__':
    preset = json.loads(Path(sys.argv[2]).read_text()) if len(sys.argv) > 2 else None
    rec = process(sys.argv[1], preset=preset)
    rec.pop('_fingerprint')
    print(json.dumps(rec, indent=2, default=str))
