from typing import List, Dict, Any, Tuple, Optional, Callable
from .db_manager import DatabaseManager


STATION_CODES = [
    'BDL', 'KRO', 'HOU', 'KFI', 'LET', 'OSA', 'MAH', 'MAL', 'MOO', 'NWA',
    'OLI', 'PHA', 'PRE', 'PUN', 'SAT', 'SHI', 'SKZ', 'STO', 'TSH', 'VLA', 'WOO'
]

STATION_METADATA = {
    'BDL': {'name': 'Boulders', 'region': 'North-Central'},
    'KRO': {'name': 'Crocodile Bridge', 'region': 'South-East'},
    'HOU': {'name': 'Houtboschrand', 'region': 'Central'},
    'KFI': {'name': 'Kingfisherspruit', 'region': 'Central-West'},
    'LET': {'name': 'Letaba', 'region': 'Central-North'},
    'OSA': {'name': 'Olifants South / Safari', 'region': 'Central'},
    'MAH': {'name': 'Mahlangeni', 'region': 'Far North'},
    'MAL': {'name': 'Malelane', 'region': 'Far South'},
    'MOO': {'name': 'Mooiplaas', 'region': 'North'},
    'NWA': {'name': 'Nwanetsi', 'region': 'East-Central'},
    'OLI': {'name': 'Olifants', 'region': 'Central'},
    'PHA': {'name': 'Phalaborwa', 'region': 'Central-West'},
    'PRE': {'name': 'Pretoriuskop', 'region': 'South-West'},
    'PUN': {'name': 'Punda Maria', 'region': 'Far North'},
    'SAT': {'name': 'Satara', 'region': 'Central'},
    'SHI': {'name': 'Shingwedzi', 'region': 'North'},
    'SKZ': {'name': 'Skukuza', 'region': 'South'},
    'STO': {'name': 'Stolsnek', 'region': 'South-West'},
    'TSH': {'name': 'Tshokwane', 'region': 'Central-South'},
    'VLA': {'name': 'Vlakteplaas', 'region': 'North'},
    'WOO': {'name': 'Woodlands', 'region': 'North-East'}
}


class RainfallProcessor:
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def spatialize_pending_rainfall(
        self,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None
    ) -> Dict[str, Any]:
        """
        Processes pending station yearly readings (Imported = 'N') and spatializes
        rainfall onto all 18,948 grid cells using Rainfall_BaseGridCells_Weight.
        """
        if progress_callback:
            progress_callback(0, 100, "Checking for pending rainfall station readings...")

        readings = self.db.get_unimported_rainfall_stations()
        if not readings:
            return {
                "status": "up_to_date",
                "message": "All available rainfall station readings are already spatialized.",
                "inserted": 0
            }

        if progress_callback:
            progress_callback(10, 100, "Loading grid cell weights...")

        weights = self.db.get_grid_cell_weights()
        if not weights:
            raise RuntimeError("Rainfall_BaseGridCells_Weight table is empty or could not be read.")

        years_to_process = sorted(list(set(int(r["YEAR"]) for r in readings if r.get("YEAR") is not None)))
        
        # Clean any existing records in Qry_RAINFALL for years_to_process to prevent duplicate grid records
        self.db.delete_grid_rainfall_for_years(years_to_process)

        # Preload prior rainfall for 2Y average calculation
        prior_years = []
        for y in years_to_process:
            prior_years.extend([y - 1, y - 2])
        rainfall_lookup = self.db.get_rainfall_lookup(prior_years)

        records_to_insert = []
        total_steps = len(weights)
        current_step = 0

        for w_row in weights:
            if is_cancelled and is_cancelled():
                return {"status": "cancelled", "inserted": 0}

            current_step += 1
            if progress_callback and current_step % 1000 == 0:
                pct = int(15 + (current_step / total_steps) * 65)
                progress_callback(pct, 100, f"Spatializing cells: {current_step}/{total_steps}...")

            fid_grid = int(w_row["FID_GRID"])

            # Extract weights for the 21 stations
            w_dict = {}
            for st in STATION_CODES:
                val = w_row.get(st)
                w_dict[st] = float(val) if val is not None else 0.0

            for r_row in readings:
                year = int(r_row["YEAR"])
                year_rain = str(r_row.get("YEAR_RAIN", f"{year}-{str(year+1)[-2:]}"))

                # Linear combination of station weights * station rainfall
                cell_rainfall = 0.0
                for st in STATION_CODES:
                    st_rain = r_row.get(st)
                    if st_rain is not None:
                        cell_rainfall += w_dict[st] * float(st_rain)

                # Prior years for 2Y average
                r1 = rainfall_lookup.get((year - 1, fid_grid), 0.0)
                r2 = rainfall_lookup.get((year - 2, fid_grid), 0.0)
                rain_2y_avg = (r1 + r2) / 2.0 if (r1 and r2) else (r1 or r2 or cell_rainfall)

                # Keep local lookup updated for subsequent years in same batch
                rainfall_lookup[(year, fid_grid)] = cell_rainfall

                records_to_insert.append({
                    "Rainfall": round(cell_rainfall),
                    "RAINFALL_2Y_AVG": round(rain_2y_avg),
                    "YEAR": float(year),
                    "YEAR_RAIN": year_rain,
                    "FID_GRID": float(fid_grid)
                })

        if progress_callback:
            progress_callback(85, 100, f"Saving {len(records_to_insert)} spatialized rainfall records...")

        inserted = self.db.insert_rainfall_records(records_to_insert)

        # Mark readings as imported
        self.db.mark_rainfall_stations_imported(years_to_process)

        if progress_callback:
            progress_callback(100, 100, "Rainfall spatialization completed successfully!")

        return {
            "status": "success",
            "years_processed": years_to_process,
            "cells_count": len(weights),
            "inserted": inserted
        }

    def diagnose_grid_and_weights(self) -> Dict[str, Any]:
        """
        Runs comprehensive diagnosis on BaseGrid vs Weights vs Qry_RAINFALL.
        Identifies missing cells, zero-weight sums, or incomplete years.
        """
        conn = self.db.connect()
        try:
            cursor = conn.cursor()

            # 1. Total cells in weights
            cursor.execute("SELECT COUNT(*) FROM Rainfall_BaseGridCells_Weight")
            row = cursor.fetchone()
            total_weights = row[0] if row is not None else 0

            # 2. Check for missing FID_GRIDs from 0 to 18947
            cursor.execute("SELECT FID_GRID FROM Rainfall_BaseGridCells_Weight")
            fids = set(int(r[0]) for r in cursor.fetchall() if r[0] is not None)

            expected_fids = set(range(18948))
            missing_in_weights = expected_fids - fids

            # 3. Check Qry_RAINFALL distinct cells per year
            cursor.execute("SELECT [Year], [FID_GRID] FROM Qry_RAINFALL")
            year_cells = {}
            for y, fid in cursor.fetchall():
                if y is not None and fid is not None:
                    year_cells.setdefault(int(y), set()).add(int(fid))

            incomplete_years = {}
            for y, cell_set in sorted(year_cells.items()):
                missing_count = 18948 - len(cell_set)
                if missing_count > 0:
                    incomplete_years[y] = {
                        "present": len(cell_set),
                        "missing": missing_count,
                        "sample_missing": sorted(list(expected_fids - cell_set))[:5]
                    }

            return {
                "total_weight_rows": total_weights,
                "missing_in_weights": sorted(list(missing_in_weights)),
                "total_years_in_db": len(year_cells),
                "year_range": (min(year_cells.keys()), max(year_cells.keys())) if year_cells else (0, 0),
                "incomplete_years": incomplete_years
            }
        finally:
            conn.close()

    def backfill_missing_cells_history(
        self,
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> int:
        """
        Fills the historical gap for cells 18945, 18946, 18947 for years 1956-2014
        using station historical readings.
        """
        conn = self.db.connect()
        try:
            cursor = conn.cursor()

            # Get target cells
            target_fids = [18945, 18946, 18947]
            fids_str = ", ".join(str(f) for f in target_fids)
            cursor.execute(f"SELECT * FROM Rainfall_BaseGridCells_Weight WHERE FID_GRID IN ({fids_str})")
            columns = [c[0] for c in cursor.description]
            weight_rows = [dict(zip(columns, r)) for r in cursor.fetchall()]

            # Get station readings for all years
            cursor.execute("SELECT * FROM Rainfall_Station_Yearly_Reading ORDER BY [YEAR]")
            st_cols = [c[0] for c in cursor.description]
            station_readings = [dict(zip(st_cols, r)) for r in cursor.fetchall()]

            # Check existing records in Qry_RAINFALL for these cells
            cursor.execute(f"SELECT [Year], [FID_GRID] FROM Qry_RAINFALL WHERE FID_GRID IN ({fids_str})")
            existing = set((int(r[0]), int(r[1])) for r in cursor.fetchall())

            records_to_insert = []
            for w in weight_rows:
                fid = int(w["FID_GRID"])
                w_dict = {st: float(w[st]) if w.get(st) is not None else 0.0 for st in STATION_CODES}

                for sr in station_readings:
                    y = int(sr["YEAR"])
                    if (y, fid) in existing:
                        continue  # Already present

                    year_rain = str(sr.get("YEAR_RAIN", f"{y-1}-{str(y)[-2:]}"))
                    cell_rainfall = sum(w_dict[st] * float(sr[st]) for st in STATION_CODES if sr.get(st) is not None)

                    records_to_insert.append({
                        "Rainfall": round(cell_rainfall),
                        "RAINFALL_2Y_AVG": round(cell_rainfall),  # reasonable fallback
                        "YEAR": float(y),
                        "YEAR_RAIN": year_rain,
                        "FID_GRID": float(fid)
                    })

            if records_to_insert:
                return self.db.insert_rainfall_records(records_to_insert)
            return 0
        finally:
            conn.close()
