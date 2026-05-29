from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, 
                             QPushButton, QLabel, QGroupBox, QSpinBox, 
                             QLineEdit, QCheckBox, QFileDialog, QMessageBox,
                             QFormLayout, QListWidget, QListWidgetItem, QComboBox,
                             QTimeEdit, QDialog, QProgressBar, QGraphicsView,
                             QGraphicsScene, QGraphicsPixmapItem, QDoubleSpinBox)
from PyQt6.QtCore import Qt, QTime, pyqtSignal, QThread, QRectF
from PyQt6.QtGui import QPixmap, QPainter, QPen, QColor
from core.adb_manager import AdbManager
from tasks.task_manager import TaskManager, ScheduledTask, TaskAction, action_names, KEY_MAP, KEY_MAP_REVERSE
from ui.task_edit_dialog import TaskEditDialog
from ui.step_edit_dialog import StepEditDialog
from ui.coordinate_picker import CoordinatePickerDialog
from ui.image_sample_picker import ImageSamplePickerDialog
from datetime import datetime
import uuid
import os
import tempfile
import time
from PIL import Image


DEFAULT_TAP_STEP = {"action": TaskAction.TAP, "params": {"x": 37, "y": 1399}}
INTERVAL_UNITS = [
    ("时", 60 * 60 * 1000),
    ("分", 60 * 1000),
    ("秒", 1000),
    ("毫秒", 1),
]


class AppRefreshWorker(QThread):
    apps_loaded = pyqtSignal(str, list, int, int, int)
    app_resolved = pyqtSignal(str, str, str)
    load_failed = pyqtSignal(str, str)

    def __init__(self, adb_manager: AdbManager, serial: str):
        super().__init__()
        self.adb_manager = adb_manager
        self.serial = serial
        self.max_precise_resolve = 80

    def run(self):
        try:
            packages = self.adb_manager.list_packages(self.serial)
            third_party_packages = set(
                self.adb_manager.list_packages(self.serial, third_party_only=True)
            )
            names = self.adb_manager.get_app_names(self.serial)
            named = 0
            precise_named = 0
            items = []
            needs_precise = []

            for package in packages:
                label = names.get(package, "")
                if len(label) < 2 or label.startswith("<"):
                    label = ""
                if label and self._looks_like_fallback_label(label, package):
                    label = ""
                if label:
                    named += 1
                elif package in third_party_packages:
                    needs_precise.append(package)

                display = f"{label} {package}" if label else package
                items.append((display, package))

            self.apps_loaded.emit(self.serial, items, len(packages), named, precise_named)

            for package in needs_precise[:self.max_precise_resolve]:
                precise_label = self.adb_manager.get_app_name(self.serial, package)
                if precise_label and not self._looks_like_fallback_label(precise_label, package):
                    self.app_resolved.emit(self.serial, package, precise_label)
        except Exception as exc:
            self.load_failed.emit(self.serial, str(exc))

    @staticmethod
    def _looks_like_fallback_label(label: str, package: str):
        normalized_label = label.strip().lower()
        package_parts = [part.lower() for part in package.split(".") if part]
        return normalized_label in package_parts


class RecordingStreamWorker(QThread):
    frame_ready = pyqtSignal(bytes, int, int)
    stream_failed = pyqtSignal(str)

    def __init__(self, adb_manager: AdbManager, serial: str):
        super().__init__()
        self.adb_manager = adb_manager
        self.serial = serial
        self.running = True

    def stop(self):
        self.running = False

    def run(self):
        frame_path = os.path.join(tempfile.gettempdir(), f"adb_record_{self.serial.replace(':', '_')}.png")
        while self.running:
            try:
                ok = self.adb_manager.take_screenshot(self.serial, frame_path)
                if ok and os.path.exists(frame_path):
                    with Image.open(frame_path) as image:
                        width, height = image.size
                    with open(frame_path, "rb") as image_file:
                        frame_data = image_file.read()
                    self.frame_ready.emit(frame_data, width, height)
                time.sleep(0.8)
            except Exception as exc:
                self.stream_failed.emit(str(exc))
                time.sleep(1.5)


class RecordingGraphicsView(QGraphicsView):
    clicked = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setMouseTracking(True)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = self.mapToScene(event.pos())
            self.clicked.emit(round(pos.x()), round(pos.y()))
        super().mousePressEvent(event)


class ControlPanel(QWidget):
    log_emitted = pyqtSignal(str, str, str)

    def __init__(self, adb_manager: AdbManager, task_manager: TaskManager):
        super().__init__()
        self.adb_manager = adb_manager
        self.task_manager = task_manager
        self.current_serial = None
        self.app_refresh_worker = None
        self.app_resolved_count = 0
        self.recording_worker = None
        self.recording_steps = []
        self.recording_serial = None
        self.recording_device_w = 0
        self.recording_device_h = 0
        self.init_ui()
        
    def _log(self, operation: str, result: str):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log_emitted.emit(timestamp, operation, result)
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        tabs = QTabWidget()
        
        tabs.addTab(self.create_device_control_tab(), "设备控制")
        tabs.addTab(self.create_app_manager_tab(), "应用管理")
        tabs.addTab(self.create_task_scheduler_tab(), "定时任务")
        tabs.addTab(self.create_operation_recording_tab(), "操作录制")
        
        layout.addWidget(tabs)
        
    def create_device_control_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        tap_group = QGroupBox("点击屏幕")
        tap_layout = QFormLayout()
        
        self.tap_x = QSpinBox()
        self.tap_x.setRange(0, 9999)
        self.tap_x.setValue(540)
        tap_layout.addRow("X坐标:", self.tap_x)
        
        self.tap_y = QSpinBox()
        self.tap_y.setRange(0, 9999)
        self.tap_y.setValue(960)
        tap_layout.addRow("Y坐标:", self.tap_y)
        
        tap_btn = QPushButton("点击")
        tap_btn.clicked.connect(self.do_tap)
        tap_layout.addRow("", tap_btn)
        
        tap_group.setLayout(tap_layout)
        layout.addWidget(tap_group)
        
        swipe_group = QGroupBox("滑动屏幕")
        swipe_layout = QFormLayout()
        
        self.swipe_x1 = QSpinBox()
        self.swipe_x1.setRange(0, 9999)
        self.swipe_x1.setValue(540)
        swipe_layout.addRow("起始X:", self.swipe_x1)
        
        self.swipe_y1 = QSpinBox()
        self.swipe_y1.setRange(0, 9999)
        self.swipe_y1.setValue(1500)
        swipe_layout.addRow("起始Y:", self.swipe_y1)
        
        self.swipe_x2 = QSpinBox()
        self.swipe_x2.setRange(0, 9999)
        self.swipe_x2.setValue(540)
        swipe_layout.addRow("结束X:", self.swipe_x2)
        
        self.swipe_y2 = QSpinBox()
        self.swipe_y2.setRange(0, 9999)
        self.swipe_y2.setValue(500)
        swipe_layout.addRow("结束Y:", self.swipe_y2)
        
        self.swipe_duration = QSpinBox()
        self.swipe_duration.setRange(100, 5000)
        self.swipe_duration.setValue(300)
        self.swipe_duration.setSuffix(" ms")
        swipe_layout.addRow("持续时间:", self.swipe_duration)
        
        swipe_btn = QPushButton("滑动")
        swipe_btn.clicked.connect(self.do_swipe)
        swipe_layout.addRow("", swipe_btn)
        
        swipe_group.setLayout(swipe_layout)
        layout.addWidget(swipe_group)
        
        screenshot_group = QGroupBox("截屏")
        screenshot_layout = QHBoxLayout()
        
        self.screenshot_path = QLineEdit("/tmp/screenshot.png")
        screenshot_layout.addWidget(self.screenshot_path)
        
        screenshot_btn = QPushButton("截屏")
        screenshot_btn.clicked.connect(self.do_screenshot)
        screenshot_layout.addWidget(screenshot_btn)
        
        screenshot_group.setLayout(screenshot_layout)
        layout.addWidget(screenshot_group)
        
        key_group = QGroupBox("按键")
        key_layout = QHBoxLayout()
        
        keys = [
            ("返回", 4), ("主页", 3), ("菜单", 82), 
            ("音量+", 24), ("音量-", 25), ("电源", 26)
        ]
        
        for name, keycode in keys:
            btn = QPushButton(name)
            btn.clicked.connect(lambda checked, kc=keycode: self.do_input_key(kc))
            key_layout.addWidget(btn)
            
        key_group.setLayout(key_layout)
        layout.addWidget(key_group)

        coord_group = QGroupBox("坐标拾取")
        coord_layout = QVBoxLayout()
        coord_btn = QPushButton("打开截图拾取坐标")
        coord_btn.clicked.connect(self.open_coord_picker)
        coord_layout.addWidget(coord_btn)
        coord_hint = QLabel("选择模式后点击截图获取坐标，复制结果后粘贴到操作框")
        coord_hint.setWordWrap(True)
        coord_hint.setStyleSheet("color: gray; font-size: 11px;")
        coord_layout.addWidget(coord_hint)
        coord_group.setLayout(coord_layout)
        layout.addWidget(coord_group)
        
        layout.addStretch()
        
        return widget

    def create_operation_recording_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        device_group = QGroupBox("录制设备")
        device_layout = QHBoxLayout()
        self.record_device_combo = QComboBox()
        self.refresh_record_device_options()
        device_layout.addWidget(self.record_device_combo)

        refresh_devices_btn = QPushButton("刷新")
        refresh_devices_btn.clicked.connect(self.refresh_record_device_options)
        device_layout.addWidget(refresh_devices_btn)
        device_group.setLayout(device_layout)
        layout.addWidget(device_group)

        preview_group = QGroupBox("实时投屏")
        preview_layout = QVBoxLayout()
        self.record_scene = QGraphicsScene(self)
        self.record_view = RecordingGraphicsView(self)
        self.record_view.setMinimumHeight(420)
        self.record_view.setScene(self.record_scene)
        self.record_view.clicked.connect(self.on_record_view_clicked)
        preview_layout.addWidget(self.record_view, 1)

        self.record_status_label = QLabel("请选择设备后开始录制")
        self.record_status_label.setStyleSheet("color: gray;")
        preview_layout.addWidget(self.record_status_label)
        preview_group.setLayout(preview_layout)
        layout.addWidget(preview_group, 1)

        steps_group = QGroupBox("已录制操作")
        steps_layout = QVBoxLayout()
        self.record_steps_list = QListWidget()
        steps_layout.addWidget(self.record_steps_list)
        steps_group.setLayout(steps_layout)
        layout.addWidget(steps_group)

        controls_layout = QHBoxLayout()
        self.start_record_btn = QPushButton("开始录制")
        self.start_record_btn.clicked.connect(self.start_operation_recording)
        controls_layout.addWidget(self.start_record_btn)

        self.stop_record_btn = QPushButton("完成录制")
        self.stop_record_btn.clicked.connect(self.stop_operation_recording)
        self.stop_record_btn.setEnabled(False)
        controls_layout.addWidget(self.stop_record_btn)

        self.clear_record_btn = QPushButton("清空")
        self.clear_record_btn.clicked.connect(self.clear_operation_recording)
        controls_layout.addWidget(self.clear_record_btn)

        layout.addLayout(controls_layout)
        return widget
        
    def create_app_manager_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        install_group = QGroupBox("安装应用")
        install_layout = QHBoxLayout()
        
        self.apk_path = QLineEdit()
        install_layout.addWidget(self.apk_path)
        
        browse_btn = QPushButton("浏览")
        browse_btn.clicked.connect(self.browse_apk)
        install_layout.addWidget(browse_btn)
        
        install_btn = QPushButton("安装")
        install_btn.clicked.connect(self.install_app)
        install_layout.addWidget(install_btn)
        
        install_group.setLayout(install_layout)
        layout.addWidget(install_group)
        
        app_list_group = QGroupBox("已安装应用")
        app_list_layout = QVBoxLayout()
        
        self.refresh_apps_btn = QPushButton("刷新应用列表")
        self.refresh_apps_btn.clicked.connect(self.refresh_apps)
        app_list_layout.addWidget(self.refresh_apps_btn)

        loading_layout = QHBoxLayout()
        self.apps_loading_label = QLabel("正在刷新应用列表...")
        self.apps_loading_label.setStyleSheet("color: gray;")
        self.apps_loading_label.setVisible(False)
        loading_layout.addWidget(self.apps_loading_label)

        self.apps_loading_bar = QProgressBar()
        self.apps_loading_bar.setRange(0, 0)
        self.apps_loading_bar.setTextVisible(False)
        self.apps_loading_bar.setVisible(False)
        loading_layout.addWidget(self.apps_loading_bar)
        app_list_layout.addLayout(loading_layout)
        
        self.app_list = QListWidget()
        app_list_layout.addWidget(self.app_list)
        
        app_buttons_layout = QHBoxLayout()
        
        self.start_app_btn = QPushButton("启动")
        self.start_app_btn.clicked.connect(self.start_app)
        app_buttons_layout.addWidget(self.start_app_btn)
        
        self.stop_app_btn = QPushButton("停止")
        self.stop_app_btn.clicked.connect(self.stop_app)
        app_buttons_layout.addWidget(self.stop_app_btn)
        
        self.uninstall_app_btn = QPushButton("卸载")
        self.uninstall_app_btn.clicked.connect(self.uninstall_app)
        app_buttons_layout.addWidget(self.uninstall_app_btn)
        
        app_list_layout.addLayout(app_buttons_layout)
        
        app_list_group.setLayout(app_list_layout)
        layout.addWidget(app_list_group)
        
        return widget
        
    def create_task_scheduler_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        add_task_group = QGroupBox("添加任务")
        add_task_layout = QFormLayout()

        self.task_name = QLineEdit()
        add_task_layout.addRow("任务名称:", self.task_name)

        task_device_layout = QHBoxLayout()
        self.task_device_combo = QComboBox()
        self.refresh_task_device_options()
        task_device_layout.addWidget(self.task_device_combo)

        refresh_task_devices_btn = QPushButton("刷新")
        refresh_task_devices_btn.clicked.connect(self.refresh_task_device_options)
        task_device_layout.addWidget(refresh_task_devices_btn)
        add_task_layout.addRow("执行设备:", task_device_layout)

        self.task_mode_combo = QComboBox()
        self.task_mode_combo.addItem("普通步骤任务", "normal")
        self.task_mode_combo.addItem("图像匹配触发任务", "image_match")
        self.task_mode_combo.currentIndexChanged.connect(self.on_task_mode_changed)
        add_task_layout.addRow("任务模式:", self.task_mode_combo)

        self.image_match_widget = QWidget()
        image_match_layout = QHBoxLayout(self.image_match_widget)
        image_match_layout.setContentsMargins(0, 0, 0, 0)
        self.sample_status_label = QLabel("未选择样本图")
        image_match_layout.addWidget(self.sample_status_label, 1)
        pick_sample_btn = QPushButton("实时截图框选样本")
        pick_sample_btn.clicked.connect(self.pick_image_sample)
        image_match_layout.addWidget(pick_sample_btn)
        add_task_layout.addRow("目标样本:", self.image_match_widget)

        self.match_threshold = QDoubleSpinBox()
        self.match_threshold.setRange(0.50, 0.99)
        self.match_threshold.setSingleStep(0.01)
        self.match_threshold.setValue(0.88)
        self.match_threshold.setDecimals(2)
        add_task_layout.addRow("匹配阈值:", self.match_threshold)

        self.steps_list = QListWidget()
        self.steps_list.setMaximumHeight(120)
        add_task_layout.addRow("操作步骤:", self.steps_list)

        step_btn_layout = QHBoxLayout()
        add_step_btn = QPushButton("+ 添加步骤")
        add_step_btn.clicked.connect(self.add_step)
        step_btn_layout.addWidget(add_step_btn)

        edit_step_btn = QPushButton("编辑")
        edit_step_btn.clicked.connect(self.edit_step)
        step_btn_layout.addWidget(edit_step_btn)

        remove_step_btn = QPushButton("删除")
        remove_step_btn.clicked.connect(self.remove_step)
        step_btn_layout.addWidget(remove_step_btn)

        move_up_btn = QPushButton("↑")
        move_up_btn.setMaximumWidth(40)
        move_up_btn.clicked.connect(self.move_step_up)
        step_btn_layout.addWidget(move_up_btn)

        move_down_btn = QPushButton("↓")
        move_down_btn.setMaximumWidth(40)
        move_down_btn.clicked.connect(self.move_step_down)
        step_btn_layout.addWidget(move_down_btn)

        add_task_layout.addRow("", step_btn_layout)

        self.schedule_type = QComboBox()
        self.schedule_type.addItem("间隔执行", "interval")
        self.schedule_type.addItem("定时执行", "scheduled")
        self.schedule_type.currentIndexChanged.connect(self.on_schedule_type_changed)
        add_task_layout.addRow("调度类型:", self.schedule_type)

        self.interval_widget = QWidget()
        interval_layout = QHBoxLayout(self.interval_widget)
        self.interval_seconds = QSpinBox()
        self.interval_seconds.setRange(1, 999999)
        self.interval_seconds.setValue(1)
        interval_layout.addWidget(self.interval_seconds)
        self.interval_unit_combo = QComboBox()
        for label, multiplier in INTERVAL_UNITS:
            self.interval_unit_combo.addItem(label, multiplier)
        self.interval_unit_combo.setCurrentText("分")
        interval_layout.addWidget(self.interval_unit_combo)
        add_task_layout.addRow("间隔时间:", self.interval_widget)

        self.scheduled_time_widget = QWidget()
        scheduled_time_layout = QHBoxLayout(self.scheduled_time_widget)
        self.time_edit = QTimeEdit()
        self.time_edit.setDisplayFormat("HH:mm:ss")
        self.time_edit.setTime(QTime.currentTime())
        scheduled_time_layout.addWidget(self.time_edit)
        add_task_layout.addRow("执行时间:", self.scheduled_time_widget)

        self.on_schedule_type_changed(0)
        self.on_task_mode_changed()

        add_task_btn = QPushButton("添加任务")
        add_task_btn.clicked.connect(self.add_task)
        add_task_layout.addRow("", add_task_btn)

        add_task_group.setLayout(add_task_layout)
        layout.addWidget(add_task_group)

        task_list_group = QGroupBox("任务列表")
        task_list_layout = QVBoxLayout()

        self.task_list = QListWidget()
        task_list_layout.addWidget(self.task_list)

        task_buttons_layout = QHBoxLayout()

        execute_btn = QPushButton("执行")
        execute_btn.clicked.connect(self.execute_selected_task)
        task_buttons_layout.addWidget(execute_btn)

        edit_btn = QPushButton("编辑")
        edit_btn.clicked.connect(self.edit_selected_task)
        task_buttons_layout.addWidget(edit_btn)

        copy_btn = QPushButton("复制")
        copy_btn.clicked.connect(self.copy_selected_task)
        task_buttons_layout.addWidget(copy_btn)

        remove_btn = QPushButton("删除")
        remove_btn.clicked.connect(self.remove_selected_task)
        task_buttons_layout.addWidget(remove_btn)

        toggle_btn = QPushButton("启用/禁用")
        toggle_btn.clicked.connect(self.toggle_selected_task)
        task_buttons_layout.addWidget(toggle_btn)

        task_list_layout.addLayout(task_buttons_layout)

        task_list_group.setLayout(task_list_layout)
        layout.addWidget(task_list_group)

        self.task_manager.task_executed.connect(self.on_task_executed)
        self.task_manager.task_log.connect(self.on_task_log)
        self.refresh_task_list()
        self.task_steps = [self._default_tap_step()]
        self.match_config = {}
        self.refresh_step_list()

        return widget

    def _step_summary(self, step: dict) -> str:
        action = step["action"]
        p = step["params"]
        name = action_names.get(action, action)
        if action == TaskAction.TAP:
            return f"{name} ({p.get('x', 0)}, {p.get('y', 0)})"
        elif action == TaskAction.SWIPE:
            return f"{name} ({p.get('x1', 0)},{p.get('y1', 0)})->({p.get('x2', 0)},{p.get('y2', 0)})"
        elif action == TaskAction.INPUT_TEXT:
            return f"{name}: {p.get('text', '')}"
        elif action == TaskAction.INPUT_KEY:
            kc = p.get("keycode", 0)
            kn = KEY_MAP_REVERSE.get(kc, f"键码{kc}")
            return f"{name}: {kn}"
        elif action == TaskAction.SCREENSHOT:
            return f"{name}: {p.get('output_path', '')}"
        elif action in (TaskAction.START_APP, TaskAction.STOP_APP):
            return f"{name}: {p.get('package', '')}"
        return name

    def refresh_step_list(self):
        self.steps_list.clear()
        for i, step in enumerate(self.task_steps):
            text = f"#{i+1} {self._step_summary(step)}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, i)
            self.steps_list.addItem(item)

    def _get_step_app_options(self):
        options = []
        seen = set()
        if hasattr(self, "app_list"):
            for index in range(self.app_list.count()):
                item = self.app_list.item(index)
                package = item.data(Qt.ItemDataRole.UserRole)
                if package and package not in seen:
                    seen.add(package)
                    options.append((item.text(), package))

        if options:
            return options

        target_scope, target_serial = self.task_device_combo.currentData()
        serial = target_serial if target_scope == "single" else self.current_serial
        if not serial:
            return []

        for package in self.adb_manager.list_packages(serial, third_party_only=True):
            if package not in seen:
                seen.add(package)
                options.append((package, package))
        return options

    def _default_tap_step(self):
        return {"action": DEFAULT_TAP_STEP["action"], "params": dict(DEFAULT_TAP_STEP["params"])}

    def _interval_milliseconds_from_inputs(self):
        return self.interval_seconds.value() * self.interval_unit_combo.currentData()

    def _format_interval(self, milliseconds: int):
        milliseconds = int(milliseconds or 0)
        for label, multiplier in INTERVAL_UNITS:
            if milliseconds >= multiplier and milliseconds % multiplier == 0:
                return f"{milliseconds // multiplier}{label}"
        return f"{milliseconds}毫秒"

    def on_task_mode_changed(self):
        is_image_match = self.task_mode_combo.currentData() == "image_match"
        self.image_match_widget.setVisible(is_image_match)
        self.match_threshold.setVisible(is_image_match)

    def pick_image_sample(self):
        target_scope, target_serial = self.task_device_combo.currentData()
        serial = target_serial
        if target_scope == "all":
            serial = self.current_serial
        if not serial:
            self._log("选择目标样本", "失败 - 请先选择一个在线设备")
            return

        dialog = ImageSamplePickerDialog(self.adb_manager, serial, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.match_config = {
                "sample_path": dialog.sample_path,
                "region": {
                    "x": round(dialog.region.x()),
                    "y": round(dialog.region.y()),
                    "width": round(dialog.region.width()),
                    "height": round(dialog.region.height()),
                },
            }
            self.sample_status_label.setText(os.path.basename(dialog.sample_path))
            self._log("选择目标样本", f"已保存 - {dialog.sample_path}")

    def add_step(self):
        default_step = self._default_tap_step()
        dialog = StepEditDialog(default_step, len(self.task_steps), self, self._get_step_app_options())
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.task_steps.append(default_step)
            self.refresh_step_list()

    def edit_step(self):
        item = self.steps_list.currentItem()
        if not item:
            return
        idx = item.data(Qt.ItemDataRole.UserRole)
        step = self.task_steps[idx]
        dialog = StepEditDialog(step, idx, self, self._get_step_app_options())
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.task_steps[idx] = step
            self.refresh_step_list()

    def remove_step(self):
        item = self.steps_list.currentItem()
        if not item:
            return
        idx = item.data(Qt.ItemDataRole.UserRole)
        if len(self.task_steps) > 1:
            self.task_steps.pop(idx)
        else:
            self.task_steps = [self._default_tap_step()]
        self.refresh_step_list()

    def move_step_up(self):
        item = self.steps_list.currentItem()
        if not item:
            return
        idx = item.data(Qt.ItemDataRole.UserRole)
        if idx <= 0:
            return
        self.task_steps[idx], self.task_steps[idx - 1] = self.task_steps[idx - 1], self.task_steps[idx]
        self.refresh_step_list()
        self.steps_list.setCurrentRow(idx - 1)

    def move_step_down(self):
        item = self.steps_list.currentItem()
        if not item:
            return
        idx = item.data(Qt.ItemDataRole.UserRole)
        if idx >= len(self.task_steps) - 1:
            return
        self.task_steps[idx], self.task_steps[idx + 1] = self.task_steps[idx + 1], self.task_steps[idx]
        self.refresh_step_list()
        self.steps_list.setCurrentRow(idx + 1)

    def on_schedule_type_changed(self, index):
        schedule_type = self.schedule_type.currentData()
        self.interval_widget.setVisible(schedule_type == "interval")
        self.scheduled_time_widget.setVisible(schedule_type == "scheduled")
            
    def set_current_device(self, serial: str):
        self.current_serial = serial or None
        if self.app_refresh_worker and self.app_refresh_worker.isRunning():
            self.app_list.clear()
            item = QListWidgetItem("设备已切换，请重新刷新应用列表")
            item.setForeground(Qt.GlobalColor.gray)
            self.app_list.addItem(item)
        if hasattr(self, "task_device_combo"):
            self.refresh_task_device_options()
        if hasattr(self, "record_device_combo") and not self.is_recording():
            self.refresh_record_device_options()

    def is_recording(self):
        return self.recording_worker is not None and self.recording_worker.isRunning()

    def refresh_task_device_options(self):
        current_value = self.task_device_combo.currentData() if hasattr(self, "task_device_combo") else None
        self.task_device_combo.clear()
        self.task_device_combo.addItem("所有在线安卓设备", ("all", "__all__"))

        seen_serials = set()
        for device in self.adb_manager.list_devices():
            if device.state != "device":
                continue
            if device.serial in seen_serials:
                continue
            seen_serials.add(device.serial)
            text = device.serial
            if device.name:
                text += f" - {device.name}"
            self.task_device_combo.addItem(text, ("single", device.serial))

        if current_value:
            index = self._find_task_device_index(current_value)
            if index >= 0:
                self.task_device_combo.setCurrentIndex(index)
                return

        if self.current_serial:
            index = self._find_task_device_index(("single", self.current_serial))
            if index >= 0:
                self.task_device_combo.setCurrentIndex(index)

    def _find_task_device_index(self, target_value):
        for index in range(self.task_device_combo.count()):
            if self.task_device_combo.itemData(index) == target_value:
                return index
        return -1

    def refresh_record_device_options(self):
        if not hasattr(self, "record_device_combo"):
            return

        current_serial = self.record_device_combo.currentData()
        self.record_device_combo.clear()
        seen_serials = set()
        for device in self.adb_manager.list_devices():
            if device.state != "device":
                continue
            if device.serial in seen_serials:
                continue
            seen_serials.add(device.serial)
            text = device.serial
            if device.name:
                text += f" - {device.name}"
            self.record_device_combo.addItem(text, device.serial)

        if current_serial:
            for index in range(self.record_device_combo.count()):
                if self.record_device_combo.itemData(index) == current_serial:
                    self.record_device_combo.setCurrentIndex(index)
                    return

        if self.current_serial:
            for index in range(self.record_device_combo.count()):
                if self.record_device_combo.itemData(index) == self.current_serial:
                    self.record_device_combo.setCurrentIndex(index)
                    return
        
    def check_device_selected(self):
        if not self.current_serial:
            self._log("检查设备", "失败 - 未选择设备")
            return False
        return True
        
    def do_tap(self):
        if not self.check_device_selected():
            return
        result = self.adb_manager.tap(
            self.tap_x.value(), self.tap_y.value(), self.current_serial
        )
        if result.returncode == 0:
            self._log(f"点击屏幕 ({self.tap_x.value()}, {self.tap_y.value()})", "成功")
        else:
            self._log(f"点击屏幕 ({self.tap_x.value()}, {self.tap_y.value()})", f"失败 - {result.stderr.strip()}")
            
    def do_swipe(self):
        if not self.check_device_selected():
            return
        result = self.adb_manager.swipe(
            self.swipe_x1.value(), self.swipe_y1.value(),
            self.swipe_x2.value(), self.swipe_y2.value(),
            self.swipe_duration.value(), self.current_serial
        )
        if result.returncode == 0:
            self._log(f"滑动屏幕 ({self.swipe_x1.value()},{self.swipe_y1.value()}) -> ({self.swipe_x2.value()},{self.swipe_y2.value()})", "成功")
        else:
            self._log(f"滑动屏幕 ({self.swipe_x1.value()},{self.swipe_y1.value()}) -> ({self.swipe_x2.value()},{self.swipe_y2.value()})", f"失败 - {result.stderr.strip()}")
            
    def do_screenshot(self):
        if not self.check_device_selected():
            return
        output_path = self.screenshot_path.text()
        success = self.adb_manager.take_screenshot(self.current_serial, output_path)
        if success:
            self._log(f"截屏保存到: {output_path}", "成功")
        else:
            self._log(f"截屏保存到: {output_path}", "失败")
            
    def open_coord_picker(self):
        if not self.check_device_selected():
            return
        dialog = CoordinatePickerDialog(self.adb_manager, self.current_serial, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result_coords:
            if dialog.result_type == "tap":
                x, y = dialog.result_coords
                self.tap_x.setValue(x)
                self.tap_y.setValue(y)
                self._log(f"坐标拾取: 点击 ({x}, {y})", "已填入点击框")
            elif dialog.result_type == "swipe":
                x1, y1, x2, y2 = dialog.result_coords
                self.swipe_x1.setValue(x1)
                self.swipe_y1.setValue(y1)
                self.swipe_x2.setValue(x2)
                self.swipe_y2.setValue(y2)
                self._log(f"坐标拾取: 滑动 ({x1},{y1}) -> ({x2},{y2})", "已填入滑动框")

    def do_input_key(self, keycode: int):
        if not self.check_device_selected():
            return
        result = self.adb_manager.input_key(keycode, self.current_serial)
        key_names = {4: "返回", 3: "主页", 82: "菜单", 24: "音量+", 25: "音量-", 26: "电源"}
        key_name = key_names.get(keycode, f"键码{keycode}")
        if result.returncode == 0:
            self._log(f"按键: {key_name}", "成功")
        else:
            self._log(f"按键: {key_name}", f"失败 - {result.stderr.strip()}")
            
    def browse_apk(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择APK文件", "", "APK Files (*.apk)"
        )
        if file_path:
            self.apk_path.setText(file_path)
            
    def install_app(self):
        if not self.check_device_selected():
            return
        apk_path = self.apk_path.text()
        if not apk_path:
            self._log("安装应用", "失败 - 未选择APK文件")
            return
            
        self._log(f"安装应用: {apk_path}", "开始安装，请稍候...")
        result = self.adb_manager.install_app(apk_path, self.current_serial)
        if result.returncode == 0:
            self._log(f"安装应用: {apk_path}", "成功")
            self.refresh_apps()
        else:
            self._log(f"安装应用: {apk_path}", f"失败 - {result.stderr.strip()}")
            
    def refresh_apps(self):
        if not self.check_device_selected():
            return
        if self.app_refresh_worker and self.app_refresh_worker.isRunning():
            self._log("刷新应用列表", "正在刷新中，请稍候...")
            return

        self.app_list.clear()
        self.app_resolved_count = 0
        loading_item = QListWidgetItem("正在加载应用列表...")
        loading_item.setForeground(Qt.GlobalColor.gray)
        self.app_list.addItem(loading_item)
        self.set_apps_loading(True)
        self._log("刷新应用列表", "正在获取应用列表和名称...")

        self.app_refresh_worker = AppRefreshWorker(self.adb_manager, self.current_serial)
        self.app_refresh_worker.apps_loaded.connect(self.on_apps_loaded)
        self.app_refresh_worker.app_resolved.connect(self.on_app_resolved)
        self.app_refresh_worker.load_failed.connect(self.on_apps_load_failed)
        self.app_refresh_worker.finished.connect(self.on_apps_refresh_finished)
        self.app_refresh_worker.start()

    def set_apps_loading(self, loading: bool):
        self.refresh_apps_btn.setEnabled(not loading)
        self.refresh_apps_btn.setText("刷新中..." if loading else "刷新应用列表")
        self.start_app_btn.setEnabled(not loading)
        self.stop_app_btn.setEnabled(not loading)
        self.uninstall_app_btn.setEnabled(not loading)
        self.apps_loading_label.setVisible(loading)
        self.apps_loading_bar.setVisible(loading)

    def on_apps_loaded(self, serial: str, items: list, package_count: int, named: int, precise_named: int):
        if serial != self.current_serial:
            self._log("刷新应用列表", f"已忽略旧设备结果: {serial}")
            return

        self.app_list.clear()
        for display, package in items:
            item = QListWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, package)
            self.app_list.addItem(item)
        self._log("刷新应用列表", f"完成: {package_count} 个应用, {named} 个已识别名称，快速模式")

    def on_app_resolved(self, serial: str, package: str, label: str):
        if serial != self.current_serial:
            return

        display = f"{label} {package}"
        for index in range(self.app_list.count()):
            item = self.app_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == package:
                item.setText(display)
                self.app_resolved_count += 1
                if self.app_resolved_count == 1 or self.app_resolved_count % 10 == 0:
                    self._log("刷新应用列表", f"已补充非系统应用中文名: {self.app_resolved_count} 个")
                return

    def on_apps_load_failed(self, serial: str, error: str):
        if serial != self.current_serial:
            self._log("刷新应用列表", f"已忽略旧设备错误: {serial}")
            return

        self.app_list.clear()
        item = QListWidgetItem("应用列表加载失败")
        item.setForeground(Qt.GlobalColor.red)
        self.app_list.addItem(item)
        self._log("刷新应用列表", f"失败 - {error}")

    def on_apps_refresh_finished(self):
        self.set_apps_loading(False)
        if self.app_refresh_worker:
            self.app_refresh_worker.deleteLater()
            self.app_refresh_worker = None

    def _looks_like_fallback_label(self, label: str, package: str):
        normalized_label = label.strip().lower()
        package_parts = [part.lower() for part in package.split(".") if part]
        return normalized_label in package_parts

    def start_operation_recording(self):
        if self.is_recording():
            self._log("操作录制", "正在录制中，请先完成当前录制")
            return

        serial = self.record_device_combo.currentData()
        if not serial:
            self._log("操作录制", "失败 - 请选择录制设备")
            QMessageBox.warning(self, "提示", "请先选择录制设备。")
            return
        if not self.adb_manager.is_android_device(serial):
            self._log("操作录制", f"失败 - 设备不可用: {serial}")
            QMessageBox.warning(self, "设备不可用", f"{serial} 不是可用的 Android 设备，或尚未授权调试。")
            return

        self.recording_serial = serial
        self.recording_steps = []
        self.record_steps_list.clear()
        self.record_scene.clear()
        self.record_status_label.setText(f"正在录制: {serial}")
        self.record_device_combo.setEnabled(False)
        self.start_record_btn.setEnabled(False)
        self.stop_record_btn.setEnabled(True)
        self.clear_record_btn.setEnabled(False)

        self.recording_worker = RecordingStreamWorker(self.adb_manager, serial)
        self.recording_worker.frame_ready.connect(self.on_record_frame_ready)
        self.recording_worker.stream_failed.connect(self.on_record_stream_failed)
        self.recording_worker.start()
        self._log("操作录制", f"开始录制: {serial}")

    def stop_operation_recording(self):
        if not self.is_recording():
            return

        self.recording_worker.stop()
        self.recording_worker.wait(2000)
        self.recording_worker.deleteLater()
        self.recording_worker = None

        self.record_device_combo.setEnabled(True)
        self.start_record_btn.setEnabled(True)
        self.stop_record_btn.setEnabled(False)
        self.clear_record_btn.setEnabled(True)

        if not self.recording_steps:
            self.record_status_label.setText("录制完成，但没有记录到操作")
            self._log("操作录制", "完成 - 未记录操作")
            return

        task_name, ok = self._ask_record_task_name()
        if not ok:
            self.record_status_label.setText(f"录制完成，已保留 {len(self.recording_steps)} 个操作")
            self._log("操作录制", "完成 - 未保存任务")
            return

        self.save_recording_as_task(task_name)

    def _ask_record_task_name(self):
        from PyQt6.QtWidgets import QInputDialog

        default_name = f"录制任务 {datetime.now().strftime('%H%M%S')}"
        return QInputDialog.getText(self, "保存录制任务", "任务名称:", text=default_name)

    def clear_operation_recording(self):
        if self.is_recording():
            QMessageBox.warning(self, "提示", "录制中不能清空，请先完成录制。")
            return

        self.recording_steps = []
        self.record_steps_list.clear()
        self.record_status_label.setText("已清空录制操作")

    def on_record_frame_ready(self, frame_data: bytes, width: int, height: int):
        if not self.is_recording():
            return

        pixmap = QPixmap()
        pixmap.loadFromData(frame_data)
        if pixmap.isNull():
            return

        self.recording_device_w = width
        self.recording_device_h = height
        self.record_scene.clear()
        self.record_scene.addItem(QGraphicsPixmapItem(pixmap))
        self.record_scene.setSceneRect(QRectF(0, 0, width, height))
        self.record_view.fitInView(QRectF(0, 0, width, height), Qt.AspectRatioMode.KeepAspectRatio)
        self.draw_record_markers()

    def on_record_stream_failed(self, error: str):
        self.record_status_label.setText(f"投屏失败: {error}")
        self._log("操作录制投屏", f"失败 - {error}")

    def on_record_view_clicked(self, x: int, y: int):
        if not self.is_recording() or not self.recording_serial:
            return
        if self.recording_device_w <= 0 or self.recording_device_h <= 0:
            return

        x = max(0, min(x, self.recording_device_w - 1))
        y = max(0, min(y, self.recording_device_h - 1))
        step = {"action": TaskAction.TAP, "params": {"x": x, "y": y}}
        self.recording_steps.append(step)

        item = QListWidgetItem(f"#{len(self.recording_steps)} 点击 ({x}, {y})")
        item.setData(Qt.ItemDataRole.UserRole, step)
        self.record_steps_list.addItem(item)
        self.record_steps_list.scrollToBottom()
        self.record_status_label.setText(f"已记录 {len(self.recording_steps)} 个操作，最后点击: ({x}, {y})")
        self.draw_record_markers()

        result = self.adb_manager.tap(x, y, self.recording_serial)
        if result.returncode != 0:
            self._log("操作录制点击", f"发送失败 - {result.stderr.strip()}")

    def draw_record_markers(self):
        for item in list(self.record_scene.items()):
            if item.data(0) == "record_marker":
                self.record_scene.removeItem(item)

        if not self.recording_steps:
            return

        last_step = self.recording_steps[-1]
        params = last_step["params"]
        marker = self.record_scene.addEllipse(
            params["x"] - 12,
            params["y"] - 12,
            24,
            24,
            QPen(QColor(255, 0, 0), 3)
        )
        marker.setData(0, "record_marker")

    def save_recording_as_task(self, task_name: str):
        task_name = task_name.strip()
        if not task_name:
            self._log("保存录制任务", "失败 - 任务名称为空")
            return

        task = ScheduledTask(
            task_id=str(uuid.uuid4()),
            name=task_name,
            action=self.recording_steps[0]["action"],
            serial=self.recording_serial,
            target_scope="single",
            params=self.recording_steps[0]["params"],
            steps=[{"action": step["action"], "params": dict(step["params"])} for step in self.recording_steps],
            schedule_type="interval",
            interval_seconds=60,
            interval_milliseconds=60000,
            enabled=False
        )
        self.task_manager.add_task(task)
        self.refresh_task_list()
        self.record_status_label.setText(f"已保存任务: {task_name} ({len(self.recording_steps)}步)")
        self._log("保存录制任务", f"成功 - {task_name}，默认禁用")

    def closeEvent(self, event):
        if self.recording_worker and self.recording_worker.isRunning():
            self.recording_worker.stop()
            self.recording_worker.wait(2000)
        super().closeEvent(event)
            
    def start_app(self):
        if not self.check_device_selected():
            return
        item = self.app_list.currentItem()
        if not item:
            self._log("启动应用", "失败 - 未选择应用")
            return

        pkg = item.data(Qt.ItemDataRole.UserRole) or item.text()
        result = self.adb_manager.start_app(pkg, self.current_serial)
        if result.returncode == 0:
            self._log(f"启动应用: {item.text()}", "成功")
        else:
            self._log(f"启动应用: {item.text()}", f"失败 - {result.stderr.strip()}")
            
    def stop_app(self):
        if not self.check_device_selected():
            return
        item = self.app_list.currentItem()
        if not item:
            self._log("停止应用", "失败 - 未选择应用")
            return

        pkg = item.data(Qt.ItemDataRole.UserRole) or item.text()
        result = self.adb_manager.stop_app(pkg, self.current_serial)
        if result.returncode == 0:
            self._log(f"停止应用: {item.text()}", "成功")
        else:
            self._log(f"停止应用: {item.text()}", f"失败 - {result.stderr.strip()}")
            
    def uninstall_app(self):
        if not self.check_device_selected():
            return
        item = self.app_list.currentItem()
        if not item:
            self._log("卸载应用", "失败 - 未选择应用")
            return

        pkg = item.data(Qt.ItemDataRole.UserRole) or item.text()
        reply = QMessageBox.question(
            self, "确认", f"确定要卸载 {item.text()} 吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            result = self.adb_manager.uninstall_app(pkg, self.current_serial)
            if result.returncode == 0:
                self._log(f"卸载应用: {item.text()}", "成功")
                self.refresh_apps()
            else:
                self._log(f"卸载应用: {item.text()}", f"失败 - {result.stderr.strip()}")
                
    def add_task(self):
        name = self.task_name.text()
        if not name:
            self._log("添加任务", "失败 - 请输入任务名称")
            return

        target_scope, target_serial = self.task_device_combo.currentData()
        if target_scope == "single" and not target_serial:
            self._log("添加任务", "失败 - 请选择执行设备")
            return

        action = self.task_steps[0]["action"]
        params = self.task_steps[0]["params"]
        schedule_type = self.schedule_type.currentData()
        task_mode = self.task_mode_combo.currentData()

        match_config = {}
        if task_mode == "image_match":
            if not self.match_config.get("sample_path"):
                self._log("添加图像匹配任务", "失败 - 请先实时截图并框选样本图")
                return
            match_config = dict(self.match_config)
            match_config["threshold"] = self.match_threshold.value()

        schedule_time = None
        if schedule_type == "scheduled":
            current_time = self.time_edit.time()
            now = datetime.now()
            schedule_time = now.replace(
                hour=current_time.hour(),
                minute=current_time.minute(),
                second=current_time.second(),
                microsecond=0
            ).isoformat()

        task = ScheduledTask(
            task_id=str(uuid.uuid4()),
            name=name,
            action=action,
            serial=target_serial,
            target_scope=target_scope,
            params=params,
            steps=self.task_steps[:],
            task_mode=task_mode,
            match_config=match_config,
            schedule_type=schedule_type,
            schedule_time=schedule_time,
            interval_seconds=max(1, round(self._interval_milliseconds_from_inputs() / 1000)),
            interval_milliseconds=self._interval_milliseconds_from_inputs(),
        )

        self.task_manager.add_task(task)
        self.refresh_task_list()
        self._log(f"添加任务: {name} ({len(self.task_steps)}步)", "成功")

        self.task_name.clear()
        self.task_steps = [self._default_tap_step()]
        self.task_mode_combo.setCurrentIndex(0)
        self.match_config = {}
        self.sample_status_label.setText("未选择样本图")
        self.refresh_step_list()
        
    def refresh_task_list(self):
        self.task_list.clear()
        tasks = self.task_manager.get_tasks()
        
        for task in tasks:
            status = "✓" if task.enabled else "✗"
            step_count = len(task.steps)
            mode_name = "图像匹配" if getattr(task, "task_mode", "normal") == "image_match" else action_names.get(task.action, task.action)
            item_text = f"{status} {task.name} [{mode_name}] ({step_count}步)"
            target_text = "所有设备" if task.target_scope == "all" or task.serial == "__all__" else task.serial
            item_text += f" - 设备: {target_text}"
            
            if task.schedule_type == "scheduled" and task.schedule_time:
                try:
                    from datetime import datetime
                    sched_time = datetime.fromisoformat(task.schedule_time)
                    item_text += f" - 定时: {sched_time.strftime('%H:%M:%S')}"
                except:
                    pass
            elif task.schedule_type == "interval":
                item_text += f" - 间隔: {self._format_interval(task.interval_milliseconds)}"
                
            if task.last_run:
                item_text += f" - 最后运行: {task.last_run}"
                
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, task.task_id)
            
            if task.enabled:
                item.setForeground(Qt.GlobalColor.darkGreen)
            else:
                item.setForeground(Qt.GlobalColor.gray)
                
            self.task_list.addItem(item)
            
    def execute_selected_task(self):
        item = self.task_list.currentItem()
        if not item:
            self._log("执行任务", "失败 - 未选择任务")
            return
            
        task_id = item.data(Qt.ItemDataRole.UserRole)
        self.task_manager.execute_task(task_id)
        
    def edit_selected_task(self):
        item = self.task_list.currentItem()
        if not item:
            self._log("编辑任务", "失败 - 未选择任务")
            return

        task_id = item.data(Qt.ItemDataRole.UserRole)
        task = self.task_manager.get_task(task_id)
        if not task:
            return

        dialog = TaskEditDialog(task, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.task_manager.update_task(task)
            self.refresh_task_list()
            self._log(f"编辑任务: {task.name}", "成功")

    def copy_selected_task(self):
        item = self.task_list.currentItem()
        if not item:
            self._log("复制任务", "失败 - 未选择任务")
            return

        task_id = item.data(Qt.ItemDataRole.UserRole)
        task = self.task_manager.get_task(task_id)
        if not task:
            self._log("复制任务", "失败 - 任务不存在")
            return

        copied_task = ScheduledTask(
            task_id=str(uuid.uuid4()),
            name=f"{task.name} - 副本",
            action=task.action,
            serial=task.serial,
            target_scope=getattr(task, "target_scope", "single"),
            params=dict(task.params),
            steps=[{"action": step["action"], "params": dict(step["params"])} for step in task.steps],
            task_mode=getattr(task, "task_mode", "normal"),
            match_config=dict(getattr(task, "match_config", {}) or {}),
            schedule_type=task.schedule_type,
            schedule_time=task.schedule_time,
            interval_seconds=task.interval_seconds,
            interval_milliseconds=getattr(task, "interval_milliseconds", task.interval_seconds * 1000),
            enabled=False
        )

        self.task_manager.add_task(copied_task)
        self.refresh_task_list()
        self._log(f"复制任务: {task.name}", f"成功 - 已创建 {copied_task.name}，默认禁用")

    def remove_selected_task(self):
        item = self.task_list.currentItem()
        if not item:
            self._log("删除任务", "失败 - 未选择任务")
            return
            
        reply = QMessageBox.question(
            self, "确认", "确定要删除这个任务吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            task_id = item.data(Qt.ItemDataRole.UserRole)
            self.task_manager.remove_task(task_id)
            self.refresh_task_list()
            self._log("删除任务", "成功")
            
    def toggle_selected_task(self):
        item = self.task_list.currentItem()
        if not item:
            self._log("切换任务状态", "失败 - 未选择任务")
            return
            
        task_id = item.data(Qt.ItemDataRole.UserRole)
        self.task_manager.toggle_task(task_id)
        self.refresh_task_list()
        
    def on_task_executed(self, task_id, task_name, success, success_serials=None, failed_serials=None):
        status = "成功" if success else "失败"
        success_serials = success_serials or []
        failed_serials = failed_serials or []
        detail = status
        if success_serials or failed_serials:
            detail += f" - 成功设备: {len(success_serials)}, 失败设备: {len(failed_serials)}"
            if failed_serials:
                detail += f" ({', '.join(failed_serials)})"
        task = self.task_manager.get_task(task_id)
        if task and getattr(task, "task_mode", "normal") == "image_match" and success and success_serials and not failed_serials:
            detail = f"扫描完成 - 已检查设备: {len(success_serials)}"
        self._log(f"定时任务: {task_name}", detail)

    def on_task_log(self, task_name: str, message: str):
        self._log(f"定时任务: {task_name}", message)
