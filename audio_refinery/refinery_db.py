"""Postgres layer: Table 1 ingest, changeset proposals, approval, Table 2 promotion and releases.

    python refinery_db.py init
    python refinery_db.py ingest <folder> --partner NAME [--enrich] [--domain pharma]
    python refinery_db.py propose --profile asr [--partner NAME]
    python refinery_db.py show <changeset>
    python refinery_db.py decide <changeset> --accept-defaults | --item ID --accept|--reject
    python refinery_db.py apply <changeset> [--release]
    python refinery_db.py status

Connection settings come from .env (PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE).
"""
from __future__ import annotations
import argparse, hashlib, json, os, sys, time
from pathlib import Path

import numpy as np
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import registry, runner, scoring  # noqa: E402
from steps import fingerprint  # noqa: E402
from bakeoff.harness import AUDIO_EXT, machine, scan  # noqa: E402

RELEASES = ROOT / 'releases'


def connect():
    for line in (ROOT / '.env').read_text().splitlines():
        if '=' in line:
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip())
    return psycopg.connect(autocommit=False)


def versions_hash():
    v = {k: f[2] for k, f in sorted(registry.IMPLEMENTED.items())}
    return hashlib.sha256(json.dumps(v, sort_keys=True).encode()).hexdigest()[:16]


def init(conn):
    conn.execute((ROOT / 'db' / 'schema.sql').read_text())
    for name, p in scoring.PROFILES.items():
        conn.execute('INSERT INTO profiles(name, version, config) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING',
                     (name, p['version'], Jsonb({k: v for k, v in p.items() if k != 'version'})))
    conn.commit()
    print('schema ready; profiles:', ', '.join(scoring.PROFILES))


# ---------------- Phase 1: ingest into Table 1 ----------------
def ingest(conn, folder, partner, enrich=False, domain=None):
    folder = Path(folder).resolve()
    pid = conn.execute('INSERT INTO partners(name) VALUES (%s) ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id',
                       (partner,)).fetchone()[0]
    run_id = conn.execute('INSERT INTO runs(partner_id, source, machine) VALUES (%s, %s, %s) RETURNING id',
                          (pid, str(folder), Jsonb(machine()))).fetchone()[0]
    conn.commit()
    files, facts = scan(folder)
    vh, routes, seen = versions_hash(), runner.load_presets(), {}
    inserted = again = 0
    for p in files:
        rel = p.relative_to(folder).as_posix()
        extra = {**(facts.get(p) or {}), 'enrich': enrich, 'domain': domain}
        sha = hashlib.sha256(p.read_bytes()).hexdigest() if p.stat().st_size else None
        hit = conn.execute('UPDATE audio_catalog SET last_seen = now() WHERE partner_id=%s AND source_path=%s AND file_sha256 IS NOT DISTINCT FROM %s AND versions_hash=%s RETURNING id',
                           (pid, rel, sha, vh)).fetchone()
        if hit:  # Baseline R1: unchanged file, same step versions -> only last_seen moves
            again += 1
            conn.commit()
            continue
        rec = runner.process(p, facts=extra, seen_index=seen, routes=routes)
        f = scoring.flatten(rec['measurements'])
        fp = rec.pop('_fingerprint', None)
        status = 'gate_failed' if f.get('gates_failed') else 'ok'
        conn.execute('''INSERT INTO audio_catalog(run_id, partner_id, source_path, file_sha256, pcm_sha256, versions_hash, bundle_id, bundle_role,
            route, status, gates_failed, duration_s, sample_rate, channels, codec, content_class, language, snr_db, speech_ratio_pct,
            quality_pq, pii_count, pii_verified, ai_generated_score, step_coverage, measurements, declared, fingerprint)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (partner_id, source_path, file_sha256, versions_hash) DO UPDATE SET last_seen = now()''',
            (run_id, pid, rel, f.get('sha256'), f.get('pcm_sha256'), vh, extra.get('bundle_id'), extra.get('bundle_role'),
             rec['route'], status, f.get('gates_failed') or [], f.get('decoded_duration_s'), f.get('sample_rate'), f.get('channels'),
             f.get('codec'), f.get('content_class'), f.get('language'), f.get('snr_wada_db'), f.get('speech_ratio_pct'),
             f.get('aes_production_quality'), f.get('pii_count'), f.get('pii_verified'), f.get('ai_generated_score'),
             rec.get('step_coverage'), Jsonb(json.loads(json.dumps(rec['measurements'], default=str))),
             Jsonb({**(extra.get('declared') or {}), **({'domain': domain} if domain else {})}),
             fp.astype('<u4').tobytes() if fp is not None and len(fp) else None))
        conn.commit()
        inserted += 1
        print(f"  {rel:55s} {rec['route']}  {status}")
    conn.execute('UPDATE runs SET finished_at=now(), files=%s, inserted=%s, seen_again=%s WHERE id=%s',
                 (len(files), inserted, again, run_id))
    conn.commit()
    print(f'run {run_id}: {len(files)} files, {inserted} new Table 1 rows, {again} unchanged (last_seen updated)')


# ---------------- Promotion: build a changeset ----------------
def _fp(b):
    return np.frombuffer(b, dtype='<u4') if b else np.zeros(0, np.uint32)


def _preferred(a, b):
    """Baseline 10.2: lossless > higher sample rate > higher bit depth > higher quality > earlier."""
    def key(r):
        f = scoring.flatten(r['measurements'])
        return (f.get('lossless_origin', 0), r['sample_rate'] or 0, f.get('effective_bit_depth') or 0, r['quality_pq'] or 0, -r['id'])
    return a if key(a) >= key(b) else b


def propose(conn, profile, partner=None):
    if profile not in scoring.PROFILES:
        raise SystemExit(f'unknown profile {profile}; choose from {", ".join(scoring.PROFILES)}')
    q = '''SELECT DISTINCT ON (c.partner_id, c.source_path) c.*, p.name AS partner FROM audio_catalog c JOIN partners p ON p.id = c.partner_id
           WHERE c.status = 'ok' AND (%s::text IS NULL OR p.name = %s) ORDER BY c.partner_id, c.source_path, c.last_seen DESC, c.id DESC'''
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(q, (partner, partner)).fetchall()
        current = cur.execute('SELECT * FROM audio_curated WHERE valid_to IS NULL').fetchall()
        bundles = cur.execute('''SELECT bundle_id, count(*) FILTER (WHERE bundle_role='speaker') AS tracks,
                   count(*) FILTER (WHERE bundle_role='speaker' AND status='ok') AS valid, max((declared->>'speakers')::int) AS declared
                   FROM audio_catalog WHERE bundle_id IS NOT NULL GROUP BY bundle_id''').fetchall()
        fps = {r['id']: _fp(r['fingerprint']) for r in rows}
        cur_fps = {c['id']: _fp(cur.execute('SELECT fingerprint FROM audio_catalog WHERE id=%s', (c['catalog_id'],)).fetchone()['fingerprint'])
                   for c in current}
    complete = {b['bundle_id']: (b['declared'] is None or b['valid'] >= b['declared']) for b in bundles}
    cur_by_pcm = {c['pcm_sha256']: c for c in current}
    cur_by_path = {(c['partner_id'], c['source_path']): c for c in current}
    pdef = scoring.PROFILES[profile]
    cs = conn.execute('INSERT INTO changesets(profile, profile_version) VALUES (%s, %s) RETURNING id', (profile, pdef['version'])).fetchone()[0]
    items, by_pcm, chosen = [], {}, {}
    for r in rows:
        f = scoring.flatten(r['measurements'])
        s = scoring.score(f, profile, declared=r['declared'], domain=r['declared'].get('domain'),
                          bundle_complete=complete.get(r['bundle_id'], True))
        item = {'catalog_id': r['id'], 'tier': s['tier'], 'quality': s['quality'], 'coverage': s['coverage'], 'scoring': s,
                'related': None}

        def put(proposal, case, reason, default):
            item.update(proposal=proposal, case=case, reason=reason, default=default)
        if s['tier'] == 'Reject':
            put('exclude', None, 'Not eligible for this profile: ' + '; '.join(s['failed'] or s['caps']), 'accept')
        elif r['pcm_sha256'] in cur_by_pcm:
            c = cur_by_pcm[r['pcm_sha256']]
            same_bytes = c['file_sha256'] == r['file_sha256']
            if c['partner_id'] != r['partner_id']:
                put('review', 'E6', 'Same audio already curated from another partner (provenance / rights)', 'reject')
            else:
                put('skip', 'E1' if same_bytes else 'E2', 'Already in Table 2 ' + ('(identical file)' if same_bytes else '(same audio, other format)'), 'accept')
            item['related'] = c['id']
        elif (r['partner_id'], r['source_path']) in cur_by_path:
            c = cur_by_path[(r['partner_id'], r['source_path'])]
            put('update', 'E5', 'Partner re-delivered this path with new content; replaces the current row', 'accept')
            item['related'] = c['id']
        else:
            put('insert', None, f"New {s['tier']} row", 'accept')
        # second pass flags that turn an insert into a review
        if item['proposal'] == 'insert':
            if r['pcm_sha256'] in by_pcm:  # same audio twice in this selection
                keep = _preferred(by_pcm[r['pcm_sha256']], r)
                loser = r if keep is not r else by_pcm[r['pcm_sha256']]
                item.update(proposal='skip', case='E2', reason=f'Same audio as {keep["source_path"]} in this selection; keeping the better copy', default='accept')
                if loser is not r:  # the earlier one loses: flip its item
                    prev = chosen[loser['id']]
                    prev.update(proposal='skip', case='E2', reason=f'Same audio as {r["source_path"]}; that copy is better', default='accept')
                    by_pcm[r['pcm_sha256']] = r
                    item.update(proposal='insert', case=None, reason=f"New {s['tier']} row (preferred copy)", default='accept')
            else:
                by_pcm[r['pcm_sha256']] = r
        if item['proposal'] == 'insert':
            for cid, cfp in list(cur_fps.items()) + [(None, fps[o['id']]) for o in rows if o['id'] in chosen and chosen[o['id']]['proposal'] in ('insert', 'review')]:
                if not len(cfp) or not len(fps[r['id']]):
                    continue
                kind = fingerprint.classify(fingerprint.compare(cfp, fps[r['id']]))
                if kind in ('duplicate', 'containment', 'partial_overlap'):
                    code = 'E3' if kind != 'containment' else 'E4'
                    item.update(proposal='review', case=code, reason=f'Near-duplicate ({kind}) of an existing or selected file', default='reject', related=cid)
                    break
        if item['proposal'] == 'insert' and (f.get('ai_generated_score') or 0) >= 0.5:
            default = 'reject' if pdef.get('ai_default') == 'exclude' else 'accept'
            item.update(proposal='review', case='E11', reason=f"AI-generated speech flag {f['ai_generated_score']:.2f}; default {pdef.get('ai_default')}", default=default)
        if item['proposal'] in ('insert', 'review') and f.get('pii_count'):
            if f.get('pii_verified'):
                item['reason'] += f"; PII muted in a verified derivative ({', '.join(f.get('pii_types') or [])})"
            else:
                item.update(proposal='review', case='E12', reason='PII found but redaction not verified', default='reject')
        if item['proposal'] in ('insert', 'review') and f.get('pii_review_count') and item['case'] != 'E12':
            item['reason'] += f"; {f['pii_review_count']} low-confidence PII match(es) to check"
            if item['proposal'] == 'insert':
                item.update(proposal='review', case='E12', default='accept')
        if item['proposal'] == 'insert' and r['bundle_id'] and not complete.get(r['bundle_id'], True):
            item.update(proposal='review', case='E14', reason='Bundle incomplete (a declared speaker track failed); promote valid members?', default='accept')
        chosen[r['id']] = item
        items.append(item)
    for it in items:
        conn.execute('''INSERT INTO changeset_items(changeset_id, catalog_id, proposal, case_code, reason, default_decision, related_curated_id,
                        tier, quality, coverage, scoring) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                     (cs, it['catalog_id'], it['proposal'], it['case'], it['reason'], it['default'], it['related'] if isinstance(it['related'], int) else None,
                      it['tier'], it['quality'], it['coverage'], Jsonb(json.loads(json.dumps(it['scoring'], default=str)))))
    conn.commit()
    counts = {}
    for it in items:
        counts[it['proposal']] = counts.get(it['proposal'], 0) + 1
    print(f'changeset {cs} ({profile}): {len(items)} candidates -> ' + ', '.join(f'{k} {v}' for k, v in sorted(counts.items())))
    return cs


def show(conn, cs):
    with conn.cursor() as cur:
        rows = cur.execute('''SELECT i.id, i.proposal, coalesce(i.case_code, ''), i.tier, i.quality, i.coverage, i.default_decision,
               coalesce(i.decision, '-'), c.source_path, i.reason FROM changeset_items i JOIN audio_catalog c ON c.id = i.catalog_id
               WHERE i.changeset_id = %s ORDER BY i.proposal, i.case_code NULLS FIRST, c.source_path''', (cs,)).fetchall()
    for r in rows:
        print(f'{r[0]:>5} {r[1]:7s} {r[2]:4s} {r[3]:7s} Q{r[4]:5.1f} C{r[5]:5.1f} default:{r[6]:6s} decided:{r[7]:6s} {r[8]}  -- {r[9][:90]}')


def decide(conn, cs, accept_defaults=False, item=None, accept=None):
    if accept_defaults:
        n = conn.execute("UPDATE changeset_items SET decision = default_decision, decided_at = now() WHERE changeset_id=%s AND decision IS NULL", (cs,)).rowcount
        print(f'{n} items decided by their default')
    else:
        conn.execute('UPDATE changeset_items SET decision=%s, decided_at=now() WHERE id=%s AND changeset_id=%s',
                     ('accept' if accept else 'reject', item, cs))
    conn.commit()


def apply(conn, cs, release=False):
    with conn.transaction():
        st = conn.execute('SELECT status, profile, profile_version FROM changesets WHERE id=%s FOR UPDATE', (cs,)).fetchone()
        if st is None or st[0] != 'pending':
            raise SystemExit(f'changeset {cs} is not pending')
        if conn.execute('SELECT count(*) FROM changeset_items WHERE changeset_id=%s AND decision IS NULL', (cs,)).fetchone()[0]:
            raise SystemExit('undecided items remain; run decide first')
        # Stale guard (Baseline V5): a newer Table 1 row for the same file blocks approval.
        stale = conn.execute('''SELECT c.source_path FROM changeset_items i JOIN audio_catalog c ON c.id=i.catalog_id
              JOIN changesets s ON s.id=i.changeset_id WHERE i.changeset_id=%s AND EXISTS (SELECT 1 FROM audio_catalog n
              WHERE n.partner_id=c.partner_id AND n.source_path=c.source_path AND n.id>c.id AND n.first_seen > s.created_at)''', (cs,)).fetchall()
        if stale:
            raise SystemExit('stale: files changed after the changeset was built: ' + ', '.join(s[0] for s in stale[:5]))
        rows = conn.execute('''SELECT i.proposal, i.related_curated_id, i.tier, i.quality, i.coverage, c.id, c.partner_id, c.source_path,
               c.pcm_sha256, c.file_sha256, c.measurements FROM changeset_items i JOIN audio_catalog c ON c.id = i.catalog_id
               WHERE i.changeset_id=%s AND i.decision='accept' AND i.proposal IN ('insert','update','review')''', (cs,)).fetchall()
        added = replaced = 0
        for proposal, related, tier, q, cov, cid, pid, path, pcm, sha, meas in rows:
            f = scoring.flatten(meas)
            labels = {k: f.get(k) for k in ('content_class', 'language', 'speakers_hint', 'topic', 'emotion', 'genre_top')}
            labels['ai_generated'] = (f.get('ai_generated_score') or 0) >= 0.5
            derivs = {k: f[k] for k in ('pii_derivative', 'vocals_derivative') if f.get(k)}
            old = conn.execute('SELECT id FROM audio_curated WHERE valid_to IS NULL AND (pcm_sha256=%s OR (partner_id=%s AND source_path=%s))',
                               (pcm, pid, path)).fetchone()
            if old:
                conn.execute('UPDATE audio_curated SET valid_to=now() WHERE id=%s', (old[0],))
            new = conn.execute('''INSERT INTO audio_curated(catalog_id, changeset_id, partner_id, source_path, pcm_sha256, file_sha256, profile,
                   profile_version, tier, quality, coverage, labels, derivatives) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',
                               (cid, cs, pid, path, pcm, sha, st[1], st[2], tier, q, cov, Jsonb(labels), Jsonb(derivs))).fetchone()[0]
            if old:
                conn.execute('UPDATE audio_curated SET superseded_by=%s WHERE id=%s', (new, old[0]))
                replaced += 1
            else:
                added += 1
        conn.execute("UPDATE changesets SET status='applied', applied_at=now() WHERE id=%s", (cs,))
        rel = None
        if release:
            items = conn.execute('''SELECT id, partner_id, source_path, pcm_sha256, file_sha256, tier, quality, derivatives
                                    FROM audio_curated WHERE valid_to IS NULL ORDER BY id''').fetchall()
            manifest = [{'curated_id': i[0], 'partner_id': i[1], 'path': i[2], 'pcm_sha256': i[3], 'file_sha256': i[4], 'tier': i[5],
                         'quality': i[6], 'derivatives': i[7]} for i in items]
            body = json.dumps(manifest, sort_keys=True)
            version = conn.execute('SELECT coalesce(max(version), 0) + 1 FROM releases').fetchone()[0]
            conn.execute('INSERT INTO releases(version, changeset_id, item_count, manifest, manifest_sha256) VALUES (%s,%s,%s,%s,%s)',
                         (version, cs, len(manifest), Jsonb(manifest), hashlib.sha256(body.encode()).hexdigest()))
            RELEASES.mkdir(exist_ok=True)
            (RELEASES / f'release_v{version}.json').write_text(body, encoding='utf-8')
            rel = version
    print(f'changeset {cs} applied: {added} added, {replaced} replaced' + (f'; release v{rel} written' if rel else ''))


def status(conn):
    q = lambda s: conn.execute(s).fetchone()[0]
    failed = q("SELECT count(*) FROM audio_catalog WHERE status = 'gate_failed'")
    print(f"Table 1 rows: {q('SELECT count(*) FROM audio_catalog')}  (gate failed: {failed})")
    print(f"Table 2 current rows: {q('SELECT count(*) FROM audio_curated WHERE valid_to IS NULL')}  (superseded: {q('SELECT count(*) FROM audio_curated WHERE valid_to IS NOT NULL')})")
    print(f"changesets: {q('SELECT count(*) FROM changesets')}  releases: {q('SELECT count(*) FROM releases')}")
    for r in conn.execute('SELECT tier, count(*) FROM audio_curated WHERE valid_to IS NULL GROUP BY tier ORDER BY tier').fetchall():
        print(f'  {r[0]}: {r[1]}')


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest='cmd', required=True)
    sp.add_parser('init')
    a = sp.add_parser('ingest'); a.add_argument('folder'); a.add_argument('--partner', required=True)
    a.add_argument('--enrich', action='store_true'); a.add_argument('--domain')
    a = sp.add_parser('propose'); a.add_argument('--profile', required=True); a.add_argument('--partner')
    a = sp.add_parser('show'); a.add_argument('changeset', type=int)
    a = sp.add_parser('decide'); a.add_argument('changeset', type=int); a.add_argument('--accept-defaults', action='store_true')
    a.add_argument('--item', type=int); g = a.add_mutually_exclusive_group(); g.add_argument('--accept', action='store_true'); g.add_argument('--reject', action='store_true')
    a = sp.add_parser('apply'); a.add_argument('changeset', type=int); a.add_argument('--release', action='store_true')
    sp.add_parser('status')
    args = ap.parse_args()
    with connect() as conn:
        if args.cmd == 'init':
            init(conn)
        elif args.cmd == 'ingest':
            ingest(conn, args.folder, args.partner, args.enrich, args.domain)
        elif args.cmd == 'propose':
            propose(conn, args.profile, args.partner)
        elif args.cmd == 'show':
            show(conn, args.changeset)
        elif args.cmd == 'decide':
            decide(conn, args.changeset, args.accept_defaults, args.item, args.accept)
        elif args.cmd == 'apply':
            apply(conn, args.changeset, args.release)
        else:
            status(conn)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
