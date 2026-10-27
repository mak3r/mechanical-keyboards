# MKC pin attachment jig

Attaches `pin.stl` to the four MKC V5 keycaps (normal, normal-home, raised-lower, raised-upper), 10 at a time, with the pin's angle, height and position set by the jig instead of by hand.

![section](section.png)

## How it works

All four V5 keycaps share the same underside: flat at z=1.8 above the rim, with skirt walls drafted about 25°. Only the tops differ. So one universal boss fits every cap, and it does all the locating:

- **Height and angle:** the boss's flat top is the datum. The pin's 8.5×4 base face and the keycap's underside both rest on that same face, so the pin ends up flush with the underside and square to it, the way it is modelled.
- **Position and rotation:** the boss walls match the skirt draft (0.15 mm clearance, chosen from the fit test), so the cap centres itself as it drops on. Two through slots hold the pin legs (0.15 mm clearance per side, chosen from the fit test), so the pin can't twist or slide.
- **Squeeze-out:** a shallow groove around the pin base catches excess slurry so it doesn't lift the cap off the datum.
- **Pressure:** a clamp plate with TPU pads, each shaped to cover its cap's whole top surface, pushes every cap down onto its boss. The plate bottoms out on a solid end wall at each end of the base, so every pad compresses by the same 0.5 mm, whatever the cap type. Each pad covers the whole top, light-bar slot included, and reaches just past the raised crest along each edge, so it seats on the cap like a lid and can't rock. It presses evenly everywhere, even on the sloped raised caps.

## Parts

| File | Material | Qty | Notes |
|---|---|---|---|
| `pinjig_base.stl` | PETG | 1 | 128.5 × 44.5 mm. Print flat, bosses up. Use the 0.2 mm nozzle, or 0.4 mm with ≤0.12 mm layers, so the leg slots come out accurate. |
| `pinjig_clamp.stl` | PETG | 1 | Plate with 10 keyed pegs on its underside. It's exported flat side down with the pegs pointing up, so it prints without supports. |
| `pinjig_pads/pinjig_pad_normal.stl` | TPU 95A | per normal cap | Exported flat back down, with the shaped face on top and the keyed socket open to the bed. Prints without supports; the only bridge is the 3.6 mm socket ceiling. 2 walls, ~15% gyroid, so it stays soft. |
| `pinjig_pads/pinjig_pad_home.stl` | TPU 95A | per home cap | Has a relief for the homing bump. |
| `pinjig_pads/pinjig_pad_raised.stl` | TPU 95A | per raised cap | The same pad works for raised-lower and raised-upper. Their tops match within 0.01 mm, and the pad bridges both light-bar positions. Thinnest point 1.7 mm, at the tall edge. |
| `pinjig_fit_test.stl` | PETG | 1 | Four single bosses at 0.05 / 0.10 / 0.15 / 0.20 mm clearance (1–4 dots). Print this first with the same settings as the base. |

Hardware: 4× M3×18 socket head screws and 4× M3 nuts. Each nut presses up into the hex trap under the base.

### Printing the base

- It prints with no supports and no bridges. Every nut-trap ceiling tapers up to its bolt hole at 45° or steeper, so nothing droops into the holes.
- The clamp stops are solid end walls with a 45° fillet at the floor, instead of free-standing posts.
- For strength, use 4–5 walls and 40%+ infill, or a modifier with 100% infill on the end walls. PETG layers bond better at 240–250 °C with the part fan at 30–50%.
- Clean each bolt hole once with a 3.2–3.4 mm drill bit by hand before fitting the nuts.

## Use

1. Drop a pin into each boss, legs down through the slots. Its base face should sit flat on the boss.
2. Put a thin layer of slurry in the keycap pocket, or on the pin's tapered top.
3. Lower the cap onto the boss and press lightly. The skirt centres it. **Raised caps go tall edge toward the small triangle** engraved in front of each boss.
4. Press the right pad onto each clamp peg. The cut corner of the socket keys it, so a pad only fits one way round.
5. Put the clamp on and tighten the 4 screws until the clamp sits on the end walls. Don't go past that.
6. Leave it to cure, then unscrew the clamp and lift the caps off. If a pin leg sticks, push it out from underneath through the slot.

PETG doesn't dissolve in acetone, so ABS slurry won't bond to the jig.

## Tuning

`pin_jig.py` regenerates everything from the current keycap STLs. Run it from this folder:

```
pip install trimesh manifold3d scipy rtree networkx
python3 pin_jig.py .. ../pin.stl .
```

Pads go into `pinjig_pads/`. Add `--preview` to also write an assembled STL with keycaps and pins in place. The main parameters are at the top:

- `boss_clear` and `slot_clear`: set these from the fit-test result. Pick the tightest step where the cap seats fully and rocks with no play, and where a pin drops in under its own weight.
- `pad_interference`: how hard each cap gets pressed. Raise it if caps lift, lower it if pads bulge.
- `cols`, `rows`, `pitch_x`, `pitch_y`: the layout. The default 2×5 base is 128.5 × 44.5 mm.

## Keycap pocket

The keycap pocket ceiling is at z=2.9, 0.1 mm above the pin's top face. That leaves room for the slurry, so the pin base and the cap underside can both sit flat on the boss.

Pin geometry comes from `keycaps/MKC/pin.stl`, which has the correct 3.5 mm choc legs. The slots go all the way through, so leg length doesn't affect the jig.
