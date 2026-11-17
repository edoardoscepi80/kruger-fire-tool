"""
Native High-Performance GIS Map Viewer Widget based on PyQt5 (QGraphicsView / QGraphicsScene).
Completely decoupled from QGIS Desktop, zero external GIS C++ runtime required.
"""

import os
import random
from typing import Optional, List, Dict
import shapefile

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QToolBar, QAction, QFileDialog,
    QLabel, QMessageBox, QGraphicsView, QGraphicsScene, QGraphicsPathItem
)
from PyQt5.QtCore import pyqtSignal, Qt, QRectF, QPointF
from PyQt5.QtGui import (
    QPainter, QPainterPath, QColor, QPen, QBrush, QWheelEvent,
    QMouseEvent, QCursor
)


class MapCanvasView(QGraphicsView):
    """
    Interactive QGraphicsView customized for GIS cartographic display.
    Handles UTM meter-based coordinates with flipped Y (North-up), smooth wheel zoom,
    and pan drag modes.
    """
    mouseMovedCoord = pyqtSignal(float, float)

    def __init__(self, scene: QGraphicsScene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setRenderHint(QPainter.SmoothPixmapTransform, True)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setBackgroundBrush(QBrush(QColor(245, 247, 250)))
        self.setMouseTracking(True)

        # Invert vertical axis so North (positive Y) points UP as in GIS
        self.scale(1, -1)

        self._mode = "pan"  # "pan", "zoom_in", "zoom_out"
        self._pan_active = False
        self._last_mouse_pos = QPointF()
        self._initial_fitted = False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._initial_fitted and self.scene() and not self.scene().itemsBoundingRect().isNull():
            rect = self.scene().itemsBoundingRect()
            if rect.width() > 0 and rect.height() > 0:
                self._initial_fitted = True
                pad_x = rect.width() * 0.03
                pad_y = rect.height() * 0.03
                self.fitInView(rect.adjusted(-pad_x, -pad_y, pad_x, pad_y), Qt.KeepAspectRatio)

    def set_mode(self, mode: str):
        self._mode = mode
        if mode == "pan":
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            self.setCursor(Qt.OpenHandCursor)
        elif mode == "zoom_in":
            self.setDragMode(QGraphicsView.NoDrag)
            self.setCursor(Qt.CrossCursor)
        elif mode == "zoom_out":
            self.setDragMode(QGraphicsView.NoDrag)
            self.setCursor(Qt.CrossCursor)

    def wheelEvent(self, event: QWheelEvent):
        """Smooth zooming centered at the mouse cursor position."""
        factor = 1.15
        if event.angleDelta().y() < 0:
            factor = 1.0 / factor
        self.scale(factor, factor)

    def mouseMoveEvent(self, event: QMouseEvent):
        super().mouseMoveEvent(event)
        scene_pos = self.mapToScene(event.pos())
        self.mouseMovedCoord.emit(scene_pos.x(), scene_pos.y())

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            if self._mode == "zoom_in":
                pos = self.mapToScene(event.pos())
                self.centerOn(pos)
                self.scale(1.3, 1.3)
                return
            elif self._mode == "zoom_out":
                pos = self.mapToScene(event.pos())
                self.centerOn(pos)
                self.scale(0.75, 0.75)
                return
        super().mousePressEvent(event)


class MapWidget(QWidget):
    layerAdded = pyqtSignal(str, object)   # layer_id, layer_proxy_object
    layerRemoved = pyqtSignal(str)         # layer_id
    mouseMovedCoord = pyqtSignal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.base_layer_id: Optional[str] = None
        self.boundary_layer_id: Optional[str] = None
        self.layers: Dict[str, dict] = {}  # layer_id -> {item, name, path, visible}

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 1. Map Toolbar
        self.toolbar = QToolBar("GIS Map Tools", self)
        self.toolbar.setStyleSheet("""
            QToolBar {
                background: #f1f3f5;
                border-bottom: 1px solid #dcdfe6;
                spacing: 6px;
                padding: 4px;
            }
        """)

        # Actions
        self.act_add_layer = QAction("➕ Add Layer", self)
        self.act_add_layer.setToolTip("Add Shapefile Layer")
        self.act_add_layer.triggered.connect(self._on_add_layer_clicked)
        self.toolbar.addAction(self.act_add_layer)

        self.act_remove_layer = QAction("❌ Remove Layer", self)
        self.act_remove_layer.setToolTip("Remove Active/Selected Layer")
        self.act_remove_layer.triggered.connect(self.remove_selected_layer)
        self.toolbar.addAction(self.act_remove_layer)

        self.act_clear_layers = QAction("🧹 Clear Secondary Layers", self)
        self.act_clear_layers.setToolTip("Remove all temporary layers except BaseGrid and Boundary")
        self.act_clear_layers.triggered.connect(self.clear_secondary_layers)
        self.toolbar.addAction(self.act_clear_layers)

        self.toolbar.addSeparator()

        self.act_pan = QAction("✋ Pan", self)
        self.act_pan.setCheckable(True)
        self.act_pan.setChecked(True)
        self.act_pan.setToolTip("Pan map by dragging")
        self.act_pan.triggered.connect(self.set_pan_mode)
        self.toolbar.addAction(self.act_pan)

        self.act_zoom_in = QAction("🔍➕ Zoom In", self)
        self.act_zoom_in.setCheckable(True)
        self.act_zoom_in.setToolTip("Zoom In (click on map or use mouse wheel)")
        self.act_zoom_in.triggered.connect(self.set_zoom_in_mode)
        self.toolbar.addAction(self.act_zoom_in)

        self.act_zoom_out = QAction("🔍➖ Zoom Out", self)
        self.act_zoom_out.setCheckable(True)
        self.act_zoom_out.setToolTip("Zoom Out (click on map or use mouse wheel)")
        self.act_zoom_out.triggered.connect(self.set_zoom_out_mode)
        self.toolbar.addAction(self.act_zoom_out)

        self.act_full_extent = QAction("🌐 Full Extent", self)
        self.act_full_extent.setToolTip("Fit all layers into view")
        self.act_full_extent.triggered.connect(self.zoom_to_full_extent)
        self.toolbar.addAction(self.act_full_extent)

        layout.addWidget(self.toolbar)

        # 2. Native Graphics Scene & Canvas
        self.scene = QGraphicsScene(self)
        self.canvas = MapCanvasView(self.scene, self)
        self.canvas.mouseMovedCoord.connect(self._on_mouse_moved)
        layout.addWidget(self.canvas)

        # 3. Bottom Coordinates Status Bar
        self.coord_label = QLabel("X: 0.00  |  Y: 0.00", self)
        self.coord_label.setStyleSheet("background-color: #e5e7eb; color: #374151; padding: 4px 8px; font-size: 11px; font-weight: bold;")
        layout.addWidget(self.coord_label)

        self.set_pan_mode()

    def _on_mouse_moved(self, x: float, y: float):
        self.coord_label.setText(f"X: {x:.2f}  |  Y: {y:.2f}")
        self.mouseMovedCoord.emit(x, y)

    def set_pan_mode(self):
        self.act_pan.setChecked(True)
        self.act_zoom_in.setChecked(False)
        self.act_zoom_out.setChecked(False)
        self.canvas.set_mode("pan")

    def set_zoom_in_mode(self):
        self.act_pan.setChecked(False)
        self.act_zoom_in.setChecked(True)
        self.act_zoom_out.setChecked(False)
        self.canvas.set_mode("zoom_in")

    def set_zoom_out_mode(self):
        self.act_pan.setChecked(False)
        self.act_zoom_in.setChecked(False)
        self.act_zoom_out.setChecked(True)
        self.canvas.set_mode("zoom_out")

    def zoom_to_full_extent(self):
        rect = self.scene.itemsBoundingRect()
        if not rect.isNull() and rect.width() > 0 and rect.height() > 0:
            pad_x = rect.width() * 0.03
            pad_y = rect.height() * 0.03
            padded_rect = rect.adjusted(-pad_x, -pad_y, pad_x, pad_y)
            self.canvas.fitInView(padded_rect, Qt.KeepAspectRatio)

    def _build_shapefile_path(self, shp_path: str) -> Optional[QPainterPath]:
        """Parses a shapefile into a single optimized QPainterPath."""
        if not os.path.exists(shp_path):
            return None

        try:
            sf = shapefile.Reader(shp_path)
            qpath = QPainterPath()
            for s in sf.shapes():
                if s.shapeType in (3, 5, 13, 15, 23, 25):  # Polyline or Polygon
                    pts = s.points
                    parts = list(s.parts) + [len(pts)]
                    for i in range(len(s.parts)):
                        ring = pts[parts[i]:parts[i+1]]
                        if not ring:
                            continue
                        qpath.moveTo(ring[0][0], ring[0][1])
                        for pt in ring[1:]:
                            qpath.lineTo(pt[0], pt[1])
                        if s.shapeType in (5, 15, 25):
                            qpath.closeSubpath()
            return qpath
        except Exception as e:
            print(f"Error parsing shapefile {shp_path}: {e}")
            return None

    def load_base_grid(self, base_grid_path: str) -> bool:
        """Loads the BaseGrid shapefile as the foundational spatial grid."""
        if not os.path.exists(base_grid_path):
            return False

        qpath = self._build_shapefile_path(base_grid_path)
        if not qpath or qpath.isEmpty():
            return False

        item = QGraphicsPathItem(qpath)
        pen = QPen(QColor(160, 160, 160, 160), 0)
        pen.setCosmetic(True)
        item.setPen(pen)
        item.setBrush(QBrush(QColor(235, 237, 240, 120)))
        item.setZValue(1)

        self.scene.addItem(item)
        layer_id = "layer_base_grid"
        self.base_layer_id = layer_id

        # Proxy layer object for compatibility with list manager
        proxy = LayerProxy(layer_id, "BaseGrid (Kruger)", base_grid_path, item)
        self.layers[layer_id] = proxy
        self.layerAdded.emit(layer_id, proxy)

        self.zoom_to_full_extent()
        return True

    def load_boundary_layer(self, boundary_path: str, name: str = "Kruger Boundary") -> bool:
        """Loads boundary polygon shapefile rendered as an overlay outline."""
        if not os.path.exists(boundary_path):
            return False

        qpath = self._build_shapefile_path(boundary_path)
        if not qpath or qpath.isEmpty():
            return False

        item = QGraphicsPathItem(qpath)
        pen = QPen(QColor(30, 35, 45, 255), 2)
        pen.setCosmetic(True)
        item.setPen(pen)
        item.setBrush(QBrush(Qt.NoBrush))
        item.setZValue(10)  # Always rendered above the grid

        self.scene.addItem(item)
        layer_id = "layer_kruger_boundary"
        self.boundary_layer_id = layer_id

        proxy = LayerProxy(layer_id, name, boundary_path, item)
        self.layers[layer_id] = proxy
        self.layerAdded.emit(layer_id, proxy)

        self.zoom_to_full_extent()
        return True

    def add_shapefile_layer(self, shp_path: str, name: Optional[str] = None) -> Optional[str]:
        """Loads an arbitrary shapefile (e.g. fire scars, management zones)."""
        if not os.path.exists(shp_path):
            return None

        qpath = self._build_shapefile_path(shp_path)
        if not qpath or qpath.isEmpty():
            return None

        item = QGraphicsPathItem(qpath)
        
        # Color styling: warm orange/red for fire shapefiles, pleasant random pastel otherwise
        base_name = os.path.splitext(os.path.basename(shp_path))[0]
        is_fire = "fire" in base_name.lower() or "burn" in base_name.lower()

        if is_fire:
            pen = QPen(QColor(180, 40, 0, 240), 1)
            brush = QBrush(QColor(234, 88, 12, 140))
        else:
            r = random.randint(40, 200)
            g = random.randint(40, 200)
            b = random.randint(40, 200)
            pen = QPen(QColor(r, g, b, 240), 1)
            brush = QBrush(QColor(r, g, b, 90))

        pen.setCosmetic(True)
        item.setPen(pen)
        item.setBrush(brush)
        item.setZValue(20 + len(self.layers))

        self.scene.addItem(item)
        layer_id = f"layer_{len(self.layers)}_{base_name}"
        layer_name = name or base_name

        proxy = LayerProxy(layer_id, layer_name, shp_path, item)
        self.layers[layer_id] = proxy
        self.layerAdded.emit(layer_id, proxy)

        return layer_id

    def set_layer_visible(self, layer_id: str, visible: bool):
        proxy = self.layers.get(layer_id)
        if proxy and proxy.item:
            proxy.item.setVisible(visible)

    def remove_selected_layer(self):
        # Remove top non-foundational layer
        for lid in list(self.layers.keys()):
            if lid not in (self.base_layer_id, self.boundary_layer_id):
                proxy = self.layers.pop(lid)
                if proxy.item:
                    self.scene.removeItem(proxy.item)
                self.layerRemoved.emit(lid)
                break

    def clear_secondary_layers(self):
        """Removes all layers except BaseGrid and Kruger Boundary."""
        to_remove = [lid for lid in self.layers.keys() if lid not in (self.base_layer_id, self.boundary_layer_id)]
        for lid in to_remove:
            proxy = self.layers.pop(lid)
            if proxy.item:
                self.scene.removeItem(proxy.item)
            self.layerRemoved.emit(lid)

    def _on_add_layer_clicked(self):
        shp_file, _ = QFileDialog.getOpenFileName(
            self, "Add Shapefile Layer", "", "ESRI Shapefile (*.shp)"
        )
        if shp_file:
            lid = self.add_shapefile_layer(shp_file)
            if not lid:
                QMessageBox.warning(self, "Load Error", f"Could not load shapefile:\n{shp_file}")


class LayerProxy:
    """Lightweight layer proxy matching the attributes expected by MainWindow."""
    def __init__(self, layer_id: str, name: str, source: str, item: QGraphicsPathItem):
        self._id = layer_id
        self._name = name
        self._source = source
        self.item = item

    def id(self) -> str:
        return self._id

    def name(self) -> str:
        return self._name

    def source(self) -> str:
        return self._source
