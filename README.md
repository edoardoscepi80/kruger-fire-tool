# Kruger National Park - Fire & Rainfall Management DSS (Python Open-Source)

Desktop application for GIS spatial analysis, ecological modeling of fire regimes and precipitation spatialization in Kruger National Park.
Modern Python migration of the decision support tool originally developed in Visual Basic .NET / DotSpatial.

---

## 🚀 Quick Start

Double-click the launcher script:
```
run_app.bat
```
or run directly from your IDE by clicking the **Run / Play ▶** button or pressing **F5**.

---

## 📂 Project Architecture

```
kruger_fire_tool/
├── config.py                 # Paths and user configuration management (settings.json, versioning)
├── version.json              # Version release manifest (version, changelog, download URL)
├── main.py                   # Desktop application entry point (QGIS & PyQt)
├── run_app.bat               # Windows launcher script
├── README.md                 # Project documentation
├── core/
│   ├── db_manager.py         # 64-bit ODBC access to Db.mdb, query optimization and batch transactions
│   ├── fire_models.py        # Mathematical & ecological models (Attorre et al. & Navashni formulas)
│   ├── fire_processor.py     # High-speed spatial intersection (STRtree) and fire record computation
│   ├── rainfall_processor.py # Rainfall spatialization (21 station weights) and historical diagnostics
│   └── updater.py            # Asynchronous online update checker, downloader, and patch installer
└── gui/
    ├── map_widget.py         # Interactive GIS canvas based on QgsMapCanvas
    ├── main_window.py        # Main window with Ribbon action bar and layer manager
    └── dialogs.py            # Asynchronous modal dialogs (Fire, Rainfall, Diagnostics, Settings, Updates)
```

---

## ✨ Key Features (Toolbar Workflow)

1. **Rainfall Station Manager (`🌦️ Rainfall Station Manager`)**:
   - Manage, inspect, add, and edit annual precipitation totals (mm) across all 21 Kruger weather stations directly in `Db.mdb` without needing Microsoft Access.
   - Quick "Add New Year" with automated hydrological season computation (`YEAR_RAIN`), status assignment, and helper baseline copy.
   - Search & filter records by calendar year or spatialization status (`Imported = 'N'` or `'Y'`).
   - One-click status toggle (`Pending ('N')` vs `Spatialized ('Y')`) to easily re-spatialize modified historical years.
   - Batch import/export from external CSV spreadsheets.
   - Direct shortcut to launch grid spatialization for pending records directly inside the manager.

2. **Grid & Weights Diagnostics (`🔍 Grid Weights Diagnostics`)**:
   - Diagnoses coverage and weight integrity across all grid cells.
   - Inspects yearly cell counts in `Qry_RAINFALL`.
   - Offers one-click automated backfill for the historical 1956-2014 gap (cells 18945, 18946, 18947).

3. **Precipitation Spatialization (`🌧️ Import Rainfall Data`)**:
   - Identifies pending station yearly readings (`Imported = 'N'`) across 21 weather stations (`BDL`, `KRO`, `HOU`, ..., `WOO`).
   - Applies weighted linear interpolation (`Rainfall_BaseGridCells_Weight`) for each of the 18,948 cells.
   - Computes 2-year moving average and updates `Qry_RAINFALL`.

4. **Fire Data Import (`🔥 Import Fire Data`)**:
   - Vectorized spatial intersection between fire polygon shapefiles and grid cells using Shapely STRtree.
   - Calculates fire frequency (years since last recorded fire per cell, max 6).
   - Pre-loads historical rainfall (2-year average).
   - Computes both ecological models concurrently:
     - **Attorre et al.**: Fuel load, season-dependent exponential fire intensity, FDI-based classification.
     - **Navashni**: Fuel load, 5 rank classes, Southern Hemisphere seasonality, decision matrix intensity.
   - Saves records into `FIRE` table in `Db.mdb`.

5. **Online Auto-Updater & System Maintenance (`🚀 Updates` & `⚙️ Settings`)**:
   - Asynchronous, non-blocking update checking in the background at application startup.
   - Dedicated `UpdateDialog` showing detailed release notes, changelog formatting, and version comparison (`v1.0.0` ➔ `v1.1.0`).
   - Integrated downloader with real-time percentage, downloaded megabytes, and transfer rate.
   - Support for both `.zip` in-place application patches and `.exe` standalone installers.
   - Configurable update manifest URL in Settings (supports online web servers, GitHub Releases, or LAN network shares).
   - Manual "Check for Updates Now" trigger at any time.

6. **Interactive GIS Map Viewer**:
   - Automatically loads foundational layers at startup:
     - `BaseGrid.shp` (or `BaseGrid_2027.shp`) as the spatial grid base.
     - `bndry_kruger.shp` styled as **`Kruger Boundary`** (transparent fill with crisp dark perimeter outline, rendered directly on top of the grid).
   - Add/remove additional shapefiles (annual burn blocks, geology, section boundaries, fire management zones).
   - "Clear Secondary Layers" cleans temporary layers while keeping foundational BaseGrid and Kruger Boundary.
   - Map tools: Pan, Zoom In, Zoom Out, Full Extent, live mouse XY coordinate tracking.
   - Layer manager with visibility toggle checkboxes.

7. **Progress Dashboard & Institution Footer Banner**:
   - Two dedicated process rows anchored beneath the GIS map view:
     - `Import Rainfall Data` button + real-time progress bar + live elapsed timer (`elapsed time: 00:00:00`).
     - `Import Fire Data` button + real-time progress bar + live elapsed timer (`elapsed time: 00:00:00`).
   - Official branding footer banner featuring:
     - South African National Parks / Kruger National Park logo (`logo_kruger.jpg`).
     - Application title banner: **`ISP 4.0 - Kruger Fire Management Data Import Tool`**.
     - PROGES logo (`logo_proges.jpg`).
