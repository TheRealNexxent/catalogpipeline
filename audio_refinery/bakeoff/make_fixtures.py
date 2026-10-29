"""Build the synthetic edge-case corpus with known ground truth (bake-off step 2, fixtures part).

Speech comes from the Windows built-in voices (System.Speech), so every speech fixture is
itself AI-generated; truth.json records that. Real labelled corpora come later.

    python bakeoff/make_fixtures.py
"""
from __future__ import annotations
import json, shutil, subprocess, sys
from pathlib import Path
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly, lfilter

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'fixtures'
RAW = OUT / '_tts'
RNG = np.random.default_rng(7)
TEXTS = [
    "The quarterly results were stronger than expected. Revenue grew in every region, and the team plans to expand next spring. Customers asked for faster delivery and better support, so we are hiring in both areas.",
    "Please remember to water the plants on Tuesday. The keys are under the blue pot by the door. If anything breaks, call the building manager before six in the evening, and leave a note on the kitchen table.",
    "Rain is expected across the north this weekend, with strong winds along the coast. Temperatures will drop sharply on Sunday night. Drivers should allow extra time and check for road closures before leaving.",
    "Thank you for calling. This call may be recorded for training and quality purposes. Please hold while we connect you to the next available agent.",
    "Hi, this is Sarah Johnson. You can reach me on four one five, five five five, zero one three two, or email sarah dot johnson at example dot com.",
    "Patient Michael Torres, born on the fourth of March nineteen seventy five, reported dizziness after starting metformin for type two diabetes.",
]
PII_TRUTH = {
    4: {'domain': 'general', 'entities': ['PERSON', 'PHONE_NUMBER', 'EMAIL_ADDRESS'], 'words': ['Sarah', 'Johnson']},
    5: {'domain': 'pharma', 'entities': ['PERSON', 'DATE_TIME', 'MEDICAL'], 'words': ['Michael', 'Torres']},
}
VOICES = ['Microsoft David Desktop', 'Microsoft Zira Desktop']


def tts(text, voice, path):
    ps = ("Add-Type -AssemblyName System.Speech;"
          "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
          f"$s.SelectVoice('{voice}');"
          "$f=New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000,[System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,[System.Speech.AudioFormat.AudioChannel]::Mono);"
          f"$s.SetOutputToWaveFile('{path}',$f);$s.Speak(@'\n{text}\n'@);$s.Dispose()")
    subprocess.run(['powershell', '-NoProfile', '-Command', ps], check=True)


def load(path):
    x, sr = sf.read(path, dtype='float64')
    return x


def active_power(x, sr=16000):
    n = int(0.025 * sr)
    frames = x[: len(x) // n * n].reshape(-1, n)
    p = np.mean(frames ** 2, axis=1)
    return float(p[p > 0.01 * p.mean()].mean())


def pink(n):
    w = RNG.standard_normal(n)
    b, a = [0.049922035, -0.095993537, 0.050612699, -0.004408786], [1, -2.494956002, 2.017265875, -0.522189400]
    y = lfilter(b, a, w)
    return y / np.sqrt(np.mean(y ** 2))


def white(n):
    return RNG.standard_normal(n)


def mix_snr(speech, noise, snr_db):
    noise = noise[: len(speech)] / np.sqrt(np.mean(noise[: len(speech)] ** 2))
    return speech + noise * np.sqrt(active_power(speech) / 10 ** (snr_db / 10))


def speech_segments(clean, sr=16000):
    """Ground-truth speech timeline from the clean (pre-noise) signal: 10 ms frames within 35 dB
    of the loudest frame, gaps under 200 ms bridged, islands under 100 ms dropped."""
    n = sr // 100
    rms = np.sqrt(np.mean(clean[: len(clean) // n * n].reshape(-1, n) ** 2, axis=1))
    active = rms > rms.max() * 10 ** (-35 / 20)
    segs, start = [], None
    for i, a in enumerate(np.r_[active, False]):
        if a and start is None:
            start = i
        elif not a and start is not None:
            segs.append([start / 100, i / 100]); start = None
    merged = []
    for s in segs:
        if merged and s[0] - merged[-1][1] < 0.2:
            merged[-1][1] = s[1]
        else:
            merged.append(s)
    return [[round(a, 2), round(b, 2)] for a, b in merged if b - a >= 0.1]


def norm(x, peak_db=-3.0):
    return x / (np.max(np.abs(x)) + 1e-12) * 10 ** (peak_db / 20)


def up(x, sr_from, sr_to):
    g = np.gcd(sr_from, sr_to)
    return resample_poly(x, sr_to // g, sr_from // g)


def write(name, x, sr, subtype='PCM_16', **truth):
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, np.clip(x, -1, 1 - 2 ** -15) if subtype.startswith('PCM') else x, sr, subtype=subtype)
    TRUTH[name] = truth
    return path


def ffmpeg(*args):
    Path(args[-1]).parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', *map(str, args)], check=True)


def music(seconds, sr=48000):
    t = np.arange(int(seconds * sr)) / sr
    out = np.zeros_like(t)
    chords = [[220, 277.2, 329.6], [196, 246.9, 293.7], [174.6, 220, 261.6], [196, 246.9, 311.1]]
    for i, start in enumerate(np.arange(0, seconds, 2.0)):
        seg = (t >= start) & (t < start + 2.2)
        env = np.clip((t[seg] - start) / 0.05, 0, 1) * np.exp(-(t[seg] - start) * 0.6)
        for f in chords[i % 4]:
            for h, amp in ((1, 1), (2, .4), (3, .2), (4, .1)):
                out[seg] += amp * env * np.sin(2 * np.pi * f * h * t[seg])
    return norm(out + 0.002 * pink(len(t)), -6)


TRUTH = {}


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    RAW.mkdir(parents=True)
    base = {}
    for vi, voice in enumerate(VOICES):
        for ti, text in enumerate(TEXTS):
            p = RAW / f'v{vi}_t{ti}.wav'
            tts(text, voice, p)
            x = load(p)
            on = np.flatnonzero(np.abs(x) > 10 ** (-50 / 20))
            base[(vi, ti)] = x[on[0]:on[-1] + 1]
    babble = sum(np.pad(base[(v, t)], (0, 400000))[:400000] for v in range(2) for t in range(3))

    sp = {k: v for k, v in base.items() if k[1] < 3}
    a, b = norm(sp[(0, 0)]), norm(sp[(1, 1)])

    # --- clean reference at 48 kHz: speech + full-band noise floor (SNR 35 dB) ---
    a48 = up(a, 16000, 48000)
    clean = norm(mix_snr(a48, white(len(a48)), 35))
    write('quality/clean_48k.wav', clean, 48000, expect_gates=[], snr_db=35, content='speech', spectral='full_band',
          stereo='mono', bit_depth=16, ai_generated=True, speech_segments=speech_segments(a), language='en',
          transcript=TEXTS[0])

    # --- SNR ladder: 2 voices x 3 noise types x 6 levels, 16 kHz mono ---
    for (vi, ti), s in sp.items():
        if ti != 0 and ti != 1:
            continue
        s = norm(s)
        for kind, gen in (('white', white), ('pink', pink), ('babble', lambda n: babble[:n])):
            for snr in (0, 5, 10, 15, 20, 30):
                write(f'snr/v{vi}t{ti}_{kind}_{snr:02d}db.wav', norm(mix_snr(s, gen(len(s)), snr), -1), 16000,
                      expect_gates=[], snr_db=snr, noise=kind, content='speech', ai_generated=True,
                      speech_segments=speech_segments(s), language='en', transcript=TEXTS[ti])

    # --- gates ---
    (OUT / 'gates').mkdir(parents=True, exist_ok=True)
    (OUT / 'gates/empty.wav').write_bytes(b''); TRUTH['gates/empty.wav'] = {'expect_gates': ['G1']}
    (OUT / 'gates/text_as_wav.wav').write_text('this is not audio\n' * 50); TRUTH['gates/text_as_wav.wav'] = {'expect_gates': ['G2']}
    (OUT / 'gates/random_bytes.mp3').write_bytes(RNG.integers(0, 256, 50000, dtype=np.uint8).tobytes())
    TRUTH['gates/random_bytes.mp3'] = {'expect_gates': ['G2']}
    full = write('gates/_full.wav', clean, 48000)
    data = full.read_bytes()
    (OUT / 'gates/truncated.wav').write_bytes(data[: int(len(data) * 0.6)]); full.unlink(); TRUTH.pop('gates/_full.wav')
    TRUTH['gates/truncated.wav'] = {'expect_gates': ['G4']}
    write('gates/digital_silence.wav', np.zeros(48000 * 10), 48000, expect_gates=['G5'])
    write('gates/too_short.wav', clean[:2400], 48000, expect_gates=['G6'])

    # --- signal defects (all 48 kHz unless stated) ---
    write('defects/clipped.wav', np.clip(clean * 8, -1, 1), 48000, expect_gates=[], clipped=True)
    write('defects/hum_50hz.wav', clean + sum(0.01 / h * np.sin(2 * np.pi * 50 * h * np.arange(len(clean)) / 48000) for h in (1, 2, 3)),
          48000, expect_gates=[], hum_hz=50)
    write('defects/hum_60hz.wav', clean + sum(0.01 / h * np.sin(2 * np.pi * 60 * h * np.arange(len(clean)) / 48000) for h in (1, 2, 3)),
          48000, expect_gates=[], hum_hz=60)
    write('defects/dc_offset.wav', clean * 0.8 + 0.05, 48000, expect_gates=[], dc_offset=True)
    d = clean.copy()
    loud = np.flatnonzero(np.sqrt(np.convolve(d ** 2, np.ones(4800) / 4800, 'same')) > 0.05)
    for pos in RNG.choice(loud, 10, replace=False):
        d[pos:pos + 1440] = 0
    write('defects/dropouts.wav', d, 48000, expect_gates=[], dropouts=10)
    write('defects/silence_padded.wav', np.r_[np.zeros(48000 * 8), clean, np.zeros(48000 * 8)], 48000,
          expect_gates=[], leading_silence_s=8, trailing_silence_s=8)
    a16 = norm(mix_snr(a, white(len(a)), 35))
    write('defects/fake_hires_from16k.wav', up(a16, 16000, 48000), 48000, expect_gates=[], spectral='upsampled_from_16000hz')
    a22 = norm(mix_snr(up(a, 16000, 22050), white(len(up(a, 16000, 22050))), 35))
    write('defects/fake_hires_from22k.wav', up(a22, 22050, 44100), 44100, expect_gates=[], spectral='upsampled_from_22050hz')
    write('defects/_tmp.wav', clean, 48000); TRUTH.pop('defects/_tmp.wav')
    ffmpeg('-i', OUT / 'defects/_tmp.wav', '-b:a', '128k', OUT / 'defects/_tmp.mp3')
    ffmpeg('-i', OUT / 'defects/_tmp.mp3', '-acodec', 'pcm_s16le', '-ar', '48000', OUT / 'defects/mp3_in_wav.wav')
    TRUTH['defects/mp3_in_wav.wav'] = {'expect_gates': [], 'spectral': 'lossy_origin_suspected'}
    (OUT / 'defects/_tmp.wav').unlink(); (OUT / 'defects/_tmp.mp3').unlink()
    q16 = np.round(clean * 32767) / 32768
    write('defects/fake_24bit.wav', q16, 48000, subtype='PCM_24', expect_gates=[], bit_depth=16, bit_depth_padded=True)
    write('defects/real_24bit.wav', clean + 1e-6 * white(len(clean)), 48000, subtype='PCM_24', expect_gates=[], bit_depth=24, bit_depth_padded=False)
    write('defects/dual_mono.wav', np.c_[clean, clean], 48000, expect_gates=[], stereo='dual_mono')
    write('defects/phase_inverted.wav', np.c_[clean, -clean], 48000, expect_gates=[], stereo='phase_inverted')
    write('defects/dead_channel.wav', np.c_[clean, np.zeros_like(clean)], 48000, expect_gates=[], stereo='dead_channel')
    ffmpeg('-i', OUT / 'quality/clean_48k.wav', '-ar', '8000', '-acodec', 'pcm_mulaw', OUT / 'routes/telephony_8k.wav')
    TRUTH['routes/telephony_8k.wav'] = {'expect_gates': [], 'route': 'R04'}
    ffmpeg('-i', OUT / 'quality/clean_48k.wav', '-b:a', '192k', OUT / 'routes/podcast.mp3')
    TRUTH['routes/podcast.mp3'] = {'expect_gates': [], 'route': 'R03', 'content': 'speech'}
    shutil.copy(OUT / 'quality/clean_48k.wav', OUT / 'defects/wav_named_mp3.mp3')
    TRUTH['defects/wav_named_mp3.mp3'] = {'expect_gates': [], 'extension_matches': False}

    # --- routes / content ---
    write('routes/music_pads.wav', music(30), 48000, expect_gates=[], content='music', route='R08')
    amb = pink(48000 * 30) * 0.05
    amb[RNG.integers(0, len(amb), 3000)] += RNG.uniform(-0.3, 0.3, 3000)
    write('routes/ambient_rain.wav', amb, 48000, expect_gates=[], content='noise_or_ambient', route='R09')
    write('routes/near_silent_room.wav', 10 ** (-70 / 20) * white(48000 * 20), 48000, expect_gates=[], route='R02')
    ca, cb = up(norm(a), 16000, 48000), up(norm(b), 16000, 48000)
    n = len(ca) + len(cb) + 48000
    left, right = np.zeros(n), np.zeros(n)
    left[: len(ca)] = ca
    right[len(ca) + 24000: len(ca) + 24000 + len(cb)] = cb
    floor = 10 ** (-60 / 20)
    write('routes/duplex_call.wav', np.c_[left + floor * white(n), right + floor * white(n)], 48000,
          expect_gates=[], stereo='independent_channels', route='R05')
    mixed = np.r_[music(10), clean[: 48000 * 10], music(10)]
    write('routes/mixed_music_speech.wav', mixed, 48000, expect_gates=[], content='mixed', route='R10')

    # --- bundle (ACN-style) ---
    voc = np.zeros(n); voc[: len(ca)] += ca; voc[len(ca) + 24000: len(ca) + 24000 + len(cb)] += cb
    acc = music(n / 48000)[:n] * 0.3
    write('bundle_001/source.wav', norm(voc + acc + floor * white(n)), 48000, expect_gates=[], route='R07', bundle_role='source')
    write('bundle_001/stems/vocals.wav', voc + floor * white(n), 48000, expect_gates=[], route='R07', bundle_role='vocals')
    write('bundle_001/stems/accompaniment.wav', acc, 48000, expect_gates=[], route='R07', bundle_role='accompaniment')
    write('bundle_001/speakers/speaker-000.wav', left + floor * white(n), 48000, expect_gates=[], route='R07', bundle_role='speaker')
    write('bundle_001/speakers/speaker-001.wav', right + floor * white(n), 48000, expect_gates=[], route='R07', bundle_role='speaker')
    write('bundle_001/speakers/speaker-002.wav', np.zeros(n), 48000, expect_gates=['G5'], bundle_role='speaker')
    (OUT / 'bundle_001/metadata.json').write_text(json.dumps(
        {'sample_id': 'bundle_001', 'speakers': 3, 'language': 'en_US', 'sample_rate': 48000, 'snr_db': 18.0, 'domain': 'podcast'}, indent=2))

    # --- duplicates / near-duplicates ---
    write('dups/original.wav', clean, 48000, dup_group='g1')
    shutil.copy(OUT / 'dups/original.wav', OUT / 'dups/exact_copy.wav'); TRUTH['dups/exact_copy.wav'] = {'dup_group': 'g1', 'dup_kind': 'exact'}
    ffmpeg('-i', OUT / 'dups/original.wav', OUT / 'dups/as_flac.flac'); TRUTH['dups/as_flac.flac'] = {'dup_group': 'g1', 'dup_kind': 'same_audio'}
    write('dups/quieter_6db.wav', clean * 0.5, 48000, dup_group='g1', dup_kind='duplicate')
    ffmpeg('-i', OUT / 'dups/original.wav', '-b:a', '96k', OUT / 'dups/reencoded_96k.mp3')
    TRUTH['dups/reencoded_96k.mp3'] = {'dup_group': 'g1', 'dup_kind': 'duplicate'}
    write('dups/clip_8s.wav', clean[48000 * 6: 48000 * 14], 48000, dup_group='g1', dup_kind='containment')
    ivr = up(norm(base[(1, 3)]), 16000, 48000)
    other1 = up(norm(sp[(0, 2)]), 16000, 48000)
    other2 = up(norm(sp[(1, 2)]), 16000, 48000)
    long1 = np.r_[other1, up(norm(sp[(0, 1)]), 16000, 48000), up(norm(sp[(0, 0)]), 16000, 48000)]
    long2 = np.r_[other2, up(norm(sp[(1, 0)]), 16000, 48000), up(norm(sp[(1, 1)]), 16000, 48000)]
    write('dups/call_A_with_ivr.wav', np.r_[ivr, long1], 48000, dup_group='ivr', dup_kind='shared_segment')
    write('dups/call_B_with_ivr.wav', np.r_[ivr, long2], 48000, dup_group='ivr', dup_kind='shared_segment')
    write('dups/unrelated.wav', up(norm(sp[(1, 0)]), 16000, 48000), 48000, dup_group='none')

    # --- wave 2/3: PII speech, two-speaker turns, a tempo track ---
    for ti, t in PII_TRUTH.items():
        x = norm(mix_snr(base[(ti % 2, ti)], white(len(base[(ti % 2, ti)])), 30))
        write(f'pii/{t["domain"]}_pii.wav', up(x, 16000, 48000), 48000, expect_gates=[], content='speech',
              transcript=TEXTS[ti], pii_entities=t['entities'], pii_words=t['words'], ai_generated=True, language='en')
    turns, parts, clock = [], [], 0.0
    for spk, (vi, ti) in (('A', (0, 0)), ('B', (1, 1)), ('A', (0, 2)), ('B', (1, 2))):
        seg = norm(base[(vi, ti)])
        parts += [seg, np.zeros(8000)]
        turns.append([spk, round(clock, 2), round(clock + len(seg) / 16000, 2)])
        clock += (len(seg) + 8000) / 16000
    conv = np.concatenate(parts)
    write('speakers/two_speaker_mono.wav', norm(mix_snr(conv, white(len(conv)), 30)), 16000, expect_gates=[],
          content='speech', speaker_turns=turns, speakers=2, ai_generated=True, language='en')
    t = np.arange(48000 * 20) / 48000
    kick = np.zeros_like(t)
    for beat in np.arange(0, 20, 0.5):  # 120 BPM
        i = int(beat * 48000)
        n = min(4800, len(t) - i)
        kick[i:i + n] += np.sin(2 * np.pi * 60 * np.arange(n) / 48000) * np.exp(-np.arange(n) / 900)
    write('music/beat_120bpm.wav', norm(0.6 * kick + 0.4 * music(20)), 48000, expect_gates=[], content='music', tempo_bpm=120)

    shutil.rmtree(RAW)
    (OUT / 'truth.json').write_text(json.dumps(TRUTH, indent=2))
    print(f'{len(TRUTH)} fixtures written to {OUT}')


if __name__ == '__main__':
    sys.exit(main())
