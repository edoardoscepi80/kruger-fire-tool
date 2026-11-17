import warnings
warnings.filterwarnings("ignore")

import os
import shutil
import pyodbc
import numpy as np
from scipy.spatial import cKDTree

from qgis.core import (
    QgsApplication, QgsVectorLayer, QgsVectorFileWriter, QgsFeature,
    QgsGeometry, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsProject, QgsPointXY, QgsField, QgsCoordinateTransformContext
)

def run():
    print("=" * 70)
    print("STARTING BASEGRID_2027 GENERATION (2 KM BOUNDARY BUFFER)")
    print("=" * 70)

    app = QgsApplication([], False)
    app.initQgis()

    shapefiles_dir = r"C:\Users\Utente\OneDrive\00.LAVORO\000.DSS_PROGES\DSS Kruger\ShapeFiles"
    tabular_dir = r"C:\Users\Utente\OneDrive\00.LAVORO\000.DSS_PROGES\DSS Kruger\TabularData"
    
    base_grid_path = os.path.join(shapefiles_dir, "BaseGrid.shp")
    bndry_path = os.path.join(shapefiles_dir, "bndry_kruger.shp")
    out_shp_path = os.path.join(shapefiles_dir, "BaseGrid_2027.shp")
    mdb_path = os.path.join(tabular_dir, "Db.mdb")
    mdb_backup_path = os.path.join(tabular_dir, "Db_backup_before_2027_grid.mdb")

    # 1. Safety Backup of Db.mdb
    print(f"\n[1/6] Creating database backup at:\n      {mdb_backup_path}")
    if not os.path.exists(mdb_backup_path):
        shutil.copyfile(mdb_path, mdb_backup_path)
        print("      Database backup created successfully!")
    else:
        print("      Backup already exists, proceeding safely.")

    # 2. Load layers
    print("\n[2/6] Loading source shapefiles...")
    grid_layer = QgsVectorLayer(base_grid_path, "BaseGrid", "ogr")
    bndry_layer = QgsVectorLayer(bndry_path, "Boundary", "ogr")
    assert grid_layer.isValid(), "BaseGrid.shp is invalid"
    assert bndry_layer.isValid(), "bndry_kruger.shp is invalid"

    total_orig = grid_layer.featureCount()
    print(f"      BaseGrid.shp loaded: {total_orig} features.")

    # 3. Read existing features & build KDTree for nearest neighbor classification
    print("\n[3/6] Reading existing features & training spatial KDTree...")
    orig_features = []
    orig_coords = []
    existing_cells_map = {}

    for f in grid_layer.getFeatures():
        bbox = f.geometry().boundingBox()
        x0 = round(bbox.xMinimum())
        y0 = round(bbox.yMinimum())
        existing_cells_map[(x0, y0)] = f
        orig_features.append(f)
        orig_coords.append([float(f["POINT_X"]), float(f["POINT_Y"])])

    kdtree = cKDTree(np.array(orig_coords))
    print(f"      KDTree built with {len(orig_coords)} cell centroids.")

    # 4. Generate 2km buffer around boundary and identify new cells
    print("\n[4/6] Buffering boundary by 2,000 meters and finding new cells...")
    bndry_feat = next(bndry_layer.getFeatures())
    bndry_geom = bndry_feat.geometry()
    bndry_buf_2km = bndry_geom.buffer(2000, 8)

    bbox = bndry_buf_2km.boundingBox()
    min_x = int(bbox.xMinimum() // 1000 * 1000)
    max_x = int(bbox.xMaximum() // 1000 * 1000) + 1000
    min_y = int(bbox.yMinimum() // 1000 * 1000)
    max_y = int(bbox.yMaximum() // 1000 * 1000) + 1000

    new_cells_origins = []
    for x in range(min_x, max_x, 1000):
        for y in range(min_y, max_y, 1000):
            if (x, y) not in existing_cells_map:
                poly = QgsGeometry.fromWkt(f"POLYGON(({x} {y}, {x+1000} {y}, {x+1000} {y+1000}, {x} {y+1000}, {x} {y}))")
                if poly.intersects(bndry_buf_2km):
                    new_cells_origins.append((x, y))

    # Sort new cells from North to South, West to East
    new_cells_origins.sort(key=lambda item: (-item[1], item[0]))
    print(f"      Found {len(new_cells_origins)} new cells to add (Total will be {total_orig + len(new_cells_origins)}).")

    # 5. Create new features with Nearest Neighbor classification
    print("\n[5/6] Creating BaseGrid_2027.shp with classified attributes...")
    new_features_to_write = []
    new_records_for_db = []
    next_fid = total_orig

    for x0, y0 in new_cells_origins:
        cx = x0 + 500.0
        cy = y0 + 500.0
        poly_geom = QgsGeometry.fromWkt(f"POLYGON(({x0} {y0}, {x0+1000} {y0}, {x0+1000} {y0+1000}, {x0} {y0+1000}, {x0} {y0}))")

        # Nearest neighbor query
        dist, nearest_idx = kdtree.query([cx, cy])
        src_feat = orig_features[nearest_idx]

        new_feat = QgsFeature(grid_layer.fields())
        new_feat.setGeometry(poly_geom)

        dem_val = int(src_feat["DEM"]) if src_feat["DEM"] is not None else 300
        block_val = str(src_feat["BLOCKNUM"]) if src_feat["BLOCKNUM"] is not None else "OUT"
        zone_val = str(src_feat["ZONE"]) if src_feat["ZONE"] is not None else "Zone 1"
        geo_val = str(src_feat["GEOLOGY"]) if src_feat["GEOLOGY"] is not None else "Unknown"
        eco_val = str(src_feat["ECOZONES"]) if src_feat["ECOZONES"] is not None else "Unknown"
        soil_val = str(src_feat["SOIL"]) if src_feat["SOIL"] is not None else "Unknown"
        veg_val = str(src_feat["VEGETATION"]) if src_feat["VEGETATION"] is not None else "Unknown"
        sec_val = str(src_feat["SECTION"]) if src_feat["SECTION"] is not None else "Unknown"
        sect_zone_val = f"{sec_val} - {zone_val}"

        new_feat["DEM"] = dem_val
        new_feat["POINT_X"] = cx
        new_feat["POINT_Y"] = cy
        new_feat["BLOCKNUM"] = block_val
        new_feat["ZONE"] = zone_val
        new_feat["GEOLOGY"] = geo_val
        new_feat["ECOZONES"] = eco_val
        new_feat["SOIL"] = soil_val
        new_feat["VEGETATION"] = veg_val
        new_feat["FID_GRID"] = float(next_fid)
        new_feat["FID_new_1"] = int(next_fid)
        new_feat["SECTION"] = sec_val
        new_feat["Sect_Zone"] = sect_zone_val

        new_features_to_write.append(new_feat)
        new_records_for_db.append({
            "FID_GRID": float(next_fid),
            "DEM": float(dem_val),
            "POINT_X": float(cx),
            "POINT_Y": float(cy),
            "BLOCKNUM": block_val,
            "ZONE": zone_val,
            "GEOLOGY": geo_val,
            "ECOZONES": eco_val,
            "SOIL": soil_val,
            "VEGETATION": veg_val,
            "SECTION": sec_val,
            "SECT_ZONE": sect_zone_val,
            "NEAREST_FID": float(src_feat["FID_GRID"])
        })
        next_fid += 1

    # Write out BaseGrid_2027.shp
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "ESRI Shapefile"
    options.fileEncoding = "UTF-8"

    writer = QgsVectorFileWriter.create(
        out_shp_path,
        grid_layer.fields(),
        grid_layer.wkbType(),
        grid_layer.crs(),
        QgsCoordinateTransformContext(),
        options
    )
    assert not writer.hasError(), f"Error creating shapefile writer: {writer.errorMessage()}"

    # Add all original features
    for f in orig_features:
        writer.addFeature(f)

    # Add all new features
    for f in new_features_to_write:
        writer.addFeature(f)

    del writer
    print(f"      Successfully saved: {out_shp_path}")
    print(f"      Total features in BaseGrid_2027.shp: {total_orig + len(new_features_to_write)}")

    # 6. Update Database Db.mdb
    print("\n[6/6] Updating Db.mdb (BaseGrid & Rainfall_BaseGridCells_Weight tables)...")
    crs_utm = QgsCoordinateReferenceSystem("EPSG:32736")
    crs_wgs = QgsCoordinateReferenceSystem("EPSG:4326")
    trans = QgsCoordinateTransform(crs_utm, crs_wgs, QgsProject.instance())

    conn = pyodbc.connect(rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={mdb_path};")
    try:
        cur = conn.cursor()

        # Check existing BaseGrid count
        cur.execute("SELECT COUNT(*) FROM [BaseGrid]")
        db_bg_count = cur.fetchone()[0]
        print(f"      Current rows in [BaseGrid]: {db_bg_count}")

        # Delete any records >= 18948 if re-running
        cur.execute(f"DELETE FROM [BaseGrid] WHERE [FID_GRID] >= {total_orig}")
        cur.execute(f"DELETE FROM [Rainfall_BaseGridCells_Weight] WHERE [FID_GRID] >= {total_orig}")
        conn.commit()

        # A. Insert into [BaseGrid]
        insert_bg_sql = """
            INSERT INTO [BaseGrid] (
                [DEM], [POINT_X], [POINT_Y], [BLOCKNUM], [ZONE], [GEOLOGY],
                [ECOZONES], [SOIL], [VEGETATION], [FID_GRID], [SECTION], [SECT_ZONE]
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        bg_params = [
            (
                r["DEM"], r["POINT_X"], r["POINT_Y"], r["BLOCKNUM"], r["ZONE"], r["GEOLOGY"],
                r["ECOZONES"], r["SOIL"], r["VEGETATION"], r["FID_GRID"], r["SECTION"], r["SECT_ZONE"]
            )
            for r in new_records_for_db
        ]
        cur.executemany(insert_bg_sql, bg_params)
        conn.commit()
        print(f"      Inserted {len(bg_params)} new rows into [BaseGrid].")

        # B. Insert into [Rainfall_BaseGridCells_Weight]
        # Preload weights of nearest cells
        print("      Loading existing station weights for nearest neighbor mapping...")
        cur.execute("SELECT * FROM [Rainfall_BaseGridCells_Weight]")
        weight_cols = [c[0] for c in cur.description]
        station_cols = [
            'BDL', 'KRO', 'HOU', 'KFI', 'LET', 'OSA', 'MAH', 'MAL', 'MOO', 'NWA',
            'OLI', 'PHA', 'PRE', 'PUN', 'SAT', 'SHI', 'SKZ', 'STO', 'TSH', 'VLA', 'WOO'
        ]
        weights_by_fid = {}
        for row in cur.fetchall():
            row_dict = dict(zip(weight_cols, row))
            weights_by_fid[float(row_dict["FID_GRID"])] = row_dict

        insert_w_sql = f"""
            INSERT INTO [Rainfall_BaseGridCells_Weight] (
                [DEM], [FID_GRID], [LAT], [LONG],
                {', '.join(f'[{c}]' for c in station_cols)}
            ) VALUES ({', '.join(['?'] * (4 + len(station_cols)))})
        """
        w_params = []
        for r in new_records_for_db:
            pt = trans.transform(QgsPointXY(r["POINT_X"], r["POINT_Y"]))
            lat = pt.y()
            lon = pt.x()

            src_w = weights_by_fid.get(r["NEAREST_FID"], {})
            row_vals = [r["DEM"], r["FID_GRID"], lat, lon]
            for st in station_cols:
                row_vals.append(float(src_w.get(st, 0.0)))
            w_params.append(tuple(row_vals))

        cur.executemany(insert_w_sql, w_params)
        conn.commit()
        print(f"      Inserted {len(w_params)} new rows into [Rainfall_BaseGridCells_Weight].")

        # Verify new totals in database
        cur.execute("SELECT COUNT(*) FROM [BaseGrid]")
        final_bg = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM [Rainfall_BaseGridCells_Weight]")
        final_w = cur.fetchone()[0]
        print(f"\n      VERIFICATION:")
        print(f"      Total rows in [BaseGrid]: {final_bg}")
        print(f"      Total rows in [Rainfall_BaseGridCells_Weight]: {final_w}")

    finally:
        conn.close()

    app.exitQgis()
    print("\n" + "=" * 70)
    print("BASEGRID_2027 AND DATABASE UPDATE COMPLETED SUCCESSFULLY!")
    print("=" * 70)

if __name__ == "__main__":
    run()
