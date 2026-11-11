"""PocketBrain enclosure: parametric CadQuery model.

Usage:  python enclosure.py <board.step> <output dir>      (pip install cadquery)

    board.step is the board with its parts, exported with
        kicad-cli pcb export step --subst-models --no-dnp --user-origin 100x40mm pocketbrain.kicad_pcb

Writes STEP and STL for every printed part, pocketbrain-assembly.step with everything in place,
and prints an interference report.

Coordinates (the same as the board STEP): X to the right seen from the display side, board from
X = 0 to 43; Y up, board from Y = 0 (top, antenna end) to -100; Z towards the display. The back of the
PCB (parts side) is Z = 0, the display side is Z = 1.6.

Printed parts
    front shell   display bezel and the upper half of the walls; the PCB sits in it on four bosses
    back shell    lower half of the walls and the back; carries the wheel slot, Talk button, USB opening
    battery tray  0.8 mm plate on five legs that stand on the PCB; the cell lies on it
    talk button   plunger with a flange, captured in the back shell wall
"""
import os
import sys

import cadquery as cq

# ------------------------------------------------------------------ parameters (mm)
W, H, T = 43.0, 100.0, 1.6           # PCB
GAP = 0.5                            # PCB edge to inner wall
WALL = 2.0
R_IN, R_OUT = 2.5, 4.5               # corner radii of cavity and shell

GLASS = (0.57, -92.0, 42.43, -19.0)  # OLED glass x0, y0, x1, y1 (41.86 x 73)
GLASS_T, TAPE_T = 2.0, 0.35          # glass on foam tape on the PCB
WINDOW = (7.54, -87.21, 39.24, -24.79)   # active area plus 0.5 mm

PART_H = 4.0                         # tallest part under the cell (the wheel)
TRAY_GAP, TRAY_T = 0.3, 0.8
CELL = (1.5, -100.0, 36.5, -20.0)    # LP553580, 35 x 80, offset towards the Talk side
CELL_T, SWELL = 5.5, 0.5

LAP, LAP_T, FIT = 1.2, 1.0, 0.15     # lap joint between the shells

HOLES = [(40.5, -3.0), (2.5, -3.0), (40.5, -97.5), (2.5, -97.5)]   # PCB holes, 2.2 mm
SCREWS = HOLES[:3]                   # M2 x 8 self-tapping; the fourth hole only gets a locating peg
BOSS_R, PILOT_R, CLEAR_R, HEAD_R = 2.75, 0.85, 1.15, 2.2
HEAD_FLOOR = 3.0                     # plastic left under the screw head

WHEEL = (38.7, -36.0, 7.25)          # dial centre and radius; dial is 2..4 mm behind the PCB
TALK_Y, TALK_Z = -36.0, -1.6         # Talk actuator centre; its tip is at X = -0.5
USB_X, USB_Z = 21.5, -1.63           # USB-C receptacle centre
USB_W, USB_H = 13.0, 7.0             # opening for the plug overmould
MIC = (36.8, -9.71)                  # microphone port in the PCB
SPEAKER = (21.5, -13.0, 15.0, 11.0)  # centre and size of a 15 x 11 mm speaker (part not chosen yet)
TRAY_LEGS = [(22.5, -42.3), (12.0, -42.3), (35.0, -82.0), (8.0, -82.0), (13.0, -70.0)]
FILM = (0.0, -43.5, 5.4, -19.0)      # tray cut-out for the thermistor film

# derived
X0, X1, Y0, Y1 = -GAP, W + GAP, -(H + GAP), GAP                   # cavity
OX0, OX1, OY0, OY1 = X0 - WALL, X1 + WALL, Y0 - WALL, Y1 + WALL    # outside
ZB, ZF = 0.0, T
Z_GLASS0 = ZF + TAPE_T
Z_FI = Z_GLASS0 + GLASS_T + 0.15     # inner face of the front wall
Z_FO = Z_FI + WALL
Z_TRAY1 = -(PART_H + TRAY_GAP)       # tray face towards the PCB
Z_TRAY0 = Z_TRAY1 - TRAY_T
Z_BI = Z_TRAY0 - CELL_T - SWELL      # inner face of the back wall
Z_BO = Z_BI - WALL


def box(x0, x1, y0, y1, z0, z1):
    return cq.Workplane('XY').box(x1 - x0, y1 - y0, z1 - z0, centered=False).translate((x0, y0, z0))


def rbox(x0, x1, y0, y1, z0, z1, r):
    return box(x0, x1, y0, y1, z0, z1).edges('|Z').fillet(r)


def cyl(x, y, r, z0, z1):
    return cq.Workplane('XY').circle(r).extrude(z1 - z0).translate((x, y, z0))


# ------------------------------------------------------------------ parts
def front_shell():
    s = rbox(OX0, OX1, OY0, OY1, ZB, Z_FO, R_OUT)
    s = s.faces('>Z').edges().fillet(1.0)
    s = s.cut(rbox(X0, X1, Y0, Y1, ZB - 1, Z_FI, R_IN))
    # outer half of the lap joint
    skirt = rbox(OX0, OX1, OY0, OY1, -LAP, ZB, R_OUT).cut(
        rbox(OX0 + LAP_T, OX1 - LAP_T, OY0 + LAP_T, OY1 - LAP_T, -LAP - 1, ZB + 1, R_OUT - LAP_T))
    s = s.union(skirt)
    # display window, chamfered towards the outside
    wx0, wy0, wx1, wy1 = WINDOW
    win = box(wx0, wx1, wy0, wy1, Z_FI - 1, Z_FO + 1)
    s = s.cut(win)
    s = s.cut(cq.Workplane('XY').workplane(offset=Z_FO - 0.8).rect(wx1 - wx0, wy1 - wy0)
              .workplane(offset=0.8).rect(wx1 - wx0 + 1.6, wy1 - wy0 + 1.6).loft()
              .translate(((wx0 + wx1) / 2, (wy0 + wy1) / 2, 0)))
    # PCB bosses: pilot holes for the screws, a peg in the fourth hole
    for x, y in HOLES:
        s = s.union(cyl(x, y, BOSS_R, ZF, Z_FI + 0.1))
    for x, y in SCREWS:
        s = s.cut(cyl(x, y, PILOT_R, ZF - 0.1, Z_FO - 0.8))
    for x, y in HOLES[3:]:
        s = s.union(cyl(x, y, 0.95, ZF - 1.4, ZF))
    # microphone port with a short tube down to the PCB (0.3 mm left for a gasket)
    s = s.union(cyl(MIC[0], MIC[1], 2.5, ZF + 0.3, Z_FI + 0.1))
    s = s.cut(cyl(MIC[0], MIC[1], 0.8, ZF, Z_FO + 1))
    # room for the USB plug and the Talk button in the skirt
    s = s.cut(box(USB_X - USB_W / 2, USB_X + USB_W / 2, OY0 - 1, Y0 + 0.01, -LAP - 0.1, USB_Z + USB_H / 2))
    s = s.cut(box(OX0 - 1, OX0 + LAP_T + 0.01, TALK_Y - 3.1, TALK_Y + 3.1, -LAP - 0.1, TALK_Z + 1.15))
    return s


def back_shell():
    s = rbox(OX0, OX1, OY0, OY1, Z_BO, -LAP, R_OUT)
    s = s.faces('<Z').edges().fillet(1.5)
    s = s.cut(rbox(X0, X1, Y0, Y1, Z_BI, ZB + 1, R_IN))
    # inner half of the lap joint
    e = LAP_T - FIT
    lip = rbox(X0 - e, X1 + e, Y0 - e, Y1 + e, -LAP, -0.1, R_IN + e).cut(rbox(X0, X1, Y0, Y1, -LAP - 1, 1, R_IN))
    s = s.union(lip)
    # screw posts up to the PCB, counterbored from the outside
    for x, y in SCREWS:
        s = s.union(cyl(x, y, BOSS_R, Z_BI - 0.1, -0.05))
    for x, y in SCREWS:
        s = s.cut(cyl(x, y, CLEAR_R, Z_BO - 1, 1))
        s = s.cut(cyl(x, y, HEAD_R, Z_BO - 1, -HEAD_FLOOR))
    # wheel: thumb recess in the wall and a slot open towards the front shell
    wx, wy, wr = WHEEL
    s = s.cut(box(OX1 - 1.0, OX1 + 0.1, wy - 10, wy + 10, -7.0, -LAP + 0.01))
    half = (wr ** 2 - (X1 - wx) ** 2) ** 0.5 + 0.9
    s = s.cut(box(X1 - 0.1, OX1 + 0.1, wy - half, wy + half, -4.5, 0))
    # Talk button: pocket for the flange on the inside, window through the rest of the wall
    s = s.cut(box(X0 - 0.8, X0 + 0.01, TALK_Y - 4.5, TALK_Y + 4.5, TALK_Z - 1.9, 0))
    s = s.cut(box(OX0 - 0.1, X0 - 0.79, TALK_Y - 2.9, TALK_Y + 2.9, TALK_Z - 1.1, TALK_Z + 1.15))
    # USB-C plug opening
    s = s.cut(box(USB_X - USB_W / 2, USB_X + USB_W / 2, OY0 - 0.1, Y0 + 0.1, USB_Z - USB_H / 2, 0.1))
    # speaker: sound slots and a locating frame
    sx, sy, sw, sh = SPEAKER
    for i in range(-2, 3):
        s = s.cut(rbox(sx + i * 2.6 - 0.6, sx + i * 2.6 + 0.6, sy - 4.0, sy + 4.0, Z_BO - 1, Z_BI + 1, 0.55))
    frame = box(sx - sw / 2 - 1.15, sx + sw / 2 + 1.15, sy - sh / 2 - 1.15, sy + sh / 2 + 1.15, Z_BI - 0.1, Z_BI + 1.2)
    s = s.union(frame.cut(box(sx - sw / 2 - 0.15, sx + sw / 2 + 0.15, sy - sh / 2 - 0.15, sy + sh / 2 + 0.15,
                              Z_BI - 1, Z_BI + 2)))
    # ribs that locate the cell
    cx0, cy0, cx1, cy1 = CELL
    zr = Z_TRAY0 - 1.2
    for ya, yb in ((-40.0, -30.0), (-85.0, -75.0)):
        s = s.union(box(cx1 + 0.4, cx1 + 1.6, ya, yb, Z_BI - 0.1, zr))
        s = s.union(box(X0 - 0.1, cx0 - 0.4, ya, yb, Z_BI - 0.1, zr))
    for xa, xb in ((2.5, 8.0), (30.5, 36.0)):          # clear of the speaker frame
        s = s.union(box(xa, xb, cy1 + 0.4, cy1 + 1.6, Z_BI - 0.1, zr))
    return s


def battery_tray():
    cx0, cy0, cx1, cy1 = CELL
    t = rbox(cx0 - 0.5, cx1 + 0.5, cy0 - 0.2, cy1 + 0.4, Z_TRAY0, Z_TRAY1, 1.5)
    t = t.cut(box(FILM[0], FILM[2], FILM[1], FILM[3], Z_TRAY0 - 1, Z_TRAY1 + 1))
    for x, y in TRAY_LEGS:
        t = t.union(cyl(x, y, 1.5, Z_TRAY1 - 0.1, -0.05))
    return t


def talk_button():
    plunger = box(OX0 + 0.3, X0 - 0.75, TALK_Y - 2.75, TALK_Y + 2.75, TALK_Z - 0.95, TALK_Z + 0.95)
    flange = box(X0 - 0.75, X0 - 0.05, TALK_Y - 4.3, TALK_Y + 4.3, TALK_Z - 1.5, TALK_Z + 1.5)
    return plunger.union(flange)


# ------------------------------------------------------------------ bought parts, for the assembly only
def glass():
    x0, y0, x1, y1 = GLASS
    return box(x0, x1, y0, y1, Z_GLASS0, Z_GLASS0 + GLASS_T)


def flex():
    """OLED flex, simplified: out of the glass edge, down through the PCB notch, across the back."""
    ya, yb = -63.25, -47.75
    zf = Z_GLASS0 + GLASS_T / 2
    f = box(-0.35, GLASS[0], ya, yb, zf - 0.1, zf + 0.1)
    f = f.union(box(-0.35, -0.15, ya, yb, -1.1, zf + 0.1))
    return f.union(box(-0.35, 21.0, ya, yb, -1.1, -0.9))      # ends at the connector mouth


def cell():
    x0, y0, x1, y1 = CELL
    return rbox(x0, x1, y0, y1, Z_TRAY0 - CELL_T, Z_TRAY0, 1.0)


def speaker():
    sx, sy, sw, sh = SPEAKER
    return rbox(sx - sw / 2, sx + sw / 2, sy - sh / 2, sy + sh / 2, Z_BI, Z_BI + 3.5, 1.0)


PRINTED = {'front_shell': front_shell, 'back_shell': back_shell, 'battery_tray': battery_tray,
           'talk_button': talk_button}
COLORS = {'front_shell': cq.Color(0.2, 0.22, 0.25), 'back_shell': cq.Color(0.2, 0.22, 0.25),
          'battery_tray': cq.Color(0.85, 0.85, 0.8), 'talk_button': cq.Color(0.9, 0.45, 0.1)}


def vol(a, b):
    try:
        return a.intersect(b).val().Volume()
    except Exception:
        return 0.0


def merge_steps(paths, out):
    """Write several coloured STEP files into one (KiCad's board STEP repeats part names, so it cannot
    go through cq.Assembly)."""
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPCAFControl import STEPCAFControl_Reader, STEPCAFControl_Writer
    from OCP.STEPControl import STEPControl_AsIs
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDocStd import TDocStd_Document
    from OCP.XCAFApp import XCAFApp_Application
    app = XCAFApp_Application.GetApplication_s()
    doc = TDocStd_Document(TCollection_ExtendedString('XmlOcaf'))
    app.InitDocument(doc)
    for p in paths:
        r = STEPCAFControl_Reader()
        r.SetColorMode(True)
        r.SetNameMode(True)
        if r.ReadFile(p) != IFSelect_RetDone:
            raise RuntimeError('cannot read ' + p)
        r.Transfer(doc)
    w = STEPCAFControl_Writer()
    w.SetColorMode(True)
    w.SetNameMode(True)
    w.Transfer(doc, STEPControl_AsIs)
    if w.Write(out) != IFSelect_RetDone:
        raise RuntimeError('cannot write ' + out)


def main(board_step, out):
    os.makedirs(out, exist_ok=True)
    parts = {k: f() for k, f in PRINTED.items()}
    for k, p in parts.items():
        cq.exporters.export(p, os.path.join(out, k + '.step'))
        cq.exporters.export(p, os.path.join(out, k + '.stl'), tolerance=0.02, angularTolerance=0.2)
        bb = p.val().BoundingBox()
        print('%-13s %5.1f x %5.1f x %5.1f mm, %6.0f mm3, valid %s' % (
            k, bb.xlen, bb.ylen, bb.zlen, p.val().Volume(), p.val().isValid()))
    bought = {'oled_glass': (glass(), cq.Color(0.05, 0.05, 0.08)), 'oled_flex': (flex(), cq.Color(0.8, 0.5, 0.1)),
              'battery': (cell(), cq.Color(0.7, 0.72, 0.75)), 'speaker': (speaker(), cq.Color(0.3, 0.3, 0.3))}

    print('outside %.1f x %.1f x %.1f mm' % (OX1 - OX0, OY1 - OY0, Z_FO - Z_BO))
    # interference report
    board = cq.importers.importStep(board_step)
    solids = [cq.Workplane('XY').add(s) for s in board.solids().vals()]
    everything = dict(parts)
    everything.update({k: v[0] for k, v in bought.items()})
    names = list(everything)
    bad = 0
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            v = vol(everything[a], everything[b])
            if v > 0.01:
                bad += 1
                print('  OVERLAP %s / %s: %.2f mm3' % (a, b, v))
    for k in names:
        bbk = everything[k].val().BoundingBox()
        tot, worst = 0.0, None
        for s in solids:
            bs = s.val().BoundingBox()
            if (bs.xmax < bbk.xmin or bs.xmin > bbk.xmax or bs.ymax < bbk.ymin or bs.ymin > bbk.ymax
                    or bs.zmax < bbk.zmin or bs.zmin > bbk.zmax):
                continue
            v = vol(everything[k], s)
            if v > 0.005:
                tot += v
                c = s.val().Center()
                if worst is None or v > worst[0]:
                    worst = (v, round(c.x, 1), round(c.y, 1), round(c.z, 1))
        if tot > 0.01:
            bad += 1
            print('  OVERLAP %s / board: %.2f mm3, largest at %s' % (k, tot, worst))
    print('interference check:', 'clean' if not bad else '%d overlaps' % bad)

    # assembly: the enclosure parts as one coloured STEP, then merged with the board STEP as it is
    asm = cq.Assembly(name='enclosure')
    for k, p in parts.items():
        asm.add(p, name=k, color=COLORS[k])
    for k, (p, c) in bought.items():
        asm.add(p, name=k, color=c)
    enc = os.path.join(out, 'enclosure-parts.step')
    asm.export(enc)
    merge_steps([board_step, enc], os.path.join(out, 'pocketbrain-assembly.step'))
    print('wrote', os.path.join(out, 'pocketbrain-assembly.step'))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
