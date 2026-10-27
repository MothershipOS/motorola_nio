"""Rounded mounting plate. All dimensions and STL coordinates are millimetres.

Run with Python and cadquery, trimesh, numpy, matplotlib installed.
Edit the parameters below to regenerate the STEP, STL, and preview.
"""

from pathlib import Path
import json
import math
import cadquery as cq
import trimesh
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Circle
import vtk
from vtk.util.numpy_support import vtk_to_numpy

LENGTH = 79.0
WIDTH = 29.5
HEIGHT = 13.0
HOLE_DIAMETER = 5.0
HOLE_SPACING = 60.0  # Centre to centre, along the length.
FILLET_RADIUS = 2.0  # Assumed radius, applied only to the four vertical corner edges.
OUTPUT = Path(__file__).resolve().parent
NAME = "plate_79x29_5x13"

plate = (
    cq.Workplane("XY")
    .box(LENGTH, WIDTH, HEIGHT, centered=(True, True, False))
    .edges("|Z").fillet(FILLET_RADIUS)
    .faces(">Z").workplane()
    .pushPoints([(-HOLE_SPACING / 2, 0), (HOLE_SPACING / 2, 0)])
    .hole(HOLE_DIAMETER)
)
solid = plate.val()
assert solid.isValid() and len(solid.Solids()) == 1
bounds = solid.BoundingBox()
assert np.allclose([bounds.xlen, bounds.ylen, bounds.zlen], [LENGTH, WIDTH, HEIGHT])

hole_centers = []
for face in solid.Faces():
    if face.geomType() == "CYLINDER":
        cylinder = face._geomAdaptor().Cylinder()
        axis = cylinder.Axis()
        if math.isclose(cylinder.Radius(), HOLE_DIAMETER / 2, abs_tol=1e-7):
            assert math.isclose(abs(axis.Direction().Z()), 1.0, abs_tol=1e-7)
            assert math.isclose(face.BoundingBox().zlen, HEIGHT, abs_tol=1e-7)
            location = axis.Location()
            hole_centers.append([location.X(), location.Y()])
assert np.allclose(sorted(hole_centers), [[-HOLE_SPACING / 2, 0], [HOLE_SPACING / 2, 0]])

cq.exporters.export(plate, str(OUTPUT / f"{NAME}.step"))
cq.exporters.export(plate, str(OUTPUT / f"{NAME}.stl"), tolerance=0.01, angularTolerance=0.05)
mesh = trimesh.load_mesh(OUTPUT / f"{NAME}.stl")
# Spherical fillet poles can create zero-area triangles during CAD tessellation.
mesh.update_faces(mesh.nondegenerate_faces())
mesh.remove_unreferenced_vertices()
mesh.export(OUTPUT / f"{NAME}.stl")
mesh = trimesh.load_mesh(OUTPUT / f"{NAME}.stl")
assert mesh.is_watertight and mesh.is_winding_consistent and mesh.is_volume
assert len(mesh.split()) == 1
assert np.allclose(mesh.extents, [LENGTH, WIDTH, HEIGHT], atol=0.001)
reimported = cq.importers.importStep(str(OUTPUT / f"{NAME}.step")).val()
assert reimported.isValid()
assert math.isclose(reimported.Volume(), solid.Volume(), rel_tol=1e-8)

report = {
    "units": "mm",
    "dimensions": [LENGTH, WIDTH, HEIGHT],
    "hole_diameter": HOLE_DIAMETER,
    "hole_spacing_center_to_center": HOLE_SPACING,
    "hole_centers_xy": sorted(hole_centers),
    "hole_center_distance_from_each_end": (LENGTH - HOLE_SPACING) / 2,
    "holes": "two straight through-holes, centered across the width",
    "top_view_corner_radius": FILLET_RADIUS,
    "top_and_bottom_edges": "square",
    "hole_edges": "sharp",
    "solid_valid": solid.isValid(),
    "stl_watertight": bool(mesh.is_watertight),
    "stl_winding_consistent": bool(mesh.is_winding_consistent),
    "step_roundtrip_valid": reimported.isValid(),
    "volume_mm3": solid.Volume(),
}
(OUTPUT / "dimensions.json").write_text(json.dumps(report, indent=2) + "\n")

fig = plt.figure(figsize=(13, 6.6), facecolor="#f8fafc")
reader = vtk.vtkSTLReader()
reader.SetFileName(str(OUTPUT / f"{NAME}.stl"))
normals = vtk.vtkPolyDataNormals()
normals.SetInputConnection(reader.GetOutputPort())
normals.SetFeatureAngle(45)
mapper = vtk.vtkPolyDataMapper()
mapper.SetInputConnection(normals.GetOutputPort())
actor = vtk.vtkActor()
actor.SetMapper(mapper)
actor.GetProperty().SetColor(0.28, 0.60, 0.86)
actor.GetProperty().SetInterpolationToPhong()
actor.GetProperty().SetSpecular(0.25)
actor.GetProperty().SetSpecularPower(30)
renderer = vtk.vtkRenderer()
renderer.SetBackground(248/255, 250/255, 252/255)
renderer.AddActor(actor)
camera = renderer.GetActiveCamera()
camera.SetPosition(100, -170, 140)
camera.SetFocalPoint(0, 0, HEIGHT/2)
camera.SetViewUp(0, 0, 1)
camera.ParallelProjectionOn()
camera.SetParallelScale(27)
window = vtk.vtkRenderWindow()
window.SetOffScreenRendering(1)
window.SetSize(1200, 800)
window.SetMultiSamples(8)
window.AddRenderer(renderer)
window.Render()
capture = vtk.vtkWindowToImageFilter()
capture.SetInput(window)
capture.ReadFrontBufferOff()
capture.Update()
pixels = vtk_to_numpy(capture.GetOutput().GetPointData().GetScalars()).reshape(800, 1200, 3)
ax = fig.add_subplot(121, facecolor="#f8fafc")
ax.imshow(np.flipud(pixels))
window.Finalize()
ax.set_axis_off()
ax.set_title("3D view · 13 mm thick", fontsize=15, pad=18, color="#152536")

top = fig.add_subplot(122, facecolor="#f8fafc")
top.add_patch(FancyBboxPatch((-LENGTH/2, -WIDTH/2), LENGTH, WIDTH,
                            boxstyle=f"round,pad=0,rounding_size={FILLET_RADIUS}",
                            facecolor="#74b5e5", edgecolor="#234c70", linewidth=1.7))
for x in [-HOLE_SPACING/2, HOLE_SPACING/2]:
    top.add_patch(Circle((x, 0), HOLE_DIAMETER/2, facecolor="#f8fafc", edgecolor="#234c70", linewidth=1.4))
    top.plot([x-4, x+4], [0, 0], color="#54728d", lw=0.6, ls="--")
    top.plot([x, x], [-4, 4], color="#54728d", lw=0.6, ls="--")

def dimension(a, b, label, text_offset=(0, 1.5)):
    top.annotate("", xy=a, xytext=b, arrowprops={"arrowstyle": "<->", "color": "#34495e", "lw": 1})
    top.text((a[0]+b[0])/2+text_offset[0], (a[1]+b[1])/2+text_offset[1], label,
             ha="center", va="center", fontsize=11, color="#152536")

for x in [-LENGTH/2, LENGTH/2]:
    top.plot([x, x], [WIDTH/2+1, WIDTH/2+8], color="#6d8194", lw=0.7)
dimension((-LENGTH/2, WIDTH/2+6), (LENGTH/2, WIDTH/2+6), "79 mm", (0, 2.4))
for x in [-HOLE_SPACING/2, HOLE_SPACING/2]:
    top.plot([x, x], [-3.5, -WIDTH/2-8], color="#6d8194", lw=0.7, ls="--")
dimension((-HOLE_SPACING/2, -WIDTH/2-6), (HOLE_SPACING/2, -WIDTH/2-6), "60 mm centers", (0, -3))
dimension((LENGTH/2+7, -WIDTH/2), (LENGTH/2+7, WIDTH/2), "29.5 mm", (7, 0))
top.annotate("2 × Ø5 mm through", xy=(-HOLE_SPACING/2, 2.5), xytext=(-19, 10),
             fontsize=10, ha="center", color="#152536", arrowprops={"arrowstyle": "->", "lw": 0.8})
top.set_xlim(-45, 65)
top.set_ylim(-29, 28)
top.set_aspect("equal")
top.set_axis_off()
top.set_title("Top view · dimensions in mm", fontsize=15, pad=18, color="#152536")
fig.suptitle("Rounded rectangular plate", fontsize=21, color="#152536", y=0.94)
fig.text(0.5, 0.10, "79 × 29.5 × 13 mm   |   Two Ø5 mm through-holes   |   60 mm center spacing",
         ha="center", fontsize=12, color="#34495e")
fig.text(0.5, 0.055, "Assumed: R2 mm corners in top view; square top/bottom edges; holes centered on the width.",
         ha="center", fontsize=11, color="#54728d")
fig.subplots_adjust(left=0.015, right=0.94, bottom=0.18, top=0.80, wspace=0.03)
fig.savefig(OUTPUT / "preview.png", dpi=180, facecolor=fig.get_facecolor())
print(json.dumps(report, indent=2))
