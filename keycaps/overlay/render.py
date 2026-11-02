"""Render preview PNGs of an assembled overlay (the *_assembled.glb that overlay.py writes).

Usage (from keycaps/overlay):
  python3 render.py out/my-art/my-art_assembled.glb [right] [left]
writes <name>_render.png (perspective, both halves), <name>_render_top.png and,
for each half named, a close-up <name>_render_<half>.png next to it.

Needs: vtk trimesh numpy. On a headless Linux box install OSMesa and run with
VTK_DEFAULT_OPENGL_WINDOW=vtkOSOpenGLRenderWindow.
"""
import sys, os
import numpy as np
import trimesh
import vtk
from vtk.util.numpy_support import numpy_to_vtk, numpy_to_vtkIdTypeArray


def polydata(t):
    pts = vtk.vtkPoints()
    pts.SetData(numpy_to_vtk(np.ascontiguousarray(t.vertices, dtype=np.float64), deep=True))
    f = np.hstack([np.full((len(t.faces), 1), 3), t.faces]).astype(np.int64).ravel()
    cells = vtk.vtkCellArray()
    cells.SetCells(len(t.faces), numpy_to_vtkIdTypeArray(f, deep=True))
    pd = vtk.vtkPolyData()
    pd.SetPoints(pts)
    pd.SetPolys(cells)
    n = vtk.vtkPolyDataNormals()
    n.SetInputData(pd)
    n.SetFeatureAngle(35)
    n.Update()
    return n.GetOutput()


def is_inlay(t):
    return str(t.metadata.get('name', '')).endswith('-inlay')


def render(glb, png, size, view, bounds=None):
    scene = trimesh.load(glb, force='scene', process=False)
    r = vtk.vtkRenderer()
    r.SetBackground(0.96, 0.96, 0.95)
    for t in scene.dump():
        m = vtk.vtkPolyDataMapper()
        m.SetInputData(polydata(t))
        if is_inlay(t):
            # the inlay can be only ~0.3 mm thick on steep edges; pull it forward in the
            # depth buffer so the base/inlay interface behind it never shows through
            m.SetResolveCoincidentTopologyToPolygonOffset()
            m.SetRelativeCoincidentTopologyPolygonOffsetParameters(-2, -8)
        a = vtk.vtkActor()
        a.SetMapper(m)
        c = np.asarray(t.visual.face_colors[0][:3]) / 255.0
        a.GetProperty().SetColor(*c)
        a.GetProperty().SetAmbient(0.25)
        a.GetProperty().SetDiffuse(0.85)
        a.GetProperty().SetSpecular(0.25)
        a.GetProperty().SetSpecularPower(30)
        r.AddActor(a)
    lo, hi = bounds if bounds is not None else scene.bounds
    ctr = (lo + hi) / 2
    cam = r.GetActiveCamera()
    cam.SetFocalPoint(*ctr)
    span = hi[0] - lo[0]
    if view == 'top':
        cam.SetPosition(ctr[0], ctr[1], ctr[2] + span * 2)
        cam.SetViewUp(0, 1, 0)
        cam.ParallelProjectionOn()
        cam.SetParallelScale(max(hi[1] - lo[1], (hi[0] - lo[0]) * size[1] / size[0]) * 0.54)
    else:
        cam.SetPosition(ctr[0], ctr[1] - span * 1.0, ctr[2] + span * 0.85)
        cam.SetViewUp(0, 0, 1)
        cam.SetViewAngle(28)
    r.ResetCameraClippingRange()
    light = vtk.vtkLight()
    light.SetPosition(ctr[0] - span, ctr[1] - span, ctr[2] + span * 2)
    light.SetFocalPoint(*ctr)
    light.SetIntensity(0.6)
    r.AddLight(light)
    w = vtk.vtkRenderWindow()
    w.SetOffScreenRendering(1)
    w.AddRenderer(r)
    w.SetSize(*size)
    w.SetMultiSamples(8)
    w.Render()
    f = vtk.vtkWindowToImageFilter()
    f.SetInput(w)
    f.Update()
    wr = vtk.vtkPNGWriter()
    wr.SetFileName(png)
    wr.SetInputConnection(f.GetOutputPort())
    wr.Write()
    print('wrote', png)


def half_bounds(glb, side):
    lo, hi = trimesh.load(glb, force='scene', process=False).bounds
    lo, hi = lo.copy(), hi.copy()
    if side == 'right':
        lo[0] = 0
    else:
        hi[0] = 0
    return lo, hi


if __name__ == '__main__':
    glb = sys.argv[1]
    stem = glb.replace('_assembled.glb', '')
    render(glb, stem + '_render.png', (1800, 900), 'persp')
    render(glb, stem + '_render_top.png', (1800, 800), 'top')
    for side in sys.argv[2:]:      # e.g. right -> close-up of one half
        render(glb, stem + f'_render_{side}.png', (1600, 1000), 'persp', bounds=half_bounds(glb, side))
