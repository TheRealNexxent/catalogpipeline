"""Probe and decode an audio file exactly once.

Every later step reads from the context built here. Nothing else opens the file.
Samples are decoded as 32-bit integers so effective bit depth can be measured,
then converted to float32 in [-1, 1).
"""
from __future__ import annotations
import hashlib, json, shutil, subprocess
from pathlib import Path
import numpy as np
from scipy.signal import resample_poly

STEP_VERSION = 'decode-v1'
ANALYSIS_RATE = 16000


def _ffprobe(path):
    if not shutil.which('ffprobe'):
        return None, 'ffprobe is not installed'
    p = subprocess.run(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)],
                       capture_output=True, text=True, timeout=60)
    if p.returncode:
        return None, p.stderr.strip()[:300] or 'ffprobe failed'
    return json.loads(p.stdout or '{}'), None


def _sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def _wav_declared_duration(path):
    """Duration the RIFF header promises (data chunk size), independent of the bytes actually present."""
    with open(path, 'rb') as f:
        if f.read(4) != b'RIFF':
            return None
        f.seek(12)
        fmt = None
        while True:
            head = f.read(8)
            if len(head) < 8:
                return None
            cid, size = head[:4], int.from_bytes(head[4:], 'little')
            if cid == b'fmt ':
                body = f.read(size)
                fmt = (int.from_bytes(body[4:8], 'little'), int.from_bytes(body[12:14], 'little'))
                f.seek(size % 2, 1)
            elif cid == b'data':
                if not fmt or size in (0, 0xFFFFFFFF) or not fmt[1]:
                    return None
                return size / fmt[1] / fmt[0]
            else:
                f.seek(size + size % 2, 1)


def probe(ctx, params=None):
    """Layer 1 header facts (M101, M104-M111)."""
    path = Path(ctx['path'])
    ctx['size_bytes'] = path.stat().st_size
    ctx['sha256'] = _sha256(path) if ctx['size_bytes'] else None
    with open(path, 'rb') as f:
        head = f.read(12)
    ctx['magic'] = ('wav' if head[:4] == b'RIFF' and head[8:12] == b'WAVE' else
                    'flac' if head[:4] == b'fLaC' else
                    'mp3' if head[:3] == b'ID3' or head[:2] in (b'\xff\xfb', b'\xff\xf3', b'\xff\xf2') else
                    'ogg' if head[:4] == b'OggS' else
                    'mp4' if head[4:8] == b'ftyp' else 'unknown')
    ext = path.suffix.lower().lstrip('.')
    ctx['extension_matches'] = ctx['magic'] == 'unknown' or ext == ctx['magic'] or (ext in ('m4a', 'aac') and ctx['magic'] == 'mp4')
    info, err = _ffprobe(path) if ctx['size_bytes'] else (None, 'empty file')
    ctx['probe_error'] = err
    audio = [s for s in (info or {}).get('streams', []) if s.get('codec_type') == 'audio']
    ctx['audio_streams'] = len(audio)
    if audio:
        s, fmt = audio[0], info.get('format', {})
        bits = s.get('bits_per_raw_sample') or s.get('bits_per_sample') or 0
        ctx.update(
            container=fmt.get('format_name'), codec=s.get('codec_name'),
            lossless=s.get('codec_name', '').startswith(('pcm_s', 'pcm_f', 'flac', 'alac', 'wavpack')),
            bitrate_kbps=round(int(fmt.get('bit_rate') or s.get('bit_rate') or 0) / 1000, 1),
            sample_rate=int(s.get('sample_rate') or 0), channels=int(s.get('channels') or 0),
            channel_layout=s.get('channel_layout'), declared_bit_depth=int(bits) or None,
            header_duration_s=float(s.get('duration') or fmt.get('duration') or 0) or None,
            tags={**fmt.get('tags', {}), **s.get('tags', {})})
        if ctx['magic'] == 'wav':
            ctx['header_duration_s'] = _wav_declared_duration(path) or ctx['header_duration_s']
    return {k: ctx.get(k) for k in ('size_bytes', 'sha256', 'magic', 'extension_matches', 'audio_streams', 'codec',
                                    'lossless', 'bitrate_kbps', 'sample_rate', 'channels', 'declared_bit_depth',
                                    'header_duration_s', 'probe_error')}


def full_decode(ctx, params=None):
    """Decode the whole file once (G3) and build the shared 16 kHz mono analysis copy."""
    if not ctx.get('audio_streams'):
        ctx['decode_ok'] = False
        return {'decode_ok': False}
    ch = ctx['channels'] or 1
    p = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(ctx['path']), '-map', '0:a:0',
                        '-f', 's32le', '-acodec', 'pcm_s32le', '-'], capture_output=True, timeout=3600)
    raw = p.stdout[: len(p.stdout) // (4 * ch) * 4 * ch]
    ints = np.frombuffer(raw, dtype='<i4').reshape(-1, ch)
    ctx['decode_errors'] = p.stderr.decode(errors='replace').strip()[:500]
    ctx['decode_ok'] = p.returncode == 0 and not ctx['decode_errors'] and len(ints) > 0
    ctx['ints'] = ints
    ctx['x'] = ints.astype(np.float32) / 2**31
    ctx['decoded_duration_s'] = len(ints) / ctx['sample_rate'] if ctx['sample_rate'] else 0
    ctx['pcm_sha256'] = hashlib.sha256(raw).hexdigest() if len(raw) else None
    x = ctx['x']
    head = x[:480000]
    if x.shape[1] == 2 and len(x) and head.std(axis=0).min() > 0 and np.corrcoef(head[:, 0], head[:, 1])[0, 1] < -0.5:
        mono = x[:, 0]  # a phase-inverted pair would cancel to silence in a plain average
    else:
        mono = x.mean(axis=1) if len(x) else np.zeros(0, np.float32)
    ctx['mono'] = mono  # phase-safe native-rate mono, shared by every model
    sr = ctx['sample_rate'] or ANALYSIS_RATE
    g = np.gcd(sr, ANALYSIS_RATE)
    ctx['x16'] = resample_poly(mono, ANALYSIS_RATE // g, sr // g).astype(np.float32) if len(mono) else mono
    return {'decode_ok': ctx['decode_ok'], 'decoded_duration_s': round(ctx['decoded_duration_s'], 3),
            'pcm_sha256': ctx['pcm_sha256'], 'decode_errors': ctx['decode_errors'] or None}
