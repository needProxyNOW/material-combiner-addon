import os
import sys
from subprocess import call

import bpy

from .. import globs


class InstallPIL(bpy.types.Operator):
    bl_idname = 'smc.get_pillow'
    bl_label = 'Install PIL'
    bl_description = 'Click to install Pillow. This could take a while and might require you to start Blender as admin'

    def execute(self, context):
        python_executable = bpy.app.binary_path_python if bpy.app.version < (3, 0, 0) else sys.executable
        try:
            import pip
            try:
                from PIL import Image, ImageChops
            except ImportError:
                call([python_executable, '-m', 'pip', 'install', 'Pillow', '--user', '--upgrade'], shell=True)
        except ImportError:
            call([python_executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'get_pip.py'),
                  '--user'], shell=True)
            call([python_executable, '-m', 'pip', 'install', 'Pillow', '--user', '--upgrade'], shell=True)
        globs.smc_pi = True
        self.report({'INFO'}, 'Installation complete')
        return {'FINISHED'}
