import os
import json

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")
APP_VERSION = "1.0.0"
APP_NAME = "Kruger National Park - Fire & Rainfall Management DSS"

DEFAULT_SETTINGS = {
    "mdb_path": r"C:\Users\Utente\OneDrive\00.LAVORO\000.DSS_PROGES\DSS Kruger\TabularData\Db.mdb",
    "shapefiles_dir": r"C:\Users\Utente\OneDrive\00.LAVORO\000.DSS_PROGES\DSS Kruger\ShapeFiles",
    "base_grid_path": r"C:\Users\Utente\OneDrive\00.LAVORO\000.DSS_PROGES\DSS Kruger\ShapeFiles\BaseGrid.shp",
    "kruger_boundary_path": r"C:\Users\Utente\OneDrive\00.LAVORO\000.DSS_PROGES\DSS Kruger\ShapeFiles\bndry_kruger.shp",
    "check_updates_on_startup": True,
    "update_manifest_url": "https://raw.githubusercontent.com/edoardoscepi80/kruger-fire-tool/main/version.json"
}

def load_settings() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                settings = json.load(f)
                return {**DEFAULT_SETTINGS, **settings}
        except Exception:
            pass
    return DEFAULT_SETTINGS.copy()

def save_settings(settings: dict) -> None:
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=4)
    except Exception as e:
        print(f"Error saving settings: {e}")
