# Independent cycle-level model of the RP2350 PIO running the PiDG pulse program.
# Semantics from RP2350 datasheet ch.11:
#  11.2.2 one instr/cycle unless stalled; 11.4.2.2 JMP X-- cond on X before dec, dec unconditional;
#  11.4.7 PULL block stalls on empty TX FIFO; 11.5.2 PC update: JMP-taken > wrap > +1;
#  11.5.6 SET writes the PIO output-level register (modelled visible from next cycle).
M32 = 0xFFFFFFFF
# --- encoders mirroring pico-sdk pio_instructions.h ---
def enc(bits, a1, a2): return bits | (a1 << 5) | (a2 & 0x1f)
PULL, MOV, SET, JMP = 0x8080, 0xa000, 0xe000, 0x0000
pins, X, Y, ISR, OSR = 0, 1, 2, 6, 7
def pull(ifempty, block): return enc(PULL, (2 if ifempty else 0) | (1 if block else 0), 0)
def mov(d, s): return enc(MOV, d & 7, s & 7)
def setp(v): return enc(SET, pins, v)
def jmp_xdec(a): return enc(JMP, 2, a)
PROG = [pull(False, True), mov(ISR, OSR), pull(False, True), mov(Y, OSR), pull(False, True),
        mov(X, ISR), jmp_xdec(6), setp(1), mov(X, Y), jmp_xdec(9), setp(0), mov(X, OSR), jmp_xdec(12)]
WRAP_T, WRAP = 5, 12
# COMBINE mode: the same program with the rising edge as SET PINS,3 (two consecutive pins)
PROG_DUAL = PROG[:7] + [setp(3)] + PROG[8:]

def load(offset, prog=None):
    mem = [None] * 32
    for i, w in enumerate(prog or PROG):
        mem[offset + i] = w + offset if (w & 0xe000) == 0 else w  # pio.c add_program_at_offset
    return mem

class SM:
    def __init__(self, mem, offset, words):
        self.mem = mem; self.pc = offset  # pio_sm_init execs jmp offset
        self.fifo = list(words); self.x = self.y = 0; self.isr = 0; self.osr = 0
        self.wb, self.wt = offset + WRAP_T, offset + WRAP
        self.pin = 0; self.edges = []  # (cycle_visible, level)
        self.writes = []  # every SET: (cycle_visible, full 5-bit value)
    def step(self, cyc, fast=True, horizon=None):
        """Execute starting at cycle cyc; returns number of cycles consumed."""
        w = self.mem[self.pc]; major = w & 0xe000
        assert ((w >> 8) & 0x1f) == 0  # no delay / sideset bits
        jumped = False; n = 1
        if major == 0:  # JMP
            cond = (w >> 5) & 7; addr = w & 0x1f
            assert cond == 2
            if fast and addr == self.pc and self.x > 0:
                # X-- self-loop: X taken iterations then one fallthrough; take all but the last here
                k = self.x
                if horizon is not None: k = min(k, max(1, horizon - cyc))
                self.x -= k; return k
            c = self.x != 0; self.x = (self.x - 1) & M32
            if c: self.pc = addr; jumped = True
        elif (w & 0xe080) == 0x8080:  # PULL
            blk = (w >> 5) & 1
            if not self.fifo:
                assert blk; return 1  # stall, PC unchanged
            self.osr = self.fifo.pop(0)
        elif major == 0xa000:
            d, op, s = (w >> 5) & 7, (w >> 3) & 3, w & 7
            assert op == 0
            v = {X: self.x, Y: self.y, ISR: self.isr, OSR: self.osr}[s]
            if d == X: self.x = v
            elif d == Y: self.y = v
            elif d == ISR: self.isr = v
            else: raise Exception
        elif major == 0xe000:
            d, v = (w >> 5) & 7, w & 0x1f
            assert d == pins
            self.writes.append((cyc + 1, v))
            v &= 1
            if v != self.pin: self.pin = v; self.edges.append((cyc + 1, v))
        else: raise Exception(hex(w))
        if not jumped:
            self.pc = self.wb if self.pc == self.wt else (self.pc + 1) & 31
        return n

def run(words, until, offset=19, fast=True):
    mem = load(offset); sm = SM(mem, offset, words); c = 0
    while c < until:
        c += sm.step(c, fast, until)
    return sm.edges

def run_writes(words, until, prog=None, offset=19, fast=True):
    """Every SET PINS write of one state machine: [(cycle_visible, value)]."""
    mem = load(offset, prog); sm = SM(mem, offset, words); c = 0
    while c < until:
        c += sm.step(c, fast, until)
    return sm.writes

def block_pins(sm_writes, npins):
    """PIO output-level latch shared by several SMs writing the same pin range
    (datasheet 11.5.6: last write wins; same cycle -> highest-numbered SM wins).
    sm_writes: list indexed by SM number of [(cycle, value)]. Returns per-pin edges."""
    ev = sorted((c, sm, v) for sm, ws in enumerate(sm_writes) for c, v in ws)
    level = [0] * npins; edges = [[] for _ in range(npins)]
    i = 0
    while i < len(ev):
        c = ev[i][0]; j = i
        while j < len(ev) and ev[j][0] == c: j += 1
        v = max(ev[i:j], key=lambda e: e[1])[2]  # highest SM this cycle
        for b in range(npins):
            nb = (v >> b) & 1
            if nb != level[b]: level[b] = nb; edges[b].append((c, nb))
        i = j
    return edges

def rises(edges): return [c for c, v in edges if v == 1]
def falls(edges): return [c for c, v in edges if v == 0]

# --- the proposed fixed math (independent Python rendering of pulse_timing.h computePulseCounts) ---
def fixed_words(P, D, W):
    if W < 3: return None
    used = D + (W - 3) + 8
    if used > P: return None
    return (D, W - 3, P - used)

def current_words(P, D, W):
    dl = D - 2 if D >= 2 else 0
    wl = W - 3 if W >= 3 else 0
    used = dl + wl + 8
    if P <= used: return None
    return (dl, wl, P - used)
