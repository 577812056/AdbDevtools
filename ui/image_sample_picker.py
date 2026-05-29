from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGraphicsView,
    QGraphicsScene, QGraphicsPixmapItem, QMessageBox
)
from PyQt6.QtCore import Qt, QRectF, QPointF, QTimer
from PyQt6.QtGui import QPixmap, QPainter, QPen, QColor
from core.adb_manager import AdbManager
import os
import shutil
import tempfile
import uuid


class RegionSelectView(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.start_pos = None
        self.current_rect = None
        self.rect_item = None
        self.on_region_changed = None
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.start_pos = self.mapToScene(event.pos())
            self._update_rect(self.start_pos)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.start_pos:
            self._update_rect(self.mapToScene(event.pos()))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.start_pos:
            self._update_rect(self.mapToScene(event.pos()))
            self.start_pos = None
        super().mouseReleaseEvent(event)

    def _update_rect(self, end_pos: QPointF):
        rect = QRectF(self.start_pos, end_pos).normalized()
        scene_rect = self.sceneRect()
        rect = rect.intersected(scene_rect)
        if rect.width() < 1 or rect.height() < 1:
            return

        self.current_rect = rect
        if self.rect_item:
            self.scene().removeItem(self.rect_item)
        self.rect_item = self.scene().addRect(rect, QPen(QColor(255, 64, 64), 3))
        self.rect_item.setData(0, "selection")
        if self.on_region_changed:
            self.on_region_changed(rect)


class ImageSamplePickerDialog(QDialog):
    def __init__(self, adb_manager: AdbManager, serial: str, parent=None):
        super().__init__(parent)
        self.adb_manager = adb_manager
        self.serial = serial
        self.screenshot_path = os.path.join(
            tempfile.gettempdir(), f"adb_sample_source_{serial.replace(':', '_')}.png"
        )
        self.sample_path = ""
        self.region = None
        self.pixmap = None
        self.device_w = 1080
        self.device_h = 1920
        self.zoom = 1.0
        self.setWindowTitle("选择目标样本图")
        self.setMinimumSize(1000, 760)
        self.resize(1100, 820)
        self.init_ui()
        self.load_screenshot()

    def init_ui(self):
        layout = QVBoxLayout(self)
        self.scene = QGraphicsScene(self)
        self.view = RegionSelectView(self)
        self.view.setScene(self.scene)
        self.view.on_region_changed = self.on_region_changed
        layout.addWidget(self.view, 1)

        zoom_layout = QHBoxLayout()
        zoom_out_btn = QPushButton("缩小")
        zoom_out_btn.clicked.connect(self.zoom_out)
        zoom_layout.addWidget(zoom_out_btn)

        zoom_fit_btn = QPushButton("适应窗口")
        zoom_fit_btn.clicked.connect(self.fit_to_window)
        zoom_layout.addWidget(zoom_fit_btn)

        zoom_original_btn = QPushButton("原始大小")
        zoom_original_btn.clicked.connect(self.zoom_original)
        zoom_layout.addWidget(zoom_original_btn)

        zoom_in_btn = QPushButton("放大")
        zoom_in_btn.clicked.connect(self.zoom_in)
        zoom_layout.addWidget(zoom_in_btn)
        zoom_layout.addStretch()
        layout.addLayout(zoom_layout)

        bottom = QHBoxLayout()
        self.status_label = QLabel("拖拽框选需要识别的目标区域")
        bottom.addWidget(self.status_label)
        bottom.addStretch()

        refresh_btn = QPushButton("重新截图")
        refresh_btn.clicked.connect(self.load_screenshot)
        bottom.addWidget(refresh_btn)

        save_btn = QPushButton("保存样本")
        save_btn.clicked.connect(self.save_sample)
        bottom.addWidget(save_btn)

        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        bottom.addWidget(cancel_btn)
        layout.addLayout(bottom)

    def load_screenshot(self):
        ok = self.adb_manager.take_screenshot(self.serial, self.screenshot_path)
        if not ok or not os.path.exists(self.screenshot_path):
            self.status_label.setText("截图失败")
            return

        self.pixmap = QPixmap(self.screenshot_path)
        if self.pixmap.isNull():
            self.status_label.setText("截图加载失败")
            return

        self.device_w = self.pixmap.width()
        self.device_h = self.pixmap.height()
        self.scene.clear()
        self.scene.addItem(QGraphicsPixmapItem(self.pixmap))
        self.scene.setSceneRect(QRectF(0, 0, self.device_w, self.device_h))
        self.view.setSceneRect(self.scene.sceneRect())
        self.region = None
        self.view.current_rect = None
        self.view.rect_item = None
        QTimer.singleShot(0, self.fit_to_window)
        self.status_label.setText(f"已截图: {self.device_w}x{self.device_h}，准备适应窗口")

    def apply_zoom(self):
        if not self.pixmap:
            return
        self.view.resetTransform()
        self.view.scale(self.zoom, self.zoom)
        self.status_label.setText(f"已截图: {self.device_w}x{self.device_h}，缩放: {int(self.zoom * 100)}%")

    def fit_to_window(self):
        if not self.pixmap:
            return
        self.view.fitInView(QRectF(0, 0, self.device_w, self.device_h), Qt.AspectRatioMode.KeepAspectRatio)
        self.zoom = self.view.transform().m11()
        self.status_label.setText(f"已截图: {self.device_w}x{self.device_h}，适应窗口")

    def zoom_original(self):
        self.zoom = 1.0
        self.apply_zoom()

    def zoom_in(self):
        self.zoom = min(self.zoom * 1.25, 4.0)
        self.apply_zoom()

    def zoom_out(self):
        self.zoom = max(self.zoom / 1.25, 0.2)
        self.apply_zoom()

    def on_region_changed(self, rect: QRectF):
        self.region = rect
        self.status_label.setText(
            f"已选择区域: x={round(rect.x())}, y={round(rect.y())}, "
            f"w={round(rect.width())}, h={round(rect.height())}"
        )

    def save_sample(self):
        if not self.region or self.region.width() < 5 or self.region.height() < 5:
            QMessageBox.warning(self, "提示", "请先框选至少 5x5 的目标区域。")
            return

        image = self.pixmap.toImage()
        rect = self.region.toAlignedRect()
        crop = image.copy(rect)
        samples_dir = os.path.join(os.getcwd(), "task_samples")
        os.makedirs(samples_dir, exist_ok=True)
        self.sample_path = os.path.join(samples_dir, f"sample_{uuid.uuid4().hex}.png")
        if not crop.save(self.sample_path, "PNG"):
            QMessageBox.warning(self, "提示", "保存样本图失败。")
            return

        source_copy = self.sample_path.replace(".png", "_source.png")
        try:
            shutil.copyfile(self.screenshot_path, source_copy)
        except Exception:
            pass
        self.accept()
