"""End-to-end test of the Postgres layer across two deliveries and two partners.

    python bakeoff/db_e2e.py --reset

1. Partner A, delivery 1 -> Table 1 -> changeset -> approval -> Table 2 -> release v1
2. Same delivery again   -> every file unchanged: only last_seen moves (Baseline R1)
3. Partner A, delivery 2 -> one path re-delivered with new audio (E5 update) + one new file -> release v2
4. Partner B sends audio already curated from partner A -> E6 review (provenance / rights)
5. Release v1 is re-read and its checksum compared: releases never change (Baseline V4)
"""
from __future__ import annotations
import hashlib, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import refinery_db as rdb  # noqa: E402

D = ROOT / 'demo_deliveries'


def counts(conn, cs):
    return dict(conn.execute('SELECT proposal || coalesce(\':\' || case_code, \'\'), count(*) FROM changeset_items WHERE changeset_id=%s GROUP BY 1 ORDER BY 1', (cs,)).fetchall())


def main(reset, enrich=False):
    sys.stdout.reconfigure(encoding='utf-8')
    with rdb.connect() as conn:
        if reset:
            rdb.init(conn)
            conn.execute('TRUNCATE releases, audio_curated, changeset_items, changesets, audio_catalog, runs, partners RESTART IDENTITY CASCADE')
            conn.commit()
        rdb.init(conn)
        print('\n== 1. partner A, delivery 1')
        rdb.ingest(conn, D / 'partnerA_d1', 'Partner A', enrich=enrich)
        cs1 = rdb.propose(conn, 'asr', 'Partner A')
        print('   proposals:', counts(conn, cs1))
        rdb.decide(conn, cs1, accept_defaults=True)
        rdb.apply(conn, cs1, release=True)
        v1 = conn.execute('SELECT manifest_sha256 FROM releases WHERE version=1').fetchone()[0]

        print('\n== 2. same delivery again')
        rdb.ingest(conn, D / 'partnerA_d1', 'Partner A', enrich=enrich)

        print('\n== 3. partner A, delivery 2 (one path re-delivered with new audio, one new file)')
        rdb.ingest(conn, D / 'partnerA_d2', 'Partner A', enrich=enrich)
        cs2 = rdb.propose(conn, 'asr', 'Partner A')
        print('   proposals:', counts(conn, cs2))
        rdb.decide(conn, cs2, accept_defaults=True)
        rdb.apply(conn, cs2, release=True)

        print('\n== 4. partner B sends a recording partner A already delivered')
        rdb.ingest(conn, D / 'partnerB', 'Partner B', enrich=enrich)
        cs3 = rdb.propose(conn, 'asr', 'Partner B')
        print('   proposals:', counts(conn, cs3))
        rdb.show(conn, cs3)

        print('\n== 5. release v1 unchanged?')
        again = conn.execute('SELECT manifest_sha256 FROM releases WHERE version=1').fetchone()[0]
        body = json.dumps(json.loads((ROOT / 'releases' / 'release_v1.json').read_text(encoding='utf-8')), sort_keys=True)
        print('   v1 checksum stable:', again == v1, '| file matches DB:', hashlib.sha256(body.encode()).hexdigest() == v1)
        print()
        rdb.status(conn)


if __name__ == '__main__':
    main('--reset' in sys.argv, '--enrich' in sys.argv)
