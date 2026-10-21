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
    cols=5, rows=2,             # keycaps per jig
    pitch_x=21.0, pitch_y=20.0,
    floor_t=4.0,                # base plate thickness below the floor
    rim_gap=1.0,                # keycap rim floats this far above the floor
    boss_clear=0.15,            # per side, boss wall to skirt wall (horizontal)
    boss_corner_r=1.0,          # cavity corners measure ~0.85
    boss_top_chamfer=0.20,      # clears the fillet where skirt meets underside
    slot_clear=0.15,            # per side, pin leg to slot
    slot_chamfer=0.15,
    moat_w=0.6, moat_d=0.4, moat_gap=0.3,   # squeeze-out groove around pin base
    margin=4.0,                 # base border outside the keycap grid
    standoff_d=9.0, wall_fillet=1.5, m3_clear=3.4, m3_nut_af=5.7, m3_nut_top=0.5,   # M3x18 SHCS from the top, nut pushed up to the top of its trap
    clamp_t=4.0, clamp_gap=1.2, # clamp underside sits this far above the tallest cap
    pad_x=10.0, pad_y=7.2, pad_r=1.5,       # pad footprint (keeps off the light-bar slots)
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
    tri = mf.CrossSection([[(1.6, 0.0), (-1.6, 0.0), (0.0, -1.8)]])
    return tri.extrude(depth + 1).translate((0, 0, z_top - depth))


def positions():
    xs = (np.arange(P['cols']) - (P['cols'] - 1) / 2) * P['pitch_x']
    ys = (np.arange(P['rows']) - (P['rows'] - 1) / 2) * P['pitch_y']
    return [(x, y) for y in ys for x in xs]


def outline():
    hx = (P['cols'] - 1) / 2 * P['pitch_x'] + 8.75 + 1.5 + P['standoff_d'] + 3.0
    hy = (P['rows'] - 1) / 2 * P['pitch_y'] + 8.25 + P['margin']
    return hx, hy


def standoff_xy():
    # at the ends of the rows, clear of the keycap skirts
    x = (P['cols'] - 1) / 2 * P['pitch_x'] + 8.75 + 1.5 + P['standoff_d'] / 2
    y = (P['rows'] - 1) / 2 * P['pitch_y']
    return [(sx * x, sy * y) for sx in (-1, 1) for sy in (-1, 1)]


def build_base():
    hx, hy = outline()
    ft = P['floor_t']
    base = slab(rrect(hx, hy, 3.0), -ft, ft)
    for (x, y) in positions():
        base = base + boss(P['boss_clear'], P['slot_clear']).translate((x, y, 0))
    # standoffs: one solid end wall per side instead of free-standing posts,
    # with a 45 degree fillet where the inner face meets the floor
    inner = (P['cols'] - 1) / 2 * P['pitch_x'] + 8.75 + 1.5
    fil = P['wall_fillet']
    for sx in (-1, 1):
        box = mf.Manifold.cube((hx - inner + 1, 2 * hy + 2, CLAMP_Z)).translate((inner, -hy - 1, 0))
        root = mf.Manifold.batch_hull([mf.Manifold.cube((hx - inner + fil, 2 * hy + 2, 0.01)).translate((inner - fil, -hy - 1, 0)),
                                       mf.Manifold.cube((hx - inner, 2 * hy + 2, 0.01)).translate((inner, -hy - 1, fil))])
        wall = (box + root) ^ slab(rrect(hx, hy, 3.0), 0.0, CLAMP_Z)
        base = base + (wall if sx > 0 else wall.mirror((1, 0, 0)))
    cuts = []
    for (x, y) in positions():
        cuts.append(leg_slots(P['slot_clear'], -ft, BOSS_TOP).translate((x, y, 0)))
        cuts.append(arrow(0.0).translate((x, y - 8.9, 0)))
    for (x, y) in standoff_xy():
        cuts.append(mf.Manifold.cylinder(CLAMP_Z + ft + 2, P['m3_clear'] / 2, P['m3_clear'] / 2, 32).translate((x, y, -ft - 1)))
        # hex trap open to the bed; its ceiling tapers up to the bolt hole at
        # 45 degrees or steeper so it prints without bridging or drooping
        rc = P['m3_nut_af'] / 2 / np.cos(np.pi / 6) + 0.1
        nut = mf.CrossSection.circle(rc, 6)
        zt = P['m3_nut_top']
        cuts.append(nut.extrude(ft + zt + 1).translate((x, y, -ft - 1)))
        cuts.append(mf.Manifold.batch_hull([nut.extrude(0.01).translate((x, y, zt - 0.01)),
                                            mf.Manifold.cylinder(0.01, P['m3_clear'] / 2, P['m3_clear'] / 2, 32)
                                            .translate((x, y, zt + rc - P['m3_clear'] / 2))]))
    return base - mf.Manifold.batch_boolean(cuts, mf.OpType.Add)


def peg_cs(clear=0.0):
    hx, hy, k = P['peg_x'] / 2 + clear, P['peg_y'] / 2 + clear, P['peg_key']
    # rectangle with one chamfered corner (-x,-y) so the pad only fits one way
    return mf.CrossSection([[(-hx + k, -hy), (hx, -hy), (hx, hy), (-hx, hy), (-hx, -hy + k)]])


def peg(z_root):
    """Keyed peg hanging down from z_root, with a lead-in chamfer at the tip."""
    h, ch = P['peg_h'], 0.3
    shaft = peg_cs().extrude(h - ch).translate((0, 0, z_root - h + ch))
    tip = mf.Manifold.batch_hull([peg_cs().extrude(0.01).translate((0, 0, z_root - h + ch - 0.01)),
                                  peg_cs().offset(-ch, mf.JoinType.Miter).extrude(0.01).translate((0, 0, z_root - h))])
    return shaft + tip


def build_clamp():
    hx, hy = outline()
    plate = slab(rrect(hx, hy, 3.0), CLAMP_Z, P['clamp_t'])
    cuts = []
    pegs = []
    for (x, y) in positions():
        pegs.append(peg(CLAMP_Z).translate((x, y, 0)))
    plate = plate + mf.Manifold.batch_boolean(pegs, mf.OpType.Add)
    for (x, y) in standoff_xy():
        cuts.append(mf.Manifold.cylinder(P['clamp_t'] + 2, P['m3_clear'] / 2, P['m3_clear'] / 2, 32).translate((x, y, CLAMP_Z - 1)))
    return plate - mf.Manifold.batch_boolean(cuts, mf.OpType.Add)


def top_surface(stl):
    m = trimesh.load(stl)
    body = max(m.split(only_watertight=False), key=lambda p: len(p.faces))
    res = 0.1
    xs = np.arange(-P['pad_x'] / 2 - 0.5413, P['pad_x'] / 2 + 0.6, res)   # grid offset so no line lies on a pad wall
    ys = np.arange(-P['pad_y'] / 2 - 0.5413, P['pad_y'] / 2 + 0.6, res)
    X, Y = np.meshgrid(xs, ys)
    o = np.c_[X.ravel(), Y.ravel(), np.full(X.size, 50.0)]
    loc, ri, _ = body.ray.intersects_location(o, np.tile([0, 0, -1.0], (X.size, 1)), multiple_hits=False)
    Z = np.full(X.size, np.nan)
    Z[ri] = loc[:, 2]
    Z = Z.reshape(X.shape)
    bad = np.isnan(Z)
    if bad.mean() > 0.01:
        raise SystemExit('gap in top surface under pad footprint for %s' % stl)
    if bad.any():   # rays that slipped between triangles: take the nearest hit
        from scipy.ndimage import distance_transform_edt
        _, (iy, ix) = distance_transform_edt(bad, return_indices=True)
        Z = Z[iy, ix]
    return xs, ys, Z


def build_pad(stl):
    xs, ys, Z = top_surface(stl)
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
        raise SystemExit('pad floor under socket only %.2f mm for %s' % (floor, stl))
    length = CLAMP_Z - float(Zj.max())
    return pad, length, float(Zj.min()), float(Zj.max()), floor


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

    report = dict(params=P, boss_top=BOSS_TOP, clamp_underside=CLAMP_Z)
    base = build_base()
    to_trimesh(base).export(os.path.join(out, 'pinjig_base.stl'))
    clamp = build_clamp()
    # print orientation: flat top on the bed, pegs pointing up (rotate 180 about X)
    flip = lambda m, z: m.rotate((180, 0, 0)).translate((0, 0, z))
    to_trimesh(flip(clamp, CLAMP_Z + P['clamp_t'])).export(os.path.join(out, 'pinjig_clamp.stl'))
    pads = {}
    for name, stl in (('normal', 'normal'), ('home', 'normal-home'), ('raised', 'raised-lower')):
        pad, length, zmin, zmax, floor = build_pad(os.path.join(capdir, stl + '.stl'))
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
    cap_names = ['normal', 'normal-home', 'raised-lower', 'raised-upper', 'normal'] * 2
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
