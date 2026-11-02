"""Build an interactive placement page for a graphic on one keyboard half.

The page shows the real cap tops, nice!view cover and case rim of the chosen half,
with the graphic on top. Drag it, scale it, rotate it, and see live which parts of
it end up inlaid (bright) and which fall between keys (faint). Then press
"Save config" to download a config with that placement, or copy the placement
block into your existing config, and run overlay.py on it.

Usage (from keycaps/overlay):
  python3 placement_tool.py configs/my-art.json                     # half from placement.fit, default left
  python3 placement_tool.py configs/my-art.json --half left
writes out/<config file name>/<config file name>_placement.html, a single self-contained file to open in any browser.

The page writes the placement as fit "none": scale is mm per SVG unit, offset is
the graphic's center in the board frame (mm), rotate is degrees CCW. overlay.py
reads exactly these numbers, so what you see is what gets inlaid.
"""
import sys, os, json, argparse
import numpy as np
from shapely import affinity
from shapely.geometry import Polygon
import overlay as o


def path_d(g, nd=2):
    out = []
    for p in o.polys(g):
        for r in [p.exterior] + list(p.interiors):
            xy = np.asarray(r.coords)[:-1]
            out.append('M' + 'L'.join(f'{x:.{nd}f},{y:.{nd}f}' for x, y in xy) + 'Z')
    return ''.join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('config')
    ap.add_argument('--half', choices=['left', 'right'])
    ap.add_argument('--out')
    a = ap.parse_args()
    raw_cfg = json.load(open(a.config))
    C = o.merge(o.DEFAULTS, raw_cfg)
    C['name'] = o.config_name(a.config)   # same output folder as overlay.py
    C['_with_disabled'] = True    # show a switched-off plate/case so it can be switched back on
    P = C['placement']
    half = a.half or (P['fit'] if P['fit'] in ('left', 'right') else 'left')

    keys = [k for k in o.build_layout(C) if k['half'] == half]
    shapes = o.load_shapes(C, keys)
    cfg_dir = os.path.dirname(os.path.abspath(a.config))
    g0 = o.load_graphic(C['graphic'], cfg_dir)
    if P['mirror']:
        g0 = affinity.scale(g0, -1, 1, origin='centroid')
    b = g0.bounds
    g0c = affinity.translate(g0, -(b[0] + b[2]) / 2, -(b[1] + b[3]) / 2)   # what overlay.py rotates and scales

    # starting placement = what overlay.py currently does with this config, as absolute numbers
    all_keys = o.build_layout(C)
    placed = o.place_graphic(o.load_graphic(C['graphic'], cfg_dir), P, all_keys, o.load_shapes(C, all_keys))
    probe = affinity.rotate(g0c, P['rotate'], origin=(0, 0))
    s_abs = (placed.bounds[2] - placed.bounds[0]) / (probe.bounds[2] - probe.bounds[0])
    cx, cy = (placed.bounds[0] + placed.bounds[2]) / 2, (placed.bounds[1] + placed.bounds[3]) / 2
    pb = affinity.scale(probe, s_abs, s_abs, origin=(0, 0)).bounds      # rotated bbox center offset
    cx -= (pb[0] + pb[2]) / 2
    cy -= (pb[1] + pb[3]) / 2

    parts = []
    for k in keys:
        s = o.shape_of(k, shapes)
        parts.append(dict(id=k['id'], kind=k['shape'] if k['shape'] in ('case', 'plate', 'cover') else 'cap',
                          d=path_d(o.to_world_2d(s.raw.simplify(0.05), k)), x=k['x'], y=k['y']))
    allg = [o.to_world_2d(o.shape_of(k, shapes).raw, k) for k in keys]
    xs = [g.bounds[0] for g in allg] + [g.bounds[2] for g in allg]
    ys = [g.bounds[1] for g in allg] + [g.bounds[3] for g in allg]
    view = [min(xs) - 15, min(ys) - 15, max(xs) - min(xs) + 30, max(ys) - min(ys) + 30]

    data = dict(name=C['name'], half=half, parts=parts, graphic=path_d(g0c, 3), view=view,
                start=dict(scale=round(s_abs, 4), rotate=float(P['rotate']), x=round(cx, 2), y=round(cy, 2)),
                colors=C['colors'], config=raw_cfg,
                plate_on=bool(C['plate'] and C['plate'].get('enabled', True)), config_file=os.path.basename(a.config))
    out = a.out or os.path.join(o.HERE, 'out', C['name'])
    os.makedirs(out, exist_ok=True)
    fn = os.path.join(out, f'{C["name"]}_placement.html')
    html = open(os.path.join(o.HERE, 'placement_tool.html')).read().replace('/*DATA*/null', json.dumps(data))
    open(fn, 'w').write(html)
    print('wrote', fn)


if __name__ == '__main__':
    main()
