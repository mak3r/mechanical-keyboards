"""Thicker Choc v1 switch plate for the Typeractive Corne (right half; mirror for left).

Geometry is derived from the existing 1.2 mm plate (switch-plate.stl) and the
Typeractive sandwich model (sandwhich-case-and-pcb.stl, metres, Y-up).

Plate frame (same as switch-plate.stl): Z=0 is the underside of the original
plate, Z=1.2 its top. The PCB top surface is at Z=-0.977 (Choc v1: plate top
2.2 mm above PCB), so the plate can only grow downward by that much.

Layers:
  lip   Z 0..1.2       The original plate with larger cutouts. Choc clips need
                       a 1.2 mm lip, so this stays 1.2 thick at every cutout.
  web   Z -web_t..0    Stiffening grid under the lip, between the switches.
                       Pockets under each cutout clear the switch clips; reliefs
                       clear the standoffs and everything else on the PCB top.

Print with the plate top on the bed: the lip prints first and every pocket
opens upward, so no supports are needed.

Parts:
  plate      in-situ (plate frame, right half) and print-oriented right/left STLs
  fit_test   1x5 coupon, one cutout per size step, 1-5 raised dots

Usage: python3 thick_plate.py <switch-plate.stl> <sandwhich-case-and-pcb.stl> <out dir>
  (from typeractive/case-designs/thick-plate:
   python3 thick_plate.py ../simple-sandwich/switch-plate.stl ../../basis/sandwhich-case-and-pcb.stl .)
"""
import sys, os, json
import numpy as np
import trimesh
import manifold3d as mf
from shapely.geometry import Polygon, MultiPolygon, Point, MultiPoint
from shapely.ops import unary_union
from shapely import affinity

# ---------------------------------------------------------------- parameters
P = dict(
    hole=13.70,             # fit test 2 (2026-10-30): 13.70 drawn (2 dots) was the snuggest. Printer prints holes ~0.05 large
    lip_t=1.2,              # Choc v1 clip engagement (plate thickness spec)
    hole_chamfer=0.3,       # 45 deg on the top (bed) edge: eats elephant's foot, eases insertion
    pcb_top=-0.977,         # PCB top surface in plate frame
    pcb_gap=0.25,           # web underside stays this far above the PCB
    pocket=15.0,            # clip relief under the lip, square
    cell_x=18.0, cell_y=17.0,   # Choc key pitch (fit-test coupon spacing)
    keepout_buf=0.5,        # clearance around standoffs and PCB-top parts
    min_feature=0.8,        # web slivers narrower than this are dropped (two perimeters)
    fit_sizes=[13.65, 13.70, 13.75, 13.80, 13.85],   # 4 dots = Choc spec (original plate)
    dot_d=1.6, dot_h=0.4,
    sandwich_dz=1.7602,     # sandwich Z = plate Y + this (sandwich X = plate X)
    sandwich_y0=-2.5868,    # sandwich Y of the plate underside; sandwich -Y is up
)
P['web_t'] = round(-P['pcb_top'] - P['pcb_gap'], 3)


# ------------------------------------------------------------------ helpers
def to_cs(geom):
    """shapely (Multi)Polygon -> manifold CrossSection."""
    polys = geom.geoms if isinstance(geom, MultiPolygon) else [geom]
    contours = []
    for p in polys:
        if p.is_empty:
            continue
        contours.append(np.array(p.exterior.coords)[:-1])
        contours += [np.array(i.coords)[:-1] for i in p.interiors]
    return mf.CrossSection(contours, mf.FillRule.EvenOdd)


def slab(geom, z0, z1):
    cs = to_cs(geom.simplify(0.01)).simplify(0.01)   # drops near-duplicate outline points that pinch in float32 STL
    return mf.Manifold.extrude(cs, z1 - z0).translate((0, 0, z0))


def square(cx, cy, s, ang, sy=None):
    sy = s if sy is None else sy
    r = Polygon([(-s / 2, -sy / 2), (s / 2, -sy / 2), (s / 2, sy / 2), (-s / 2, sy / 2)])
    return affinity.translate(affinity.rotate(r, ang, origin=(0, 0)), cx, cy)


def hole_tool(cx, cy, ang, hole, ch, z_top):
    """Cutout with a 45 deg chamfer at z_top, built as one 12-vertex solid so nothing coincides."""
    e = 0.05
    rings = [(hole, -0.1), (hole, z_top - ch), (hole + 2 * (ch + e), z_top + e)]
    v = np.array([(sx * s / 2, sy * s / 2, z) for s, z in rings
                  for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))], np.float32)
    f = [(0, 2, 1), (0, 3, 2), (8, 9, 10), (8, 10, 11)]          # bottom, top
    for r in range(2):
        for i in range(4):
            a, b = 4 * r + i, 4 * r + (i + 1) % 4
            f += [(a, b, b + 4), (a, b + 4, a + 4)]
    m = mf.Manifold(mf.Mesh(vert_properties=v, tri_verts=np.array(f, np.uint32)))
    assert m.status() == mf.Error.NoError and m.volume() > 0, m.status()
    return m.rotate((0, 0, ang)).translate((cx, cy, 0))


def to_trimesh(m):
    mesh = m.to_mesh()
    return trimesh.Trimesh(vertices=np.asarray(mesh.vert_properties)[:, :3],
                           faces=np.asarray(mesh.tri_verts), process=True)


def clean(geom, w):
    """Morphological opening: drops features narrower than w."""
    return geom.buffer(-w / 2, join_style=2).buffer(w / 2, join_style=2).intersection(geom)


# ------------------------------------------------------------------ inputs
def read_plate(path):
    m = trimesh.load(path)
    sec = m.section(plane_origin=[0, 0, 0.6], plane_normal=[0, 0, 1])
    p2, _ = sec.to_2D(to_2D=np.eye(4))
    poly = max(p2.polygons_full, key=lambda q: q.area)
    keys, mounts = [], []
    for ring in poly.interiors:
        h = Polygon(ring)
        if h.area > 100:
            r = np.array(h.minimum_rotated_rectangle.exterior.coords)[:4]
            ang = np.degrees(np.arctan2(*(r[1] - r[0])[::-1])) % 90
            ang = 0.0 if min(ang, 90 - ang) < 0.05 else (ang if ang < 45 else ang - 90)
            keys.append((h.centroid.x, h.centroid.y, round(ang, 3)))
        else:
            mounts.append((h.centroid.x, h.centroid.y, 2 * np.sqrt(h.area / np.pi)))
    return Polygon(poly.exterior), keys, mounts


def read_keepouts(path, band):
    """XY footprints (plate frame) of every non-PCB body that reaches into the web's Z band."""
    m = trimesh.load(path)
    m.apply_scale(1000)
    z_lo, z_hi = band
    out = []
    for b in m.split(only_watertight=False):
        if b.bounds[1][0] < 0 or b.extents[0] > 120:   # left half, PCBs and plates
            continue
        z = -(b.vertices[:, 1] - P['sandwich_y0'])     # sandwich Y -> plate Z
        sel = (z > z_lo - 0.05) & (z < z_hi + 0.05)
        if not sel.any() and not (z.min() < z_lo and z.max() > z_hi):
            continue
        xy = np.c_[b.vertices[:, 0], b.vertices[:, 2] - P['sandwich_dz']]
        hull = MultiPoint(xy).convex_hull
        out.append(hull.buffer(P['keepout_buf']) if hull.area > 0 else hull.buffer(P['keepout_buf'] + 0.1))
    return unary_union(out)


# ------------------------------------------------------------------ parts
def build_plate(outline, keys, mounts, keepout):
    hole, lip, web = P['hole'], P['lip_t'], P['web_t']
    lip2d = outline.difference(unary_union([Point(x, y).buffer(d / 2, 64) for x, y, d in mounts]))
    web2d = outline.buffer(-0.05, join_style=2).difference(unary_union(   # inset: no faces shared with the lip
        [square(x, y, P['pocket'], a) for x, y, a in keys] +
        [Point(x, y).buffer(d / 2, 64) for x, y, d in mounts] + [keepout]))
    web2d = clean(web2d, P['min_feature'])
    plate = slab(lip2d, 0, lip)
    plate -= mf.Manifold.batch_boolean([hole_tool(x, y, a, hole, P['hole_chamfer'], lip) for x, y, a in keys],
                                       mf.OpType.Add)
    plate += slab(web2d, -web, 0.01)
    return plate, lip2d, web2d


def build_fit_test():
    n = len(P['fit_sizes'])
    cx, cy = P['cell_x'], P['cell_y']
    W, H = n * cx + 4, cy + 8
    outline = square(W / 2 - 2, cy / 2 + 2, W, 0, H)   # dot strip along +Y
    keys = [(i * cx + cx / 2, cy / 2, 0.0) for i in range(n)]
    web2d = outline.difference(unary_union([square(x, y, P['pocket'], 0) for x, y, _ in keys]))
    part = slab(outline, 0, P['lip_t'])
    for (x, y, _), s in zip(keys, P['fit_sizes']):
        part -= hole_tool(x, y, 0, s, P['hole_chamfer'], P['lip_t'])
    part += slab(web2d, -P['web_t'], 0.01)
    # 1..n dots on the web side (top of the print), above each cutout
    for i, (x, y, _) in enumerate(keys):
        for j in range(i + 1):
            dx = (j - i / 2) * (P['dot_d'] + 0.8)
            part += mf.Manifold.cylinder(P['dot_h'] + 0.01, P['dot_d'] / 2, P['dot_d'] / 2, 32) \
                .translate((x + dx, cy + 2.8, -P['web_t'] - P['dot_h']))
    return part


def print_orient(m):
    """Plate top on the bed."""
    m = m.rotate((180, 0, 0))
    return m.translate((0, 0, -m.bounding_box()[2]))


# ------------------------------------------------------------------ main
def main(plate_stl, sandwich_stl, out):
    os.makedirs(out, exist_ok=True)
    outline, keys, mounts = read_plate(plate_stl)
    keepout = read_keepouts(sandwich_stl, (-P['web_t'], 0.0))
    plate, lip2d, web2d = build_plate(outline, keys, mounts, keepout)
    fit = build_fit_test()

    to_trimesh(plate).export(os.path.join(out, 'thick_plate_insitu.stl'))
    to_trimesh(print_orient(plate)).export(os.path.join(out, 'thick_plate_print_right.stl'))
    to_trimesh(print_orient(plate.mirror((1, 0, 0)))).export(os.path.join(out, 'thick_plate_print_left.stl'))
    to_trimesh(print_orient(fit)).export(os.path.join(out, 'thick_plate_fit_test.stl'))

    t = to_trimesh(plate)
    report = dict(params=P, keys=len(keys), mounts=len(mounts),
                  total_thickness=round(P['lip_t'] + P['web_t'], 3),
                  watertight=bool(t.is_watertight), volume_mm3=round(t.volume, 1),
                  bounds=np.round(t.bounds, 3).tolist(),
                  web_area_mm2=round(web2d.area, 1))
    json.dump(report, open(os.path.join(out, 'report.json'), 'w'), indent=2)
    print(json.dumps(report, indent=2))
    return plate, keepout


if __name__ == '__main__':
    main(*sys.argv[1:4])
