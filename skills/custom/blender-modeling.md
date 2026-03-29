---
name: "blender-modeling"
description: >
  Expert guide for AI-driven 3D modeling in Blender via the OpenACM bridge.
  Use when the user asks to model, create, or sculpt anything in 3D, generate
  Blender scenes, export GLB/OBJ/STL files, or set up lighting and materials.
  Covers correct bpy patterns, safe object creation, workflows, and anti-patterns
  that cause NoneType errors. Also applies to blender_run_script (background mode).
category: "custom"
---

# Blender Modeling Skill

## Workflow (always follow this order)

```
1. blender_start()              → open Blender + bridge
2. blender_exec(setup code)     → clear scene, camera, lights
3. blender_exec(modeling code)  → build geometry step by step
4. blender_exec(..., screenshot=True) → verify visually
5. blender_export("glb")        → deliver file
6. blender_stop()               → close Blender
```

Take screenshots frequently (after each major step) to verify the scene looks right.
If a step fails, read the error and fix it in the next call — the scene stays live.

---

## RULE #0 — Variables persist across blender_exec calls

All variables (objects, materials, collections, etc.) created in one `blender_exec` call
are available in all subsequent calls within the same session. You do NOT need to redefine them.

```python
# Call 1
cube = new_primitive('cube', name='Box')
mat = add_material(cube, name='Red', color=(1,0,0,1))

# Call 2 — cube and mat are still available
apply_modifier(cube, 'SUBSURF', levels=2)
apply_smooth_shading(cube)

# Call 3 — still fine
select_only(cube)
```

If a variable is unexpectedly missing, it means a previous exec call failed before defining it.
Fix the earlier error first — don't redefine everything from scratch.

---

## RULE #1 — Never use `bpy.context.active_object` to capture new objects

`bpy.ops.mesh.primitive_*_add()` does NOT guarantee `context.active_object` is set
when running from the OpenACM bridge timer. This is the cause of:

```
AttributeError: 'NoneType' object has no attribute 'select_set'
```

### ❌ WRONG — causes NoneType errors
```python
bpy.ops.mesh.primitive_cube_add(location=(0, 0, 0))
cube = bpy.context.active_object   # ← may be None!
cube.select_set(True)              # ← CRASH
add_material(cube, color=(1,0,0,1))  # ← CRASH
```

### ✅ CORRECT — always use new_primitive()
```python
cube = new_primitive('cube', name='MyCube', location=(0, 0, 0), size=2)
add_material(cube, name='Red', color=(1, 0, 0, 1))
apply_modifier(cube, 'SUBSURF', levels=2)
```

`new_primitive()` compares object sets before/after the op, so it always returns
the real object reference. Always keep the return value in a variable.

---

## Available primitive types for new_primitive()

| prim_type | Blender primitive | Useful kwargs |
|---|---|---|
| `'cube'` | Cube | `size`, `location`, `scale` |
| `'uv_sphere'` | UV Sphere | `radius`, `segments`, `ring_count`, `location` |
| `'ico_sphere'` | Icosphere | `radius`, `subdivisions`, `location` |
| `'cylinder'` | Cylinder | `radius`, `depth`, `vertices`, `location` |
| `'cone'` | Cone | `radius1`, `radius2`, `depth`, `vertices`, `location` |
| `'torus'` | Torus | `major_radius`, `minor_radius`, `location` |
| `'plane'` | Plane | `size`, `location` |
| `'circle'` | Circle | `radius`, `vertices`, `fill_type`, `location` |
| `'monkey'` | Suzanne head | `size`, `location` |

---

## Available helpers (pre-imported in every exec call)

```python
# Scene
clear_scene()                          # delete all objects, meshes, lights

# Objects — ALWAYS use these
obj = new_primitive('cube', name='X')  # reliable object creation
obj = get_active()                     # get active obj with safe fallback

# Camera & lights
cam = setup_camera(location=(7,-7,5), rotation_deg=(63,0,47))
sun = add_light('SUN', location=(4,1,6), energy=3.0)
add_light('POINT', location=(0,0,4), energy=100.0)
add_light('AREA', location=(2,2,3), energy=200.0)

# Materials
mat = add_material(obj, name='Gold', color=(1.0,0.8,0.1,1.0), roughness=0.2, metallic=1.0)

# Modifiers
apply_modifier(obj, 'SUBSURF', levels=2)  # subdivision surface
apply_modifier(obj, 'SOLIDIFY', thickness=0.05)
apply_modifier(obj, 'BEVEL', width=0.05, segments=2)
apply_modifier(obj, 'ARRAY', count=3, relative_offset_displace=(1.5,0,0))
apply_modifier(obj, 'MIRROR', use_axis=(True,False,False))

# Shading
apply_smooth_shading(obj)  # or None for all meshes

# Transforms
select_only(obj)
obj.location = (x, y, z)
obj.rotation_euler = Euler((rx, ry, rz), 'XYZ')
obj.scale = (sx, sy, sz)

# Utilities
set_origin_to_center(obj)
joined = join_objects([obj1, obj2, obj3])
```

Also available: `bpy`, `math`, `mathutils`, `Vector`, `Euler`, `Matrix`

---

## Standard scene setup (use at the start of every session)

```python
clear_scene()
setup_camera(location=(7, -6, 4), rotation_deg=(70, 0, 46))
add_light('SUN', location=(5, 3, 8), energy=3.0)
add_light('AREA', location=(-3, -2, 5), energy=150.0)
```

---

## Complete examples

### Example 1 — Smooth sphere with metallic material
```python
clear_scene()
setup_camera()
add_light('SUN', energy=4.0)

sphere = new_primitive('uv_sphere', name='Sphere', radius=1.5, segments=64, ring_count=32)
add_material(sphere, name='Chrome', color=(0.9, 0.9, 0.9, 1.0), roughness=0.05, metallic=1.0)
apply_smooth_shading(sphere)
```

### Example 2 — Stylized tree (trunk + canopy)
```python
clear_scene()
setup_camera(location=(6, -6, 3), rotation_deg=(75, 0, 45))
add_light('SUN', energy=3.0)

trunk = new_primitive('cylinder', name='Trunk', radius=0.2, depth=2.0, location=(0, 0, 1))
add_material(trunk, name='Wood', color=(0.35, 0.2, 0.1, 1.0), roughness=0.9)

canopy = new_primitive('ico_sphere', name='Canopy', radius=1.2, subdivisions=3, location=(0, 0, 2.8))
add_material(canopy, name='Leaves', color=(0.1, 0.5, 0.1, 1.0), roughness=0.8)
apply_smooth_shading(canopy)
```

### Example 3 — Subdivided cube with bevel
```python
clear_scene()
setup_camera()
add_light('SUN', energy=3.0)
add_light('AREA', location=(-2, -2, 4), energy=200.0)

box = new_primitive('cube', name='Box', size=2)
apply_modifier(box, 'BEVEL', width=0.1, segments=3)
apply_modifier(box, 'SUBSURF', levels=2)
apply_smooth_shading(box)
add_material(box, name='Clay', color=(0.9, 0.85, 0.78, 1.0), roughness=0.6)
```

### Example 4 — Array of objects
```python
clear_scene()
setup_camera(location=(10, -8, 4))
add_light('SUN', energy=3.0)

col = new_primitive('cylinder', name='Column', radius=0.15, depth=3.0)
apply_modifier(col, 'ARRAY', count=6, relative_offset_displace=(3.0, 0, 0))
add_material(col, name='Stone', color=(0.7, 0.7, 0.65, 1.0), roughness=0.8)
apply_smooth_shading(col)
```

---

## Edit mode operations (topology changes)

When you need to do mesh editing (extrude, loop cuts, etc.), always switch context
and switch back:

```python
obj = new_primitive('cube', name='Base', size=2)
select_only(obj)

# Enter edit mode
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.select_all(action='SELECT')
bpy.ops.mesh.extrude_region_move(TRANSFORM_OT_translate={"value": (0, 0, 1.5)})
bpy.ops.mesh.select_all(action='DESELECT')

# Back to object mode before any next operation
bpy.ops.object.mode_set(mode='OBJECT')
apply_smooth_shading(obj)
```

**Always return to OBJECT mode before the exec call ends.** Leaving Blender in
EDIT mode breaks subsequent blender_exec calls.

---

## Material advanced patterns

### Emission (glowing object)
```python
mat = add_material(obj, name='Glow', color=(0.2, 0.6, 1.0, 1.0))
emission = mat.node_tree.nodes.new('ShaderNodeEmission')
emission.inputs['Color'].default_value = (0.2, 0.6, 1.0, 1.0)
emission.inputs['Strength'].default_value = 5.0
mat.node_tree.links.new(emission.outputs['Emission'],
    mat.node_tree.nodes['Material Output'].inputs['Surface'])
```

### Glass
```python
mat = add_material(obj, name='Glass', color=(0.9, 0.95, 1.0, 1.0), roughness=0.0)
mat.blend_method = 'BLEND'
bsdf = mat.node_tree.nodes.get('Principled BSDF')
if bsdf:
    bsdf.inputs['Transmission Weight'].default_value = 1.0
    bsdf.inputs['IOR'].default_value = 1.45
```

---

## Sculpting

The AI cannot replicate free-form brush sculpting (which uses 2D screen coordinates),
but can achieve equivalent organic results through three techniques that work perfectly
in 3D world space from scripts.

### Technique 1 — Procedural displacement (best for surfaces: skin, rock, bark, terrain)

Always subdivide first to have enough geometry for detail:

```python
head = new_primitive('uv_sphere', name='Head', radius=1.2, segments=64, ring_count=32)
apply_modifier(head, 'SUBSURF', levels=3)   # density first
apply_smooth_shading(head)

# Skin-like bumps
sculpt_displace(head, texture_type='STUCCI', noise_scale=0.3, strength=0.08)

# Alternatively: smooth organic shapes (fat, clay)
# sculpt_displace(head, texture_type='CLOUDS', noise_scale=0.5, strength=0.12)

# Rock / stone surface
# sculpt_displace(head, texture_type='MUSGRAVE', noise_scale=0.4, strength=0.25)

# Cell / scales pattern
# sculpt_displace(head, texture_type='VORONOI', noise_scale=0.6, strength=0.15)
```

| texture_type | Best for |
|---|---|
| `STUCCI` | Skin, rough surfaces, stucco |
| `CLOUDS` | Smooth organic shapes, fat, clay |
| `MUSGRAVE` | Terrain, rocky ground, mountains |
| `VORONOI` | Scales, cell patterns, cracked earth |
| `WOOD` | Wood grain, bark rings |
| `MARBLE` | Veins, marbling, fluid patterns |

### Technique 2 — bmesh per-vertex sculpt (precise mathematical deformations)

`bmesh_sculpt(obj, fn)` applies a function to every vertex.
`fn(co: Vector, normal: Vector) -> Vector` — returns offset to add.

```python
sphere = new_primitive('uv_sphere', name='Organic', segments=128, ring_count=64)
apply_smooth_shading(sphere)

# Push the front face outward (facial forehead bulge)
bmesh_sculpt(sphere, lambda co, n: n * 0.2 if co.y > 0.3 else Vector((0,0,0)))

# Add high-frequency noise (organic imperfection)
sculpt_noise_bmesh(sphere, scale=12.0, amplitude=0.04, seed=42)

# Inflate the whole mesh slightly
sculpt_inflate(sphere, factor=0.05)
```

```python
# Inflate only the top hemisphere (like a mushroom cap)
sculpt_inflate(sphere, factor=0.15, mask_fn=lambda co, n: max(0.0, co.z))

# Inflate only where x < 0 (left side cheek puff)
sculpt_inflate(sphere, factor=0.12, mask_fn=lambda co, n: max(0.0, -co.x))
```

### Technique 3 — Specialized sculpt operations

```python
# Pinch toward a point — eye socket, belly button, nipple, dimple
sculpt_pinch(head, center=(0.4, 0.9, 0.3), radius=0.35, strength=0.25)
sculpt_pinch(head, center=(-0.4, 0.9, 0.3), radius=0.35, strength=0.25)

# Twist — rope, drill bit, twisted column, horn
horn = new_primitive('cone', name='Horn', radius1=0.4, radius2=0.0, depth=2.5,
                     vertices=32, location=(0,0,1.25))
apply_modifier(horn, 'SUBSURF', levels=3)
sculpt_twist(horn, axis='Z', angle_per_unit=1.2)

# Smooth a region after other operations
sculpt_smooth_region(head, center=(0, 0.8, 0.4), radius=0.3, iterations=5)
```

### Multiresolution workflow (for high-fidelity surface)

```python
obj = new_primitive('uv_sphere', name='Bust', radius=1.0, segments=32, ring_count=16)
sculpt_multires(obj, levels=4)   # 16x poly density
apply_smooth_shading(obj)

# Now apply sculpt operations on the dense mesh
sculpt_noise_bmesh(obj, scale=15.0, amplitude=0.02)
sculpt_inflate(obj, factor=0.03, mask_fn=lambda co, n: max(0.0, co.z * 0.5))
```

### Full organic character head example

```python
clear_scene()
setup_camera(location=(0, -4, 1.5), rotation_deg=(85, 0, 0))
add_light('SUN', location=(3, -2, 5), energy=3.0)
add_light('AREA', location=(-2, -3, 3), energy=200.0)

# Base head shape
head = new_primitive('uv_sphere', name='Head', radius=1.0, segments=64, ring_count=32)
apply_smooth_shading(head)

# Shape the skull — elongate vertically
head.scale = (0.85, 0.9, 1.0)
bpy.ops.object.transform_apply(scale=True)

# Organic skin texture
apply_modifier(head, 'SUBSURF', levels=2)
sculpt_displace(head, 'STUCCI', noise_scale=0.25, strength=0.04)

# Facial features — brow ridge
bmesh_sculpt(head, lambda co, n: n * 0.08 if (co.z > 0.5 and abs(co.x) < 0.6 and co.y > 0.5) else Vector())

# Eye sockets
sculpt_pinch(head, center=( 0.35, 0.78, 0.35), radius=0.25, strength=0.18)
sculpt_pinch(head, center=(-0.35, 0.78, 0.35), radius=0.25, strength=0.18)

# Nose bridge — slight pinch
sculpt_pinch(head, center=(0.0, 0.85, 0.1), radius=0.15, strength=0.08)

# Skin material
add_material(head, name='Skin', color=(0.9, 0.72, 0.62, 1.0), roughness=0.65, metallic=0.0)
```

---

## Anti-patterns to NEVER use

```python
# ❌ NEVER — active_object is unreliable from the bridge
bpy.ops.mesh.primitive_cube_add()
obj = bpy.context.active_object    # may be None

# ❌ NEVER — same issue with lights/camera
bpy.ops.object.light_add(type='SUN')
light = bpy.context.active_object  # use add_light() instead

# ❌ NEVER — leave edit mode open at end of exec
bpy.ops.object.mode_set(mode='EDIT')
# (no mode_set back to OBJECT)

# ❌ NEVER — call select_only(None)
obj = None
select_only(obj)   # will raise a clear error now, but avoid it

# ❌ NEVER — export manually inside blender_exec
# Use blender_export() tool instead
bpy.ops.export_scene.gltf(filepath="C:/some/path.glb")
```

---

## Troubleshooting

| Error | Cause | Fix |
|---|---|---|
| `'NoneType' has no attribute 'select_set'` | Used `context.active_object` after an op | Use `new_primitive()` instead |
| `'NoneType' has no attribute 'data'` | Same — obj is None | Use `new_primitive()`, keep return value |
| `name 'mat_X' is not defined` | Previous exec call failed before defining it | Check the error in that call; variables persist so fix the root cause |
| `key "Specular" not found` | Blender 4.x renamed the input | Use `add_material()` — it uses safe `_set()` that skips missing inputs |
| `Context is incorrect` | Called an op that needs active object | Call `select_only(obj)` before the op |
| `EDIT mode` errors on next exec | Previous exec left Blender in EDIT mode | Always end with `bpy.ops.object.mode_set(mode='OBJECT')` |
| Export file not found | Export op silently failed | Check format vs Blender version; use `blender_export()` |
| Bridge timeout | Script took >120s | Break into smaller blender_exec calls |
