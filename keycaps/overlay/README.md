# Keycap graphic overlay

Spread a 2D graphic across the whole keyboard so that every keycap (and the
nice!view cover) shows its own piece of it, like a pixel in a larger picture.
The graphic is inlaid into each cap's top, so with two filaments you get a
solid color graphic instead of a painted or stuck-on one.

## How it works

1. **Virtual Corne.** `overlay.py` reads the switch cutouts from
   `typeractive/case-designs/simple-sandwich/switch-plate.stl` (Choc v1, 18 × 17
   pitch, same method as `thick_plate.py`) and puts a keycap STL on each
   switch: raised-upper on the top row, normal on the home row
   (normal-home on the index key), raised-lower on the bottom row, and the
   three MKC thumbs. `lcd-cover.stl` goes over the nice!view. The left half is
   a mirror image of the right one. Its V5 caps are only moved and rotated,
   never mirrored, so they're the same STLs you already print. The thumb caps
   are drawn for the right hand, so the left half gets mirrored copies
   (`mirror_left`). The cover is mirrored too.
2. **Graphic.** Paths are read from the SVG, filtered by fill color, and fitted
   into the chosen half (or both). Scale, offset, rotation and mirroring can
   be adjusted on top of the fit.
3. **Inlay.** For each cap, a heightmap finds the top surface. Only slopes
   under `max_slope` (55°) count as top, so the side walls never pick up a
   sliver of color. The graphic is clipped to that area, and anything thinner
   than `min_feature` (0.3 mm) is dropped. Then:
   `inlay = cap ∩ prism(graphic) − (cap shifted down by depth)`. That gives a
   layer exactly `depth` thick, measured straight down, which is the direction
   the printer builds layers. Where the cap is thinner than that, the inlay goes
   all the way through, so that spot is fully the second color. Specks that
   don't reach the top surface, such as upward-facing faces inside the pocket,
   are thrown away so they don't cost a filament swap.
4. **Outputs.** The base and the inlay are written as two parts of one object
   per cap.

## Outputs (`out/<name>/`)

`<name>` is the config's file name without `.json`, so
`configs/my-art-v2.json` goes to `out/my-art-v2/`.
The `"name"` field inside the config is ignored. Each run first deletes that
folder's earlier results and renders, so nothing stale is left behind. The
placement page is kept.

| File | What |
|---|---|
| `<name>_right.3mf`, `<name>_left.3mf` | Print plates for Bambu Studio. One object per cap with two parts: base (filament 1) and inlay (filament 2). The caps are laid out like the keyboard, just spread apart, so you can see where each one goes. Object names match the map (e.g. `R-C3R2` = right half, column 3 from the thumb side, row 2 from the top; `R-T1` = innermost thumb). |
| `<name>_<half>_all.3mf` | Everything for that half on one plate when `case` and/or `plate` are set: caps and cover in the keyboard layout, the case, and the switch plate (top-down when `print_flip`). Each group keeps its layout and may be turned 90°. Packed for `bed` (default 256 × 256 mm); a warning is printed if it doesn't fit. The case's tent struts aren't included. |
| `<name>_assembled.glb` | The whole keyboard in color, in position. Opens in Blender, online glTF viewers, or Windows 3D Viewer. |
| `<name>_map.png` | Top-down 2D map: the graphic's outline (dashed) and what each cap gets |
| `<name>_render*.png` | 3D previews made by `render.py` |
| `report.json` | Parameters, the coverage and inlay volume of each cap, and a watertight check |

There's no STEP output. The caps only exist as STL meshes, so a STEP file
would just wrap thousands of triangles (tens of MB) and give you nothing you
can edit. The GLB and the renders are easier ways to look at the result.

## Printing

- Open `<name>_right.3mf` in Bambu Studio. Each cap should load as one object
  with its `-inlay` part already on filament 2. If the parts come in on
  filament 1, select every `-inlay` part in the object list and set it to
  filament 2. Or run with `--stl` and import `<name>_right_base.stl` and
  `<name>_right_inlay.stl` together, answer **Yes** to "load as a single object
  with multiple parts", and set the inlay part to filament 2.
- Caps print lying on one of their flat (drafted) sides, set per cap shape by
  `print_side`: raised C, normal and home A, thumb-1.5 A, thumb-center D,
  thumb-outer C (letters as in `print-sides.png`: seen from above in the
  STL, A = +Y, B = +X, C = −Y, D = −X). Mirrored left thumbs swap B and D so the
  same physical face goes down. Set a shape to `null` to print it upright.
  On their sides the color runs through most layers of each cap, so expect a
  color change on most layers. Where the cap top meets the bed side, a thin strip
  of color starts on the first layer; overlay.py lists those caps.
- With a 0.2 mm nozzle at 0.1 mm layers, 0.6 mm is six layers of color. Raise
  `depth` if the base color shows through.

## Fine-tuning placement by hand

`out/<name>/<name>_placement.html` (made by `placement_tool.py`, below) is a standalone page: open it
in any browser, no install needed. It shows the left half's real cap tops, the
nice!view cover and the case rim, with the graphic on top. Drag the graphic,
scroll to scale it (shift-scroll rotates), or use the sliders and arrow keys.
Bright green is what gets inlaid; faint green falls between parts. The **switch plate** checkbox hides or shows the plate. A config saved with it off gets `"enabled": false` on the plate, so `overlay.py` leaves the plate out. The stats
show how much of the graphic lands on keys, the case and the cover. **Save
config** downloads the config with your placement (`fit: "none"`, absolute
scale/rotation/center). Put it in `configs/` and run `overlay.py` on it. To review saved configs, press **Load configs…** (or drop the JSON files on the drawing). Pick any of them, or the config the page was built from, in the list that appears. Loaded configs need `fit: "none"`, which is what the page saves.

To make the page for another config or half:
`python3 placement_tool.py configs/<file>.json [--half left|right]`

## Making your own

`configs/`, `graphics/` and `out/` are local and not in git (see `.gitignore`).
Put an SVG in `graphics/` and a config in `configs/`, for example
`configs/my-art.json` for the left half with the case and switch plate:

```json
{
  "graphic": {"svg": "../graphics/my-art.svg", "fill": ["#30BA78"]},
  "placement": {"fit": "left", "include_cover": true, "scale": 0.9, "offset": [0, 0], "rotate": 0},
  "halves": ["left"],
  "case": {"stl": "typeractive/case-designs/folding-tent-legs/CorneCase_TentStruts_v16_PrintLayout.stl", "top_z": 1.5},
  "plate": {"stl": "typeractive/case-designs/thick-plate/thick_plate_insitu.stl", "top_z": 1.2, "print_flip": true}
}
```

Then run:

```
cd keycaps/overlay
python3 overlay.py configs/my-art.json          # add --stl for base/inlay STL pairs
python3 render.py out/my-art/my-art_assembled.glb right
```

Setup, once (a virtual environment, because Homebrew's Python refuses a plain `pip install`):

```
python3 -m venv .venv
source .venv/bin/activate
pip install numpy trimesh manifold3d shapely svgpathtools contourpy matplotlib networkx scipy rtree lxml vtk
```

`networkx scipy rtree lxml` are trimesh extras it needs for slicing. `vtk` is only
for `render.py`. Building both halves takes about 30 s.

Config keys (all optional except `graphic.svg`, defaults in `DEFAULTS` in `overlay.py`):

| Key | Default | Meaning |
|---|---|---|
| `graphic.svg` | | SVG path, relative to the config file |
| `graphic.fill` | all | Only paths with these fill colors, e.g. `["#30BA78"]` |
| `placement.fit` | `right` | `right`, `left`, `both` (one graphic across the split) or `none` |
| `placement.include_cover` | `true` | Count the nice!view cover as part of the fit area |
| `placement.scale` / `offset` / `rotate` / `mirror` | 1 / [0,0] / 0 / false | Adjustments after the fit (mm, degrees). With `fit: none`, `scale` is mm per SVG unit and `offset` is the graphic's center in the board frame |
| `halves` | both | Which halves to build |
| `depth` | 0.6 | Inlay depth (mm, vertical) |
| `mode` | `inlay` | `inlay` = the exact shape on each cap; `pixel` = a cap is fully colored when the graphic covers at least `pixel_threshold` of it |
| `invert` | false | Color everything except the graphic |
| `include_cover` | true | Inlay the nice!view cover too |
| `case` | none | `{"stl": "<repo path>", "top_z": 1.2}`: also inlay the graphic into the case's top rim (largest body in the STL, right-hand, mirrored for the left). The case is written to its own `<name>_<half>_case.3mf`; it isn't used for the fit |
| `plate` | none | Same as `case`, for the switch plate (`thick-plate/thick_plate_insitu.stl`, mirrored for the left). Its top shows in the gaps between caps. `print_flip: true` writes `<name>_<half>_plate.3mf` top-down, like `thick_plate_print_left.stl` |
| `bed` | [256, 256] | Print bed size (mm) used to pack `<name>_<half>_all.3mf` |
| `print_side` | see Printing | Side each cap shape lies on in the print files |
| `min_feature` | 0.3 | Drop inlay/base features narrower than this (mm) |
| `max_slope` | 55 | Steeper surfaces stay base color (degrees) |
| `mirror_left` | the three thumbs | Cap STLs mirrored for the left half (they're drawn right-handed) |
| `rows`, `home_keys`, `thumbs` | V5 rows, index home, 1.5/center/outer | Which cap STL goes where |
| `spin`, `spin_half` | see code (left thumb-1.5 180, thumb-center +90, thumb-outer −90 built in) | Rotation added to each cap so its STL sits the right way round |
| `colors` | | Only used for previews |

Board frame: +X right, +Y away from you, mm. The halves sit either side of
X = 0 with `gap` (40 mm) between their inner edges.

### Cap orientation assumptions (check before printing)

The graphic is projected straight down, so a cap that sits the wrong way
round on the board gets the wrong piece of the picture. The defaults follow
the pin-jig notes: on V5 caps STL −Y is the light-bar side (+Y on
raised-lower), so the light bar faces away from you and raised edges face
away from the home row. The thumbs are placed as their STLs are drawn
(STL +Y away from you, then turned by the switch angle). If a thumb sits the
other way round, set `spin_half`, e.g. `{"right": {"thumb-1.5": 180}}`. The left thumbs are mirrored copies.
On the left, thumb-1.5 gets a built-in half turn and thumb-center and
thumb-outer get a quarter turn (+90° and −90°), so configs don't need to set
it.

## Files

- `overlay.py` builds the layout, places the graphic, computes the inlays, and writes the 3MF, GLB, map and report
- `render.py` makes the VTK preview renders from the GLB
- `placement_tool.py` + `placement_tool.html` make the drag-and-drop placement page
- `print-sides.png` shows which side each cap shape prints on (`print_side`)
- `configs/`, `graphics/` and `out/` hold your own configs, SVGs and results; they stay out of git

License: CC BY-NC-SA 4.0, same as the rest of the repo.
