"""LTspice integration: locate the simulator, generate a SPICE netlist for
each topology, run it in batch mode and parse the ASCII .raw waveforms.

The generated netlists use ideal voltage-controlled switches (S) and ideal
diodes (D) driven by fixed duty-ratio pulse sources — i.e. an *open-loop
switching* transient, which reproduces the steady-state switching waveforms
(inductor/primary current, switch-node, output ripple).  The GUI schematic
shows the closed loop; the feedback loop is drawn but the LTspice run is a
fixed-duty transient for waveform inspection.
"""

import os
import subprocess
import numpy as np

TOPO_LLC = 'LLC'

LTSPICE_PATHS = [
    r'C:\Program Files\LTC\LTspiceXVII\XVIIx64.exe',
    r'C:\Program Files\ADI\LTspice\LTspice.exe',
    r'C:\Program Files\LTspice\LTspice.exe',
    r'C:\Program Files (x86)\LTC\LTspiceXVII\XVIIx86.exe',
    os.path.expandvars(r'%LOCALAPPDATA%\Programs\ADI\LTspice\LTspice.exe'),
]


def find_ltspice():
    """Return the LTspice executable path if installed, else None."""
    for p in LTSPICE_PATHS:
        if os.path.isfile(p):
            return p
    return None


def _fmt(x):
    return f'{x:.8g}'


def generate_netlist(p, op):
    """Build a SPICE netlist string for the given params + operating point."""
    topo = p['topology']
    Vin, Vout = p['V_in'], p['V_out']
    L, C = p['L'], p['C_out']
    Rc, ESL = p['Rc'], p.get('ESL', 0.0)
    R = op['R']
    T = op['Ts']
    D = op['D']
    Rds = p['Rds_on']
    Vf = p['Vf_diode']
    Rd = p['Rd_diode']
    Vgs = p['Vgs']

    hdr = [f'* {topo} switching simulation (fixed duty, open loop)',
           f'* Vin={Vin} Vout={Vout} fsw={1/T:.3g} D={D:.3f}',
           '.option plotwinsize=0', '']

    def cap_esr(n_hi, n_lo):
        """C with ESR (Rc) and ESL in series, from node to ground rail."""
        return [f'C1 {n_hi} nc {_fmt(C)}',
                f'Rc nc nr {_fmt(Rc)}' if Rc else None,
                f'L_ESL nr {n_lo} {_fmt(ESL)}' if ESL else None]

    if topo == 'BUCK':
        body = [
            f'Vin n_in 0 {_fmt(Vin)}',
            f'S1 n_in n_sw n_gate 0 SW',
            f'D1 0 n_sw D',
            f'L1 n_sw n_out {_fmt(L)}',
            f'Rload n_out 0 {_fmt(R)}',
            f'Vg n_gate 0 PULSE(0 {_fmt(Vgs)} 0 1n 1n {_fmt(D*T)} {_fmt(T)})',
            f'.model SW SW(Ron={_fmt(Rds)} Roff=1e7 Vt=2.5 Vh=0.1)',
            f'.model D D(Ron={_fmt(Rd)} Vfwd={_fmt(Vf)})',
        ]
        body += [x for x in cap_esr('n_out', '0') if x]
    elif topo == 'BOOST':
        body = [
            f'Vin n_in 0 {_fmt(Vin)}',
            f'L1 n_in n_sw {_fmt(L)}',
            f'S1 n_sw 0 n_gate 0 SW',
            f'D1 n_sw n_out D',
            f'Rload n_out 0 {_fmt(R)}',
            f'Vg n_gate 0 PULSE(0 {_fmt(Vgs)} 0 1n 1n {_fmt(D*T)} {_fmt(T)})',
            f'.model SW SW(Ron={_fmt(Rds)} Roff=1e7 Vt=2.5 Vh=0.1)',
            f'.model D D(Ron={_fmt(Rd)} Vfwd={_fmt(Vf)})',
        ]
        body += [x for x in cap_esr('n_out', '0') if x]
    elif topo == 'BUCK-BOOST':
        body = [
            f'Vin n_in 0 {_fmt(Vin)}',
            f'S1 n_in n_sw n_gate 0 SW',
            f'L1 n_sw 0 {_fmt(L)}',
            f'D1 0 n_out D',
            f'Rload n_out 0 {_fmt(R)}',
            f'Vg n_gate 0 PULSE(0 {_fmt(Vgs)} 0 1n 1n {_fmt(D*T)} {_fmt(T)})',
            f'.model SW SW(Ron={_fmt(Rds)} Roff=1e7 Vt=2.5 Vh=0.1)',
            f'.model D D(Ron={_fmt(Rd)} Vfwd={_fmt(Vf)})',
        ]
        body += [x for x in cap_esr('n_out', '0') if x]
    elif topo == 'FLYBACK':
        n = p['N']
        Lm = L
        Ls = Lm / n ** 2
        body = [
            f'Vin n_in 0 {_fmt(Vin)}',
            f'S1 n_in n_sw n_gate 0 SW',
            f'Lp n_sw 0 {_fmt(Lm)}',
            f'Ls n_s 0 {_fmt(Ls)}',
            f'K1 Lp Ls 0.999',
            f'D1 n_s n_out D',
            f'Rload n_out 0 {_fmt(R)}',
            f'Vg n_gate 0 PULSE(0 {_fmt(Vgs)} 0 1n 1n {_fmt(D*T)} {_fmt(T)})',
            f'.model SW SW(Ron={_fmt(Rds)} Roff=1e7 Vt=2.5 Vh=0.1)',
            f'.model D D(Ron={_fmt(Rd)} Vfwd={_fmt(Vf)})',
        ]
        body += [x for x in cap_esr('n_out', '0') if x]
    elif topo == TOPO_LLC:
        Lr, Cr, Lm = op['Lr'], op['Cr'], op['Lm']
        n = op['n']
        Ls = Lm / n ** 2
        half = T / 2
        body = [
            f'Vin n_in 0 {_fmt(Vin)}',
            f'S1 n_in n_a g1 0 SW', f'S4 n_a n_lo g4 0 SW',
            f'S2 n_in n_b g2 0 SW', f'S3 n_b n_lo g3 0 SW',
            f'Lr n_a n_r {_fmt(Lr)}',
            f'Cr n_r n_c {_fmt(Cr)}',
            f'Lp n_c 0 {_fmt(Lm)}',
            f'Ls1 n_s1 0 {_fmt(Ls)}', f'Ls2 n_s2 0 {_fmt(Ls)}',
            f'K1 Lp Ls1 Ls2 0.999',
            f'D1 n_s1 n_out D', f'D2 n_s2 n_out D',
            f'Rload n_out 0 {_fmt(R)}',
            f'Vg1 g1 0 PULSE(0 {_fmt(Vgs)} 0 1n 1n {_fmt(half)} {_fmt(T)})',
            f'Vg4 g4 0 PULSE(0 {_fmt(Vgs)} 0 1n 1n {_fmt(half)} {_fmt(T)})',
            f'Vg2 g2 0 PULSE(0 {_fmt(Vgs)} {_fmt(half)} 1n 1n {_fmt(half)} {_fmt(T)})',
            f'Vg3 g3 0 PULSE(0 {_fmt(Vgs)} {_fmt(half)} 1n 1n {_fmt(half)} {_fmt(T)})',
            f'.model SW SW(Ron={_fmt(Rds)} Roff=1e7 Vt=2.5 Vh=0.1)',
            f'.model D D(Ron={_fmt(Rd)} Vfwd={_fmt(Vf)})',
            f'Rlo n_lo 0 1m',
        ]
        body += [x for x in cap_esr('n_out', '0') if x]
    else:
        raise ValueError(f'no netlist for topology {topo!r}')

    tail = ['.tran 0 3m', '.end']
    return '\n'.join(hdr + body + tail) + '\n'


def run_ltspice(netlist_path, ltspice=None):
    """Run LTspice in batch mode; return the .raw path or None."""
    exe = ltspice or find_ltspice()
    if not exe or not os.path.isfile(exe):
        return None
    base, _ = os.path.splitext(netlist_path)
    raw = base + '.raw'
    if os.path.isfile(raw):
        os.remove(raw)
    subprocess.run([exe, '-b', '-ascii', netlist_path], check=False,
                   cwd=os.path.dirname(netlist_path) or '.',
                   capture_output=True, timeout=120)
    return raw if os.path.isfile(raw) else None


def parse_raw_ascii(raw_path):
    """Parse an LTspice ASCII .raw into dict(t=..., signals={name: array})."""
    with open(raw_path, 'r', errors='ignore') as f:
        lines = f.readlines()
    i = 0
    vars_, values_idx = [], None
    while i < len(lines):
        ln = lines[i].strip()
        if ln.startswith('Variables:'):
            i += 1
            while i < len(lines) and lines[i].strip().lower() != 'values:':
                parts = lines[i].split()
                if len(parts) >= 2:
                    vars_.append(parts[1])
                i += 1
            values_idx = i + 1
            break
        i += 1
    if values_idx is None:
        return None
    data = np.loadtxt(lines[values_idx:], ndmin=2)
    if data.size == 0:
        return None
    out = {'t': data[:, 0], 'signals': {}}
    for j, name in enumerate(vars_[1:]):
        if j + 1 < data.shape[1]:
            out['signals'][name] = data[:, j + 1]
    return out
