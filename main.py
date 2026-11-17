import os
import sys

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
