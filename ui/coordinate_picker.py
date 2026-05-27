from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QComboBox, QGraphicsView, QGraphicsScene,
                             QGraphicsPixmapItem, QFormLayout, QSpinBox)
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QPixmap, QPainter, QPen, QColor
from core.adb_manager import AdbManager
import os


class ClickableGraphicsView(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.click_callback = None
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.click_callback:
            scene_pos = self.mapToScene(event.pos())
            self.click_callback(scene_pos.x(), scene_pos.y())
        super().mousePressEvent(event)


class CoordinatePickerDialog(QDialog):
    def __init__(self, adb_manager: AdbManager, serial: str, parent=None):
        super().__init__(parent)
        self.adb_manager = adb_manager
        self.serial = serial
        self.pixmap = None
        self.scale_x = 1.0
        self.scale_y = 1.0
        self.zoom = 1.0
        self.device_w = 1080
        self.device_h = 1920

        self.tap_point = None
        self.swipe_start = None
        self.swipe_end = None

        # results for caller
        self.result_type = None  # "tap" or "swipe"
        self.result_coords = None  # (x,y) or (x1,y1,x2,y2)

        self.setWindowTitle("坐标拾取")
        self.setMinimumSize(1000, 760)
        self.resize(1100, 820)
        self.init_ui()
        self.load_screenshot()

    def init_ui(self):
        layout = QVBoxLayout(self)

        self.scene = QGraphicsScene(self)
        self.view = ClickableGraphicsView(self)
        self.view.click_callback = self.on_image_click
        layout.addWidget(self.view, 1)

        info_layout = QHBoxLayout()
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("点击 - 拾取单点", "tap")
        self.mode_combo.addItem("滑动 - 拾取起点/终点", "swipe")
        self.mode_combo.currentIndexChanged.connect(self.on_mode_changed)
        info_layout.addWidget(QLabel("模式:"))
        info_layout.addWidget(self.mode_combo)
        info_layout.addStretch()

        self.coord_label = QLabel("点击截图获取坐标")
        self.coord_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        info_layout.addWidget(self.coord_label)
        layout.addLayout(info_layout)

        zoom_layout = QHBoxLayout()
        zoom_out_btn = QPushButton("缩小")
        zoom_out_btn.clicked.connect(self.zoom_out)
        zoom_layout.addWidget(zoom_out_btn)

        zoom_reset_btn = QPushButton("适应窗口")
        zoom_reset_btn.clicked.connect(self.fit_to_window)
        zoom_layout.addWidget(zoom_reset_btn)

        zoom_100_btn = QPushButton("原始大小")
        zoom_100_btn.clicked.connect(self.zoom_original)
        zoom_layout.addWidget(zoom_100_btn)

        zoom_in_btn = QPushButton("放大")
        zoom_in_btn.clicked.connect(self.zoom_in)
        zoom_layout.addWidget(zoom_in_btn)
        zoom_layout.addStretch()
        layout.addLayout(zoom_layout)

        form = QFormLayout()
        self.result_x = QSpinBox()
        self.result_x.setRange(0, 9999)
        self.result_y = QSpinBox()
        self.result_y.setRange(0, 9999)

        form.addRow("结果 X:", self.result_x)
        form.addRow("结果 Y:", self.result_y)
        layout.addLayout(form)

        btn_layout = QHBoxLayout()
        fill_tap_btn = QPushButton("填入点击坐标")
        fill_tap_btn.clicked.connect(self.fill_tap)
        btn_layout.addWidget(fill_tap_btn)

        fill_swipe_btn = QPushButton("填入滑动坐标")
        fill_swipe_btn.clicked.connect(self.fill_swipe)
        btn_layout.addWidget(fill_swipe_btn)

        btn_layout.addStretch()

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.close)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

    def load_screenshot(self):
        tmp = "/tmp/adb_screenshot_coord.png"
        ok = self.adb_manager.take_screenshot(self.serial, tmp)
        if not ok or not os.path.exists(tmp):
            self.coord_label.setText("截图失败")
            return

        self.pixmap = QPixmap(tmp)
        if self.pixmap.isNull():
            self.coord_label.setText("截图加载失败")
            return

        self.device_w = self.pixmap.width()
        self.device_h = self.pixmap.height()

        self.scene.clear()
        item = QGraphicsPixmapItem(self.pixmap)
        self.scene.addItem(item)
        self.view.setScene(self.scene)
        self.view.setSceneRect(QRectF(0, 0, self.device_w, self.device_h))
        self.zoom_original()

        self.scale_x = self.view.viewport().width() / self.device_w
        self.scale_y = self.view.viewport().height() / self.device_h
        self.coord_label.setText(f"已加载: {self.device_w}x{self.device_h}")

    def apply_zoom(self):
        if not self.pixmap:
            return
        self.view.resetTransform()
        self.view.scale(self.zoom, self.zoom)
        self.coord_label.setText(f"已加载: {self.device_w}x{self.device_h}，缩放: {int(self.zoom * 100)}%")

    def fit_to_window(self):
        if not self.pixmap:
            return
        self.view.fitInView(QRectF(0, 0, self.device_w, self.device_h), Qt.AspectRatioMode.KeepAspectRatio)
        transform = self.view.transform()
        self.zoom = transform.m11()
        self.coord_label.setText(f"已加载: {self.device_w}x{self.device_h}，适应窗口")

    def zoom_original(self):
        self.zoom = 1.0
        self.apply_zoom()

    def zoom_in(self):
        self.zoom = min(self.zoom * 1.25, 4.0)
        self.apply_zoom()

    def zoom_out(self):
        self.zoom = max(self.zoom / 1.25, 0.2)
        self.apply_zoom()

    def on_image_click(self, sx, sy):
        dx = round(sx)
        dy = round(sy)
        dx = max(0, min(dx, self.device_w - 1))
        dy = max(0, min(dy, self.device_h - 1))

        mode = self.mode_combo.currentData()

        if mode == "tap":
            self.tap_point = (dx, dy)
            self.result_x.setValue(dx)
            self.result_y.setValue(dy)
            self.coord_label.setText(f"点击坐标: ({dx}, {dy})")
        elif mode == "swipe":
            if self.swipe_start is None:
                self.swipe_start = (dx, dy)
                self.result_x.setValue(dx)
                self.result_y.setValue(dy)
                self.coord_label.setText(f"起点: ({dx}, {dy}) - 再次点击设置终点")
            else:
                self.swipe_end = (dx, dy)
                self.coord_label.setText(f"起点: {self.swipe_start}, 终点: ({dx}, {dy})")

        self.draw_markers()

    def draw_markers(self):
        if self.scene is None:
            return
        for item in list(self.scene.items()):
            if isinstance(item, MarkerItem) or item.data(0) == "marker":
                self.scene.removeItem(item)

        mode = self.mode_combo.currentData()
        pen = QPen(QColor(255, 0, 0), 3)
        cross_size = 20

        if mode == "tap" and self.tap_point:
            x, y = self.tap_point
            m = MarkerItem(x, y, cross_size, pen)
            self.scene.addItem(m)

        elif mode == "swipe":
            if self.swipe_start:
                x, y = self.swipe_start
                m = MarkerItem(x, y, cross_size, QPen(QColor(0, 255, 0), 3), "S")
                self.scene.addItem(m)
            if self.swipe_end:
                x, y = self.swipe_end
                m = MarkerItem(x, y, cross_size, QPen(QColor(255, 0, 0), 3), "E")
                self.scene.addItem(m)
            if self.swipe_start and self.swipe_end:
                line = self.scene.addLine(
                    self.swipe_start[0], self.swipe_start[1],
                    self.swipe_end[0], self.swipe_end[1],
                    QPen(QColor(0, 255, 255), 2, Qt.PenStyle.DashLine)
                )
                line.setData(0, "marker")

    def on_mode_changed(self):
        self.tap_point = None
        self.swipe_start = None
        self.swipe_end = None
        self.coord_label.setText("点击截图获取坐标")
        self.draw_markers()

    def fill_tap(self):
        if self.tap_point:
            self.result_type = "tap"
            self.result_coords = self.tap_point
            self.accept()

    def fill_swipe(self):
        if self.swipe_start and self.swipe_end:
            self.result_type = "swipe"
            self.result_coords = (*self.swipe_start, *self.swipe_end)
            self.accept()


class MarkerItem(QGraphicsPixmapItem):
    def __init__(self, x, y, size, pen, label=None):
        super().__init__()
        self.x = x
        self.y = y
        self.size = size
        self.pen = pen
        self.label = label
        self.redraw()

    def redraw(self):
        sz = self.size
        pix = QPixmap(sz * 2 + 10, sz * 2 + 10)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setPen(self.pen)
        cx = sz + 5
        cy = sz + 5
        p.drawLine(cx - sz, cy, cx + sz, cy)
        p.drawLine(cx, cy - sz, cx, cy + sz)
        if self.label:
            p.drawText(cx + 5, cy - 5, self.label)
        p.end()
        self.setPixmap(pix)
        self.setPos(self.x - sz - 5, self.y - sz - 5)
