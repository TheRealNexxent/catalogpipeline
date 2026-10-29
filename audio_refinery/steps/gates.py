"""Hard gates G1-G6 from Baseline.md section 3. A failed gate stops the preset."""
from __future__ import annotations
import numpy as np

STEP_VERSION = 'gates-v1'


def basic(ctx, params=None):
    failed = []
    if not ctx.get('size_bytes'):
        failed.append(('G1', 'This file contains zero bytes.'))
    elif not ctx.get('audio_streams'):
        failed.append(('G2', 'No audio stream found. ' + (ctx.get('probe_error') or '')))
    else:
        header, decoded = ctx.get('header_duration_s'), ctx.get('decoded_duration_s', 0)
        truncated = bool(header and decoded < header * 0.98 and header - decoded > (1.0 if header < 50 else 0))
        if truncated:
            # Checked before G3: a cut-off file usually also raises decoder errors, but G4 is the
            # more useful verdict because the readable part can become a trimmed derivative (E13).
            failed.append(('G4', f'Only {decoded:.1f} s decoded from a nominal {header:.1f} s file.'))
        elif not ctx.get('decode_ok'):
            failed.append(('G3', 'The file could not be decoded cleanly: ' + (ctx.get('decode_errors') or 'no samples')))
        if len(ctx.get('ints', [])) and not np.any(ctx['ints']):
            failed.append(('G5', 'The file is entirely digital silence.'))
        if decoded < 0.1:
            failed.append(('G6', f'Too short ({decoded:.3f} s).'))
    ctx['gates_failed'] = [g for g, _ in failed]
    ctx['stop'] = bool(failed)
    return {'gates_failed': ctx['gates_failed'], 'gate_reasons': [r for _, r in failed]}
