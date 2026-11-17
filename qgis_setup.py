"""
Auto-configures system environment, DLL paths and sys.path for QGIS 3.44.
Must be imported before any qgis or PyQt5 imports.
"""

import sys
import os

QGIS_ROOT = r"C:\Program Files\QGIS 3.44.12"

# 1. Add DLL directories on Windows (Python 3.8+ required)
add_dll = getattr(os, "add_dll_directory", None)
_DLL_HANDLES = []
if add_dll is not None:
    dll_dirs = [
        os.path.join(QGIS_ROOT, "bin"),
        os.path.join(QGIS_ROOT, "apps", "qgis-ltr", "bin"),
        os.path.join(QGIS_ROOT, "apps", "qt5", "bin"),
    ]
    for d in dll_dirs:
        if os.path.exists(d):
            try:
                _DLL_HANDLES.append(add_dll(d))
            except Exception:
                pass

# 2. Add QGIS Python module directory to sys.path
qgis_python = os.path.join(QGIS_ROOT, "apps", "qgis-ltr", "python")
if os.path.exists(qgis_python) and qgis_python not in sys.path:
    sys.path.insert(0, qgis_python)

# 3. Specific QGIS env variables
os.environ["QGIS_PREFIX_PATH"] = os.path.join(QGIS_ROOT, "apps", "qgis-ltr").replace("\\", "/")
os.environ["QT_PLUGIN_PATH"] = (
    os.path.join(QGIS_ROOT, "apps", "qgis-ltr", "qtplugins") + ";" +
    os.path.join(QGIS_ROOT, "apps", "qt5", "plugins")
)
os.environ["GDAL_DATA"] = os.path.join(QGIS_ROOT, "apps", "gdal", "share", "gdal")
os.environ["PROJ_DATA"] = os.path.join(QGIS_ROOT, "share", "proj")
os.environ["GDAL_FILENAME_IS_UTF8"] = "YES"
