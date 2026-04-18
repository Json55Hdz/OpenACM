import os
import shutil

dirs = ['src/core', 'src/components/3d', 'src/state', 'public']
for d in dirs:
    os.makedirs(d, exist_ok=True)

if os.path.exists('machine.glb'):
    shutil.move('machine.glb', 'public/machine.glb')
    print("Moved machine.glb to public/")
