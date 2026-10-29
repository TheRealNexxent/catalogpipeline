"""Build the partner deliveries used by db_e2e.py from the generated fixtures.

    python bakeoff/make_deliveries.py

partnerA_d1  a first delivery (PII speech, duplicates, two speakers, an ACN-style bundle, five route samples)
partnerA_d2  the same folder re-delivered: bundle_001/source.wav remixed (E5 update) + one new file
partnerB     a copy of a partner A recording (near-duplicate review)
partnerB_2   a copy of the re-delivered bundle mix, which is in Table 2 by then (E6 provenance review)
"""
from __future__ import annotations
import shutil
from pathlib import Path
import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
F, D = ROOT / 'fixtures', ROOT / 'demo_deliveries'


def main():
    if D.exists():
        shutil.rmtree(D)
    d1 = D / 'partnerA_d1'
    for sub in ('pii', 'dups', 'speakers', 'bundle_001'):
        shutil.copytree(F / sub, d1 / sub)
    (d1 / 'routes').mkdir()
    for name in ('telephony_8k.wav', 'podcast.mp3', 'music_pads.wav', 'ambient_rain.wav', 'duplex_call.wav'):
        shutil.copy(F / 'routes' / name, d1 / 'routes' / name)
    shutil.copy(F / 'quality' / 'clean_48k.wav', d1 / 'clean_48k.wav')

    d2 = D / 'partnerA_d2'
    shutil.copytree(d1, d2)
    v, sr = sf.read(F / 'bundle_001' / 'stems' / 'vocals.wav')
    a, _ = sf.read(F / 'bundle_001' / 'stems' / 'accompaniment.wav')
    mix = v + 0.6 * a
    sf.write(d2 / 'bundle_001' / 'source.wav', mix / np.abs(mix).max() * 0.7, sr, subtype='PCM_16')
    shutil.copy(F / 'snr' / 'v1t1_white_20db.wav', d2 / 'new_interview.wav')

    (D / 'partnerB').mkdir()
    shutil.copy(F / 'dups' / 'as_flac.flac', D / 'partnerB' / 'interview_copy.flac')
    (D / 'partnerB_2').mkdir()
    shutil.copy(d2 / 'bundle_001' / 'source.wav', D / 'partnerB_2' / 'podcast_episode.wav')
    print('deliveries written to', D)


if __name__ == '__main__':
    main()
