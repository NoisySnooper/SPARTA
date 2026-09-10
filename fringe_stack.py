"""
fringe_stack.py -- forward thin-film model: predicted Fourier lines for the cell.

Vendored from `defringe_dac.py` (DAC Absorption Fringe Analysis).
    Source module : defringe_dac.py
    Author        : Matthew R. Diamond
    Repository    : github.com/matthewrdiamond/DAC-Absorption-Fringe-Analysis
    License       : vendored under MIT by permission of the author.
    Upstream snapshot: commit 7988300 (2026-08-03)

Deliberate deviations from that snapshot, kept on purpose (hardening; every
other difference is a bug): drift #4 per-window rejection instead of hot-path
asserts, #8 point-count / finiteness gate on detection, #9 Fisher p-value
overflow guard, #10 the 20-point floor extended to the full and wide tiers,
#13 ValueError on a zero or negative notch half-width.

Contents (source line refs are into defringe_dac.py):
    matsym / matplain        (:8669/:8676)  mathtext and plain n-symbols
    thinfilm_sample_lines    (:8681)  6 Fourier lines for the 5-layer stack
    thinfilm_medium_lines    (:8744)  single line for the anvil|medium|anvil etalon
    merge_lines              (:8766)  merge coincident optical paths, signed coeffs

The stack is  anvil | layer2(d1) | sample(t) | layer2(d2) | anvil, with the
cascaded Fresnel amplitudes I1..I4 giving each interface pair's contrast.

SPARTA adaptations: pure functions, no matplotlib import (the returned
'formula' strings are mathtext source, rendered by the caller), no printing,
input validation, Python 3.8 compatible.
"""

import numpy as np


def matsym(name):
    r"""mathtext 'n_{\mathrm{<name>}}' with a sanitised, upright subscript so a
    material name (e.g. 'Ar', 'KCl') renders as a real subscript on n."""
    safe = ''.join(ch for ch in str(name) if ch.isalnum() or ch in '()+-/')
    return r'n_{\mathrm{' + (safe or 'x') + r'}}'


def matplain(name):
    """Plain-text 'n_<name>' for CSV / non-mathtext contexts."""
    return 'n_' + (str(name).strip() or 'x')


def _require(p, keys, who):
    """SPARTA addition: name the missing stack key instead of raising KeyError
    from the middle of the Fresnel algebra."""
    missing = [k for k in keys if k not in p]
    if missing:
        raise KeyError("%s: stack dict missing %s" % (who, ', '.join(missing)))
    for k in ('n_diamond', 'n_layer2', 'n_sample', 'n_medium'):
        if k in p and not (float(p[k]) > 0):
            raise ValueError("%s: %s must be > 0 (got %r)" % (who, k, p[k]))


def thinfilm_sample_lines(p):
    """Predicted Fourier-space lines for anvil|layer2(d1)|sample(t)|layer2(d2)|anvil.

    Returns a list of dicts {id, desc, formula, plain, nt, coeff} for the six
    interface pairs. nt is the optical path n*t (um); coeff = 2*s*sqrt(Ii*Ij) carries
    the Fresnel sign (pairs odd in rho2 -- 12,13,24,34 -- flip when n_s>n_layer2).
    'formula' is a mathtext string built from the material names; 'plain' is its CSV form."""
    _require(p, ('n_diamond', 'n_layer2', 'n_sample', 'd1_um', 't_um', 'd2_um'),
             'thinfilm_sample_lines')
    n_dia, n_layer2, n_s = p['n_diamond'], p['n_layer2'], p['n_sample']
    d1, t, d2 = p['d1_um'], p['t_um'], p['d2_um']          # um
    M = p.get('layer2_name', 'layer2')
    S = p.get('sample_name', 'sample')
    R_dm = ((n_dia - n_layer2) / (n_dia + n_layer2)) ** 2
    R_ms = ((n_layer2 - n_s) / (n_layer2 + n_s)) ** 2
    I1 = R_dm
    I2 = (1.0 - R_dm) ** 2 * R_ms
    I3 = (1.0 - R_dm) ** 2 * (1.0 - R_ms) ** 2 * R_ms
    I4 = (1.0 - R_dm) ** 2 * (1.0 - R_ms) ** 4 * R_dm
    f = 1.0 if n_s < n_layer2 else -1.0        # rho2-odd pairs flip when n_s>n_layer2
    a = n_layer2 * d1        # interface 1<->2 round trip (um)
    b = n_s * t              # interface 2<->3
    c = n_layer2 * d2        # interface 3<->4
    nm, ns = matsym(M), matsym(S)       # mathtext n-symbols
    pm, ps = matplain(M), matplain(S)   # plain n-symbols (CSV)

    def co(s, Ii, Ij):
        return 2.0 * s * np.sqrt(Ii * Ij)

    # Only thicknesses that are actually present get a term in the label: with
    # d1=0 the '13' pair reads '$n_s t$', not '$n_{L2} d_1 + n_s t$'.
    terms = {'d1': (d1, '%sd_1' % nm, '%s*d1' % pm),
             't':  (t,  '%st' % ns,   '%s*t' % ps),
             'd2': (d2, '%sd_2' % nm, '%s*d2' % pm)}

    def lab(*keys):
        kept = [terms[k] for k in keys if terms[k][0] != 0.0]
        if not kept:
            return '', ''            # zero optical path: stem still drawn, but unlabelled
        return ('$' + '+'.join(k[1] for k in kept) + '$',
                '+'.join(k[2] for k in kept))

    f12, p12 = lab('d1')
    f23, p23 = lab('t')
    f34, p34 = lab('d2')
    f13, p13 = lab('d1', 't')
    f24, p24 = lab('t', 'd2')
    f14, p14 = lab('d1', 't', 'd2')

    return [
        dict(id='12', desc='lower layer2',  formula=f12,
             plain=p12,                          nt=a,         coeff=co(+f,   I1, I2)),
        dict(id='23', desc='sample',        formula=f23,
             plain=p23,                          nt=b,         coeff=co(-1.0, I2, I3)),
        dict(id='34', desc='upper layer2',  formula=f34,
             plain=p34,                          nt=c,         coeff=co(+f,   I3, I4)),
        dict(id='13', desc='layer2+sample', formula=f13,
             plain=p13,                          nt=a + b,     coeff=co(-f,   I1, I3)),
        dict(id='24', desc='sample+layer2', formula=f24,
             plain=p24,                          nt=b + c,     coeff=co(-f,   I2, I4)),
        dict(id='14', desc='whole cell',    formula=f14,
             plain=p14,                          nt=a + b + c, coeff=co(-1.0, I1, I4)),
    ]


def thinfilm_medium_lines(p):
    """Predicted line for the anvil|medium(L)|anvil etalon (no sample), L=d1+t+d2,
    index n_medium: a single tone at n_medium*L with coeff -2*R."""
    _require(p, ('n_diamond', 'n_medium', 'd1_um', 't_um', 'd2_um'),
             'thinfilm_medium_lines')
    n_dia, n_medium = p['n_diamond'], p['n_medium']
    L = p['d1_um'] + p['t_um'] + p['d2_um']
    B = p.get('medium_name', 'medium')
    R = ((n_dia - n_medium) / (n_dia + n_medium)) ** 2
    # Drop zero thicknesses from the label, and skip the parentheses if only one survives.
    kept = [(m, pl) for v, m, pl in ((p['d1_um'], 'd_1', 'd1'), (p['t_um'], 't', 't'),
                                     (p['d2_um'], 'd_2', 'd2')) if v != 0.0]
    if not kept:
        return [dict(id='12', desc='etalon', formula='', plain='',   # unlabelled stem at n*t=0
                     nt=n_medium * L, coeff=-2.0 * R)]
    if len(kept) == 1:
        sumtex, sumplain = kept[0][0], kept[0][1]
    else:
        sumtex = '(' + '+'.join(k[0] for k in kept) + ')'
        sumplain = '(' + '+'.join(k[1] for k in kept) + ')'
    return [dict(id='12', desc='etalon',
                 formula='$%s%s$' % (matsym(B), sumtex),
                 plain='%s*%s' % (matplain(B), sumplain),
                 nt=n_medium * L, coeff=-2.0 * R)]


def merge_lines(lines, tol_um=1e-6):
    """Merge tones at coincident optical paths (e.g. d1=0 collapses 13->23 and
    14->24): sum the SIGNED coeffs, take |sum| as the magnitude, and keep the
    most-complete constituent's formula. Returns dicts {ids, desc, formula, plain,
    nt, coeff, mag} sorted by optical path."""
    merged = []
    for ln in sorted(lines, key=lambda x: x['nt']):
        if merged and abs(ln['nt'] - merged[-1]['nt']) <= tol_um:
            prev = merged[-1]
            prev['ids'].append(ln['id'])
            prev['coeff'] += ln['coeff']
            if len(ln['plain']) > len(prev['plain']):      # prefer the fuller path
                prev['formula'] = ln['formula']
                prev['plain'] = ln['plain']
                prev['desc'] = ln['desc']
        else:
            merged.append(dict(ids=[ln['id']], desc=ln['desc'], formula=ln['formula'],
                               plain=ln['plain'], nt=ln['nt'], coeff=ln['coeff']))
    for m in merged:
        m['mag'] = abs(m['coeff'])
    return merged


def stack_lines(p, kind='sample', tol_um=1e-6):
    """Convenience: the merged forward lines for one channel.

    `kind` is 'sample' (the 5-layer stack) or 'medium' (the bare etalon).
    SPARTA helper -- the source calls the two builders and `_merge_lines`
    separately at every draw site.
    """
    if kind == 'sample':
        lines = thinfilm_sample_lines(p)
    elif kind == 'medium':
        lines = thinfilm_medium_lines(p)
    else:
        raise ValueError("stack_lines: kind must be 'sample' or 'medium' (got %r)"
                         % (kind,))
    return merge_lines(lines, tol_um=tol_um)


__all__ = ['matsym', 'matplain', 'thinfilm_sample_lines', 'thinfilm_medium_lines',
           'merge_lines', 'stack_lines']
