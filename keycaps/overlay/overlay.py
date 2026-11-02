"""Project a 2D graphic across a virtual Typeractive Corne and inlay it into the keycap tops.

Every keycap (and optionally the nice!view cover) becomes one "pixel" of the
graphic: the part of the graphic that lands on a cap is inlaid into its top
surface to a vertical depth of `depth` (default 0.6 mm). Each cap is split into
two bodies, base and inlay, and written as a Bambu Studio multi-part 3MF
(base = filament 1, inlay = filament 2). Where the cap is thinner than `depth`
the inlay simply runs all the way through, so that region is fully the
alternate color.

Board frame (mm): +X right, +Y away from the typist (north), Z up. The two
halves sit either side of X=0 with `gap` between their inner edges. The right
half uses the plate frame of typeractive/case-designs/simple-sandwich/
switch-plate.stl, shifted in X; the left half is its mirror image. V5 keycaps are
never mirrored, only placed and rotated, so the left half uses the same STLs. The
thumb caps are right-handed and are mirrored for the left (`mirror_left`).

Pipeline:
  1. layout    switch positions from switch-plate.stl (Choc v1, 18 x 17 pitch),
               a keycap STL and spin per position, the nice!view cover.
  2. graphic   SVG paths (filtered by fill color) -> shapely polygons, fitted
               to the target half (or placed explicitly) in the board frame.
  3. inlay     per cap: top region from a heightmap (slopes under `max_slope`,
               so side walls never get color), graphic clipped to it and
               cleaned of features under `min_feature`, then
               inlay = cap ∩ prism(region) − (cap shifted down by depth).
  4. outputs   print-ready 3MF per half, assembled colored GLB, 2D map,
               report.json. render.py makes the 3D preview PNGs.

Usage (from keycaps/overlay):
  python3 overlay.py configs/my-art.json          # writes out/my-art/
  python3 overlay.py configs/my-art.json --stl    # also base/inlay STL pairs per half

Needs: numpy trimesh manifold3d shapely svgpathtools contourpy matplotlib
License: CC BY-NC-SA 4.0 (see repo LICENSE).
"""
import sys, os, re, json, zipfile, argparse
from xml.sax.saxutils import escape
import numpy as np
import trimesh
import manifold3d as mf
import contourpy
from svgpathtools import svg2paths2
from shapely.geometry import Polygon, MultiPolygon, box
from shapely.ops import unary_union
from shapely import affinity

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, '..', '..'))

# ---------------------------------------------------------------- defaults
# Every key here can be overridden from the config JSON (nested dicts merge).
DEFAULTS = dict(
    name='overlay',
    graphic=dict(
        svg=None,              # path relative to the config file
        fill=None,             # list of fill colors to keep (e.g. ["#30BA78"]); None keeps every path
        samples_per_mm=4,      # curve sampling density in final mm
    ),
    placement=dict(
        fit='right',           # 'right' | 'left' | 'both' | 'none' : fit the graphic's bbox into that target
        include_cover=True,    # count the nice!view cover as part of the fit target
        margin=0.0,            # mm inside the fit target's bounding box
        scale=1.0,             # multiplies the fitted scale (fit='none': mm per SVG unit)
        offset=[0.0, 0.0],     # mm, applied after fitting
        rotate=0.0,            # degrees CCW about the graphic's center
        mirror=False,          # flip the graphic left-right
    ),
    halves=['right', 'left'],  # which halves to build
    gap=40.0,                  # mm between the halves' inner edges (only affects 'both' fits and previews)
    depth=0.6,                 # vertical inlay depth, mm
    min_feature=0.3,           # inlay/base features narrower than this (in XY) are dropped
    max_slope=55.0,            # degrees; steeper cap surfaces (edge roll-off, side walls) never get color
    mode='inlay',              # 'inlay': true shape on each cap | 'pixel': whole cap top colored when covered
    pixel_threshold=0.5,       # 'pixel' mode: fraction of the cap top the graphic must cover
    invert=False,              # color everything except the graphic
    include_cover=True,        # inlay the nice!view cover too
    # Optional case: the graphic goes into the top of its rim. Given in the plate frame
    # (as the case-design STLs are), right-hand; the left half gets the mirror image.
    # stl: path from the repo root; the largest body in the file is used.
    # top_z: rim height in the board frame for previews (plate top = 1.2).
    case=None,
    # Optional switch plate, same keys as `case` plus print_flip (true: printed top-down,
    # as thick_plate.py's print STLs are). Its top shows between the caps.
    plate=None,
    # Either can carry "enabled": false to leave it out (the placement page's toggle sets this).
    cap_z=3.0,                 # cap rim height above the plate top (preview only)
    print_spacing=4.0,         # mm min gap between parts on the print plate
    bed=[256, 256],            # mm print bed, for the combined <name>_<half>_all.3mf
    # Which side each cap prints on, in the cap STL's own frame seen from above:
    # A = +Y, B = +X, C = -Y, D = -X (see print-sides.png). Chosen by
    # mak3r 2026-11-02. For mirrored caps (mirror_left) B and D swap automatically,
    # so the same physical face goes down. None = upright, rim on the bed.
    print_side={'raised-upper': 'C', 'raised-lower': 'C', 'normal': 'A', 'normal-home': 'A',
                'thumb-1.5': 'A', 'thumb-center': 'D', 'thumb-outer': 'C'},
    colors=dict(base='#1E1E1E', inlay='#30BA78'),
    # Keycap assignment. Rows are numbered from the top (0) of each column, columns
    # from the inner (thumb-side) column (0) outward.
    rows=['raised-upper', 'normal', 'raised-lower'],
    home_keys=[[1, 1]],        # [col, row] -> normal-home (index-finger home key)
    # Spin (deg CCW) added to each cap's switch angle so the STL sits the right way
    # round. STL -Y is the light-bar side on every V5 cap except raised-lower, and
    # raised caps have their tall edge on STL -Y, so 180 puts the light bar north
    # and raised-upper's tall edge away from the home row.
    spin={'raised-upper': 180, 'normal': 180, 'normal-home': 180, 'raised-lower': 0,
          'thumb-1.5': 0, 'thumb-center': 0, 'thumb-outer': 0},
    # Extra spin per half, on top of `spin`. The left thumbs are mirrored copies
    # (`mirror_left`), and two of them then need a quarter turn to sit right
    # (checked by mak3r in Bambu Studio, 2026-11-02). A config only needs this key
    # to change it; its entries are merged over these.
    spin_half={'left': {'thumb-1.5': 180, 'thumb-center': 90, 'thumb-outer': -90}},
    # Thumb keys from the innermost (toward the other half) outward.
    thumbs=['thumb-1.5', 'thumb-center', 'thumb-outer'],
    # Cap STLs drawn for the right half that the left half needs as a mirror image
    # (flipped left-right in the STL's own frame before placing). The thumbs are
    # right-handed; the V5 caps are symmetric and are only rotated.
    mirror_left=['thumb-1.5', 'thumb-center', 'thumb-outer'],
)

CAP_FILES = {
    'raised-upper': 'keycaps/MKC V5/raised-upper.stl',
    'raised-lower': 'keycaps/MKC V5/raised-lower.stl',
    'normal': 'keycaps/MKC V5/normal.stl',
    'normal-home': 'keycaps/MKC V5/normal-home.stl',
    'thumb-1.5': 'keycaps/MKC Thumbs/thumb-1.5.stl',
    'thumb-center': 'keycaps/MKC Thumbs/thumb-center.stl',
    'thumb-outer': 'keycaps/MKC Thumbs/thumb-outer.stl',
}
PLATE_STL = 'typeractive/case-designs/simple-sandwich/switch-plate.stl'
COVER_STL = 'typeractive/case-designs/simple-sandwich/lcd-cover.stl'


def merge(a, b):
    out = dict(a)
    for k, v in b.items():
        out[k] = merge(a[k], v) if isinstance(v, dict) and isinstance(a.get(k), dict) else v
    return out


# ------------------------------------------------------------------ geometry helpers
def load_manifold(path, mirror=False, upright=False):
    m = trimesh.load(path)
    M = mf.Manifold(mf.Mesh(vert_properties=np.asarray(m.vertices, np.float32),
                            tri_verts=np.asarray(m.faces, np.uint32)))
    assert M.status() == mf.Error.NoError, (path, M.status())
    if upright:
        # Caps are expected rim down at z=0, top up. A cap STL exported top-down
        # (everything at z <= 0) is turned over about Y and put back on z=0. About Y,
        # not X: that keeps STL +Y (the cap's front/back) where the designer drew it
        # (checked by mak3r on thumb-1.5, 2026-11-02).
        lo = M.bounding_box()
        if lo[5] <= 0.01 and lo[2] < -0.5:
            print(f'note: {os.path.basename(path)} is upside down (z {lo[2]:.2f}..{lo[5]:.2f}); turning it over about Y')
            M = M.rotate((0, 180, 0))
        M = M.translate((0, 0, -M.bounding_box()[2]))
    return M.mirror((1, 0, 0)) if mirror else M


def to_trimesh(M):
    mesh = M.to_mesh()
    return trimesh.Trimesh(np.asarray(mesh.vert_properties)[:, :3], np.asarray(mesh.tri_verts), process=False)


def to_cs(geom):
    polys = geom.geoms if isinstance(geom, MultiPolygon) else [geom]
    contours = []
    for p in polys:
        if p.is_empty:
            continue
        contours.append(np.array(p.exterior.coords)[:-1])
        contours += [np.array(i.coords)[:-1] for i in p.interiors]
    return mf.CrossSection(contours, mf.FillRule.EvenOdd)


def prism(geom, z0, z1):
    return mf.Manifold.extrude(to_cs(geom), z1 - z0).translate((0, 0, z0))


def polys(g):
    if g.is_empty:
        return []
    if isinstance(g, Polygon):
        return [g]
    return [p for p in getattr(g, 'geoms', []) if isinstance(p, Polygon) and not p.is_empty]


def as_poly(g):
    return MultiPolygon(polys(g)) if not isinstance(g, Polygon) else g


def clean(g, w):
    """Drop features narrower than w: closing (fills slivers of base) then opening (drops slivers of inlay)."""
    if w <= 0 or g.is_empty:
        return g
    g = g.buffer(w / 2, join_style=2).buffer(-w / 2, join_style=2)
    return as_poly(g.buffer(-w / 2, join_style=2).buffer(w / 2, join_style=2))


# ------------------------------------------------------------------ layout
def read_switches(path):
    """Switch cutouts (x, y, angle) from the 1.2 mm plate, same method as thick_plate.py."""
    m = trimesh.load(path)
    sec = m.section(plane_origin=[0, 0, 0.6], plane_normal=[0, 0, 1])
    p2, _ = sec.to_2D(to_2D=np.eye(4))
    poly = max(p2.polygons_full, key=lambda q: q.area)
    keys = []
    for ring in poly.interiors:
        h = Polygon(ring)
        if h.area > 100:
            r = np.array(h.minimum_rotated_rectangle.exterior.coords)[:4]
            ang = np.degrees(np.arctan2(*(r[1] - r[0])[::-1])) % 90
            ang = 0.0 if min(ang, 90 - ang) < 0.05 else (ang if ang < 45 else ang - 90)
            keys.append((h.centroid.x, h.centroid.y, round(ang, 2)))
    return keys


def build_layout(C):
    """List of key dicts for both halves in the board frame."""
    sw = read_switches(os.path.join(REPO, PLATE_STL))
    grid = [k for k in sw if k[2] == 0 and k[1] > -10]
    thumbs = sorted([k for k in sw if k not in grid], key=lambda k: k[0])   # inner -> outer
    xs = sorted({round(k[0], 1) for k in grid})
    cover = trimesh.load(os.path.join(REPO, COVER_STL))
    x_in = min(cover.bounds[0][0], min(k[0] for k in sw) - 9)               # inner edge of the half
    home = {tuple(h) for h in C['home_keys']}
    keys = []
    for half in ('right', 'left'):
        sgn = 1 if half == 'right' else -1
        def place(x, y):
            return sgn * (x - x_in + C['gap'] / 2), y
        for ci, cx in enumerate(xs):
            col = sorted([k for k in grid if abs(k[0] - cx) < 0.5], key=lambda k: -k[1])
            for ri, (x, y, a) in enumerate(col):
                shape = 'normal-home' if (ci, ri) in home else C['rows'][ri]
                X, Y = place(x, y)
                keys.append(dict(id=f"{half[0].upper()}-C{ci + 1}R{ri + 1}", half=half, shape=shape,
                                 x=X, y=Y, switch_angle=sgn * a))
        for ti, ((x, y, a), shape) in enumerate(zip(thumbs, C['thumbs'])):
            X, Y = place(x, y)
            keys.append(dict(id=f"{half[0].upper()}-T{ti + 1}", half=half, shape=shape,
                             x=X, y=Y, switch_angle=sgn * a))
        if half == 'left':
            for k in keys:
                if k['half'] == 'left' and k['shape'] in C['mirror_left']:
                    k['mirror'] = True
        for kind in FRAME_PARTS:
            if C[kind] and (C[kind].get('enabled', True) or C.get('_with_disabled')):
                X, _ = place(read_frame(C, kind).bounds[0][0], 0)
                keys.append(dict(id=f"{half[0].upper()}-{kind.upper()}", half=half, shape=kind,
                                 x=X, y=0.0, switch_angle=0.0, mirror=half == 'left'))
        if C['include_cover']:
            X, _ = place(cover.bounds[0][0], 0)
            keys.append(dict(id=f"{half[0].upper()}-COVER", half=half, shape='cover',
                             x=X, y=0.0, switch_angle=0.0, mirror=half == 'left'))
    for k in keys:
        if k['shape'] not in ('cover',) + FRAME_PARTS:
            k['angle'] = k['switch_angle'] + C['spin'].get(k['shape'], 0) + \
                C['spin_half'].get(k['half'], {}).get(k['shape'], 0)
        else:
            k['angle'] = 0.0
    return keys


FRAME_PARTS = ('case', 'plate')   # flat-topped parts given in the plate frame (right-hand)
_frame_cache = {}


def read_frame(C, kind):
    """Largest body of the case/plate STL (case print layouts also hold the tent struts)."""
    path = os.path.join(REPO, C[kind]['stl'])
    if path not in _frame_cache:
        _frame_cache[path] = max(trimesh.load(path).split(only_watertight=False), key=lambda b: b.volume)
    return _frame_cache[path]


# ------------------------------------------------------------------ cap shapes
class Shape:
    """A cap (or cover) in its own frame, with its printable top region."""

    def __init__(self, name, M, max_slope, res=0.08, flat_top=False):
        self.name, self.M = name, M
        t = to_trimesh(M)
        if flat_top:
            # A flat rim (the case): the colorable top is exactly the section just under
            # the highest face. No hull, since the rim is a ring around the plate.
            z = t.bounds[1][2]
            sec = t.section(plane_origin=[0, 0, z - 0.05], plane_normal=[0, 0, 1])
            p2, _ = sec.to_2D(to_2D=np.eye(4))
            self.raw = self.top = as_poly(unary_union(p2.polygons_full))
            self.top_zmin = self.top_zmax = float(z)
            self.z0 = float(t.bounds[0][2])
            return
        lo, hi = t.bounds
        xs = np.arange(lo[0] - res, hi[0] + res, res)
        ys = np.arange(lo[1] - res, hi[1] + res, res)
        X, Y = np.meshgrid(xs, ys)
        o = np.c_[X.ravel(), Y.ravel(), np.full(X.size, hi[2] + 5)]
        loc, ri, _ = t.ray.intersects_location(o, np.tile([0, 0, -1.0], (len(o), 1)), multiple_hits=False)
        H = np.full(X.size, np.nan)
        H[ri] = loc[:, 2]
        H = H.reshape(X.shape)
        gy, gx = np.gradient(np.nan_to_num(H, nan=-50), res)
        ok = np.isfinite(H) & (np.hypot(gx, gy) < np.tan(np.radians(max_slope)))
        filled = contourpy.contour_generator(xs, ys, ok.astype(float), fill_type='OuterOffset').filled(0.5, 1.5)
        parts = []
        for pts, offs in zip(*filled):
            rings = [pts[offs[i]:offs[i + 1]] for i in range(len(offs) - 1)]
            p = Polygon(rings[0], rings[1:]).buffer(0)
            if p.area > 1:
                parts.append(p)
        # Each part is replaced by its convex hull. The slope threshold crosses the STL's
        # facets in small steps, which would print as a ragged color edge; the hull gives a
        # clean line. It also fills holes: a home bump's steep sides would otherwise leave
        # a ring of base color, and over a real hole (the cover window) there is no
        # material to color anyway. Every current cap and the cover are convex in plan.
        self.raw = as_poly(unary_union(parts))      # true colorable area (with holes), for coverage and the map
        self.top = as_poly(unary_union([p.convex_hull for p in parts]).simplify(0.01))
        self.H, self.xs, self.ys = H, xs, ys
        inside = ok & np.isfinite(H)
        self.top_zmin = float(np.nanmin(H[inside]))
        self.top_zmax = float(np.nanmax(H[inside]))
        self.z0 = float(lo[2])


def load_shapes(C, keys):
    shapes = {}
    for k in keys:
        s = k['shape'] + ('-mirror' if k.get('mirror') else '')
        if s in shapes:
            continue
        if k['shape'] == 'cover':
            M = load_manifold(os.path.join(REPO, COVER_STL), mirror=k.get('mirror', False))
            lo = M.bounding_box()
            # cover frame: inner edge of the half at x=0 (mirrored: x<=0), base at z=0
            cx = lo[0] if not k.get('mirror') else lo[3]
            M = M.translate((-cx, 0, -lo[2]))
        elif k['shape'] in FRAME_PARTS:
            b = read_frame(C, k['shape'])
            M = mf.Manifold(mf.Mesh(vert_properties=np.asarray(b.vertices, np.float32),
                                    tri_verts=np.asarray(b.faces, np.uint32)))
            if k.get('mirror'):
                M = M.mirror((1, 0, 0))
            lo = M.bounding_box()
            cx = lo[0] if not k.get('mirror') else lo[3]     # same frame convention as the cover
            M = M.translate((-cx, 0, -lo[2]))
            shapes[s] = Shape(s, M, C['max_slope'], flat_top=True)
            continue
        else:
            M = load_manifold(os.path.join(REPO, CAP_FILES[k['shape']]), mirror=k.get('mirror', False),
                              upright=True)
        shapes[s] = Shape(s, M, C['max_slope'])
    return shapes


def shape_of(k, shapes):
    return shapes[k['shape'] + ('-mirror' if k.get('mirror') else '')]


def to_world_2d(g, k):
    return affinity.translate(affinity.rotate(g, k['angle'], origin=(0, 0)), k['x'], k['y'])


def to_local_2d(g, k):
    return affinity.rotate(affinity.translate(g, -k['x'], -k['y']), -k['angle'], origin=(0, 0))


def world_z(k, shape, C):
    """Rim height in the board frame (plate top = 1.2). Cover keeps its own height from the STL."""
    if k['shape'] == 'cover':
        return trimesh.load(os.path.join(REPO, COVER_STL)).bounds[0][2]
    if k['shape'] in FRAME_PARTS:
        return C[k['shape']].get('top_z', 1.2) - shape.top_zmax
    return 1.2 + C['cap_z']


def to_world_3d(M, k, z):
    return M.rotate((0, 0, k['angle'])).translate((k['x'], k['y'], z))


# ------------------------------------------------------------------ graphic
def load_graphic(G, cfg_dir):
    path = os.path.join(cfg_dir, G['svg'])
    paths, attrs, _ = svg2paths2(path)
    keep = [c.lower() for c in G['fill']] if G.get('fill') else None
    shapes = []
    for p, a in zip(paths, attrs):
        fill = (a.get('fill') or '').lower()
        if not fill and 'style' in a:
            for kv in a['style'].split(';'):
                if kv.strip().startswith('fill:'):
                    fill = kv.split(':', 1)[1].strip().lower()
        if keep is not None and fill not in keep:
            continue
        g = None
        for sp in p.continuous_subpaths():
            n = max(8, int(sp.length() * 2))
            pts = [sp.point(t) for t in np.linspace(0, 1, n)]
            ring = Polygon([(z.real, -z.imag) for z in pts]).buffer(0)   # SVG Y is down
            if ring.area < 1e-6:
                continue
            g = ring if g is None else g.symmetric_difference(ring)      # even-odd fill
        if g is not None:
            shapes.append(g)
    if not shapes:
        raise SystemExit(f'no paths matched fill {keep} in {path}')
    return as_poly(unary_union(shapes))


def place_graphic(g, P, keys, shapes):
    if P['mirror']:
        g = affinity.scale(g, -1, 1, origin='centroid')
    minx, miny, maxx, maxy = g.bounds
    c = ((minx + maxx) / 2, (miny + maxy) / 2)
    g = affinity.translate(g, -c[0], -c[1])
    g = affinity.rotate(g, P['rotate'], origin=(0, 0))
    gw, gh = g.bounds[2] - g.bounds[0], g.bounds[3] - g.bounds[1]
    if P['fit'] == 'none':
        s, cx, cy = P['scale'], 0, 0
    else:
        tgt = [k for k in keys if (P['fit'] == 'both' or k['half'] == P['fit'])
               and (P['include_cover'] or k['shape'] != 'cover') and k['shape'] not in FRAME_PARTS]
        region = unary_union([to_world_2d(shape_of(k, shapes).top, k) for k in tgt])
        x0, y0, x1, y1 = region.bounds
        m = P['margin']
        s = min((x1 - x0 - 2 * m) / gw, (y1 - y0 - 2 * m) / gh) * P['scale']
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    g = affinity.scale(g, s, s, origin=(0, 0))
    return as_poly(affinity.translate(g, cx + P['offset'][0], cy + P['offset'][1]))


# ------------------------------------------------------------------ inlay
def split_cap(k, shape, graphic, C):
    """Returns (base, inlay or None, region2d_local, coverage) in the cap's own frame."""
    top = shape.top
    g_local = to_local_2d(graphic, k)
    cover = top.intersection(g_local)
    frac = shape.raw.intersection(g_local).area / shape.raw.area
    if C['mode'] == 'pixel' and k['shape'] not in FRAME_PARTS:
        region = top if frac >= C['pixel_threshold'] else Polygon()
    else:
        region = cover
    if C['invert']:
        region = top.difference(region)
    region = clean(as_poly(region.intersection(top)), C['min_feature'])
    region = as_poly(region.intersection(top))
    region = MultiPolygon([p for p in polys(region) if p.area > C['min_feature'] ** 2])
    if region.is_empty:
        return shape.M, None, region, frac
    d = C['depth']
    zlo = shape.top_zmin - d - 0.05          # keeps internal upward faces (e.g. an embedded pin) out
    cutter = prism(region, zlo, shape.top_zmax + 1.0)
    inlay = (shape.M ^ cutter) - shape.M.translate((0, 0, -d))
    # Keep only pieces that reach the top surface. Upward faces inside the cap (pocket
    # ledges, an embedded pin) and boolean slivers would otherwise become hidden specks
    # of inlay that cost a filament swap for nothing.
    keep = [p for p in inlay.decompose()
            if p.volume() > 0.05 and p.bounding_box()[5] >= shape.top_zmin - 0.01]
    inlay = mf.Manifold.batch_boolean(keep, mf.OpType.Add) if keep else mf.Manifold()
    if inlay.volume() < 1e-3:
        return shape.M, None, MultiPolygon(), frac
    base = shape.M - inlay
    return base, inlay, region, frac


# ------------------------------------------------------------------ 3MF (Bambu Studio)
def _mesh_xml(oid, name, t):
    v = '\n'.join(f'<vertex x="{a:.4f}" y="{b:.4f}" z="{c:.4f}"/>' for a, b, c in t.vertices)
    f = '\n'.join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in t.faces)
    return (f'<object id="{oid}" name="{escape(name)}" type="model"><mesh><vertices>\n{v}\n</vertices>'
            f'<triangles>\n{f}\n</triangles></mesh></object>\n')


def write_3mf(path, items):
    """items: list of (name, [(part_name, trimesh, extruder)], (tx, ty)).

    Each item becomes one object with one part per body, the way Bambu Studio
    saves a multi-part object, so it loads as a single cap with the inlay part
    already on filament 2.
    """
    objs, build, cfg = [], [], []
    oid = 1
    for name, parts, (tx, ty) in items:
        comp_ids = []
        for pname, t, _ in parts:
            objs.append(_mesh_xml(oid, f'{name}-{pname}', t))
            comp_ids.append(oid)
            oid += 1
        comps = ''.join(f'<component objectid="{c}"/>' for c in comp_ids)
        objs.append(f'<object id="{oid}" name="{escape(name)}" type="model"><components>{comps}</components></object>\n')
        build.append(f'<item objectid="{oid}" transform="1 0 0 0 1 0 0 0 1 {tx:.3f} {ty:.3f} 0" printable="1"/>')
        cfg.append(f'<object id="{oid}">\n<metadata key="name" value="{escape(name)}"/>\n'
                   f'<metadata key="extruder" value="{parts[0][2]}"/>\n' +
                   ''.join(f'<part id="{c}" subtype="normal_part">\n<metadata key="name" value="{escape(name)}-{escape(p[0])}"/>\n'
                           f'<metadata key="extruder" value="{p[2]}"/>\n</part>\n' for c, p in zip(comp_ids, parts)) +
                   '</object>')
        oid += 1
    model = ('<?xml version="1.0" encoding="UTF-8"?>\n'
             '<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">\n'
             '<metadata name="Application">BambuStudio-02.00.00.00</metadata>\n'   # so Bambu reads the part filaments
             '<metadata name="BambuStudio:3mfVersion">1</metadata>\n'
             '<metadata name="Title">MKC keycap overlay</metadata>\n'
             '<metadata name="License">CC BY-NC-SA 4.0</metadata>\n'
             f'<resources>\n{"".join(objs)}</resources>\n<build>\n' + '\n'.join(build) + '\n</build>\n</model>\n')
    ctypes = ('<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
              '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
              '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
              '<Default Extension="config" ContentType="text/xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
            '</Relationships>')
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', ctypes)
        z.writestr('_rels/.rels', rels)
        z.writestr('3D/3dmodel.model', model)
        z.writestr('Metadata/model_settings.config',
                   '<?xml version="1.0" encoding="UTF-8"?>\n<config>\n' + '\n'.join(cfg) + '\n</config>\n')


SIDES = {'A': (0, 1), 'B': (1, 0), 'C': (0, -1), 'D': (-1, 0)}


def side_down(M, side, mirrored=False):
    """Rotation (4x4) that lays a cap on one of its drafted flat sides, top facing +Y.

    The side's exact plane is found by tilting the horizontal side direction up to 25
    deg and keeping the tilt with the most mesh area flat on that plane."""
    if mirrored and side in 'BD':
        side = 'D' if side == 'B' else 'B'
    dx, dy = SIDES[side]
    m = to_trimesh(M)
    best = (-1, None)
    for tilt in np.radians(np.arange(0, 25.01, 0.25)):
        d = np.array([dx * np.cos(tilt), dy * np.cos(tilt), np.sin(tilt)])
        ext = (m.vertices @ d).max()
        sel = (m.face_normals @ d > np.cos(np.radians(1.5))) & (m.triangles_center @ d > ext - 0.05)
        a = m.area_faces[sel].sum()
        if a > best[0]:
            best = (a, d)
    R = trimesh.geometry.align_vectors(best[1], [0, 0, -1])
    up = R[:3, :3] @ [0, 0, 1]                                # where the cap top now points
    spin = np.arctan2(up[0], up[1])                           # turn it to face +Y
    return trimesh.transformations.rotation_matrix(spin, [0, 0, 1]) @ R


def side_layout(hk, parts_of, spacing):
    """Grid for caps lying on their sides: one column per keyboard column, one row per
    keyboard row, thumbs and cover in a last row. Returns item positions (x, y)."""
    def slot(k):
        mt = re.match(r'.-C(\d+)R(\d+)$', k['id'])
        if mt:
            return int(mt.group(1)) - 1, int(mt.group(2)) - 1
        mt = re.match(r'.-T(\d+)$', k['id'])
        return (int(mt.group(1)) - 1 if mt else 3), 9
    slots = {k['id']: slot(k) for k in hk}
    rows = sorted({v[1] for v in slots.values()})
    ext = {k['id']: parts_of(k)[0][1].bounds for k in hk}
    colw = {}
    for k in hk:
        if slots[k['id']][1] == 9:
            continue                      # the last row is laid out on its own below
        c = slots[k['id']][0]
        colw[c] = max(colw.get(c, 0), ext[k['id']][1][0] - ext[k['id']][0][0])
    rowh = {r_: max(ext[k['id']][1][1] - ext[k['id']][0][1] for k in hk if slots[k['id']][1] == r_) for r_ in rows}
    x0 = {c: sum(colw[cc] + spacing for cc in sorted(colw) if cc < c) for c in colw}
    y0 = {r_: -sum(rowh[rr] + spacing for rr in rows if rr < r_) for r_ in rows}
    pos, xl = [], 0.0
    for k in sorted(hk, key=lambda k: slots[k['id']]):
        c, r_ = slots[k['id']]
        lo, hi = ext[k['id']]
        if r_ == 9:                       # thumbs and cover: packed left to right
            x = xl - lo[0]
            xl += hi[0] - lo[0] + spacing
        else:
            x = x0[c] + colw[c] / 2 - (lo[0] + hi[0]) / 2
        pos.append((k['id'], (x, y0[r_] - rowh[r_] / 2 - (lo[1] + hi[1]) / 2)))
    pos = dict(pos)
    return [pos[k['id']] for k in hk]


def print_positions(keys, shapes, spacing):
    """Spread the keyboard layout out until no two parts are closer than `spacing`."""
    foot = [to_world_2d(shape_of(k, shapes).top.convex_hull.buffer(0.5), k) for k in keys]
    cx = np.mean([k['x'] for k in keys]); cy = np.mean([k['y'] for k in keys])
    for f in np.arange(1.0, 3.0, 0.02):
        moved = [affinity.translate(p, (k['x'] - cx) * (f - 1), (k['y'] - cy) * (f - 1)) for p, k in zip(foot, keys)]
        if all(moved[i].distance(moved[j]) >= spacing for i in range(len(moved)) for j in range(i + 1, len(moved))):
            break
    allb = unary_union(moved).bounds
    ox, oy = 128 - (allb[0] + allb[2]) / 2, 128 - (allb[1] + allb[3]) / 2   # center on a 256 mm bed
    return [((k['x'] - cx) * f + cx + ox, (k['y'] - cy) * f + cy + oy) for k in keys], f, (allb[2] - allb[0], allb[3] - allb[1])


def pack_blocks(blocks, bed, spacing):
    """Lay groups of 3MF items (caps, case, plate) side by side on one bed.

    blocks: list of item lists as for write_3mf. Each group keeps its own layout
    and may be turned 90 deg as a whole. Tries every order and turn with simple
    shelf packing (rows left to right) and keeps the arrangement with the smallest
    footprint that fits. Returns (items, fits, (w, h))."""
    import itertools

    def turned(items, q):
        out = []
        for name, parts, (tx, ty) in items:
            R = trimesh.transformations.rotation_matrix(np.pi / 2 * q, (0, 0, 1))
            parts = [(n, t.copy().apply_transform(R), e) for n, t, e in parts]
            c, s_ = np.cos(np.pi / 2 * q), np.sin(np.pi / 2 * q)
            out.append((name, parts, (c * tx - s_ * ty, s_ * tx + c * ty)))
        return out

    def bounds(items):
        b = np.array([t.bounds + [[tx, ty, 0], [tx, ty, 0]] for _, parts, (tx, ty) in items for _, t, _ in parts])
        return b[:, 0, :2].min(0), b[:, 1, :2].max(0)

    best = None
    for order in itertools.permutations(range(len(blocks))):
        for turns in itertools.product((0, 1), repeat=len(blocks)):
            placed, x, y, row_h, W = [], 0.0, 0.0, 0.0, 0.0
            for i, q in zip(order, turns):
                its = turned(blocks[i], q)
                lo, hi = bounds(its)
                w, h = hi - lo
                if x > 0 and x + w > bed[0]:
                    x, y, row_h = 0.0, y + row_h + spacing, 0.0
                placed.append((its, lo, (x, y)))
                W, x, row_h = max(W, x + w), x + w + spacing, max(row_h, h)
            H = y + row_h
            fits = W <= bed[0] and H <= bed[1]
            score = (not fits, max(W / bed[0], H / bed[1]))
            if best is None or score < best[0]:
                best = (score, placed, fits, (W, H))
    _, placed, fits, (W, H) = best
    ox, oy = (bed[0] - W) / 2, (bed[1] - H) / 2          # center the whole arrangement
    items = [(n, parts, (tx - lo[0] + x + ox, ty - lo[1] + y + oy))
             for its, lo, (x, y) in placed for n, parts, (tx, ty) in its]
    return items, fits, (W, H)


# ------------------------------------------------------------------ previews
def draw_map(path, keys, shapes, results, graphic, C):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import PathPatch
    from matplotlib.path import Path as MPath

    def patch(g, **kw):
        for p in polys(g):
            verts, codes = [], []
            for r in [p.exterior] + list(p.interiors):
                xy = np.asarray(r.coords)
                verts += xy.tolist()
                codes += [MPath.MOVETO] + [MPath.LINETO] * (len(xy) - 2) + [MPath.CLOSEPOLY]
            yield PathPatch(MPath(verts, codes), **kw)

    fig, ax = plt.subplots(figsize=(16, 7))
    for p in patch(graphic, fc='none', ec='#888', lw=0.6, ls='--'):
        ax.add_patch(p)
    order = {'case': 0, 'plate': 1}
    for k in sorted(keys, key=lambda k: order.get(k['shape'], 2)):     # case, then plate, under the caps
        s = shape_of(k, shapes)
        for p in patch(to_world_2d(s.raw, k), fc=C['colors']['base'], ec='k', lw=0.4):
            ax.add_patch(p)
        reg = results[k['id']]['region'].intersection(s.raw)
        for p in patch(to_world_2d(reg, k), fc=C['colors']['inlay'], ec='none'):
            ax.add_patch(p)
        ax.text(k['x'], k['y'], k['id'], ha='center', va='center', fontsize=5, color='#bbb')
    ax.autoscale_view()
    ax.set_aspect('equal')
    ax.set_title(f"{C['name']}: graphic (dashed) projected onto cap tops, inlay {C['depth']} mm")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


# ------------------------------------------------------------------ main
def config_name(path):
    return os.path.splitext(os.path.basename(path))[0]


def clean_outputs(out, name):
    """Remove results of an earlier run (and its renders) so the folder only holds this run.
    The placement page is kept: it's made by placement_tool.py, not by this script."""
    for fn in os.listdir(out):
        if fn == 'report.json' or (fn.startswith(name + '_') and not fn.endswith('_placement.html')
                                   and fn.rsplit('.', 1)[-1] in ('3mf', 'stl', 'glb', 'png')):
            os.remove(os.path.join(out, fn))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('config')
    ap.add_argument('--out', help='output dir (default out/<config file name> next to this script)')
    ap.add_argument('--stl', action='store_true', help='also write <name>_<half>_base/_inlay.stl (laid out, for any slicer)')
    a = ap.parse_args()
    C = merge(DEFAULTS, json.load(open(a.config)))
    C['name'] = config_name(a.config)      # outputs are named after the config file, not its "name" field
    out = a.out or os.path.join(HERE, 'out', C['name'])
    os.makedirs(out, exist_ok=True)
    clean_outputs(out, C['name'])

    keys = build_layout(C)
    shapes = load_shapes(C, keys)
    graphic = place_graphic(load_graphic(C['graphic'], os.path.dirname(os.path.abspath(a.config))),
                            C['placement'], keys, shapes)

    results = {}
    for k in keys:
        s = shape_of(k, shapes)
        base, inlay, region, frac = split_cap(k, s, graphic, C)
        results[k['id']] = dict(base=base, inlay=inlay, region=region, frac=frac)
        print(f"{k['id']:10s} {k['shape']:13s} coverage {frac:5.2f}  inlay {0 if inlay is None else inlay.volume():7.1f} mm3")

    # print-ready 3MF per half, laid out like the keyboard
    halves = {}
    for half in C['halves']:
        hk = [k for k in keys if k['half'] == half and k['shape'] not in FRAME_PARTS]
        side_of = {k['id']: C['print_side'].get(k['shape']) for k in hk}
        _pp = {}

        def parts_of(k):
            if k['id'] in _pp:
                return _pp[k['id']]
            r = results[k['id']]
            sd = side_of[k['id']]
            if sd:
                # print frame: cap lying on its chosen side, top facing +Y
                T = side_down(shape_of(k, shapes).M, sd, k.get('mirror', False))
                ms = [to_trimesh(r['base']).apply_transform(T)]
                if r['inlay'] is not None:
                    ms.append(to_trimesh(r['inlay']).apply_transform(T))
                z0 = ms[0].bounds[0][2]
                ms = [t.apply_translation((0, 0, -z0)) for t in ms]
            else:
                # print frame: rotated as on the board, rim on the bed. Next to caps lying
                # on their sides, the long cover is turned lengthwise so its row stays short.
                ang = k['angle']
                if any(side_of.values()) and k['shape'] == 'cover':
                    b = r['base'].bounding_box()
                    ang += 90 if b[4] - b[1] > b[3] - b[0] else 0
                ms = [to_trimesh(r['base'].rotate((0, 0, ang)))]
                if r['inlay'] is not None:
                    ms.append(to_trimesh(r['inlay'].rotate((0, 0, ang))))
            _pp[k['id']] = [('base', ms[0], 1)] + ([('inlay', ms[1], 2)] if len(ms) > 1 else [])
            return _pp[k['id']]

        if any(side_of.values()):
            pos = side_layout(hk, parts_of, C['print_spacing'])
            allb = np.array([[t.bounds[0][:2] + p, t.bounds[1][:2] + p] for k, p in zip(hk, np.array(pos))
                             for _, t, _ in parts_of(k)])
            lo_, hi_ = allb[:, 0].min(0), allb[:, 1].max(0)
            pos = [(x + 128 - (lo_[0] + hi_[0]) / 2, y + 128 - (lo_[1] + hi_[1]) / 2) for x, y in pos]
            f, size = 1.0, hi_ - lo_
        else:
            pos, f, size = print_positions(hk, shapes, C['print_spacing'])
        items = [(k['id'], parts_of(k), (px, py)) for k, (px, py) in zip(hk, pos)]
        touch = [k['id'] for k in hk if side_of[k['id']] and len(parts_of(k)) > 1
                 and parts_of(k)[1][1].bounds[0][2] < 0.05]
        if touch:   # the cap top meets the side it lies on, so a thin strip of color starts on the bed
            print(f"note: inlay reaches the bed edge on {len(touch)} caps ({', '.join(touch)})")
        fn = os.path.join(out, f'{C["name"]}_{half}.3mf')
        write_3mf(fn, items)
        # Fallback for any slicer: all bases in one STL, all inlays in another, already
        # laid out. Import both together and answer Yes to "load as a single object
        # with multiple parts", then set the inlay part to the second filament.
        for n, idx in (('base', 0), ('inlay', 1)) if a.stl else ():
            ts = [p[idx][1].copy().apply_translation((x, y, 0)) for _, p, (x, y) in items if len(p) > idx]
            if ts:
                trimesh.util.concatenate(ts).export(os.path.join(out, f'{C["name"]}_{half}_{n}.stl'))
        halves[half] = dict(file=os.path.basename(fn), spread=round(float(f), 2),
                            plate_size_mm=[round(float(x), 1) for x in size])
        blocks = [items]
        # the case and plate each get their own print plate: they don't fit beside the caps
        for k in [k for k in keys if k['half'] == half and k['shape'] in FRAME_PARTS]:
            r = results[k['id']]
            flip = C[k['shape']].get('print_flip', False)
            def prep(M):
                if not flip:
                    return to_trimesh(M)
                t = to_trimesh(M.rotate((180, 0, 0)))          # top on the bed (mirror_left caps are already mirrored)
                return t.apply_translation((0, 0, -to_trimesh(r['base'].rotate((180, 0, 0))).bounds[0][2]))
            parts = [('base', prep(r['base']), 1)]
            if r['inlay'] is not None:
                parts.append(('inlay', prep(r['inlay']), 2))
            lo, hi = parts[0][1].bounds
            cfn = os.path.join(out, f'{C["name"]}_{half}_{k["shape"]}.3mf')
            write_3mf(cfn, [(k['id'], parts, (128 - (lo[0] + hi[0]) / 2, 128 - (lo[1] + hi[1]) / 2))])
            halves[half][f'{k["shape"]}_file'] = os.path.basename(cfn)
            blocks.append([(k['id'], parts, (0.0, 0.0))])
        # everything for this half on one plate: caps + cover, case, switch plate
        if len(blocks) > 1:
            all_items, fits, size = pack_blocks(blocks, C['bed'], C['print_spacing'] * 2)
            afn = os.path.join(out, f'{C["name"]}_{half}_all.3mf')
            write_3mf(afn, all_items)
            halves[half]['all_file'] = os.path.basename(afn)
            halves[half]['all_size_mm'] = [round(float(v), 1) for v in size]
            if not fits:
                print(f'warning: {os.path.basename(afn)} needs {size[0]:.0f} x {size[1]:.0f} mm, '
                      f'more than the {C["bed"][0]} x {C["bed"][1]} mm bed; set "bed" in the config')

    # assembled, colored GLB (board frame, metres) for viewing; render.py reads it
    scene = trimesh.Scene()
    col = {n: trimesh.visual.color.hex_to_rgba(c) for n, c in C['colors'].items()}
    for k in keys:
        r = results[k['id']]
        z = world_z(k, shape_of(k, shapes), C)
        for n in ('base', 'inlay'):
            if r[n] is None:
                continue
            t = to_trimesh(to_world_3d(r[n], k, z))
            t.apply_scale(0.001)            # glTF is in metres
            t.visual = trimesh.visual.ColorVisuals(t, face_colors=np.tile(col[n], (len(t.faces), 1)))
            scene.add_geometry(t, node_name=f"{k['id']}-{n}", geom_name=f"{k['id']}-{n}")
    scene.export(os.path.join(out, f'{C["name"]}_assembled.glb'))

    draw_map(os.path.join(out, f'{C["name"]}_map.png'), keys, shapes, results, graphic, C)

    report = dict(
        name=C['name'], depth=C['depth'], mode=C['mode'], invert=C['invert'], placement=C['placement'],
        graphic_bounds_mm=[round(float(v), 2) for v in graphic.bounds],
        halves=halves,
        keys=[dict(id=k['id'], shape=k['shape'], x=round(k['x'], 2), y=round(k['y'], 2),
                   angle=round(k['angle'], 2), coverage=round(results[k['id']]['frac'], 3),
                   inlay_mm3=round(results[k['id']]['inlay'].volume(), 2) if results[k['id']]['inlay'] else 0,
                   watertight=bool(to_trimesh(results[k['id']]['base']).is_watertight))
              for k in keys])
    json.dump(report, open(os.path.join(out, 'report.json'), 'w'), indent=1)
    print('wrote', out)


if __name__ == '__main__':
    main()
