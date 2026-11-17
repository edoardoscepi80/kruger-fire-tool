import os
import re
from typing import List, Dict, Any, Optional, Callable
from osgeo import ogr, osr
import shapely.wkb
from shapely.strtree import STRtree
from shapely.geometry import shape

from .fire_models import (
    calc_season,
    calc_frequency,
    calc_simulated_fuel_load_att,
    calc_simulated_fuel_load_nav,
    calc_rank_fuel_loads_nav,
    calc_fire_intensity,
    calc_classed_intensity_att,
    calc_classed_intensity_nav
)
from .db_manager import DatabaseManager


def extract_month_from_date(date_str: str) -> int:
    """
    Extracts month from strings like '2002-08-15', '2002/08/15', '15/08/2002', etc.
    Fallback to 8 (August / winter) if invalid.
    """
    if not date_str:
        return 8
    
    # Try ISO YYYY-MM-DD or YYYY/MM/DD
    m = re.search(r"\d{4}[-/](\d{1,2})[-/]\d{1,2}", str(date_str))
    if m:
        try:
            val = int(m.group(1))
            if 1 <= val <= 12:
                return val
        except ValueError:
            pass

    # Try DD-MM-YYYY or DD/MM/YYYY
    m = re.search(r"\d{1,2}[-/](\d{1,2})[-/]\d{4}", str(date_str))
    if m:
        try:
            val = int(m.group(1))
            if 1 <= val <= 12:
                return val
        except ValueError:
            pass

    return 8


class FireImportProcessor:
    def __init__(self, db_manager: DatabaseManager, base_grid_path: str):
        self.db = db_manager
        self.base_grid_path = base_grid_path

    def process_fire_shapefile(
        self,
        fire_shp_path: str,
        default_year: Optional[int] = None,
        default_date_start: Optional[str] = None,
        default_date_end: Optional[str] = None,
        default_cause: Optional[str] = None,
        default_comments: Optional[str] = None,
        default_fdi: Optional[float] = 50.0,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None
    ) -> Dict[str, Any]:
        """
        Executes the spatial intersection and ecological model calculations.
        Returns a summary dictionary with counts and elapsed stats.
        """
        if not os.path.exists(self.base_grid_path):
            raise FileNotFoundError(f"BaseGrid shapefile not found: {self.base_grid_path}")
        if not os.path.exists(fire_shp_path):
            raise FileNotFoundError(f"Fire shapefile not found: {fire_shp_path}")

        # 1. Load BaseGrid and build spatial index with Shapely STRtree
        if progress_callback:
            progress_callback(0, 100, "Loading BaseGrid and building spatial index...")

        grid_ds = ogr.Open(self.base_grid_path)
        if not grid_ds:
            raise RuntimeError(f"Could not open {self.base_grid_path}")
        grid_lyr = grid_ds.GetLayer()

        grid_geoms = []
        grid_fids = []
        for feat in grid_lyr:
            fid = feat.GetField("FID_GRID")
            geom_ref = feat.GetGeometryRef()
            if geom_ref and fid is not None:
                # Convert OGR to Shapely geometry
                wkb = bytes(geom_ref.ExportToWkb())
                s_geom = shapely.wkb.loads(wkb)
                grid_geoms.append(s_geom)
                grid_fids.append(int(fid))

        if not grid_geoms:
            raise RuntimeError("BaseGrid shapefile contains no valid features")

        tree = STRtree(grid_geoms)

        # 2. Open Fire Shapefile
        fire_ds = ogr.Open(fire_shp_path)
        if not fire_ds:
            raise RuntimeError(f"Could not open {fire_shp_path}")
        fire_lyr = fire_ds.GetLayer()
        total_fire_feats = fire_lyr.GetFeatureCount()

        defn = fire_lyr.GetLayerDefn()
        field_names = {defn.GetFieldDefn(i).GetName().upper(): defn.GetFieldDefn(i).GetName() for i in range(defn.GetFieldCount())}

        # 3. Read fire features into list
        fire_features_data = []
        years_involved = set()
        for feat in fire_lyr:
            geom_ref = feat.GetGeometryRef()
            if not geom_ref:
                continue
            wkb = bytes(geom_ref.ExportToWkb())
            s_geom = shapely.wkb.loads(wkb)

            # Extract fields
            def get_f(upper_name: str, fallback: Any) -> Any:
                if upper_name in field_names:
                    val = feat.GetField(field_names[upper_name])
                    if val is not None and str(val).strip() != "":
                        return val
                return fallback

            feat_year = get_f("FIRE_YEAR", get_f("YEAR", default_year))
            try:
                feat_year = int(float(feat_year))
            except (ValueError, TypeError):
                feat_year = default_year or 2002

            years_involved.add(feat_year)

            start_d = str(get_f("DATE_START", default_date_start or f"{feat_year}-08-01"))
            end_d = str(get_f("DATE_END", default_date_end or f"{feat_year}-08-05"))
            cause = str(get_f("FIRECAUSE", get_f("CAUSE", default_cause or "Management")))
            comments = str(get_f("COMMENTS", default_comments or ""))
            fdi_val = get_f("FDI", default_fdi or 50.0)
            try:
                fdi_val = float(fdi_val)
            except (ValueError, TypeError):
                fdi_val = 50.0

            fire_features_data.append({
                "geom": s_geom,
                "year": feat_year,
                "date_start": start_d,
                "date_end": end_d,
                "cause": cause,
                "comments": comments,
                "fdi": fdi_val
            })

        # 4. Preload rainfall and fire history lookups
        if progress_callback:
            progress_callback(10, 100, "Querying database for rainfall and fire history...")

        target_years = []
        for y in years_involved:
            target_years.extend([y - 1, y - 2])
        rainfall_lookup = self.db.get_rainfall_lookup(target_years)

        min_year = min(years_involved) if years_involved else 2002
        max_year = max(years_involved) if years_involved else 2002
        fire_history_lookup = self.db.get_fire_history_lookup(max_year + 1)

        # 5. Spatial Intersections and Model Calculations
        records_to_insert = []
        processed_fires = 0

        for fire_item in fire_features_data:
            if is_cancelled and is_cancelled():
                return {"status": "cancelled", "inserted": 0}

            processed_fires += 1
            if progress_callback:
                pct = int(10 + (processed_fires / len(fire_features_data)) * 70)
                progress_callback(pct, 100, f"Intersecting fire {processed_fires}/{len(fire_features_data)}...")

            f_geom = fire_item["geom"]
            f_year = fire_item["year"]
            start_date = fire_item["date_start"]
            end_date = fire_item["date_end"]
            cause = fire_item["cause"]
            comments = fire_item["comments"]
            fdi = fire_item["fdi"]

            # Year fire string, e.g. "2002-03"
            yf = f"{f_year}-{str(f_year + 1)[-2:]}"
            month = extract_month_from_date(start_date)

            # Query candidate cells using STRtree
            candidate_indices = tree.query(f_geom)
            for idx in candidate_indices:
                cell_geom = grid_geoms[idx]
                fid_grid = grid_fids[idx]

                if f_geom.intersects(cell_geom):
                    inter = f_geom.intersection(cell_geom)
                    if not inter.is_empty:
                        # Area in hectares (assuming coordinate system in meters)
                        area_ha = inter.area / 10000.0
                        if area_ha > 0.0001:
                            # 1. Rainfall (2Y Avg)
                            r1 = rainfall_lookup.get((f_year - 1, fid_grid), 0.0)
                            r2 = rainfall_lookup.get((f_year - 2, fid_grid), 0.0)
                            rainfall_avg = (r1 + r2) / 2.0 if (r1 and r2) else (r1 or r2 or 0.0)

                            # 2. Fire Frequency
                            prev_y = fire_history_lookup.get(fid_grid)
                            freq = calc_frequency(f_year, prev_y)

                            # 3. Fuel loads
                            fuel_att = calc_simulated_fuel_load_att(rainfall_avg, freq)
                            fuel_nav = calc_simulated_fuel_load_nav(rainfall_avg, freq)
                            rank_nav = calc_rank_fuel_loads_nav(fuel_nav)

                            # 4. Season
                            season_att = calc_season(month)
                            season_nav = season_att

                            # 5. Fire Intensity
                            int_att = calc_fire_intensity(season_att, fuel_att)
                            int_nav = calc_fire_intensity(season_nav, fuel_nav)

                            # 6. Classed Intensity
                            class_att = calc_classed_intensity_att(int_att, fdi)
                            class_nav = calc_classed_intensity_nav(rank_nav, season_nav, fdi)

                            records_to_insert.append({
                                "AREA_BURNT": area_ha,
                                "YEAR": str(f_year),
                                "YEAR_FIRE": yf,
                                "FID_GRID": fid_grid,
                                "DATE_START": start_date,
                                "DATE_END": end_date,
                                "FIRECAUSE": cause,
                                "COMMENTS": comments,
                                "SIMULATED_FUEL_LOAD_ATT": fuel_att,
                                "SIMULATED_FUEL_LOAD_NAV": fuel_nav,
                                "Rank_fuel_loads_Nav": rank_nav,
                                "FREQUENCY": str(freq),
                                "Fire_intensity_Att": int_att,
                                "Fire_intensity_Nav": int_nav,
                                "MONTH": str(month).zfill(2),
                                "SEASON_ATT": season_att,
                                "SEASON_NAV": season_nav,
                                "FDI": str(int(fdi)),
                                "Classed_Intensity_Att": class_att,
                                "Classed_Intensity_Nav": class_nav,
                                "RAIN_2Y_AVG": round(rainfall_avg)
                            })

        # 6. Save records into Db.mdb
        if progress_callback:
            progress_callback(85, 100, f"Saving {len(records_to_insert)} records to Db.mdb...")

        inserted = self.db.insert_fire_records(records_to_insert)

        if progress_callback:
            progress_callback(100, 100, "Import completed successfully!")

        return {
            "status": "success",
            "fire_features": len(fire_features_data),
            "intersections": len(records_to_insert),
            "inserted": inserted
        }
