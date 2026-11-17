import os
import sys
import subprocess

# 1. Trampoline check: if not running inside the initialized QGIS OSGeo4W shell,
# re-launch via python-qgis-ltr.bat so that all 40+ native C++ GIS DLLs are in scope.
QGIS_BAT = r"C:\Program Files\QGIS 3.44.12\bin\python-qgis-ltr.bat"
if "QGIS_PREFIX_PATH" not in os.environ and os.path.exists(QGIS_BAT):
    script_path = os.path.abspath(__file__)
    cmd = f'"{QGIS_BAT}" "{script_path}"'
    exit_code = subprocess.call(cmd, shell=True)
    sys.exit(exit_code)

# 2. Base QGIS directory
QGIS_ROOT = os.environ.get("OSGEO4W_ROOT", r"C:\Program Files\QGIS 3.44.12")

# 3. Add QGIS Python modules and site-packages to sys.path
qgis_python = os.path.join(QGIS_ROOT, "apps", "qgis-ltr", "python")
qgis_site = os.path.join(QGIS_ROOT, "apps", "Python312", "Lib", "site-packages")
for p in [qgis_python, qgis_site]:
    if os.path.exists(p) and p not in sys.path:
        sys.path.insert(0, p)

# 4. Project root in sys.path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from qgis.core import QgsApplication
from gui.main_window import MainWindow


def main():
    # Set Windows AppUserModelID so taskbar and window title bar display the custom icon
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("kruger.dss.fire.tool")
    except Exception:
        pass

    # Initialize QGIS Application (GUI enabled = True)
    qgs_app = QgsApplication([], True)
    qgs_app.initQgis()

    # Set Application Icon
    from PyQt5.QtGui import QIcon
    app_icon = QIcon()
    ico_path = os.path.join(PROJECT_ROOT, "resources", "logo_proges.ico")
    png_path = os.path.join(PROJECT_ROOT, "resources", "logo_proges_clean.png")
    if os.path.exists(ico_path):
        app_icon.addFile(ico_path)
    if os.path.exists(png_path):
        app_icon.addFile(png_path)
    if not app_icon.isNull():
        qgs_app.setWindowIcon(app_icon)

    window = MainWindow()
    window.show()

    exit_code = qgs_app.exec_()

    # Clean QGIS shutdown
    qgs_app.exitQgis()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
