import os
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QToolBar, QAction,
    QDockWidget, QListWidget, QListWidgetItem, QTextEdit, QLabel,
    QMessageBox, QSplitter, QStatusBar, QFileDialog, QProgressBar,
    QFrame, QPushButton, QSizePolicy
)
from PyQt5.QtCore import Qt, QTimer, QTime
from PyQt5.QtGui import QIcon, QFont, QPixmap

from config import load_settings, save_settings, APP_VERSION, APP_NAME
from core.db_manager import DatabaseManager
from core.updater import CheckUpdateWorker
from .map_widget import MapWidget
from .dialogs import (
    SettingsDialog, FireImportDialog, RainfallImportDialog, DiagnosticsDialog,
    StationReadingsDialog, UpdateDialog
)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Kruger National Park - Fire & Rainfall Management DSS")
        self.resize(1280, 800)

        # Set Window Icon
        res_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources")
        app_icon = QIcon()
        ico_path = os.path.join(res_dir, "logo_proges.ico")
        png_path = os.path.join(res_dir, "logo_proges_clean.png")
        if os.path.exists(ico_path):
            app_icon.addFile(ico_path)
        if os.path.exists(png_path):
            app_icon.addFile(png_path)
        if not app_icon.isNull():
            self.setWindowIcon(app_icon)

        self.settings = load_settings()
        self.db = DatabaseManager(self.settings.get("mdb_path", ""))

        # Timers for Rainfall & Fire processes
        self.rain_timer = QTimer(self)
        self.rain_time = QTime(0, 0, 0)
        self.rain_timer.timeout.connect(self._on_rain_tick)

        self.fire_timer = QTimer(self)
        self.fire_time = QTime(0, 0, 0)
        self.fire_timer.timeout.connect(self._on_fire_tick)

        # Update Workers
        self._startup_updater = None
        self._manual_updater = None

        self._setup_ui()
        self._load_initial_data()

        # Background update check on startup (polite 1.5s delay)
        QTimer.singleShot(1500, self._check_updates_on_startup)

    def _setup_ui(self):
        # 1. Main Action Toolbar (Top Ribbon)
        self.main_toolbar = QToolBar("Main Actions", self)
        self.main_toolbar.setMovable(False)
        self.main_toolbar.setStyleSheet("""
            QToolBar {
                background: #2b303c;
                border-bottom: 2px solid #1f232b;
                spacing: 8px;
                padding: 6px;
            }
            QToolButton {
                background: #3a4150;
                color: white;
                font-size: 13px;
                font-weight: bold;
                padding: 6px 14px;
                border-radius: 4px;
                border: 1px solid #4a5366;
            }
            QToolButton:hover {
                background: #4f5a6e;
                border: 1px solid #70809b;
            }
            QToolButton:pressed {
                background: #252b36;
            }
        """)
        self.addToolBar(Qt.TopToolBarArea, self.main_toolbar)

        # Actions (Order: Rainfall Station Manager, Grid Weights Diagnostics, Import Rainfall Data, Import Fire Data, Settings)
        act_station_mgr = QAction("🌦️ Rainfall Station Manager", self)
        act_station_mgr.setToolTip("View, add, edit, import and spatialize weather station rainfall measurements directly in Db.mdb")
        act_station_mgr.triggered.connect(self._open_station_manager)
        self.main_toolbar.addAction(act_station_mgr)

        act_diag = QAction("🔍 Grid Weights Diagnostics", self)
        act_diag.setToolTip("Diagnose grid cells coverage, weights integrity and historical rainfall records")
        act_diag.triggered.connect(self._open_diagnostics)
        self.main_toolbar.addAction(act_diag)

        act_rain = QAction("🌧️ Import Rainfall Data", self)
        act_rain.setToolTip("Spatialize pending rainfall readings across all grid cells")
        act_rain.triggered.connect(self._open_rainfall_import)
        self.main_toolbar.addAction(act_rain)

        act_fire = QAction("🔥 Import Fire Data", self)
        act_fire.setToolTip("Import fire shapefile and calculate Attorre & Navashni ecological models")
        act_fire.triggered.connect(self._open_fire_import)
        self.main_toolbar.addAction(act_fire)

        self.main_toolbar.addSeparator()

        act_settings = QAction("⚙️ Settings", self)
        act_settings.setToolTip("Configure paths for Db.mdb, BaseGrid.shp and ShapeFiles directory")
        act_settings.triggered.connect(self._open_settings)
        self.main_toolbar.addAction(act_settings)

        act_updates = QAction("🚀 Updates", self)
        act_updates.setToolTip("Check for online updates, download new releases or view release notes")
        act_updates.triggered.connect(self._check_for_updates_manual)
        self.main_toolbar.addAction(act_updates)

        # 2. Central Splitter (Layers List + Map)
        splitter = QSplitter(Qt.Horizontal, self)

        # Left Panel: Layers
        left_panel = QWidget(self)
        left_panel.setFixedWidth(200)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(6, 6, 6, 6)
        lbl_layers = QLabel("<b>Map Layers</b>", left_panel)
        left_layout.addWidget(lbl_layers)

        self.list_layers = QListWidget(left_panel)
        self.list_layers.itemChanged.connect(self._on_layer_visibility_changed)
        left_layout.addWidget(self.list_layers)

        splitter.addWidget(left_panel)

        # Center Panel: Map Canvas
        self.map_widget = MapWidget(self)
        self.map_widget.layerAdded.connect(self._on_layer_added)
        self.map_widget.layerRemoved.connect(self._on_layer_removed)
        splitter.addWidget(self.map_widget)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)

        # 3. Progress Bars Container (Rainfall Spatialization & Fire Import)
        res_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources")
        progress_container = QWidget(self)
        progress_container.setFixedHeight(64)
        progress_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        progress_layout = QVBoxLayout(progress_container)
        progress_layout.setContentsMargins(12, 4, 12, 4)
        progress_layout.setSpacing(4)

        # Row 1: Rainfall Progress
        h_rain = QHBoxLayout()
        h_rain.setSpacing(10)
        lbl_rain_title = QLabel("🌧️ Rainfall Spatialization:", self)
        lbl_rain_title.setFixedWidth(175)
        lbl_rain_title.setStyleSheet("font-weight: bold; font-size: 12px; color: #374151;")

        self.prog_main_rain = QProgressBar(self)
        self.prog_main_rain.setFixedHeight(20)
        self.prog_main_rain.setRange(0, 100)
        self.prog_main_rain.setValue(0)
        self.prog_main_rain.setTextVisible(True)

        self.lbl_time_rain = QLabel("elapsed time: 00:00:00", self)
        self.lbl_time_rain.setFixedWidth(190)
        self.lbl_time_rain.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lbl_time_rain.setStyleSheet("font-family: Consolas, monospace; font-size: 11px; color: #495057;")

        h_rain.addWidget(lbl_rain_title)
        h_rain.addWidget(self.prog_main_rain)
        h_rain.addWidget(self.lbl_time_rain)
        progress_layout.addLayout(h_rain)

        # Row 2: Fire Progress
        h_fire = QHBoxLayout()
        h_fire.setSpacing(10)
        lbl_fire_title = QLabel("🔥 Fire Data Import:", self)
        lbl_fire_title.setFixedWidth(175)
        lbl_fire_title.setStyleSheet("font-weight: bold; font-size: 12px; color: #374151;")

        self.prog_main_fire = QProgressBar(self)
        self.prog_main_fire.setFixedHeight(20)
        self.prog_main_fire.setRange(0, 100)
        self.prog_main_fire.setValue(0)
        self.prog_main_fire.setTextVisible(True)

        self.lbl_time_fire = QLabel("elapsed time: 00:00:00", self)
        self.lbl_time_fire.setFixedWidth(190)
        self.lbl_time_fire.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lbl_time_fire.setStyleSheet("font-family: Consolas, monospace; font-size: 11px; color: #495057;")

        h_fire.addWidget(lbl_fire_title)
        h_fire.addWidget(self.prog_main_fire)
        h_fire.addWidget(self.lbl_time_fire)
        progress_layout.addLayout(h_fire)

        # 4. Bottom Brand Banner (Kruger Logo, Title, Proges Logo) - Fixed size & non-resizable
        footer_banner = QFrame(self)
        footer_banner.setFixedHeight(74)
        footer_banner.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        footer_banner.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border-top: 1px solid #d1d5db;
                border-bottom: 1px solid #d1d5db;
            }
        """)
        h_banner = QHBoxLayout(footer_banner)
        h_banner.setContentsMargins(15, 2, 15, 2)

        # Left: Kruger Logo
        lbl_kruger = QLabel(footer_banner)
        kruger_path = os.path.join(res_dir, "logo_kruger.jpg")
        if os.path.exists(kruger_path):
            pix_k = QPixmap(kruger_path).scaledToHeight(64, Qt.SmoothTransformation)
            lbl_kruger.setPixmap(pix_k)
        lbl_kruger.setFixedSize(70, 64)
        h_banner.addWidget(lbl_kruger, alignment=Qt.AlignLeft | Qt.AlignVCenter)

        # Center: Title
        lbl_brand_title = QLabel("ISP 4.0 - Kruger Fire Management Data Tool", footer_banner)
        lbl_brand_title.setAlignment(Qt.AlignCenter)
        lbl_brand_title.setStyleSheet("""
            font-size: 20px;
            font-weight: bold;
            color: #111827;
            letter-spacing: 0.5px;
        """)
        h_banner.addWidget(lbl_brand_title, stretch=1, alignment=Qt.AlignCenter)

        # Right: Proges Logo
        lbl_proges = QLabel(footer_banner)
        proges_path = os.path.join(res_dir, "logo_proges.jpg")
        if os.path.exists(proges_path):
            pix_p = QPixmap(proges_path).scaledToHeight(64, Qt.SmoothTransformation)
            lbl_proges.setPixmap(pix_p)
        lbl_proges.setFixedSize(70, 64)
        h_banner.addWidget(lbl_proges, alignment=Qt.AlignRight | Qt.AlignVCenter)

        # Assemble into Central Widget
        central_widget = QWidget(self)
        central_layout = QVBoxLayout(central_widget)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(splitter, stretch=1)
        central_layout.addWidget(progress_container)
        central_layout.addWidget(footer_banner)

        self.setCentralWidget(central_widget)

        # 3. Bottom Dock: Event Log
        self.dock_log = QDockWidget("Operation Log & Notifications", self)
        self.dock_log.setAllowedAreas(Qt.BottomDockWidgetArea | Qt.TopDockWidgetArea)
        self.txt_log = QTextEdit(self.dock_log)
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumHeight(120)
        self.txt_log.setMinimumHeight(75)
        self.dock_log.setWidget(self.txt_log)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.dock_log)

        # 4. Status Bar
        self.status_bar = QStatusBar(self)
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

    def log(self, message: str):
        self.txt_log.append(message)
        self.status_bar.showMessage(message, 5000)

    def _load_initial_data(self):
        base_grid = self.settings.get("base_grid_path", "")
        if not base_grid or not os.path.exists(base_grid):
            # Prompt user to locate BaseGrid.shp
            reply = QMessageBox.question(
                self,
                "BaseGrid Not Found",
                "The foundational grid shapefile (BaseGrid.shp) was not found at the configured location.\n\n"
                "Would you like to browse and select it now?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                file_path, _ = QFileDialog.getOpenFileName(
                    self,
                    "Select BaseGrid.shp",
                    self.settings.get("shapefiles_dir", ""),
                    "ESRI Shapefiles (*.shp);;All Files (*.*)"
                )
                if file_path and os.path.exists(file_path):
                    base_grid = file_path
                    self.settings["base_grid_path"] = file_path
                    save_settings(self.settings)
                    self.log(f"New BaseGrid path saved: {file_path}")

        if base_grid and os.path.exists(base_grid):
            self.log(f"Loading base layer: {base_grid}...")
            ok = self.map_widget.load_base_grid(base_grid)
            if ok:
                self.log("✔ BaseGrid loaded successfully.")
            else:
                self.log("⚠ Could not load BaseGrid shapefile.")
        else:
            self.log("⚠ BaseGrid not loaded. You can select it later in Settings.")

        # Load Kruger Boundary shapefile on top of BaseGrid
        bndry_path = self.settings.get("kruger_boundary_path", "")
        if not bndry_path or not os.path.exists(bndry_path):
            candidate = os.path.join(self.settings.get("shapefiles_dir", ""), "bndry_kruger.shp")
            if os.path.exists(candidate):
                bndry_path = candidate
                self.settings["kruger_boundary_path"] = candidate
                save_settings(self.settings)

        if bndry_path and os.path.exists(bndry_path):
            self.log(f"Loading boundary layer: {bndry_path}...")
            b_layer = self.map_widget.load_boundary_layer(bndry_path, "Kruger Boundary")
            if b_layer:
                self.log("✔ Kruger Boundary loaded successfully.")
            else:
                self.log("⚠ Could not load Kruger Boundary shapefile.")
        else:
            self.log("ℹ Kruger Boundary shapefile (bndry_kruger.shp) not found.")

        # Test DB connection
        ok, msg = self.db.test_connection()
        if ok:
            self.log(f"✔ Connection to Db.mdb established.")
        else:
            self.log(f"⚠ Database connection inactive: {msg}")

    def _on_layer_added(self, layer_id: str, layer):
        item = QListWidgetItem(layer.name())
        item.setData(Qt.UserRole, layer_id)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked)
        self.list_layers.insertItem(0, item)
        self.log(f"Layer added: {layer.name()}")

    def _on_layer_removed(self, layer_id: str):
        for i in range(self.list_layers.count()):
            item = self.list_layers.item(i)
            if item.data(Qt.UserRole) == layer_id:
                self.list_layers.takeItem(i)
                break
        self.log(f"Layer removed: {layer_id}")

    def showEvent(self, event):
        super().showEvent(event)
        # Ensure full extent fitting is applied once the main window is visible
        QTimer.singleShot(120, self.map_widget.zoom_to_full_extent)

    def _on_layer_visibility_changed(self, item: QListWidgetItem):
        layer_id = item.data(Qt.UserRole)
        is_visible = (item.checkState() == Qt.Checked)
        self.map_widget.set_layer_visible(layer_id, is_visible)

    def _on_rain_tick(self):
        self.rain_time = self.rain_time.addSecs(1)
        self.lbl_time_rain.setText(f"elapsed time: {self.rain_time.toString('hh:mm:ss')}")

    def _on_fire_tick(self):
        self.fire_time = self.fire_time.addSecs(1)
        self.lbl_time_fire.setText(f"elapsed time: {self.fire_time.toString('hh:mm:ss')}")

    def _open_fire_import(self):
        # Check if there is an active fire layer loaded on canvas
        preloaded_shp = None
        for l in self.map_widget.layers_list:
            if "fire" in l.name().lower() and l.id() != self.map_widget.base_layer_id:
                preloaded_shp = l.source()
                break

        base_grid = self.settings.get("base_grid_path", "")
        dlg = FireImportDialog(self.db, base_grid, preloaded_shp=preloaded_shp, parent=self)
        dlg.importStarted.connect(self._on_fire_started)
        dlg.importProgress.connect(self._on_fire_progress)
        dlg.importFinished.connect(self._on_fire_finished)
        dlg.importError.connect(self._on_fire_error)
        dlg.exec_()

    def _on_fire_started(self):
        self.fire_time = QTime(0, 0, 0)
        self.lbl_time_fire.setText("elapsed time: 00:00:00")
        self.prog_main_fire.setValue(0)
        self.fire_timer.start(1000)

    def _on_fire_progress(self, cur, total, msg):
        self.prog_main_fire.setValue(cur)

    def _on_fire_finished(self, res):
        self.fire_timer.stop()
        self.prog_main_fire.setValue(100)
        self.lbl_time_fire.setText(f"elapsed time: {self.fire_time.toString('hh:mm:ss')} (Completed)")

    def _on_fire_error(self, err):
        self.fire_timer.stop()
        self.lbl_time_fire.setText(f"elapsed time: {self.fire_time.toString('hh:mm:ss')} (Error)")

    def _open_rainfall_import(self):
        dlg = RainfallImportDialog(self.db, parent=self)
        dlg.importStarted.connect(self._on_rain_started)
        dlg.importProgress.connect(self._on_rain_progress)
        dlg.importFinished.connect(self._on_rain_finished)
        dlg.importError.connect(self._on_rain_error)
        dlg.exec_()

    def _on_rain_started(self):
        self.rain_time = QTime(0, 0, 0)
        self.lbl_time_rain.setText("elapsed time: 00:00:00")
        self.prog_main_rain.setValue(0)
        self.rain_timer.start(1000)

    def _on_rain_progress(self, cur, total, msg):
        self.prog_main_rain.setValue(cur)

    def _on_rain_finished(self, res):
        self.rain_timer.stop()
        self.prog_main_rain.setValue(100)
        self.lbl_time_rain.setText(f"elapsed time: {self.rain_time.toString('hh:mm:ss')} (Completed)")

    def _on_rain_error(self, err):
        self.rain_timer.stop()
        self.lbl_time_rain.setText(f"elapsed time: {self.rain_time.toString('hh:mm:ss')} (Error)")

    def _open_station_manager(self):
        dlg = StationReadingsDialog(parent=self, db=self.db)
        dlg.exec_()

    def _open_diagnostics(self):
        dlg = DiagnosticsDialog(self.db, parent=self)
        dlg.exec_()

    def _open_settings(self):
        dlg = SettingsDialog(parent=self)
        if dlg.exec_() == SettingsDialog.Accepted:
            self.settings = load_settings()
            self.db = DatabaseManager(self.settings.get("mdb_path", ""))
            self.log("Settings saved successfully.")

    # ==============================================================================
    # Online Update System Handlers
    # ==============================================================================

    def _check_updates_on_startup(self):
        if not self.settings.get("check_updates_on_startup", True):
            return

        manifest_url = self.settings.get("update_manifest_url", "").strip()
        if not manifest_url:
            return

        self._startup_updater = CheckUpdateWorker(manifest_url, APP_VERSION)
        self._startup_updater.updateFound.connect(self._on_startup_update_found)
        # Quiet on upToDate and checkFailed during startup so we don't bother the user
        self._startup_updater.start()

    def _on_startup_update_found(self, update_info: dict):
        new_v = update_info.get("latest_version", "unknown")
        self.statusBar().showMessage(f"🚀 New update available: v{new_v}", 10000)
        self.log(f"Online Update: Version {new_v} is available!")
        # Prompt user gently
        dlg = UpdateDialog(update_info, parent=self)
        dlg.exec_()

    def _check_for_updates_manual(self):
        manifest_url = self.settings.get("update_manifest_url", "").strip()
        if not manifest_url:
            QMessageBox.warning(
                self, "Update URL Missing",
                "No update manifest URL is configured. Please set it in Settings -> Online Updates."
            )
            return

        self.statusBar().showMessage("Checking for online updates...", 4000)
        self._manual_updater = CheckUpdateWorker(manifest_url, APP_VERSION)
        self._manual_updater.updateFound.connect(self._on_manual_update_found)
        self._manual_updater.upToDate.connect(self._on_manual_up_to_date)
        self._manual_updater.checkFailed.connect(self._on_manual_check_failed)
        self._manual_updater.start()

    def _on_manual_update_found(self, update_info: dict):
        dlg = UpdateDialog(update_info, parent=self)
        dlg.exec_()

    def _on_manual_up_to_date(self, current_ver: str):
        QMessageBox.information(
            self, "Up to Date",
            f"You are running the latest version of Kruger DSS (v{current_ver})!\n\nNo updates are currently available."
        )

    def _on_manual_check_failed(self, err_msg: str):
        QMessageBox.warning(
            self, "Update Check Failed",
            f"Could not connect to the update server or parse the manifest:\n\n{err_msg}"
        )

