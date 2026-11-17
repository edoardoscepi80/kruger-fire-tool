import os
import sys
import PyInstaller.__main__

base_dir = r"C:\Users\Utente\.gemini\antigravity\scratch\kruger_fire_tool"
main_py = os.path.join(base_dir, "main.py")
icon_ico = os.path.join(base_dir, "resources", "logo_proges.ico")
res_dir = os.path.join(base_dir, "resources")
ver_json = os.path.join(base_dir, "version.json")
dist_dir = os.path.join(base_dir, "dist")
build_dir = os.path.join(base_dir, "build")

args = [
    main_py,
    "--name=KrugerFireDSS",
    "--windowed",
    "--noconfirm",
    f"--icon={icon_ico}",
    f"--distpath={dist_dir}",
    f"--workpath={build_dir}",
    f"--add-data={res_dir};resources",
    f"--add-data={ver_json};.",
    "--clean"
]

print("Starting PyInstaller compilation with args:", args)
PyInstaller.__main__.run(args)
print("PyInstaller build finished!")
