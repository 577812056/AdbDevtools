from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QLineEdit,
                             QComboBox, QSpinBox, QTimeEdit, QWidget,
                             QDialogButtonBox, QMessageBox, QListWidget,
                             QListWidgetItem, QHBoxLayout, QPushButton)
from PyQt6.QtCore import Qt, QTime
from tasks.task_manager import ScheduledTask, TaskAction, action_names, KEY_MAP, KEY_MAP_REVERSE
from ui.step_edit_dialog import StepEditDialog
from datetime import datetime


class TaskEditDialog(QDialog):
    def __init__(self, task: ScheduledTask, parent=None):
        super().__init__(parent)
        self.task = task
        self.steps = [dict(s) for s in task.steps]
        self.setWindowTitle("编辑任务")
        self.setMinimumWidth(450)
        self.init_ui()

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

    def init_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.name_edit = QLineEdit(self.task.name)
        form.addRow("任务名称:", self.name_edit)

        device_layout = QHBoxLayout()
        self.device_combo = QComboBox()
        self.refresh_device_options()
        device_layout.addWidget(self.device_combo)

        refresh_devices_btn = QPushButton("刷新")
        refresh_devices_btn.clicked.connect(self.refresh_device_options)
        device_layout.addWidget(refresh_devices_btn)
        form.addRow("执行设备:", device_layout)

        self.steps_list = QListWidget()
        self.steps_list.setMaximumHeight(150)
        form.addRow("操作步骤:", self.steps_list)

        step_btn_layout = QHBoxLayout()
        add_btn = QPushButton("+ 添加步骤")
        add_btn.clicked.connect(self.add_step)
        step_btn_layout.addWidget(add_btn)

        edit_btn = QPushButton("编辑")
        edit_btn.clicked.connect(self.edit_step)
        step_btn_layout.addWidget(edit_btn)

        remove_btn = QPushButton("删除")
        remove_btn.clicked.connect(self.remove_step)
        step_btn_layout.addWidget(remove_btn)

        up_btn = QPushButton("↑")
        up_btn.setMaximumWidth(40)
        up_btn.clicked.connect(self.move_up)
        step_btn_layout.addWidget(up_btn)

        down_btn = QPushButton("↓")
        down_btn.setMaximumWidth(40)
        down_btn.clicked.connect(self.move_down)
        step_btn_layout.addWidget(down_btn)

        form.addRow("", step_btn_layout)

        self.schedule_combo = QComboBox()
        self.schedule_combo.addItem("间隔执行", "interval")
        self.schedule_combo.addItem("定时执行", "scheduled")
        idx = self.schedule_combo.findData(self.task.schedule_type)
        if idx >= 0:
            self.schedule_combo.setCurrentIndex(idx)
        self.schedule_combo.currentIndexChanged.connect(self.on_schedule_changed)
        form.addRow("调度类型:", self.schedule_combo)

        self.interval_widget = QWidget()
        interval_layout = QVBoxLayout(self.interval_widget)
        interval_layout.setContentsMargins(0, 0, 0, 0)
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 86400)
        self.interval_spin.setValue(self.task.interval_seconds or 60)
        self.interval_spin.setSuffix(" 秒")
        interval_layout.addWidget(self.interval_spin)
        form.addRow("间隔时间:", self.interval_widget)

        self.time_widget = QWidget()
        time_layout = QVBoxLayout(self.time_widget)
        time_layout.setContentsMargins(0, 0, 0, 0)
        self.time_edit = QTimeEdit()
        self.time_edit.setDisplayFormat("HH:mm:ss")
        if self.task.schedule_time:
            try:
                t = datetime.fromisoformat(self.task.schedule_time)
                self.time_edit.setTime(QTime(t.hour, t.minute, t.second))
            except:
                self.time_edit.setTime(QTime.currentTime())
        else:
            self.time_edit.setTime(QTime.currentTime())
        time_layout.addWidget(self.time_edit)
        form.addRow("执行时间:", self.time_widget)

        layout.addLayout(form)
        self.on_schedule_changed()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.refresh_steps()

    def refresh_steps(self):
        self.steps_list.clear()
        for i, step in enumerate(self.steps):
            text = f"#{i+1} {self._step_summary(step)}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, i)
            self.steps_list.addItem(item)

    def refresh_device_options(self):
        current_value = self.device_combo.currentData() if self.device_combo.count() else None
        self.device_combo.clear()
        self.device_combo.addItem("所有在线安卓设备", ("all", "__all__"))

        parent = self.parent()
        adb_manager = getattr(parent, "adb_manager", None)
        seen_serials = set()
        if adb_manager:
            for device in adb_manager.list_devices():
                if device.state != "device":
                    continue
                if device.serial in seen_serials:
                    continue
                seen_serials.add(device.serial)
                text = device.serial
                if device.name:
                    text += f" - {device.name}"
                self.device_combo.addItem(text, ("single", device.serial))

        current_scope = getattr(self.task, "target_scope", "single")
        current_serial = self.task.serial or ""
        if current_scope == "all" or current_serial == "__all__":
            self.device_combo.setCurrentIndex(0)
            return

        target_value = current_value if current_value and current_value[1] == current_serial else ("single", current_serial)
        index = self._find_device_index(target_value)
        if index >= 0:
            self.device_combo.setCurrentIndex(index)
        elif current_serial:
            self.device_combo.addItem(f"{current_serial} (未连接)", ("single", current_serial))
            self.device_combo.setCurrentIndex(self.device_combo.count() - 1)

    def _find_device_index(self, target_value):
        for index in range(self.device_combo.count()):
            if self.device_combo.itemData(index) == target_value:
                return index
        return -1

    def add_step(self):
        default = {"action": TaskAction.TAP, "params": {"x": 540, "y": 960}}
        d = StepEditDialog(default, len(self.steps), self)
        if d.exec() == QDialog.DialogCode.Accepted:
            self.steps.append(default)
            self.refresh_steps()

    def edit_step(self):
        item = self.steps_list.currentItem()
        if not item:
            return
        idx = item.data(Qt.ItemDataRole.UserRole)
        step = self.steps[idx]
        d = StepEditDialog(step, idx, self)
        if d.exec() == QDialog.DialogCode.Accepted:
            self.steps[idx] = step
            self.refresh_steps()

    def remove_step(self):
        item = self.steps_list.currentItem()
        if not item:
            return
        idx = item.data(Qt.ItemDataRole.UserRole)
        if len(self.steps) > 1:
            self.steps.pop(idx)
        else:
            self.steps = [{"action": TaskAction.TAP, "params": {"x": 540, "y": 960}}]
        self.refresh_steps()

    def move_up(self):
        item = self.steps_list.currentItem()
        if not item:
            return
        idx = item.data(Qt.ItemDataRole.UserRole)
        if idx <= 0:
            return
        self.steps[idx], self.steps[idx - 1] = self.steps[idx - 1], self.steps[idx]
        self.refresh_steps()
        self.steps_list.setCurrentRow(idx - 1)

    def move_down(self):
        item = self.steps_list.currentItem()
        if not item:
            return
        idx = item.data(Qt.ItemDataRole.UserRole)
        if idx >= len(self.steps) - 1:
            return
        self.steps[idx], self.steps[idx + 1] = self.steps[idx + 1], self.steps[idx]
        self.refresh_steps()
        self.steps_list.setCurrentRow(idx + 1)

    def on_schedule_changed(self):
        typ = self.schedule_combo.currentData()
        self.interval_widget.setVisible(typ == "interval")
        self.time_widget.setVisible(typ == "scheduled")

    def on_accept(self):
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "警告", "请输入任务名称")
            return

        self.task.name = name
        self.task.action = self.steps[0]["action"]
        self.task.params = self.steps[0]["params"]
        self.task.steps = [dict(s) for s in self.steps]
        target_scope, target_serial = self.device_combo.currentData()
        self.task.target_scope = target_scope
        self.task.serial = target_serial
        self.task.schedule_type = self.schedule_combo.currentData()
        self.task.interval_seconds = self.interval_spin.value()

        if self.task.schedule_type == "scheduled":
            t = self.time_edit.time()
            now = datetime.now()
            self.task.schedule_time = now.replace(
                hour=t.hour(), minute=t.minute(), second=t.second(), microsecond=0
            ).isoformat()
        else:
            self.task.schedule_time = None

        self.accept()
