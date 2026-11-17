import os
import pyodbc
from typing import Dict, Tuple, List, Optional, Any


class DatabaseManager:
    def __init__(self, mdb_path: str):
        self.mdb_path = mdb_path
        self._conn = None

    def connect(self) -> pyodbc.Connection:
        if not os.path.exists(self.mdb_path):
            raise FileNotFoundError(f"Database file not found: {self.mdb_path}")
        
        conn_str = rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={self.mdb_path};"
        return pyodbc.connect(conn_str, autocommit=False)

    def test_connection(self) -> Tuple[bool, str]:
        try:
            conn = self.connect()
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            conn.close()
            return True, "Connected successfully"
        except Exception as e:
            return False, str(e)

    def get_rainfall_lookup(self, target_years: List[int]) -> Dict[Tuple[int, int], float]:
        """
        Pre-loads rainfall for target years (e.g. Year-1 and Year-2) into a dictionary:
        (year, fid_grid) -> rainfall value.
        Massively accelerates processing compared to single-cell queries.
        """
        lookup = {}
        if not target_years:
            return lookup

        conn = self.connect()
        try:
            cursor = conn.cursor()
            years_str = ", ".join(str(int(y)) for y in set(target_years))
            query = f"SELECT [Year], [FID_GRID], [Rainfall] FROM Qry_RAINFALL WHERE [Year] IN ({years_str})"
            cursor.execute(query)
            for y, fid, r in cursor.fetchall():
                if y is not None and fid is not None and r is not None:
                    lookup[(int(y), int(fid))] = float(r)
        finally:
            conn.close()
        return lookup

    def get_fire_history_lookup(self, before_year: int) -> Dict[int, int]:
        """
        Pre-loads MAX(YEAR) from FIRE for each FID_GRID where YEAR < before_year:
        fid_grid -> max_prev_year.
        """
        lookup = {}
        conn = self.connect()
        try:
            cursor = conn.cursor()
            # In Access, YEAR is a text column in FIRE table
            query = f"SELECT [FID_GRID], MAX(CInt([YEAR])) FROM FIRE WHERE CInt([YEAR]) < {before_year} GROUP BY [FID_GRID]"
            cursor.execute(query)
            for fid, max_y in cursor.fetchall():
                if fid is not None and max_y is not None:
                    lookup[int(fid)] = int(max_y)
        except Exception:
            # Fallback if CInt fails due to non-numeric strings
            try:
                cursor.execute(f"SELECT [FID_GRID], [YEAR] FROM FIRE")
                for fid, y in cursor.fetchall():
                    if fid is not None and y is not None:
                        try:
                            iy = int(float(y))
                            if iy < before_year:
                                if fid not in lookup or iy > lookup[fid]:
                                    lookup[int(fid)] = iy
                        except ValueError:
                            pass
            except Exception:
                pass
        finally:
            conn.close()
        return lookup

    def insert_fire_records(self, records: List[dict], batch_size: int = 500) -> int:
        """
        Inserts calculated fire records into the FIRE table using parameterized batch inserts.
        """
        if not records:
            return 0

        insert_sql = """
            INSERT INTO [FIRE] (
                [AREA_BURNT], [YEAR], [YEAR_FIRE], [FID_GRID], [DATE_START], [DATE_END],
                [FIRECAUSE], [COMMENTS], [SIMULATED_FUEL_LOAD_ATT], [SIMULATED_FUEL_LOAD_NAV],
                [Rank_fuel_loads_Nav], [FREQUENCY], [Fire_intensity_Att], [Fire_intensity_Nav],
                [MONTH], [SEASON_ATT], [SEASON_NAV], [FDI], [Classed_Intensity_Att],
                [Classed_Intensity_Nav], [RAIN_2Y_AVG]
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        conn = self.connect()
        inserted = 0
        try:
            cursor = conn.cursor()
            params_list = []
            for r in records:
                params_list.append((
                    float(r.get("AREA_BURNT", 0.0)),
                    str(r.get("YEAR", "")),
                    str(r.get("YEAR_FIRE", "")),
                    float(r.get("FID_GRID", 0)),
                    str(r.get("DATE_START", "")),
                    str(r.get("DATE_END", "")),
                    str(r.get("FIRECAUSE", "")),
                    str(r.get("COMMENTS", "")),
                    float(r.get("SIMULATED_FUEL_LOAD_ATT", 0.0)),
                    float(r.get("SIMULATED_FUEL_LOAD_NAV", 0.0)),
                    int(r.get("Rank_fuel_loads_Nav", 1)),
                    str(r.get("FREQUENCY", "6")),
                    float(r.get("Fire_intensity_Att", 0.0)),
                    float(r.get("Fire_intensity_Nav", 0.0)),
                    str(r.get("MONTH", "")),
                    str(r.get("SEASON_ATT", "")),
                    str(r.get("SEASON_NAV", "")),
                    str(r.get("FDI", "")),
                    str(r.get("Classed_Intensity_Att", "")),
                    str(r.get("Classed_Intensity_Nav", "")),
                    round(r.get("RAIN_2Y_AVG", 0))
                ))

                if len(params_list) >= batch_size:
                    cursor.executemany(insert_sql, params_list)
                    conn.commit()
                    inserted += len(params_list)
                    params_list = []

            if params_list:
                cursor.executemany(insert_sql, params_list)
                conn.commit()
                inserted += len(params_list)

        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

        return inserted

    def get_unimported_rainfall_stations(self) -> List[dict]:
        """
        Retrieves station yearly readings where Imported = 'N'.
        """
        conn = self.connect()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM [Rainfall_Station_Yearly_Reading] WHERE [Imported] = 'N' ORDER BY [YEAR]")
            columns = [col[0] for col in cursor.description]
            results = []
            for row in cursor.fetchall():
                results.append(dict(zip(columns, row)))
            return results
        finally:
            conn.close()

    def get_grid_cell_weights(self) -> List[dict]:
        """
        Retrieves all cell weights from Rainfall_BaseGridCells_Weight.
        """
        conn = self.connect()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM [Rainfall_BaseGridCells_Weight] ORDER BY [FID_GRID]")
            columns = [col[0] for col in cursor.description]
            results = []
            for row in cursor.fetchall():
                results.append(dict(zip(columns, row)))
            return results
        finally:
            conn.close()

    def insert_rainfall_records(self, records: List[dict], batch_size: int = 1000) -> int:
        """
        Batch inserts spatialized rainfall records into Qry_RAINFALL.
        """
        if not records:
            return 0

        insert_sql = """
            INSERT INTO [Qry_RAINFALL] ([Rainfall], [RAINFALL_2Y_AVG], [YEAR], [YEAR_RAIN], [FID_GRID])
            VALUES (?, ?, ?, ?, ?)
        """

        conn = self.connect()
        inserted = 0
        try:
            cursor = conn.cursor()
            params_list = []
            for r in records:
                params_list.append((
                    float(int(r["Rainfall"])),
                    float(int(r["RAINFALL_2Y_AVG"])),
                    float(r["YEAR"]),
                    str(r["YEAR_RAIN"]),
                    float(r["FID_GRID"])
                ))
                if len(params_list) >= batch_size:
                    cursor.executemany(insert_sql, params_list)
                    conn.commit()
                    inserted += len(params_list)
                    params_list = []

            if params_list:
                cursor.executemany(insert_sql, params_list)
                conn.commit()
                inserted += len(params_list)

        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

        return inserted

    def mark_rainfall_stations_imported(self, years: Optional[List[int]] = None) -> None:
        """
        Marks readings as Imported = 'Y'. If years are provided, marks only those.
        """
        conn = self.connect()
        try:
            cursor = conn.cursor()
            if years:
                years_str = ", ".join(str(float(y)) for y in years)
                cursor.execute(f"UPDATE [Rainfall_Station_Yearly_Reading] SET [Imported] = 'Y' WHERE [YEAR] IN ({years_str})")
            else:
                cursor.execute("UPDATE [Rainfall_Station_Yearly_Reading] SET [Imported] = 'Y'")
            conn.commit()
        finally:
            conn.close()

    def get_all_station_readings(self) -> List[dict]:
        """
        Retrieves all station yearly readings ordered by YEAR descending.
        """
        conn = self.connect()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM [Rainfall_Station_Yearly_Reading] ORDER BY [YEAR] DESC")
            columns = [col[0] for col in cursor.description]
            results = []
            for row in cursor.fetchall():
                results.append(dict(zip(columns, row)))
            return results
        finally:
            conn.close()

    def get_station_reading(self, year: int) -> Optional[dict]:
        """
        Retrieves a single year's station reading.
        """
        conn = self.connect()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM [Rainfall_Station_Yearly_Reading] WHERE [YEAR] = ?", (float(year),))
            columns = [col[0] for col in cursor.description]
            row = cursor.fetchone()
            if row:
                return dict(zip(columns, row))
            return None
        finally:
            conn.close()

    def save_station_reading(self, reading_data: dict) -> None:
        """
        Inserts or updates a yearly reading in Rainfall_Station_Yearly_Reading.
        """
        station_cols = [
            'BDL', 'KRO', 'HOU', 'KFI', 'LET', 'OSA', 'MAH', 'MAL', 'MOO', 'NWA',
            'OLI', 'PHA', 'PRE', 'PUN', 'SAT', 'SHI', 'SKZ', 'STO', 'TSH', 'VLA', 'WOO'
        ]
        year = float(reading_data["YEAR"])
        year_rain = str(reading_data.get("YEAR_RAIN", f"{int(year)}-{str(int(year)+1)[-2:]}"))
        imported = str(reading_data.get("Imported", "N"))

        conn = self.connect()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM [Rainfall_Station_Yearly_Reading] WHERE [YEAR] = ?", (year,))
            row = cursor.fetchone()
            exists = (row[0] > 0) if row else False

            if exists:
                set_clauses = ["[YEAR_RAIN] = ?", "[Imported] = ?"] + [f"[{col}] = ?" for col in station_cols]
                sql = f"UPDATE [Rainfall_Station_Yearly_Reading] SET {', '.join(set_clauses)} WHERE [YEAR] = ?"
                values = [year_rain, imported]
                for col in station_cols:
                    val = reading_data.get(col)
                    values.append(float(val) if val is not None and str(val).strip() != "" else 0.0)
                values.append(year)
                cursor.execute(sql, tuple(values))
            else:
                cols = ["[YEAR]", "[YEAR_RAIN]", "[Imported]"] + [f"[{col}]" for col in station_cols]
                placeholders = ["?"] * len(cols)
                sql = f"INSERT INTO [Rainfall_Station_Yearly_Reading] ({', '.join(cols)}) VALUES ({', '.join(placeholders)})"
                values = [year, year_rain, imported]
                for col in station_cols:
                    val = reading_data.get(col)
                    values.append(float(val) if val is not None and str(val).strip() != "" else 0.0)
                cursor.execute(sql, tuple(values))

            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    def delete_station_reading(self, year: int) -> None:
        """
        Deletes a yearly record from Rainfall_Station_Yearly_Reading.
        """
        conn = self.connect()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM [Rainfall_Station_Yearly_Reading] WHERE [YEAR] = ?", (float(year),))
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    def set_station_reading_status(self, year: int, status: str) -> None:
        """
        Sets the Imported status ('Y' or 'N') for a specific year.
        """
        conn = self.connect()
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE [Rainfall_Station_Yearly_Reading] SET [Imported] = ? WHERE [YEAR] = ?", (str(status), float(year)))
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    def delete_grid_rainfall_for_years(self, years: List[int]) -> int:
        """
        Deletes records from Qry_RAINFALL for the given years (e.g. before re-spatializing).
        """
        if not years:
            return 0
        conn = self.connect()
        deleted = 0
        try:
            cursor = conn.cursor()
            for y in years:
                cursor.execute("DELETE FROM [Qry_RAINFALL] WHERE [YEAR] = ?", (float(y),))
                deleted += cursor.rowcount
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
        return deleted
