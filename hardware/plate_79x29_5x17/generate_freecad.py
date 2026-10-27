"""Generate the plate with installed FreeCAD; numeric parameters come from model.py.
Run: snap run freecad.cmd /absolute/path/generate_freecad.py
"""
import ast
import json
import math
from pathlib import Path
import FreeCAD as App
import Part
import MeshPart

OUTPUT = Path(__file__).resolve().parent
params = {}
for node in ast.parse((OUTPUT / 'model.py').read_text()).body:
    if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
        for target in node.targets:
            if isinstance(target, ast.Name):
                params[target.id] = node.value.value
L, W, H = (params[k] for k in ('LENGTH', 'WIDTH', 'HEIGHT'))
R, D, SPACING = (params[k] for k in ('FILLET_RADIUS', 'HOLE_DIAMETER', 'HOLE_SPACING'))
NAME = params['NAME']
base = Part.makeBox(L, W, H, App.Vector(-L / 2, -W / 2, 0))
vertical = [e for e in base.Edges if math.isclose(e.BoundBox.ZLength, H, abs_tol=1e-7)]
assert len(vertical) == 4
shape = base.makeFillet(R, vertical)
for x in (-SPACING / 2, SPACING / 2):
    shape = shape.cut(Part.makeCylinder(D / 2, H, App.Vector(x, 0, 0)))
shape = shape.removeSplitter()
assert shape.isValid() and len(shape.Solids) == 1
bounds = shape.BoundBox
assert all(math.isclose(a, b, abs_tol=1e-7) for a, b in zip((bounds.XLength, bounds.YLength, bounds.ZLength), (L, W, H)))
volume = (L * W - (4 - math.pi) * R * R - 2 * math.pi * (D / 2) ** 2) * H
assert math.isclose(shape.Volume, volume, rel_tol=1e-8)
holes = []
for face in shape.Faces:
    if isinstance(face.Surface, Part.Cylinder) and math.isclose(face.Surface.Radius, D / 2, abs_tol=1e-7):
        assert math.isclose(face.BoundBox.ZLength, H, abs_tol=1e-7)
        c = face.Surface.Center
        holes.append([c.x, c.y])
assert sorted(holes) == [[-SPACING / 2, 0], [SPACING / 2, 0]]
doc = App.newDocument('Plate79x29_5x17')
obj = doc.addObject('PartDesign::Feature', 'Plate')
obj.Label = '79 x 29.5 x 17 mm - R2 corners - 2 x diameter 5'
obj.Shape = shape
doc.recompute()
doc.saveAs(str(OUTPUT / (NAME + '.FCStd')))
Part.export([obj], str(OUTPUT / (NAME + '.step')))
mesh = MeshPart.meshFromShape(Shape=shape, LinearDeflection=0.01, AngularDeflection=0.05, Relative=False)
assert mesh.isSolid()
mesh.write(str(OUTPUT / (NAME + '.stl')))
roundtrip = Part.read(str(OUTPUT / (NAME + '.step')))
assert roundtrip.isValid() and math.isclose(roundtrip.Volume, shape.Volume, rel_tol=1e-8)
report = {'units':'mm', 'dimensions':[L,W,H], 'hole_diameter':D,
          'hole_spacing_center_to_center':SPACING, 'hole_centers_xy':sorted(holes),
          'hole_center_distance_from_each_end':(L-SPACING)/2,
          'holes':'two straight through-holes, centered across the width',
          'top_view_corner_radius':R, 'top_and_bottom_edges':'square', 'hole_edges':'sharp',
          'solid_valid':True, 'stl_watertight':mesh.isSolid(), 'step_roundtrip_valid':True,
          'volume_mm3':shape.Volume}
(OUTPUT / 'dimensions.json').write_text(json.dumps(report,indent=2)+'\n')
print('MODEL_READY '+json.dumps(report),flush=True)
App.closeDocument(doc.Name)
