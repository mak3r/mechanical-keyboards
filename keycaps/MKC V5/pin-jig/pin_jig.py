"""MKC keycap pin-attachment jig generator.

Geometry is derived from the MKC V5 keycap STLs and pin.stl (keycap frame:
skirt rim at z=0, flat underside at z=1.8, pin base face at z=1.8, legs down).

Jig frame: Z=0 is the top of the base floor. Every keycap sits on a boss whose
flat top is at Z=BOSS_TOP, so the keycap frame maps to jig Z = z + KZ.

Parts:
  base      PETG. Self-centering bosses (match the drafted skirt walls),
            through slots for the pin legs, M3 standoffs (hard stops).
  clamp     PETG. Plate with keyed pegs on its underside; print pegs up.
  pad_*     TPU. Conformal to each keycap top, with a keyed socket in its
            flat back that presses onto a clamp peg; print back down.
  fit_test  PETG. One boss per clearance step for dialling in tolerances.

Usage: python3 pin_jig.py <keycap stl dir> <pin.stl> <out dir> [--preview]
  (from keycaps/MKC V5/pin-jig: python3 pin_jig.py .. ../pin.stl .)
"""
import sys, os, json
import numpy as np
import trimesh
import manifold3d as mf

# ---------------------------------------------------------------- parameters
P = dict(
    cols=3, rows=3,             # keycaps per jig: 3x3 = one Corne half, three columns at a time
    pitch_x=21.0, pitch_y=20.0,
    floor_t=4.0,                # base plate thickness below the floor
    rim_gap=1.0,                # keycap rim floats this far above the floor
    boss_clear=0.15,            # per side, boss wall to skirt wall (horizontal)
    boss_corner_r=1.0,          # cavity corners measure ~0.85
    boss_top_chamfer=0.20,      # clears the fillet where skirt meets underside
    slot_clear=0.15,            # per side, pin leg to slot
    slot_chamfer=0.15,
    moat_w=0.6, moat_d=0.4, moat_gap=0.3,   # squeeze-out groove around pin base
    frame_gap=1.5,              # keycap skirt to frame inner face
    frame_w=9.0, frame_r=4.0, wall_fillet=1.0,
    vent=4.8, vent_pitch=7.0, vent_z=5.6,   # diamond vents through the frame sides (45 deg edges)
    foot_h=2.5, channel_w=6.0,  # underside skid with an open air channel under each row of leg slots
    m3_clear=3.4,
    key_bolt_y=29.0,            # the +x,+y bolt sits off the corner, so the clamp fits only one way round
    key_chamfer=8.0,            # matching cut corner on base and clamp, as a visual cue
    head_af=5.5, head_h=2.0, head_clear=0.15,   # M3 hex-head screw, inserted from below
    rib_w=0.8, rib_interf=0.12, # crush ribs in the head pocket (interference with the head flats)
    bridge_layer=0.3,           # stepped sacrificial bridge above the head pocket
    clamp_t=3.0, clamp_gap=1.2, # clamp plate; underside sits this far above the tallest cap
    rib_t=2.0, rib_bottom=4.0,  # stiffening ribs under the clamp, between the rows and columns of caps
    screw_len=20.0, min_thread=4.0,   # 20 mm screw must leave this much thread above the clamp for the wing nut
    pad_x=14.6, pad_y=13.8, pad_r=2.0,      # pad footprint: the whole cap top, out past the edge crest
    pad_interference=0.5,       # how far each pad is pushed into the cap top
    pad_min_len=3.0,
    peg_x=6.0, peg_y=3.6, peg_key=1.2, peg_h=2.5, peg_clear=0.0,   # peg is on the clamp, socket in the pad
    socket_extra=0.3, pad_min_floor=1.2,
)

# keycap geometry (keycap frame), measured from the V5 STLs
UNDERSIDE_Z = 1.8
WALL_X0, WALL_Y0 = 7.75, 7.25   # skirt inner wall half-widths at z=0
WALL_DRAFT = 0.466              # horizontal mm per mm of height (about 25 deg)
LEG_CX, LEG_W, LEG_L = 2.85, 1.16, 2.96   # pin legs: centres +-x, size x, y
PIN_BASE = (8.5, 4.0)


def rrect(hx, hy, r):
    r = min(r, hx - 1e-3, hy - 1e-3)
    c = mf.CrossSection.circle(r, 48)
    return mf.CrossSection.batch_hull([c.translate((sx * (hx - r), sy * (hy - r)))
                                       for sx in (-1, 1) for sy in (-1, 1)])


def slab(cs, z0, h):
    return cs.extrude(h).translate((0, 0, z0))


def to_trimesh(m):
    mesh = m.to_mesh()
    return trimesh.Trimesh(np.array(mesh.vert_properties)[:, :3], np.array(mesh.tri_verts), process=True)


def from_trimesh(t):
    return mf.Manifold(mf.Mesh(np.asarray(t.vertices, np.float32), np.asarray(t.faces, np.uint32)))


def boss(c, slot_c):
    """One self-centering boss in jig frame, top face at BOSS_TOP, centred at origin."""
    top = BOSS_TOP
    kz = KZ
    def half(z_key):  # skirt wall half widths at keycap height z, minus clearance
        return WALL_X0 - WALL_DRAFT * z_key - c, WALL_Y0 - WALL_DRAFT * z_key - c
    r = P['boss_corner_r'] + c
    ch = P['boss_top_chamfer']
    hx0, hy0 = half(0.0)
    hx1, hy1 = half(UNDERSIDE_Z - ch)
    lower = slab(rrect(hx0, hy0, r), 0.0, kz)                                    # straight below the rim
    taper = mf.Manifold.batch_hull([slab(rrect(hx0, hy0, r), kz, 0.01),
                                    slab(rrect(hx1, hy1, r), top - ch - 0.01, 0.01),
                                    slab(rrect(hx1 - ch, hy1 - ch, r), top - 0.01, 0.01)])
    b = lower + taper
    # squeeze-out moat around the pin base footprint
    g = P['moat_gap']; w = P['moat_w']
    bx, by = PIN_BASE[0] / 2 + g, PIN_BASE[1] / 2 + g
    moat = slab(rrect(bx + w, by + w, w) - rrect(bx, by, 0.2), top - P['moat_d'], P['moat_d'] + 1)
    b = b - moat
    return b


def leg_slots(slot_c, z0, z1):
    sx, sy = LEG_W / 2 + slot_c, LEG_L / 2 + slot_c
    ch = P['slot_chamfer']
    out = []
    for s in (-1, 1):
        cut = slab(mf.CrossSection.square((2 * sx, 2 * sy), True), z0 - 1, z1 - z0 + 2)
        cham = mf.Manifold.batch_hull([slab(mf.CrossSection.square((2 * sx, 2 * sy), True), z1 - ch, 0.01),
                                       slab(mf.CrossSection.square((2 * (sx + ch), 2 * (sy + ch)), True), z1, 0.5)])
        bot = mf.Manifold.batch_hull([slab(mf.CrossSection.square((2 * sx, 2 * sy), True), z0 + ch, 0.01),
                                      slab(mf.CrossSection.square((2 * (sx + ch), 2 * (sy + ch)), True), z0 - 0.5, 0.5)])
        out.append((cut + cham + bot).translate((s * LEG_CX, 0, 0)))
    return out[0] + out[1]


def arrow(z_top, depth=0.4):
    """Small engraved triangle pointing at -Y (the tall edge of raised caps)."""
    tri = mf.CrossSection([[(1.2, 0.0), (-1.2, 0.0), (0.0, -1.2)]])
    return tri.extrude(depth + 1).translate((0, 0, z_top - depth))


def positions():
    xs = (np.arange(P['cols']) - (P['cols'] - 1) / 2) * P['pitch_x']
    ys = (np.arange(P['rows']) - (P['rows'] - 1) / 2) * P['pitch_y']
    return [(x, y) for y in ys for x in xs]


def frame_inner():
    ix = (P['cols'] - 1) / 2 * P['pitch_x'] + 8.75 + P['frame_gap']
    iy = (P['rows'] - 1) / 2 * P['pitch_y'] + 8.25 + P['frame_gap']
    return ix, iy


def outline():
    ix, iy = frame_inner()
    return ix + P['frame_w'], iy + P['frame_w']


def outline_cs():
    """Base/clamp footprint: rounded rectangle with the +x,+y corner cut off."""
    hx, hy = outline()
    c = P['key_chamfer']
    cut = mf.CrossSection([[(hx - c, hy + 1), (hx + 1, hy - c), (hx + 1, hy + 1)]])
    return rrect(hx, hy, P['frame_r']) - cut


def standoff_xy():
    # one bolt in each corner of the frame; the +x,+y one is moved along its
    # side so the bolt pattern only matches with the clamp the right way round
    ix, iy = frame_inner()
    x, y = ix + P['frame_w'] / 2, iy + P['frame_w'] / 2
    pts = [(sx * x, sy * y) for sx in (-1, 1) for sy in (-1, 1)]
    pts[3] = (x, P['key_bolt_y'])
    return pts


def head_bearing_z():
    """Z of the face the screw head pulls up against."""
    return -P['floor_t'] + P['head_h'] + 0.3


def head_pocket(x, y):
    """Hex pocket for the screw head, open to the bed, with crush ribs on three
    flats and a two-step sacrificial bridge above it so the ceiling prints flat
    with no droop into the bolt hole."""
    ft, fh = P['floor_t'], P['foot_h']
    zb = head_bearing_z()
    af = P['head_af'] + 2 * P['head_clear']
    rc = af / 2 / np.cos(np.pi / 6)
    hexs = mf.CrossSection.circle(rc, 6)          # flats face +-y, +-60 deg
    pocket = hexs.extrude(zb + ft + fh + 1).translate((0, 0, -ft - fh - 1))
    # ribs: half-round bumps standing proud of alternate flats
    rr = P['rib_w'] / 2
    ribs = []
    for k in range(3):
        ang = np.pi / 2 + k * 2 * np.pi / 3        # normals of flats
        d = af / 2 + rr - (P['head_clear'] + P['rib_interf'])
        ribs.append(mf.Manifold.cylinder(zb + ft + fh, rr, rr, 16)
                    .translate((d * np.cos(ang), d * np.sin(ang), -ft - fh)))
    pocket = pocket - mf.Manifold.batch_boolean(ribs, mf.OpType.Add)
    bl, hole = P['bridge_layer'], P['m3_clear']
    step1 = mf.Manifold.cube((hole, 2 * rc, bl)).translate((-hole / 2, -rc, zb))
    step2 = mf.Manifold.cube((hole, hole, bl)).translate((-hole / 2, -hole / 2, zb + bl))
    return (pocket + step1 + step2).translate((x, y, 0))


def build_base():
    hx, hy = outline()
    ix, iy = frame_inner()
    ft, fh = P['floor_t'], P['foot_h']
    r = P['frame_r']
    base = slab(outline_cs(), -ft, ft)
    for (x, y) in positions():
        base = base + boss(P['boss_clear'], P['slot_clear']).translate((x, y, 0))
    # closed frame: the clamp rests on all four sides; 45 degree fillet inside at the floor
    fil = P['wall_fillet']
    inner = mf.Manifold.batch_hull([slab(rrect(ix - fil, iy - fil, 1.0), 0.0, 0.01),
                                    slab(rrect(ix, iy, 1.0), fil, 0.01),
                                    slab(rrect(ix, iy, 1.0), CLAMP_Z + 1, 0.01)])
    frame = slab(outline_cs(), 0.0, CLAMP_Z) - inner
    # diamond vents through each side, clear of the corner bolts
    v = P['vent'] / 2
    dia = mf.CrossSection([[(v, 0.0), (0.0, v), (-v, 0.0), (0.0, -v)]])
    vents = []
    for span, along_x in ((ix, True), (iy, False)):
        n = int((2 * (span - 3.0)) // P['vent_pitch']) + 1
        for i in range(n):
            t = (i - (n - 1) / 2) * P['vent_pitch']
            if not along_x and abs(t - P['key_bolt_y']) < v + P['m3_clear'] / 2 + 0.8:
                continue
            if along_x:   # holes through the walls at +-y, running along x
                hole = dia.extrude(2 * hy + 2).rotate((90, 0, 0)).translate((t, hy + 1, P['vent_z']))
            else:         # holes through the walls at +-x, running along y
                hole = dia.extrude(2 * hx + 2).rotate((0, 90, 0)).translate((-hx - 1, t, P['vent_z']))
            vents.append(hole)
    frame = frame - mf.Manifold.batch_boolean(vents, mf.OpType.Add)
    base = base + frame
    # skid under the floor, with an air channel along each row so the bottoms
    # of the leg slots stay open to the room; channel roofs are short bridges
    skid = slab(outline_cs(), -ft - fh, fh + 0.01)
    chans = [mf.Manifold.cube((2 * hx + 2, P['channel_w'], fh + 1)).translate((-hx - 1, y - P['channel_w'] / 2, -ft - fh - 1))
             for y in sorted(set(p[1] for p in positions()))]
    base = base + (skid - mf.Manifold.batch_boolean(chans, mf.OpType.Add))
    cuts = []
    for (x, y) in positions():
        cuts.append(leg_slots(P['slot_clear'], -ft, BOSS_TOP).translate((x, y, 0)))
        cuts.append(arrow(0.0).translate((x, y - 7.4, 0)))
    for (x, y) in standoff_xy():
        cuts.append(mf.Manifold.cylinder(CLAMP_Z + ft + 2, P['m3_clear'] / 2, P['m3_clear'] / 2, 32).translate((x, y, -ft - 1)))
        cuts.append(head_pocket(x, y))
    return base - mf.Manifold.batch_boolean(cuts, mf.OpType.Add)


def peg_cs(clear=0.0):
    hx, hy, k = P['peg_x'] / 2 + clear, P['peg_y'] / 2 + clear, P['peg_key']
    # rectangle with one chamfered corner (-x,-y) so the pad only fits one way round
    return mf.CrossSection([[(-hx + k, -hy), (hx, -hy), (hx, hy), (-hx, hy), (-hx, -hy + k)]])


def peg(z_root):
    """Keyed peg hanging down from z_root, with a lead-in chamfer at the tip."""
    h, ch = P['peg_h'], 0.3
    shaft = peg_cs().extrude(h - ch).translate((0, 0, z_root - h + ch))
    tip = mf.Manifold.batch_hull([peg_cs().extrude(0.01).translate((0, 0, z_root - h + ch - 0.01)),
                                  peg_cs().offset(-ch, mf.JoinType.Miter).extrude(0.01).translate((0, 0, z_root - h))])
    return shaft + tip


def build_clamp():
    """Thin plate (so a 20 mm screw leaves room for the wing nut) stiffened by a
    grid of ribs that hang down in the gaps between the caps and pads. Printed
    upside down: flat top on the bed, ribs and pegs pointing up."""
    hx, hy = outline()
    ix, iy = frame_inner()
    tip = head_bearing_z() + P['screw_len']
    if CLAMP_Z + P['clamp_t'] > tip - P['min_thread'] + 1e-6:
        raise SystemExit('screw too short: only %.2f mm of thread above the clamp'
                         % (tip - CLAMP_Z - P['clamp_t']))
    plate = slab(outline_cs(), CLAMP_Z, P['clamp_t'])
    adds = [peg(CLAMP_Z).translate((x, y, 0)) for (x, y) in positions()]
    h = CLAMP_Z - P['rib_bottom']
    t = P['rib_t']
    e = 0.5   # stop short of the frame's inner face
    for k in range(1, P['rows']):
        y = (k - P['rows'] / 2) * P['pitch_y']
        adds.append(mf.Manifold.cube((2 * (ix - e), t, h + 0.01)).translate((-(ix - e), y - t / 2, P['rib_bottom'])))
    for k in range(1, P['cols']):
        x = (k - P['cols'] / 2) * P['pitch_x']
        adds.append(mf.Manifold.cube((t, 2 * (iy - e), h + 0.01)).translate((x - t / 2, -(iy - e), P['rib_bottom'])))
    plate = plate + mf.Manifold.batch_boolean(adds, mf.OpType.Add)
    cuts = [mf.Manifold.cylinder(P['clamp_t'] + 2, P['m3_clear'] / 2, P['m3_clear'] / 2, 32).translate((x, y, CLAMP_Z - 1))
            for (x, y) in standoff_xy()]
    return plate - mf.Manifold.batch_boolean(cuts, mf.OpType.Add)


def top_surface(stls):
    """Cap top height map under the pad footprint. Several STLs are averaged
    (raised-lower and raised-upper share one pad); the light-bar slot is a hole
    in the top, so it is filled by interpolating across it as if the bar is flush."""
    res = 0.1
    xs = np.arange(-P['pad_x'] / 2 - 0.5413, P['pad_x'] / 2 + 0.6, res)   # grid offset so no line lies on a pad wall
    ys = np.arange(-P['pad_y'] / 2 - 0.5413, P['pad_y'] / 2 + 0.6, res)
    X, Y = np.meshgrid(xs, ys)
    maps = []
    for stl in stls:
        m = trimesh.load(stl)
        body = max(m.split(only_watertight=False), key=lambda p: len(p.faces))
        o = np.c_[X.ravel(), Y.ravel(), np.full(X.size, 50.0)]
        loc, ri, _ = body.ray.intersects_location(o, np.tile([0, 0, -1.0], (X.size, 1)), multiple_hits=False)
        Z = np.full(X.size, np.nan)
        Z[ri] = loc[:, 2]
        maps.append(Z.reshape(X.shape))
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', RuntimeWarning)   # all-NaN cells are filled below
        Z = np.nanmean(np.stack(maps), axis=0)
    bad = np.isnan(Z)
    if bad.mean() > 0.15:
        raise SystemExit('too much of the top surface is missing under the pad for %s' % stls)
    if bad.any():
        from scipy.interpolate import griddata
        pts = np.c_[X[~bad], Y[~bad]]
        fill = griddata(pts, Z[~bad], (X[bad], Y[bad]), method='linear')
        near = griddata(pts, Z[~bad], (X[bad], Y[bad]), method='nearest')
        Z[bad] = np.where(np.isnan(fill), near, fill)
    return xs, ys, Z


def build_pad(stls):
    xs, ys, Z = top_surface(stls)
    Zj = Z + KZ - P['pad_interference']          # pad face in jig frame
    # unit-height pad body, refined so the bottom can follow the cap surface, then
    # warped: z=0 -> conformal face, z=1 -> flat back at the clamp underside
    from scipy.interpolate import RegularGridInterpolator
    face = RegularGridInterpolator((ys, xs), Zj)
    body = slab(rrect(P['pad_x'] / 2, P['pad_y'] / 2, P['pad_r']), 0.0, 1.0).refine_to_length(0.25)
    def warp(v):
        zf = face(np.c_[v[:, 1], v[:, 0]])
        out = v.copy()
        out[:, 2] = zf + (CLAMP_Z - zf) * v[:, 2]
        return out
    body = body.warp_batch(warp)
    depth = P['peg_h'] + P['socket_extra']
    socket = peg_cs(P['peg_clear']).extrude(depth + 1).translate((0, 0, CLAMP_Z - depth))
    pad = body - socket
    # material left between the socket floor and the conformal face
    X, Y = np.meshgrid(xs, ys)
    over = (abs(X) <= P['peg_x'] / 2 + 0.2) & (abs(Y) <= P['peg_y'] / 2 + 0.2)
    floor = (CLAMP_Z - depth) - float(Zj[over].max())
    if floor < P['pad_min_floor']:
        raise SystemExit('pad floor under socket only %.2f mm for %s' % (floor, stls))
    r = P['pad_r']
    cx = np.clip(abs(X) - (P['pad_x'] / 2 - r), 0, None)
    cy = np.clip(abs(Y) - (P['pad_y'] / 2 - r), 0, None)
    foot = (abs(X) <= P['pad_x'] / 2) & (abs(Y) <= P['pad_y'] / 2) & (cx ** 2 + cy ** 2 <= r * r)
    length = CLAMP_Z - float(Zj[foot].max())
    return pad, length, float(Zj[foot].min()), float(Zj[foot].max()), floor


def build_fit_test():
    steps = [0.05, 0.10, 0.15, 0.20]
    parts = []
    for i, c in enumerate(steps):
        x = (i - 1.5) * 21.0
        plate = slab(rrect(10.0, 9.5, 2.0), -2.0, 2.0)
        b = plate + boss(c, c)
        b = b - leg_slots(c, -2.0, BOSS_TOP)
        for k in range(i + 1):   # dots = step number
            b = b - mf.Manifold.cylinder(1.0, 0.5, 0.5, 16).translate((-7.5 + k * 1.6, -8.3, -0.4))
        parts.append(b.translate((x, 0, 0)))
    return mf.Manifold.batch_boolean(parts, mf.OpType.Add)


if __name__ == '__main__':
    capdir, pin_stl, out = sys.argv[1], sys.argv[2], sys.argv[3]
    os.makedirs(os.path.join(out, 'pinjig_pads'), exist_ok=True)
    preview = '--preview' in sys.argv
    KZ = P['rim_gap']                         # keycap z=0 -> jig Z
    BOSS_TOP = KZ + UNDERSIDE_Z
    tallest = max(trimesh.load(os.path.join(capdir, n + '.stl')).bounds[1, 2]
                  for n in ('normal', 'normal-home', 'raised-lower', 'raised-upper'))
    CLAMP_Z = round(KZ + tallest + P['clamp_gap'], 2)

    report = dict(params=P, boss_top=BOSS_TOP, clamp_underside=CLAMP_Z,
                  head_bearing_z=head_bearing_z(), clamp_top_z=CLAMP_Z + P['clamp_t'],
                  screw_tip_z=head_bearing_z() + P['screw_len'],
                  outline_mm=[2 * v for v in outline()])
    base = build_base()
    to_trimesh(base).export(os.path.join(out, 'pinjig_base.stl'))
    clamp = build_clamp()
    # print orientation: flat top on the bed, pegs pointing up (rotate 180 about X)
    flip = lambda m, z: m.rotate((180, 0, 0)).translate((0, 0, z))
    to_trimesh(flip(clamp, CLAMP_Z + P['clamp_t'])).export(os.path.join(out, 'pinjig_clamp.stl'))
    pads = {}
    for name, caps in (('normal', ['normal']), ('home', ['normal-home']), ('raised', ['raised-lower', 'raised-upper'])):
        pad, length, zmin, zmax, floor = build_pad([os.path.join(capdir, c + '.stl') for c in caps])
        pads[name] = pad
        # print orientation: flat back on the bed, conformal face up (rotate, never mirror)
        to_trimesh(flip(pad, CLAMP_Z)).export(os.path.join(out, 'pinjig_pads', 'pinjig_pad_%s.stl' % name))
        report['pad_' + name] = dict(min_length=round(length, 2), socket_floor=round(floor, 2),
                                     face_z=[round(zmin, 2), round(zmax, 2)])
    to_trimesh(build_fit_test()).export(os.path.join(out, 'pinjig_fit_test.stl'))

    # assembled preview with keycaps + pins in place, for checking interference
    if not preview:
        json.dump(report, open(os.path.join(out, 'report.json'), 'w'), indent=1)
        print(json.dumps(report, indent=1))
        sys.exit(0)
    cap_names = ['raised-lower'] * 3 + ['normal', 'normal-home', 'normal'] + ['raised-upper'] * 3
    pin = trimesh.load(pin_stl)
    scene = [to_trimesh(base), to_trimesh(clamp)]
    checks = {}
    for (x, y), n in zip(positions(), cap_names):
        cap = trimesh.load(os.path.join(capdir, n + '.stl'))
        body = max(cap.split(only_watertight=False), key=lambda p: len(p.faces))
        body.apply_translation((x, y, KZ)); scene.append(body)
        p = pin.copy(); p.apply_translation((x, y, KZ)); scene.append(p)
        padn = {'normal': 'normal', 'normal-home': 'home'}.get(n, 'raised')
        scene.append(to_trimesh(pads[padn].translate((x, y, 0))))
        # interference: pin vs base, cap vs base
        inter = (from_trimesh(p) ^ base).volume()
        checks.setdefault('pin_x_base_mm3', []).append(round(inter, 4))
    report['checks'] = checks
    trimesh.util.concatenate(scene).export(os.path.join(out, 'preview_assembly.stl'))
    json.dump(report, open(os.path.join(out, 'report.json'), 'w'), indent=1)
    print(json.dumps(report, indent=1))
