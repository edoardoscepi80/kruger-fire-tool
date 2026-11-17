import os
import sys

# Ensure Qt / PyQt5 C++ DLLs are found regardless of which Python binary is invoked
qt_dll_candidates = [
    os.path.join(os.path.dirname(sys.executable), "Lib", "site-packages", "PyQt5", "Qt5", "bin"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Python", "Python312", "Lib", "site-packages", "PyQt5", "Qt5", "bin"),
    r"C:\Program Files\QGIS 3.44.12\bin",
    r"C:\Program Files\QGIS 3.34.14\bin",
    r"C:\OSGeo4W\bin",
    r"C:\OSGeo4W64\bin",
]
for p in qt_dll_candidates:
    if os.path.exists(p):
        try:
            os.add_dll_directory(p)
        except Exception:
            pass
        if p not in os.environ.get("PATH", ""):
            os.environ["PATH"] = p + os.pathsep + os.environ.get("PATH", "")

# Project root in sys.path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QIcon
from gui.main_window import MainWindow


def main():
    # Set Windows AppUserModelID so taskbar and window title bar display the custom icon
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("kruger.dss.fire.tool")
    except Exception:
        pass

    app = QApplication(sys.argv)

    # Set Application Icon
    app_icon = QIcon()
    ico_path = os.path.join(PROJECT_ROOT, "resources", "logo_proges.ico")
    png_path = os.path.join(PROJECT_ROOT, "resources", "logo_proges_clean.png")
    if os.path.exists(ico_path):
        app_icon.addFile(ico_path)
    if os.path.exists(png_path):
        app_icon.addFile(png_path)
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)

    window = MainWindow()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
