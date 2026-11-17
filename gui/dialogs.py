import os
import sys
import csv
import subprocess
from typing import Optional, List, Dict, Any
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit, QPushButton,
    QFileDialog, QMessageBox, QProgressBar, QTextEdit, QGroupBox,
    QFormLayout, QSpinBox, QDoubleSpinBox, QComboBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QFrame, QCheckBox
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QBrush

from config import load_settings, save_settings, APP_VERSION, APP_NAME
from core.db_manager import DatabaseManager
from core.fire_processor import FireImportProcessor
from core.rainfall_processor import RainfallProcessor, STATION_CODES, STATION_METADATA
from core.updater import (
    CheckUpdateWorker, DownloadUpdateWorker, launch_installer, create_batch_updater_script
)


# ==============================================================================
# Worker Threads for Asynchronous Processing
# ==============================================================================

class FireWorkerThread(QThread):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, processor: FireImportProcessor, fire_shp_path: str, **kwargs):
        super().__init__()
        self.processor = processor
        self.fire_shp_path = fire_shp_path
        self.kwargs = kwargs
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            def cb(cur, total, msg):
                self.progress.emit(cur, total, msg)

            def is_canc():
                return self._cancelled

            res = self.processor.process_fire_shapefile(
                self.fire_shp_path,
                progress_callback=cb,
                is_cancelled=is_canc,
                **self.kwargs
            )
            self.finished.emit(res)
        except Exception as e:
            self.error.emit(str(e))


class RainfallWorkerThread(QThread):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, processor: RainfallProcessor):
        super().__init__()
        self.processor = processor
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            def cb(cur, total, msg):
                self.progress.emit(cur, total, msg)

            def is_canc():
                return self._cancelled

            res = self.processor.spatialize_pending_rainfall(
                progress_callback=cb,
                is_cancelled=is_canc
            )
            self.finished.emit(res)
        except Exception as e:
            self.error.emit(str(e))


class BackfillWorkerThread(QThread):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(int)
    error = pyqtSignal(str)

    def __init__(self, processor: RainfallProcessor):
        super().__init__()
        self.processor = processor

    def run(self):
        try:
            def cb(cur, total, msg):
                self.progress.emit(cur, total, msg)

            inserted = self.processor.backfill_missing_cells_history(progress_callback=cb)
            self.finished.emit(inserted)
        except Exception as e:
            self.error.emit(str(e))


# ==============================================================================
# Online Auto-Update Dialog
# ==============================================================================

class UpdateDialog(QDialog):
    def __init__(self, update_info: dict, parent=None):
        super().__init__(parent)
        self.update_info = update_info
        self.setWindowTitle("Software Update Available - Kruger DSS")
        self.resize(600, 440)
        self.download_worker: Optional[DownloadUpdateWorker] = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        cur_v = self.update_info.get("current_version", APP_VERSION)
        new_v = self.update_info.get("latest_version", "1.0.0")
        rel_date = self.update_info.get("release_date", "Recently")

        lbl_header = QLabel(
            f"<h2 style='margin:0; color:#1e3a8a;'>🚀 A new version of Kruger DSS is available!</h2>"
            f"<p style='font-size:13px; margin:6px 0; color:#374151;'>"
            f"<b>Current Version:</b> <span style='color:#6b7280;'>v{cur_v}</span> &nbsp;&nbsp;➔&nbsp;&nbsp; "
            f"<b>New Version:</b> <span style='color:#16a34a; font-weight:bold;'>v{new_v}</span> "
            f"&nbsp;&nbsp;<i>(Released: {rel_date})</i></p>"
        )
        lbl_header.setTextFormat(Qt.RichText)
        layout.addWidget(lbl_header)

        # Changelog Group
        grp_cl = QGroupBox("Release Notes & Changelog", self)
        v_cl = QVBoxLayout(grp_cl)
        self.txt_changelog = QTextEdit(self)
        self.txt_changelog.setReadOnly(True)
        raw_cl = self.update_info.get("changelog", "No release notes provided.")
        self.txt_changelog.setPlainText(raw_cl)
        self.txt_changelog.setStyleSheet(
            "background:#f9fafb; border:1px solid #e5e7eb; font-family:Consolas, monospace; font-size:12px;"
        )
        v_cl.addWidget(self.txt_changelog)
        layout.addWidget(grp_cl)

        # Download Progress Area (hidden initially)
        self.progress_container = QWidget(self)
        v_prog = QVBoxLayout(self.progress_container)
        v_prog.setContentsMargins(0, 0, 0, 0)
        self.lbl_progress = QLabel("Preparing download...", self)
        self.lbl_progress.setStyleSheet("font-size:12px; color:#4b5563;")
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #d1d5db;
                border-radius: 4px;
                text-align: center;
                height: 20px;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: #2563eb;
            }
        """)
        v_prog.addWidget(self.lbl_progress)
        v_prog.addWidget(self.progress_bar)
        self.progress_container.setVisible(False)
        layout.addWidget(self.progress_container)

        # Buttons
        h_btns = QHBoxLayout()
        self.btn_update = QPushButton("⬇️ Download & Install Update", self)
        self.btn_update.setStyleSheet("""
            QPushButton {
                background: #16a34a;
                color: white;
                font-weight: bold;
                font-size: 13px;
                padding: 8px 18px;
                border-radius: 4px;
            }
            QPushButton:hover { background: #15803d; }
            QPushButton:disabled { background: #9ca3af; }
        """)
        self.btn_update.clicked.connect(self._start_download)

        self.btn_later = QPushButton("Remind Me Later", self)
        self.btn_later.clicked.connect(self._on_cancel)

        h_btns.addStretch()
        h_btns.addWidget(self.btn_update)
        h_btns.addWidget(self.btn_later)
        layout.addLayout(h_btns)

    def _start_download(self):
        self.btn_update.setEnabled(False)
        self.btn_later.setText("Cancel")
        self.progress_container.setVisible(True)
        self.lbl_progress.setText("Connecting to update server...")

        self.download_worker = DownloadUpdateWorker(self.update_info)
        self.download_worker.progress.connect(self._on_download_progress)
        self.download_worker.finished.connect(self._on_download_finished)
        self.download_worker.error.connect(self._on_download_error)
        self.download_worker.start()

    def _on_download_progress(self, pct: int, downloaded: int, total: int):
        self.progress_bar.setValue(pct)
        mb_down = downloaded / (1024 * 1024)
        if total > 0:
            mb_tot = total / (1024 * 1024)
            self.lbl_progress.setText(f"Downloading update: {pct}% ({mb_down:.1f} MB / {mb_tot:.1f} MB)")
        else:
            self.lbl_progress.setText(f"Downloading update: {mb_down:.1f} MB downloaded...")

    def _on_download_finished(self, dest_path: str, pkg_type: str, info: dict):
        self.lbl_progress.setText("✔ Download complete!")
        self.progress_bar.setValue(100)

        if pkg_type == "installer":
            reply = QMessageBox.question(
                self, "Ready to Install",
                f"The new setup installer has been downloaded to:\n{dest_path}\n\n"
                f"Would you like to close the application and launch the installer now?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                launch_installer(dest_path)
                from PyQt5.QtWidgets import QApplication
                QApplication.quit()
        else:
            # Archive .zip
            reply = QMessageBox.question(
                self, "Ready to Apply Update",
                f"The update archive has been downloaded successfully.\n\n"
                f"Would you like to apply the update and restart the application now?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                main_py = os.path.join(app_dir, "main.py")
                launcher = sys.executable
                batch = create_batch_updater_script(dest_path, app_dir, launcher, main_py)
                subprocess.Popen(["cmd.exe", "/c", batch], shell=True)
                from PyQt5.QtWidgets import QApplication
                QApplication.quit()

        self.accept()

    def _on_download_error(self, err_msg: str):
        self.progress_container.setVisible(False)
        self.btn_update.setEnabled(True)
        self.btn_later.setText("Close")
        QMessageBox.critical(self, "Download Error", f"Failed to download update:\n{err_msg}")

    def _on_cancel(self):
        if self.download_worker and self.download_worker.isRunning():
            self.download_worker.cancel()
            self.download_worker.wait()
        self.reject()


# ==============================================================================
# Settings Dialog
# ==============================================================================

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings & Maintenance - Kruger DSS")
        self.resize(680, 480)
        self.settings = load_settings()
        self._check_thread: Optional[CheckUpdateWorker] = None

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # 1. Main Paths
        group_paths = QGroupBox("Main Application Paths (Kruger DSS)", self)
        form = QFormLayout(group_paths)

        # MDB Path
        h_mdb = QHBoxLayout()
        self.txt_mdb = QLineEdit(self.settings.get("mdb_path", ""), self)
        btn_mdb = QPushButton("Browse...", self)
        btn_mdb.clicked.connect(self._browse_mdb)
        h_mdb.addWidget(self.txt_mdb)
        h_mdb.addWidget(btn_mdb)
        form.addRow("Access Database (Db.mdb):", h_mdb)

        # BaseGrid Path
        h_grid = QHBoxLayout()
        self.txt_grid = QLineEdit(self.settings.get("base_grid_path", ""), self)
        btn_grid = QPushButton("Browse...", self)
        btn_grid.clicked.connect(self._browse_grid)
        h_grid.addWidget(self.txt_grid)
        h_grid.addWidget(btn_grid)
        form.addRow("BaseGrid Shapefile:", h_grid)

        # Kruger Boundary Path
        h_bndry = QHBoxLayout()
        self.txt_bndry = QLineEdit(self.settings.get("kruger_boundary_path", ""), self)
        btn_bndry = QPushButton("Browse...", self)
        btn_bndry.clicked.connect(self._browse_bndry)
        h_bndry.addWidget(self.txt_bndry)
        h_bndry.addWidget(btn_bndry)
        form.addRow("Kruger Boundary Shapefile:", h_bndry)

        # Shapefiles Directory
        h_shps = QHBoxLayout()
        self.txt_shps = QLineEdit(self.settings.get("shapefiles_dir", ""), self)
        btn_shps = QPushButton("Browse...", self)
        btn_shps.clicked.connect(self._browse_shps)
        h_shps.addWidget(self.txt_shps)
        h_shps.addWidget(btn_shps)
        form.addRow("ShapeFiles Directory:", h_shps)

        layout.addWidget(group_paths)

        # Test Connection button
        btn_test = QPushButton("Test Database Connection", self)
        btn_test.clicked.connect(self._test_connection)
        layout.addWidget(btn_test)

        # 2. Online Updates & Maintenance
        group_updates = QGroupBox("Online Updates & System Maintenance", self)
        v_upd = QVBoxLayout(group_updates)

        self.chk_auto_update = QCheckBox("Check for updates automatically on application startup", self)
        self.chk_auto_update.setChecked(self.settings.get("check_updates_on_startup", True))
        v_upd.addWidget(self.chk_auto_update)

        h_upd_url = QHBoxLayout()
        self.txt_update_url = QLineEdit(self.settings.get("update_manifest_url", ""), self)
        btn_browse_upd = QPushButton("Browse...", self)
        btn_browse_upd.clicked.connect(self._browse_manifest)
        h_upd_url.addWidget(self.txt_update_url)
        h_upd_url.addWidget(btn_browse_upd)

        form_upd = QFormLayout()
        form_upd.addRow("Update Server / Manifest URL:", h_upd_url)
        v_upd.addLayout(form_upd)

        h_upd_actions = QHBoxLayout()
        lbl_current_ver = QLabel(f"Installed Version: <b>v{APP_VERSION}</b>", self)
        self.btn_check_updates = QPushButton("🔍 Check for Updates Now", self)
        self.btn_check_updates.setStyleSheet("""
            QPushButton {
                background: #1e40af;
                color: white;
                font-weight: bold;
                padding: 6px 14px;
                border-radius: 4px;
            }
            QPushButton:hover { background: #1d4ed8; }
        """)
        self.btn_check_updates.clicked.connect(self._check_updates_manually)
        h_upd_actions.addWidget(lbl_current_ver)
        h_upd_actions.addStretch()
        h_upd_actions.addWidget(self.btn_check_updates)
        v_upd.addLayout(h_upd_actions)

        layout.addWidget(group_updates)

        # Bottom buttons
        btn_box = QHBoxLayout()
        btn_save = QPushButton("Save", self)
        btn_save.clicked.connect(self._save_and_close)
        btn_cancel = QPushButton("Cancel", self)
        btn_cancel.clicked.connect(self.reject)
        btn_box.addStretch()
        btn_box.addWidget(btn_save)
        btn_box.addWidget(btn_cancel)
        layout.addLayout(btn_box)

    def _browse_mdb(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select Db.mdb", self.txt_mdb.text(), "Access Database (*.mdb *.accdb)")
        if f:
            self.txt_mdb.setText(f)

    def _browse_grid(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select BaseGrid.shp", self.txt_grid.text(), "Shapefiles (*.shp)")
        if f:
            self.txt_grid.setText(f)

    def _browse_bndry(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select bndry_kruger.shp", self.txt_bndry.text(), "Shapefiles (*.shp)")
        if f:
            self.txt_bndry.setText(f)

    def _browse_shps(self):
        d = QFileDialog.getExistingDirectory(self, "Select ShapeFiles Directory", self.txt_shps.text())
        if d:
            self.txt_shps.setText(d)

    def _browse_manifest(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select version.json Manifest", self.txt_update_url.text(), "JSON Files (*.json)")
        if f:
            self.txt_update_url.setText(f)

    def _test_connection(self):
        db = DatabaseManager(self.txt_mdb.text())
        ok, msg = db.test_connection()
        if ok:
            QMessageBox.information(self, "Connection OK", "Connection to Db.mdb established successfully!")
        else:
            QMessageBox.critical(self, "Connection Error", f"Could not connect to database:\n{msg}")

    def _check_updates_manually(self):
        url = self.txt_update_url.text().strip()
        if not url:
            QMessageBox.warning(self, "Missing URL", "Please specify an update server manifest URL or file path.")
            return

        self.btn_check_updates.setEnabled(False)
        self.btn_check_updates.setText("Checking...")

        self._check_thread = CheckUpdateWorker(url, APP_VERSION)
        self._check_thread.updateFound.connect(self._on_manual_update_found)
        self._check_thread.upToDate.connect(self._on_manual_up_to_date)
        self._check_thread.checkFailed.connect(self._on_manual_check_failed)
        self._check_thread.start()

    def _on_manual_update_found(self, update_info: dict):
        self.btn_check_updates.setEnabled(True)
        self.btn_check_updates.setText("🔍 Check for Updates Now")
        dlg = UpdateDialog(update_info, self)
        dlg.exec_()

    def _on_manual_up_to_date(self, current_ver: str):
        self.btn_check_updates.setEnabled(True)
        self.btn_check_updates.setText("🔍 Check for Updates Now")
        QMessageBox.information(
            self, "Up to Date",
            f"You are running the latest version of Kruger DSS (v{current_ver})!\n\nNo updates are currently available."
        )

    def _on_manual_check_failed(self, err_msg: str):
        self.btn_check_updates.setEnabled(True)
        self.btn_check_updates.setText("🔍 Check for Updates Now")
        QMessageBox.warning(
            self, "Update Check Failed",
            f"Could not reach update server or parse manifest:\n\n{err_msg}"
        )

    def _save_and_close(self):
        self.settings["mdb_path"] = self.txt_mdb.text()
        self.settings["base_grid_path"] = self.txt_grid.text()
        self.settings["kruger_boundary_path"] = self.txt_bndry.text()
        self.settings["shapefiles_dir"] = self.txt_shps.text()
        self.settings["check_updates_on_startup"] = self.chk_auto_update.isChecked()
        self.settings["update_manifest_url"] = self.txt_update_url.text().strip()
        save_settings(self.settings)
        self.accept()



# ==============================================================================
# Fire Import Dialog
# ==============================================================================

class FireImportDialog(QDialog):
    importStarted = pyqtSignal()
    importProgress = pyqtSignal(int, int, str)
    importFinished = pyqtSignal(dict)
    importError = pyqtSignal(str)

    def __init__(self, db_manager: DatabaseManager, base_grid_path: str, preloaded_shp: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import Fire Data")
        self.resize(650, 480)
        self.db = db_manager
        self.base_grid_path = base_grid_path
        self.thread: Optional[FireWorkerThread] = None

        self._setup_ui(preloaded_shp)

    def _setup_ui(self, preloaded_shp: Optional[str]):
        layout = QVBoxLayout(self)

        # File Selection
        h_file = QHBoxLayout()
        self.txt_shp = QLineEdit(preloaded_shp or "", self)
        btn_browse = QPushButton("Browse...", self)
        btn_browse.clicked.connect(self._browse_shp)
        h_file.addWidget(self.txt_shp)
        h_file.addWidget(btn_browse)

        layout.addWidget(QLabel("Fire Shapefile to Process:"))
        layout.addLayout(h_file)

        # Parameters
        grp_param = QGroupBox("Fallback Parameters (used if not present in SHP attributes):", self)
        form = QFormLayout(grp_param)

        self.spn_year = QSpinBox(self)
        self.spn_year.setRange(1950, 2050)
        self.spn_year.setValue(2002)
        form.addRow("Fire Year (FIRE_YEAR):", self.spn_year)

        self.txt_date_start = QLineEdit("2002-08-01", self)
        form.addRow("Start Date (DATE_START YYYY-MM-DD):", self.txt_date_start)

        self.txt_date_end = QLineEdit("2002-08-05", self)
        form.addRow("End Date (DATE_END YYYY-MM-DD):", self.txt_date_end)

        self.cmb_cause = QComboBox(self)
        self.cmb_cause.addItems(["Management", "Lightning", "Point ignition", "Arson", "Accidental", "Unknown"])
        form.addRow("Fire Cause (FIRECAUSE):", self.cmb_cause)

        self.spn_fdi = QDoubleSpinBox(self)
        self.spn_fdi.setRange(0, 150)
        self.spn_fdi.setValue(50.0)
        form.addRow("Fire Danger Index (FDI):", self.spn_fdi)

        layout.addWidget(grp_param)

        # Progress
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.txt_log = QTextEdit(self)
        self.txt_log.setReadOnly(True)
        layout.addWidget(self.txt_log)

        # Buttons
        h_btns = QHBoxLayout()
        self.btn_start = QPushButton("▶ Start Import", self)
        self.btn_start.clicked.connect(self._start_import)
        self.btn_cancel = QPushButton("Close", self)
        self.btn_cancel.clicked.connect(self._on_close)
        h_btns.addStretch()
        h_btns.addWidget(self.btn_start)
        h_btns.addWidget(self.btn_cancel)
        layout.addLayout(h_btns)

    def _browse_shp(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select Fire Shapefile", "", "Shapefiles (*.shp)")
        if f:
            self.txt_shp.setText(f)

    def _start_import(self):
        shp_path = self.txt_shp.text().strip()
        if not shp_path or not os.path.exists(shp_path):
            QMessageBox.warning(self, "Warning", "Please select a valid shapefile!")
            return

        self.btn_start.setEnabled(False)
        self.btn_cancel.setText("Stop")
        self.txt_log.append(f"Starting processing for: {shp_path}...")

        processor = FireImportProcessor(self.db, self.base_grid_path)
        self.thread = FireWorkerThread(
            processor,
            shp_path,
            default_year=self.spn_year.value(),
            default_date_start=self.txt_date_start.text().strip(),
            default_date_end=self.txt_date_end.text().strip(),
            default_cause=self.cmb_cause.currentText(),
            default_fdi=self.spn_fdi.value()
        )
        self.thread.progress.connect(self._on_progress)
        self.thread.finished.connect(self._on_finished)
        self.thread.error.connect(self._on_error)
        self.thread.start()
        self.importStarted.emit()

    def _on_progress(self, cur, total, msg):
        self.progress_bar.setValue(cur)
        self.txt_log.append(msg)
        self.importProgress.emit(cur, total, msg)

    def _on_finished(self, res):
        self.btn_start.setEnabled(True)
        self.btn_cancel.setText("Close")
        self.importFinished.emit(res)
        if res.get("status") == "success":
            msg = f"Completed! {res.get('fire_features')} fire polygons analyzed, {res.get('inserted')} records inserted into FIRE."
            self.txt_log.append(f"✔ {msg}")
            QMessageBox.information(self, "Import Completed", msg)
        else:
            self.txt_log.append("Operation cancelled.")

    def _on_error(self, err_msg):
        self.btn_start.setEnabled(True)
        self.btn_cancel.setText("Close")
        self.txt_log.append(f"❌ ERROR: {err_msg}")
        self.importError.emit(err_msg)
        QMessageBox.critical(self, "Error", f"An error occurred:\n{err_msg}")

    def _on_close(self):
        if self.thread and self.thread.isRunning():
            self.thread.cancel()
            self.thread.wait()
        self.accept()


# ==============================================================================
# Rainfall Import Dialog
# ==============================================================================

class RainfallImportDialog(QDialog):
    importStarted = pyqtSignal()
    importProgress = pyqtSignal(int, int, str)
    importFinished = pyqtSignal(dict)
    importError = pyqtSignal(str)

    def __init__(self, db_manager: DatabaseManager, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Spatial Rainfall Import")
        self.resize(600, 420)
        self.db = db_manager
        self.processor = RainfallProcessor(db_manager)
        self.thread: Optional[RainfallWorkerThread] = None

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Status of Weather Station Yearly Readings (Imported = 'N'):"))

        self.txt_status = QTextEdit(self)
        self.txt_status.setReadOnly(True)
        layout.addWidget(self.txt_status)

        self._check_pending()

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        h_btns = QHBoxLayout()
        self.btn_start = QPushButton("▶ Start Spatialization", self)
        self.btn_start.clicked.connect(self._start_spatialization)
        self.btn_close = QPushButton("Close", self)
        self.btn_close.clicked.connect(self._on_close)
        h_btns.addStretch()
        h_btns.addWidget(self.btn_start)
        h_btns.addWidget(self.btn_close)
        layout.addLayout(h_btns)

    def _check_pending(self):
        try:
            readings = self.db.get_unimported_rainfall_stations()
            if readings:
                years = [r.get('YEAR') for r in readings]
                self.txt_status.append(f"Found {len(readings)} yearly reading records to spatialize: {years}")
            else:
                self.txt_status.append("All available weather station readings are already spatialized.")
                self.btn_start.setEnabled(False)
        except Exception as e:
            self.txt_status.append(f"Error reading station records: {e}")

    def _start_spatialization(self):
        self.btn_start.setEnabled(False)
        self.btn_close.setText("Stop")
        self.txt_status.append("Starting spatialization across all 18,948 grid cells...")

        self.thread = RainfallWorkerThread(self.processor)
        self.thread.progress.connect(self._on_progress)
        self.thread.finished.connect(self._on_finished)
        self.thread.error.connect(self._on_error)
        self.thread.start()
        self.importStarted.emit()

    def _on_progress(self, cur, total, msg):
        self.progress_bar.setValue(cur)
        self.txt_status.append(msg)
        self.importProgress.emit(cur, total, msg)

    def _on_finished(self, res):
        self.btn_start.setEnabled(True)
        self.btn_close.setText("Close")
        self.importFinished.emit(res)
        if res.get("status") == "success":
            msg = f"Spatialization completed! {res.get('inserted')} records inserted into Qry_RAINFALL."
            self.txt_status.append(f"✔ {msg}")
            QMessageBox.information(self, "Success", msg)
        else:
            self.txt_status.append(res.get("message", "Operation terminated."))

    def _on_error(self, err):
        self.btn_start.setEnabled(True)
        self.btn_close.setText("Close")
        self.txt_status.append(f"❌ ERROR: {err}")
        self.importError.emit(err)
        QMessageBox.critical(self, "Error", f"Error during spatialization:\n{err}")

    def _on_close(self):
        if self.thread and self.thread.isRunning():
            self.thread.cancel()
            self.thread.wait()
        self.accept()


# ==============================================================================
# Diagnostics & Data Repair Dialog
# ==============================================================================

class DiagnosticsDialog(QDialog):
    def __init__(self, db_manager: DatabaseManager, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Grid, Weights & Historical Rainfall Diagnostics")
        self.resize(720, 520)
        self.db = db_manager
        self.processor = RainfallProcessor(db_manager)
        self.thread: Optional[BackfillWorkerThread] = None

        self._setup_ui()
        self._run_diagnosis()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        self.lbl_summary = QLabel("Analyzing grid cells and station weights...", self)
        layout.addWidget(self.lbl_summary)

        self.table = QTableWidget(self)
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Year", "Present Cells", "Missing Cells", "Sample Missing FIDs"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        h_box = QHBoxLayout()
        self.btn_backfill = QPushButton("🛠️ Backfill Missing Historical Cells (18945, 18946, 18947)", self)
        self.btn_backfill.clicked.connect(self._start_backfill)
        self.btn_close = QPushButton("Close", self)
        self.btn_close.clicked.connect(self.accept)
        h_box.addWidget(self.btn_backfill)
        h_box.addStretch()
        h_box.addWidget(self.btn_close)
        layout.addLayout(h_box)

    def _run_diagnosis(self):
        try:
            diag = self.processor.diagnose_grid_and_weights()
            summary = (
                f"<b>Total rows in Weights table (Rainfall_BaseGridCells_Weight):</b> {diag['total_weight_rows']}<br>"
                f"<b>Years recorded in Qry_RAINFALL:</b> {diag['total_years_in_db']} (from {diag['year_range'][0]} to {diag['year_range'][1]})<br>"
                f"<b>Years with missing cells (historical records &lt; 2015):</b> {len(diag['incomplete_years'])} years"
            )
            self.lbl_summary.setText(summary)

            self.table.setRowCount(len(diag['incomplete_years']))
            row = 0
            for y, info in sorted(diag['incomplete_years'].items()):
                self.table.setItem(row, 0, QTableWidgetItem(str(y)))
                self.table.setItem(row, 1, QTableWidgetItem(str(info["present"])))
                self.table.setItem(row, 2, QTableWidgetItem(str(info["missing"])))
                self.table.setItem(row, 3, QTableWidgetItem(str(info["sample_missing"])))
                row += 1

            if not diag['incomplete_years']:
                self.btn_backfill.setEnabled(False)
                self.btn_backfill.setText("✔ All historical years have complete coverage (18,948 cells)")

        except Exception as e:
            self.lbl_summary.setText(f"<font color='red'>Error during diagnostics: {e}</font>")

    def _start_backfill(self):
        reply = QMessageBox.question(
            self, "Confirm Backfill",
            "Do you want to compute and insert the missing historical rainfall records for cells 18945, 18946, and 18947 for all years 1956-2014?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self.btn_backfill.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(50)

        self.thread = BackfillWorkerThread(self.processor)
        self.thread.finished.connect(self._on_backfill_finished)
        self.thread.error.connect(self._on_backfill_error)
        self.thread.start()

    def _on_backfill_finished(self, count):
        self.progress_bar.setValue(100)
        QMessageBox.information(self, "Completed", f"Successfully backfilled {count} historical rainfall records!")
        self._run_diagnosis()

    def _on_backfill_error(self, err):
        self.progress_bar.setVisible(False)
        self.btn_backfill.setEnabled(True)
        QMessageBox.critical(self, "Error", f"Error during saving backfilled records:\n{err}")


# ==============================================================================
# Station Reading Edit Sub-Dialog
# ==============================================================================

class StationReadingEditDialog(QDialog):
    def __init__(self, parent=None, db: Optional[DatabaseManager] = None, reading_data: Optional[dict] = None):
        super().__init__(parent)
        self.db = db
        self.reading_data = reading_data
        self.is_edit_mode = reading_data is not None

        title = f"Edit Weather Station Readings - Year {int(reading_data['YEAR'])}" if self.is_edit_mode else "Add New Weather Station Yearly Readings"
        self.setWindowTitle(title)
        self.resize(780, 580)

        self.spin_boxes: Dict[str, QDoubleSpinBox] = {}
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Basic Info Group
        grp_info = QGroupBox("Year & Spatialization Status", self)
        form_info = QFormLayout(grp_info)

        # Determine default year
        default_year = 2024
        if self.is_edit_mode and self.reading_data:
            default_year = int(self.reading_data["YEAR"])
        elif self.db:
            try:
                readings = self.db.get_all_station_readings()
                if readings:
                    default_year = int(max(float(r["YEAR"]) for r in readings if r.get("YEAR") is not None)) + 1
            except Exception:
                pass

        self.spn_year = QSpinBox(self)
        self.spn_year.setRange(1900, 2100)
        self.spn_year.setValue(default_year)
        if self.is_edit_mode:
            self.spn_year.setEnabled(False)
        else:
            self.spn_year.valueChanged.connect(self._on_year_changed)
        form_info.addRow("Calendar Year:", self.spn_year)

        default_year_rain = f"{default_year}-{str(default_year + 1)[-2:]}"
        if self.is_edit_mode and self.reading_data:
            default_year_rain = str(self.reading_data.get("YEAR_RAIN", default_year_rain))
        self.txt_year_rain = QLineEdit(default_year_rain, self)
        form_info.addRow("Hydrological Season (YEAR_RAIN):", self.txt_year_rain)

        self.cmb_status = QComboBox(self)
        self.cmb_status.addItem("Pending Spatialization (Imported = 'N')", "N")
        self.cmb_status.addItem("Already Spatialized (Imported = 'Y')", "Y")
        if self.is_edit_mode and self.reading_data:
            curr_imp = str(self.reading_data.get("Imported", "N")).strip().upper()
            idx = 1 if curr_imp == "Y" else 0
            self.cmb_status.setCurrentIndex(idx)
        else:
            self.cmb_status.setCurrentIndex(0)
        form_info.addRow("Spatialization Status:", self.cmb_status)

        layout.addWidget(grp_info)

        # 21 Weather Stations Group
        grp_stations = QGroupBox("Weather Station Rainfall Readings (mm)", self)
        v_stations = QVBoxLayout(grp_stations)

        # Helper buttons bar
        h_tools = QHBoxLayout()
        btn_zero = QPushButton("Reset All to 0 mm", self)
        btn_zero.setAutoDefault(False)
        btn_zero.setDefault(False)
        btn_zero.clicked.connect(self._reset_all_zero)
        h_tools.addWidget(btn_zero)

        if self.db and not self.is_edit_mode:
            btn_copy_last = QPushButton("Copy From Latest Recorded Year", self)
            btn_copy_last.setAutoDefault(False)
            btn_copy_last.setDefault(False)
            btn_copy_last.clicked.connect(self._copy_from_latest)
            h_tools.addWidget(btn_copy_last)

        h_tools.addStretch()
        v_stations.addLayout(h_tools)

        # 3 columns x 7 rows grid
        grid = QGridLayout()
        grid.setHorizontalSpacing(15)
        grid.setVerticalSpacing(8)

        cols_per_row = 3
        for idx, code in enumerate(STATION_CODES):
            col = idx % cols_per_row
            row = idx // cols_per_row

            meta = STATION_METADATA.get(code, {})
            name = meta.get("name", code)
            region = meta.get("region", "")

            lbl = QLabel(f"<b>{code}</b> ({name}):", self)
            lbl.setToolTip(f"{name} - Region: {region}")

            spn = QDoubleSpinBox(self)
            spn.setRange(0.0, 9999.0)
            spn.setDecimals(1)
            spn.setSuffix(" mm")

            val = 0.0
            if self.is_edit_mode and self.reading_data:
                raw_v = self.reading_data.get(code)
                if raw_v is not None and str(raw_v).strip() != "":
                    try:
                        val = float(raw_v)
                    except ValueError:
                        pass
            spn.setValue(val)
            self.spin_boxes[code] = spn

            sub_h = QHBoxLayout()
            sub_h.addWidget(lbl)
            sub_h.addWidget(spn)
            grid.addLayout(sub_h, row, col)

        v_stations.addLayout(grid)
        layout.addWidget(grp_stations)

        # Bottom Buttons
        h_btns = QHBoxLayout()
        btn_save = QPushButton("💾 Save to Database", self)
        btn_save.setAutoDefault(False)
        btn_save.setDefault(False)
        btn_save.setStyleSheet("font-weight: bold; background-color: #0d6efd; color: white; padding: 6px 14px; border-radius: 4px;")
        btn_save.clicked.connect(self._save)

        btn_cancel = QPushButton("Cancel", self)
        btn_cancel.setAutoDefault(False)
        btn_cancel.setDefault(False)
        btn_cancel.clicked.connect(self.reject)

        h_btns.addStretch()
        h_btns.addWidget(btn_save)
        h_btns.addWidget(btn_cancel)
        layout.addLayout(h_btns)

        # Set initial focus to the input fields so NO button is pre-highlighted or pre-focused
        if not self.is_edit_mode:
            self.spn_year.setFocus()
        else:
            self.txt_year_rain.setFocus()

    def _on_year_changed(self, y: int):
        self.txt_year_rain.setText(f"{y}-{str(y + 1)[-2:]}")

    def _reset_all_zero(self):
        # If any station has values > 0, ask for confirmation to avoid accidental data loss
        if any(spn.value() > 0.0 for spn in self.spin_boxes.values()):
            reply = QMessageBox.question(
                self,
                "Confirm Reset",
                "Are you sure you want to reset all rainfall readings to 0.0 mm?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return
        for spn in self.spin_boxes.values():
            spn.setValue(0.0)

    def _copy_from_latest(self):
        if not self.db:
            return
        readings = self.db.get_all_station_readings()
        if not readings:
            QMessageBox.information(self, "No Records", "No existing station readings found in database.")
            return
        latest = readings[0]
        for code, spn in self.spin_boxes.items():
            val = latest.get(code, 0.0)
            spn.setValue(float(val) if val is not None else 0.0)
        QMessageBox.information(self, "Copied", f"Copied rainfall values from Year {int(latest['YEAR'])} as baseline.")

    def _save(self):
        year = self.spn_year.value()
        year_rain = self.txt_year_rain.text().strip()
        if not year_rain:
            year_rain = f"{year}-{str(year + 1)[-2:]}"

        imported = self.cmb_status.currentData()

        # Check overwrite if not in edit mode
        if not self.is_edit_mode and self.db:
            existing = self.db.get_station_reading(year)
            if existing:
                reply = QMessageBox.question(
                    self, "Year Already Exists",
                    f"A reading for Year {year} already exists in the database.\nDo you want to overwrite its values?",
                    QMessageBox.Yes | QMessageBox.No
                )
                if reply != QMessageBox.Yes:
                    return

        reading_dict = {
            "YEAR": float(year),
            "YEAR_RAIN": year_rain,
            "Imported": imported
        }
        for code, spn in self.spin_boxes.items():
            reading_dict[code] = spn.value()

        if self.db:
            try:
                self.db.save_station_reading(reading_dict)
            except Exception as e:
                QMessageBox.critical(self, "Database Error", f"Failed to save station reading:\n{e}")
                return

        self.accept()


# ==============================================================================
# Weather Station Readings Manager Dialog
# ==============================================================================

class StationReadingsDialog(QDialog):
    def __init__(self, parent=None, db: Optional[DatabaseManager] = None):
        super().__init__(parent)
        self.db = db
        self.processor = RainfallProcessor(db) if db else None
        self.setWindowTitle("🌦️ Rainfall Station Manager - Kruger Fire & Rainfall DSS")
        self.resize(1200, 680)

        self._all_records: List[dict] = []
        self._thread: Optional[RainfallWorkerThread] = None

        self._setup_ui()
        self._load_data()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # 1. Top Header Banner
        header_frame = QFrame(self)
        header_frame.setStyleSheet("""
            QFrame {
                background-color: #2b303c;
                border-radius: 6px;
                padding: 10px;
            }
            QLabel {
                color: white;
            }
        """)
        h_layout = QVBoxLayout(header_frame)
        h_layout.setContentsMargins(8, 6, 8, 6)

        lbl_title = QLabel("<h2>🌦️ Kruger Rainfall Station Manager (21 Stations)</h2>", header_frame)
        lbl_subtitle = QLabel(
            "Inspect, add, edit, import and spatialize annual rainfall totals (mm) directly in <i>Db.mdb</i> without opening Microsoft Access.",
            header_frame
        )
        self.lbl_stats = QLabel("Loading database records...", header_frame)
        self.lbl_stats.setStyleSheet("font-size: 13px; color: #a0aec0; margin-top: 4px;")

        h_layout.addWidget(lbl_title)
        h_layout.addWidget(lbl_subtitle)
        h_layout.addWidget(self.lbl_stats)
        layout.addWidget(header_frame)

        # 2. Action Toolbar & Filter Row
        tools_layout = QHBoxLayout()

        self.txt_search = QLineEdit(self)
        self.txt_search.setPlaceholderText("🔍 Search year (e.g. 2023)...")
        self.txt_search.setFixedWidth(200)
        self.txt_search.textChanged.connect(self._apply_filter)
        tools_layout.addWidget(self.txt_search)

        self.cmb_filter = QComboBox(self)
        self.cmb_filter.addItem("Show All Years", "ALL")
        self.cmb_filter.addItem("Pending Spatialization Only (N)", "N")
        self.cmb_filter.addItem("Already Spatialized Only (Y)", "Y")
        self.cmb_filter.currentIndexChanged.connect(self._apply_filter)
        tools_layout.addWidget(self.cmb_filter)

        tools_layout.addSpacing(10)

        btn_add = QPushButton("➕ Add New Year", self)
        btn_add.setStyleSheet("font-weight: bold;")
        btn_add.clicked.connect(self._add_year)
        tools_layout.addWidget(btn_add)

        btn_edit = QPushButton("✏️ Edit Selected", self)
        btn_edit.clicked.connect(self._edit_selected)
        tools_layout.addWidget(btn_edit)

        btn_delete = QPushButton("🗑️ Delete Selected", self)
        btn_delete.clicked.connect(self._delete_selected)
        tools_layout.addWidget(btn_delete)

        btn_toggle = QPushButton("🔄 Toggle Pending (N/Y)", self)
        btn_toggle.setToolTip("Mark selected year as 'Pending' ('N') to allow re-spatializing it across the grid.")
        btn_toggle.clicked.connect(self._toggle_pending_status)
        tools_layout.addWidget(btn_toggle)

        tools_layout.addStretch()

        btn_import = QPushButton("📥 Import CSV...", self)
        btn_import.setToolTip("Import annual readings for the 21 stations from an external CSV file.")
        btn_import.clicked.connect(self._import_csv)
        tools_layout.addWidget(btn_import)

        btn_export = QPushButton("📤 Export CSV...", self)
        btn_export.setToolTip("Export the current station readings table to a CSV file.")
        btn_export.clicked.connect(self._export_csv)
        tools_layout.addWidget(btn_export)

        btn_spatialize = QPushButton("🌧️ Spatialize Rainfall...", self)
        btn_spatialize.setStyleSheet("font-weight: bold; background-color: #198754; color: white; padding: 5px 12px; border-radius: 4px;")
        btn_spatialize.setToolTip("Spatialize any pending station readings ('N') onto all 18,948 grid cells.")
        btn_spatialize.clicked.connect(self._spatialize_rainfall_now)
        tools_layout.addWidget(btn_spatialize)

        btn_refresh = QPushButton("🔄 Refresh", self)
        btn_refresh.clicked.connect(self._load_data)
        tools_layout.addWidget(btn_refresh)

        layout.addLayout(tools_layout)

        # 3. Main Data Table
        self.table = QTableWidget(self)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.cellDoubleClicked.connect(self._on_table_double_click)

        # Setup Columns: Year, Season, Status + 21 Stations
        columns = ["Year", "Hydrological Season", "Status"] + STATION_CODES
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels(columns)

        # Set Header Tooltips for Stations
        for idx, code in enumerate(STATION_CODES):
            col_idx = 3 + idx
            meta = STATION_METADATA.get(code, {})
            name = meta.get("name", code)
            reg = meta.get("region", "")
            item = self.table.horizontalHeaderItem(col_idx)
            if item:
                item.setToolTip(f"{code} - {name} ({reg})")

        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        for c in range(3, len(columns)):
            self.table.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeToContents)

        layout.addWidget(self.table)

        # 4. Progress Bar & Bottom Info
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        h_bottom = QHBoxLayout()
        lbl_tip = QLabel("<i>Tip: Double-click any row to edit station readings. Edited or newly added years marked as 'Pending' can be spatialized across the 18,948 grid cells.</i>", self)
        lbl_tip.setStyleSheet("color: #6c757d;")
        h_bottom.addWidget(lbl_tip)
        h_bottom.addStretch()

        btn_close = QPushButton("Close", self)
        btn_close.clicked.connect(self.accept)
        h_bottom.addWidget(btn_close)
        layout.addLayout(h_bottom)

    def _load_data(self):
        if not self.db:
            return
        try:
            self._all_records = self.db.get_all_station_readings()
            self._update_stats()
            self._apply_filter()
        except Exception as e:
            QMessageBox.critical(self, "Database Error", f"Failed to load station readings:\n{e}")

    def _update_stats(self):
        total = len(self._all_records)
        pending = sum(1 for r in self._all_records if str(r.get("Imported", "")).strip().upper() == "N")
        if total > 0:
            min_y = int(min(float(r["YEAR"]) for r in self._all_records if r.get("YEAR") is not None))
            max_y = int(max(float(r["YEAR"]) for r in self._all_records if r.get("YEAR") is not None))
            range_str = f"({min_y} - {max_y})"
        else:
            range_str = "(No records)"

        pending_badge = f"<font color='#ffc107'><b>⚠️ {pending} Pending Spatialization ('N')</b></font>" if pending > 0 else "<font color='#20c997'><b>✔ All Spatialized ('Y')</b></font>"
        self.lbl_stats.setText(
            f"<b>Total Recorded Years:</b> {total} {range_str} &nbsp;|&nbsp; <b>Status:</b> {pending_badge}"
        )

    def _apply_filter(self):
        search_txt = self.txt_search.text().strip().lower()
        filter_mode = self.cmb_filter.currentData()

        filtered_rows = []
        for r in self._all_records:
            year_val = str(int(float(r.get("YEAR", 0)))) if r.get("YEAR") is not None else ""
            season_val = str(r.get("YEAR_RAIN", "")).lower()
            imp_val = str(r.get("Imported", "N")).strip().upper()

            # Text filter
            if search_txt and (search_txt not in year_val and search_txt not in season_val):
                continue

            # Status filter
            if filter_mode == "N" and imp_val != "N":
                continue
            if filter_mode == "Y" and imp_val != "Y":
                continue

            filtered_rows.append(r)

        self._populate_table(filtered_rows)

    def _populate_table(self, records: List[dict]):
        self.table.setRowCount(len(records))
        for row_idx, r in enumerate(records):
            year_val = int(float(r.get("YEAR", 0))) if r.get("YEAR") is not None else 0
            season_val = str(r.get("YEAR_RAIN", ""))
            imp_val = str(r.get("Imported", "N")).strip().upper()

            # Year item
            item_year = QTableWidgetItem(str(year_val))
            item_year.setTextAlignment(Qt.AlignCenter)
            item_year.setData(Qt.UserRole, r)  # Store row dict
            font = item_year.font()
            font.setBold(True)
            item_year.setFont(font)
            self.table.setItem(row_idx, 0, item_year)

            # Season item
            item_season = QTableWidgetItem(season_val)
            item_season.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row_idx, 1, item_season)

            # Status item
            if imp_val == "Y":
                item_status = QTableWidgetItem("✔ Spatialized")
                item_status.setForeground(QBrush(QColor("#198754")))
            else:
                item_status = QTableWidgetItem("⏳ Pending (N)")
                item_status.setForeground(QBrush(QColor("#fd7e14")))
                f_bold = item_status.font()
                f_bold.setBold(True)
                item_status.setFont(f_bold)
            item_status.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row_idx, 2, item_status)

            # 21 Stations
            for col_idx, code in enumerate(STATION_CODES):
                val = r.get(code)
                val_str = f"{float(val):.1f}" if val is not None and str(val).strip() != "" else "-"
                item_val = QTableWidgetItem(val_str)
                item_val.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(row_idx, 3 + col_idx, item_val)

    def _get_selected_record(self) -> Optional[dict]:
        selected = self.table.selectedItems()
        if not selected:
            return None
        row = selected[0].row()
        item = self.table.item(row, 0)
        return item.data(Qt.UserRole) if item else None

    def _on_table_double_click(self, row: int, col: int):
        item = self.table.item(row, 0)
        if item:
            record = item.data(Qt.UserRole)
            if record:
                self._open_edit_dialog(record)

    def _add_year(self):
        dlg = StationReadingEditDialog(self, self.db, reading_data=None)
        if dlg.exec_() == QDialog.Accepted:
            self._load_data()

    def _edit_selected(self):
        record = self._get_selected_record()
        if not record:
            QMessageBox.warning(self, "Selection Required", "Please select a year from the table to edit.")
            return
        self._open_edit_dialog(record)

    def _open_edit_dialog(self, record: dict):
        dlg = StationReadingEditDialog(self, self.db, reading_data=record)
        if dlg.exec_() == QDialog.Accepted:
            self._load_data()

    def _delete_selected(self):
        record = self._get_selected_record()
        if not record:
            QMessageBox.warning(self, "Selection Required", "Please select a year from the table to delete.")
            return
        year = int(float(record["YEAR"]))
        reply = QMessageBox.question(
            self, "Confirm Deletion",
            f"Are you sure you want to permanently delete the station readings for Year {year}?\n\nNote: This will remove the record from Rainfall_Station_Yearly_Reading in Db.mdb.",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            if self.db:
                try:
                    self.db.delete_station_reading(year)
                    self._load_data()
                    QMessageBox.information(self, "Deleted", f"Record for Year {year} has been deleted.")
                except Exception as e:
                    QMessageBox.critical(self, "Database Error", f"Failed to delete record:\n{e}")

    def _toggle_pending_status(self):
        record = self._get_selected_record()
        if not record:
            QMessageBox.warning(self, "Selection Required", "Please select a year from the table to change status.")
            return
        year = int(float(record["YEAR"]))
        current_status = str(record.get("Imported", "N")).strip().upper()
        new_status = "N" if current_status == "Y" else "Y"

        if self.db:
            try:
                self.db.set_station_reading_status(year, new_status)
                self._load_data()
            except Exception as e:
                QMessageBox.critical(self, "Database Error", f"Failed to update status:\n{e}")

    def _export_csv(self):
        if not self._all_records:
            QMessageBox.information(self, "Empty Table", "There are no records to export.")
            return

        filepath, _ = QFileDialog.getSaveFileName(
            self, "Export Station Readings to CSV", "Kruger_Station_Readings.csv", "CSV Files (*.csv)"
        )
        if not filepath:
            return

        try:
            headers = ["YEAR", "YEAR_RAIN", "Imported"] + STATION_CODES
            with open(filepath, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                for r in self._all_records:
                    row = [
                        int(float(r.get("YEAR", 0))),
                        r.get("YEAR_RAIN", ""),
                        r.get("Imported", "N")
                    ]
                    for code in STATION_CODES:
                        row.append(r.get(code, 0.0))
                    writer.writerow(row)
            QMessageBox.information(self, "Export Complete", f"Successfully exported {len(self._all_records)} records to:\n{filepath}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to export CSV:\n{e}")

    def _import_csv(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Import Station Readings from CSV", "", "CSV Files (*.csv)"
        )
        if not filepath:
            return

        try:
            imported_count = 0
            with open(filepath, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                if not reader.fieldnames:
                    raise ValueError("CSV file has no headers.")

                # Normalize headers map (case insensitive)
                header_map = {name.strip().upper(): name for name in reader.fieldnames}
                if "YEAR" not in header_map:
                    raise ValueError("CSV must contain a 'YEAR' column.")

                for row in reader:
                    year_val = row[header_map["YEAR"]].strip()
                    if not year_val:
                        continue
                    year = int(float(year_val))
                    year_rain_col = header_map.get("YEAR_RAIN")
                    year_rain = row[year_rain_col].strip() if year_rain_col else f"{year}-{str(year + 1)[-2:]}"
                    imp_col = header_map.get("IMPORTED")
                    imp = row[imp_col].strip().upper() if imp_col else "N"

                    rec = {
                        "YEAR": float(year),
                        "YEAR_RAIN": year_rain,
                        "Imported": imp
                    }
                    for code in STATION_CODES:
                        if code in header_map:
                            val_str = row[header_map[code]].strip()
                            rec[code] = float(val_str) if val_str else 0.0
                        else:
                            rec[code] = 0.0

                    if self.db:
                        self.db.save_station_reading(rec)
                        imported_count += 1

            self._load_data()
            QMessageBox.information(
                self, "Import Successful",
                f"Successfully imported/updated {imported_count} annual records from CSV!\nNew records are marked as 'Pending' and ready to spatialize."
            )
        except Exception as e:
            QMessageBox.critical(self, "Import Error", f"Failed to import from CSV:\n{e}")

    def _spatialize_rainfall_now(self):
        if not self.processor or not self.db:
            return
        pending = self.db.get_unimported_rainfall_stations()
        if not pending:
            QMessageBox.information(
                self, "All Up to Date",
                "All station readings are already spatialized ('Y')!\n\nIf you edited a year and wish to re-spatialize it, select the year and click 'Toggle Pending (N/Y)'."
            )
            return

        years = sorted(list(set(int(r["YEAR"]) for r in pending if r.get("YEAR") is not None)))
        reply = QMessageBox.question(
            self, "Confirm Spatialization",
            f"Found {len(years)} pending year(s) to spatialize:\n{years}\n\nDo you want to compute the spatial interpolation onto all 18,948 grid cells and calculate 2-year moving averages now?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)

        self._thread = RainfallWorkerThread(self.processor)
        self._thread.progress.connect(self._on_spatialize_progress)
        self._thread.finished.connect(self._on_spatialize_finished)
        self._thread.error.connect(self._on_spatialize_error)
        self._thread.start()

    def _on_spatialize_progress(self, current: int, total: int, msg: str):
        self.progress_bar.setValue(current)

    def _on_spatialize_finished(self, result: dict):
        self.progress_bar.setVisible(False)
        self._load_data()
        QMessageBox.information(
            self, "Spatialization Complete",
            f"Rainfall spatialization completed successfully!\n\n"
            f"Years processed: {result.get('years_processed')}\n"
            f"Grid records inserted into Qry_RAINFALL: {result.get('inserted')}"
        )

    def _on_spatialize_error(self, err_msg: str):
        self.progress_bar.setVisible(False)
        QMessageBox.critical(self, "Spatialization Error", f"Error during spatialization:\n{err_msg}")
