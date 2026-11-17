import os
from typing import Optional, List
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QToolBar, QAction, QFileDialog,
    QLabel, QMessageBox
)
from PyQt5.QtCore import pyqtSignal, Qt
from PyQt5.QtGui import QIcon, QColor

from qgis.core import (
    QgsVectorLayer, QgsProject, QgsSimpleFillSymbolLayer, QgsFillSymbol,
    QgsSingleSymbolRenderer, QgsPointXY
)
from qgis.gui import (
    QgsMapCanvas, QgsMapToolPan, QgsMapToolZoom
)


class MapWidget(QWidget):
    layerAdded = pyqtSignal(str, object)   # layer_id, QgsVectorLayer
    layerRemoved = pyqtSignal(str)         # layer_id
    mouseMovedCoord = pyqtSignal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.base_layer_id: Optional[str] = None
        self.boundary_layer_id: Optional[str] = None
        self.layers_list: List[QgsVectorLayer] = []

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 1. Map Toolbar
        self.toolbar = QToolBar("GIS Map Tools", self)
        self.toolbar.setIconSize(self.toolbar.iconSize())

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
        self.act_clear_layers.setToolTip("Remove all layers except BaseGrid")
        self.act_clear_layers.triggered.connect(self.clear_secondary_layers)
        self.toolbar.addAction(self.act_clear_layers)

        self.toolbar.addSeparator()

        self.act_pan = QAction("✋ Pan", self)
        self.act_pan.setCheckable(True)
        self.act_pan.setChecked(True)
        self.act_pan.setToolTip("Pan map")
        self.act_pan.triggered.connect(self.set_pan_mode)
        self.toolbar.addAction(self.act_pan)

        self.act_zoom_in = QAction("🔍➕ Zoom In", self)
        self.act_zoom_in.setCheckable(True)
        self.act_zoom_in.setToolTip("Zoom In (click or drag box)")
        self.act_zoom_in.triggered.connect(self.set_zoom_in_mode)
        self.toolbar.addAction(self.act_zoom_in)

        self.act_zoom_out = QAction("🔍➖ Zoom Out", self)
        self.act_zoom_out.setCheckable(True)
        self.act_zoom_out.setToolTip("Zoom Out")
        self.act_zoom_out.triggered.connect(self.set_zoom_out_mode)
        self.toolbar.addAction(self.act_zoom_out)

        self.act_full_extent = QAction("🌐 Full Extent", self)
        self.act_full_extent.setToolTip("Zoom to full extent of all layers")
        self.act_full_extent.triggered.connect(self.zoom_to_full_extent)
        self.toolbar.addAction(self.act_full_extent)

        layout.addWidget(self.toolbar)

        # 2. QgsMapCanvas
        self.canvas = QgsMapCanvas(self)
        self.canvas.setCanvasColor(QColor(245, 247, 250))
        self.canvas.enableAntiAliasing(True)
        layout.addWidget(self.canvas)

        # 3. Coordinate status bar
        self.coord_label = QLabel("Coordinates: 0.00, 0.00", self)
        self.coord_label.setStyleSheet("background-color: #e0e0e0; padding: 3px; font-size: 11px;")
        layout.addWidget(self.coord_label)

        # Map tools
        self.tool_pan = QgsMapToolPan(self.canvas)
        self.tool_zoom_in = QgsMapToolZoom(self.canvas, False)
        self.tool_zoom_out = QgsMapToolZoom(self.canvas, True)

        self.canvas.setMapTool(self.tool_pan)
        self.canvas.xyCoordinates.connect(self._on_mouse_moved)

    def _on_mouse_moved(self, point: QgsPointXY):
        self.coord_label.setText(f"X: {point.x():.2f}  |  Y: {point.y():.2f}")
        self.mouseMovedCoord.emit(point.x(), point.y())

    def set_pan_mode(self):
        self.act_pan.setChecked(True)
        self.act_zoom_in.setChecked(False)
        self.act_zoom_out.setChecked(False)
        self.canvas.setMapTool(self.tool_pan)

    def set_zoom_in_mode(self):
        self.act_pan.setChecked(False)
        self.act_zoom_in.setChecked(True)
        self.act_zoom_out.setChecked(False)
        self.canvas.setMapTool(self.tool_zoom_in)

    def set_zoom_out_mode(self):
        self.act_pan.setChecked(False)
        self.act_zoom_in.setChecked(False)
        self.act_zoom_out.setChecked(True)
        self.canvas.setMapTool(self.tool_zoom_out)

    def zoom_to_full_extent(self):
        self.canvas.zoomToFullExtent()

    def load_base_grid(self, base_grid_path: str) -> bool:
        """
        Loads the BaseGrid shapefile as the foundational layer.
        """
        if not os.path.exists(base_grid_path):
            return False

        layer = QgsVectorLayer(base_grid_path, "BaseGrid (Kruger)", "ogr")
        if not layer.isValid():
            return False

        # Semi-transparent styling with light gray border
        sym = QgsFillSymbol.createSimple({
            "color": "240,240,240,30",
            "outline_color": "160,160,160,180",
            "outline_width": "0.2"
        })
        layer.setRenderer(QgsSingleSymbolRenderer(sym))
        layer.triggerRepaint()

        # Add to project and canvas
        QgsProject.instance().addMapLayer(layer)
        self.base_layer_id = layer.id()
        self.layers_list.insert(0, layer)
        self._refresh_canvas()
        self.canvas.zoomToFullExtent()

        self.layerAdded.emit(layer.id(), layer)
        return True

    def load_boundary_layer(self, bndry_path: str, name: str = "Kruger Boundary") -> Optional[QgsVectorLayer]:
        """
        Loads the Kruger Boundary shapefile on top of the BaseGrid.
        """
        if not os.path.exists(bndry_path):
            return None

        layer = QgsVectorLayer(bndry_path, name, "ogr")
        if not layer.isValid():
            return None

        # Distinct boundary styling: transparent fill with a crisp dark outline
        sym = QgsFillSymbol.createSimple({
            "color": "0,0,0,0",
            "outline_color": "20,20,20,255",
            "outline_width": "0.9"
        })
        layer.setRenderer(QgsSingleSymbolRenderer(sym))
        layer.triggerRepaint()

        QgsProject.instance().addMapLayer(layer)
        self.boundary_layer_id = layer.id()
        self.layers_list.append(layer)  # Appended so it renders on top of BaseGrid
        self._refresh_canvas()

        self.layerAdded.emit(layer.id(), layer)
        return layer

    def add_vector_layer(self, path: str, name: Optional[str] = None) -> Optional[QgsVectorLayer]:
        """
        Adds a generic vector layer to the map.
        """
        if not os.path.exists(path):
            QMessageBox.warning(self, "File Not Found", f"Shapefile does not exist:\n{path}")
            return None

        if not name:
            name = os.path.splitext(os.path.basename(path))[0]

        layer = QgsVectorLayer(path, name, "ogr")
        if not layer.isValid():
            QMessageBox.warning(self, "Invalid Layer", f"Could not load vector layer from:\n{path}")
            return None

        # Distinct style depending on name
        if "fire" in name.lower():
            # Orange/red fire styling
            sym = QgsFillSymbol.createSimple({
                "color": "255,100,20,130",
                "outline_color": "180,30,0,220",
                "outline_width": "0.6"
            })
            layer.setRenderer(QgsSingleSymbolRenderer(sym))
        elif "bndry" in name.lower() or "boundary" in name.lower():
            sym = QgsFillSymbol.createSimple({
                "color": "0,0,0,0",
                "outline_color": "30,30,30,255",
                "outline_width": "1.2"
            })
            layer.setRenderer(QgsSingleSymbolRenderer(sym))

        QgsProject.instance().addMapLayer(layer)
        # Put on top of list
        self.layers_list.append(layer)
        self._refresh_canvas()

        self.layerAdded.emit(layer.id(), layer)
        return layer

    def _on_add_layer_clicked(self):
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, "Select Shapefiles to Load", "", "ESRI Shapefiles (*.shp);;All Files (*.*)"
        )
        for path in file_paths:
            self.add_vector_layer(path)

    def remove_selected_layer(self, layer_id: Optional[str] = None):
        """
        Removes the specified layer, or the topmost secondary layer.
        """
        if not layer_id and len(self.layers_list) > 1:
            # Pick topmost non-base layer
            layer_to_remove = self.layers_list[-1]
            if layer_to_remove.id() != self.base_layer_id:
                layer_id = layer_to_remove.id()

        if layer_id:
            if layer_id == self.base_layer_id:
                reply = QMessageBox.question(
                    self, "Remove Base Layer?",
                    "Are you sure you want to remove the foundational BaseGrid layer?",
                    QMessageBox.Yes | QMessageBox.No
                )
                if reply != QMessageBox.Yes:
                    return

            QgsProject.instance().removeMapLayer(layer_id)
            self.layers_list = [l for l in self.layers_list if l.id() != layer_id]
            self._refresh_canvas()
            self.layerRemoved.emit(layer_id)

    def clear_secondary_layers(self):
        """
        Removes all layers except the base grid and the Kruger boundary.
        """
        keep_ids = {self.base_layer_id, self.boundary_layer_id}
        layers_to_remove = [l for l in self.layers_list if l.id() not in keep_ids]
        for l in layers_to_remove:
            QgsProject.instance().removeMapLayer(l.id())
            self.layerRemoved.emit(l.id())

        self.layers_list = [l for l in self.layers_list if l.id() in keep_ids]
        self._refresh_canvas()

    def _refresh_canvas(self):
        # Canvas layers order: reverse so first in list is bottom layer
        ordered = list(reversed(self.layers_list))
        self.canvas.setLayers(ordered)
        self.canvas.refresh()
