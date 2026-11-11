"""Generate simple STEP models for the PocketBrain footprints that have none.

Usage: python make_models.py <output dir>      (needs CadQuery: pip install cadquery)

Model coordinates follow KiCad: origin at the footprint origin, X as in the footprint, Y = -footprint Y,
Z up from the board surface. Dimensions come from the same datasheets as the footprints.
"""
import math
import os
import sys

import cadquery as cq

BLACK = cq.Color(0.12, 0.12, 0.13)
DARK = cq.Color(0.25, 0.25, 0.27)
METAL = cq.Color(0.78, 0.78, 0.8)
TIN = cq.Color(0.85, 0.85, 0.85)
CREAM = cq.Color(0.92, 0.9, 0.82)
AMBER = cq.Color(0.85, 0.55, 0.12)
GREY = cq.Color(0.45, 0.45, 0.47)


def box(x0, x1, y0, y1, z0, z1):
    return cq.Workplane('XY').box(x1 - x0, y1 - y0, z1 - z0, centered=False).translate((x0, y0, z0))


def cyl(x, y, r, z0, z1):
    return cq.Workplane('XY').circle(r).extrude(z1 - z0).translate((x, y, z0))


def qfn(w, h, t, dot=(-1, 1)):
    """Leadless package body with a pin 1 dot (footprint pin 1 is top-left)."""
    body = box(-w / 2, w / 2, -h / 2, h / 2, 0.02, t).edges('|Z').fillet(0.05)
    d = cyl(dot[0] * (w / 2 - 0.4), dot[1] * (h / 2 - 0.4), 0.15, t - 0.03, t)
    a = cq.Assembly()
    a.add(body.cut(d), name='body', color=BLACK)
    a.add(box(-w / 2 + 0.1, w / 2 - 0.1, -h / 2 + 0.1, h / 2 - 0.1, 0, 0.02), name='pads', color=TIN)
    return a


def dla():
    return qfn(2.0, 3.0, 1.0)


def vqfn16():
    return qfn(3.0, 3.0, 0.9)


def tqfn16():
    return qfn(3.0, 3.0, 0.75)


def dfe252012():
    a = cq.Assembly()
    a.add(box(-0.65, 0.65, -1.0, 1.0, 0, 1.2), name='core', color=DARK)
    for i, s in enumerate((-1, 1)):
        a.add(box(min(s * 0.65, s * 1.25), max(s * 0.65, s * 1.25), -1.0, 1.0, 0, 1.2), name='t%d' % i, color=TIN)
    return a


def nr3015():
    a = cq.Assembly()
    a.add(box(-1.5, 1.5, -1.5, 1.5, 0.05, 1.5).edges('|Z').chamfer(0.5), name='core', color=DARK)
    for i, s in enumerate((-1, 1)):
        a.add(box(min(s * 0.9, s * 1.5), max(s * 0.9, s * 1.5), -1.0, 1.0, 0, 0.3), name='t%d' % i, color=TIN)
    return a


def ts1101vs():
    """Footprint: body x +-3.5, y -1.0..1.3, actuator towards -Y; here Y is negated."""
    a = cq.Assembly()
    a.add(box(-3.5, 3.5, -1.3, 1.0, 0, 3.45), name='cover', color=METAL)
    a.add(box(-1.5, 1.5, 1.0, 2.0, 0.85, 2.35).edges('|Y').fillet(0.2), name='actuator', color=BLACK)
    for i, s in enumerate((-1, 1)):
        a.add(box(min(s * 3.5, s * 3.9), max(s * 3.5, s * 3.9), -0.3, 1.0, 0, 2.0), name='leg%d' % i, color=METAL)
        a.add(cyl(s * 1.15, 0, 0.375, -0.75, 0), name='peg%d' % i, color=BLACK)
        a.add(box(s * 2.1 - 0.3, s * 2.1 + 0.3, -1.5, -1.0, 0, 0.3), name='term%d' % i, color=TIN)
    return a


def siq02fvs3():
    """Footprint: dial centre at the origin, terminals at y = +7.7, dial overhangs towards -Y."""
    a = cq.Assembly()
    base = box(-5.15, 5.15, -7.25, 0, 0, 1.9)
    arch = cyl(0, 0, 4.2, 0, 1.9).intersect(box(-4.2, 4.2, 0, 3.85, 0, 1.9))
    a.add(base.union(arch), name='base', color=GREY)
    dial = cyl(0, 0, 7.25, 2.0, 4.0)
    for i in range(24):                         # knurling
        ang = math.radians(i * 15)
        dial = dial.cut(cyl(7.45 * math.cos(ang), 7.45 * math.sin(ang), 0.55, 2.0, 4.0))
    dial = dial.cut(cyl(0, 0, 3.6, 3.6, 4.0))
    a.add(dial, name='dial', color=BLACK)
    a.add(cyl(0, 0, 3.0, 1.9, 2.0), name='hub', color=BLACK)
    for i, s in enumerate((-1, 1)):
        a.add(cyl(s * 3.0, -4.5, 0.775, -1.0, 0), name='boss%d' % i, color=GREY)
    for i, x in enumerate((-4.0, -1.475, 1.475, 4.0)):
        a.add(box(x - 0.5, x + 0.5, -8.0, -7.0, 0, 0.3), name='term%d' % i, color=TIN)
    return a


def jt_thermistor():
    """Leads through the pads, film bent over and running along footprint +Y (model -Y), 4.6 mm up."""
    a = cq.Assembly()
    zf = 4.6
    for i, x in enumerate((-0.9, 0.9)):
        a.add(box(x - 0.25, x + 0.25, -0.085, 0.085, -2.0, zf), name='lead%d' % i, color=TIN)
    a.add(box(-1.8, 1.8, -25.0, 0.4, zf, zf + 0.3), name='film', color=AMBER)
    a.add(box(-1.0, 1.0, -24.5, -22.5, zf + 0.3, zf + 0.4), name='sensor', color=DARK)
    return a


def jst_ph_b2b_sm4():
    """Top-entry PH header. Footprint fab outline x +-2.95, y -4.3..0.8."""
    a = cq.Assembly()
    shell = box(-2.95, 2.95, -0.8, 4.3, 0, 5.0).cut(box(-2.35, 2.35, -0.2, 3.7, 1.2, 5.0))
    shell = shell.cut(box(-1.0, 1.0, 3.7, 4.3, 2.5, 5.0))          # latch slot
    a.add(shell, name='housing', color=CREAM)
    for i, x in enumerate((-1.0, 1.0)):
        a.add(box(x - 0.25, x + 0.25, 1.5, 2.0, 1.2, 4.4), name='pin%d' % i, color=TIN)
        a.add(box(x - 0.25, x + 0.25, -3.2, -0.8, 0, 0.2), name='tail%d' % i, color=TIN)
    for i, s in enumerate((-1, 1)):
        a.add(box(min(s * 2.95, s * 4.0), max(s * 2.95, s * 4.0), 0.4, 3.1, 0, 0.3), name='tab%d' % i, color=TIN)
    return a


MODELS = {
    'Texas_DLA0010A_VSON-HR-10_2x3mm_P0.5mm': dla,
    'L_Murata_DFE252012': dfe252012,
    'SW_XKB_TS-1101VS_SidePush': ts1101vs,
    'RotaryEncoder_Mitsumi_SIQ-02FVS3': siq02fvs3,
    'Thermistor_Semitec_JT_Leads_P1.8mm': jt_thermistor,
    'JST_PH_B2B-PH-SM4-TB_1x02-1MP_P2.00mm_Vertical': jst_ph_b2b_sm4,
    'L_Taiyo-Yuden_NR-30xx': nr3015,
    'VQFN-16-1EP_3x3mm_P0.5mm_EP1.6x1.6mm': vqfn16,
    'TQFN-16-1EP_3x3mm_P0.5mm_EP1.23x1.23mm': tqfn16,
}

if __name__ == '__main__':
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    for name, fn in MODELS.items():
        fn().save(os.path.join(out, name + '.step'))
        print('wrote', name)
