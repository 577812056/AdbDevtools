from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
                             QComboBox, QSpinBox, QLineEdit, QWidget,
                             QDialogButtonBox)
from PyQt6.QtCore import Qt
from tasks.task_manager import TaskAction, KEY_MAP, KEY_MAP_REVERSE


class StepEditDialog(QDialog):
    def __init__(self, step: dict, step_index: int, parent=None, app_options=None):
        super().__init__(parent)
        self.step = step
        self.step_index = step_index
        self.app_options = app_options or []
        self.setWindowTitle(f"编辑步骤 #{step_index + 1}")
        self.setMinimumWidth(380)
        self.params_widgets = {}
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.action_combo = QComboBox()
        self.action_combo.addItem("点击屏幕", TaskAction.TAP)
        self.action_combo.addItem("滑动屏幕", TaskAction.SWIPE)
        self.action_combo.addItem("输入文本", TaskAction.INPUT_TEXT)
        self.action_combo.addItem("按键", TaskAction.INPUT_KEY)
        self.action_combo.addItem("截屏", TaskAction.SCREENSHOT)
        self.action_combo.addItem("启动应用", TaskAction.START_APP)
        self.action_combo.addItem("停止应用", TaskAction.STOP_APP)
        idx = self.action_combo.findData(self.step["action"])
        if idx >= 0:
            self.action_combo.setCurrentIndex(idx)
        self.action_combo.currentIndexChanged.connect(self.on_action_changed)
        form.addRow("操作类型:", self.action_combo)

        self.params_widget = QWidget()
        self.params_form = QFormLayout(self.params_widget)
        form.addRow("参数:", self.params_widget)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.on_action_changed()

    def on_action_changed(self):
        for i in reversed(range(self.params_form.count())):
            w = self.params_form.itemAt(i).widget()
            if w:
                w.deleteLater()
        self.params_widgets = {}
        action = self.action_combo.currentData()
        self._build_params(action)

    def _build_params(self, action: str):
        params = self.step["params"]

        if action == TaskAction.TAP:
            x = QSpinBox()
            x.setRange(0, 9999)
            x.setValue(params.get("x", 37))
            self.params_form.addRow("X坐标:", x)
            y = QSpinBox()
            y.setRange(0, 9999)
            y.setValue(params.get("y", 1399))
            self.params_form.addRow("Y坐标:", y)
            self.params_widgets = {"x": x, "y": y}

        elif action == TaskAction.SWIPE:
            x1 = QSpinBox()
            x1.setRange(0, 9999)
            x1.setValue(params.get("x1", 540))
            self.params_form.addRow("起始X:", x1)
            y1 = QSpinBox()
            y1.setRange(0, 9999)
            y1.setValue(params.get("y1", 1500))
            self.params_form.addRow("起始Y:", y1)
            x2 = QSpinBox()
            x2.setRange(0, 9999)
            x2.setValue(params.get("x2", 540))
            self.params_form.addRow("结束X:", x2)
            y2 = QSpinBox()
            y2.setRange(0, 9999)
            y2.setValue(params.get("y2", 500))
            self.params_form.addRow("结束Y:", y2)
            duration = QSpinBox()
            duration.setRange(100, 5000)
            duration.setValue(params.get("duration", 300))
            duration.setSuffix(" ms")
            self.params_form.addRow("持续时间:", duration)
            self.params_widgets = {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "duration": duration}

        elif action == TaskAction.INPUT_TEXT:
            text = QLineEdit(params.get("text", ""))
            self.params_form.addRow("文本:", text)
            self.params_widgets = {"text": text}

        elif action == TaskAction.INPUT_KEY:
            combo = QComboBox()
            combo.addItem("-- 选择按键 --", None)
            sorted_keys = sorted(KEY_MAP.items(), key=lambda x: x[0])
            for name, kc in sorted_keys:
                combo.addItem(f"{name} ({kc})", kc)
            combo.addItem("自定义...", "custom")
            current_kc = params.get("keycode", 4)
            if current_kc in KEY_MAP_REVERSE:
                idx = combo.findData(current_kc)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            self.params_form.addRow("按键:", combo)

            custom_widget = QWidget()
            custom_layout = QVBoxLayout(custom_widget)
            custom_layout.setContentsMargins(0, 0, 0, 0)
            custom_spin = QSpinBox()
            custom_spin.setRange(0, 255)
            custom_spin.setValue(current_kc)
            custom_layout.addWidget(custom_spin)
            custom_widget.setVisible(combo.currentData() == "custom")
            self.params_form.addRow("自定义键码:", custom_widget)

            combo.currentIndexChanged.connect(
                lambda: custom_widget.setVisible(combo.currentData() == "custom")
            )
            self.params_widgets = {"combo": combo, "custom_spin": custom_spin}

        elif action == TaskAction.SCREENSHOT:
            path = QLineEdit(params.get("output_path", "/tmp/screenshot.png"))
            self.params_form.addRow("保存路径:", path)
            self.params_widgets = {"output_path": path}

        elif action in (TaskAction.START_APP, TaskAction.STOP_APP):
            current_package = params.get("package", "")
            package_layout = QHBoxLayout()
            package_combo = QComboBox()
            package_combo.setEditable(True)
            package_combo.addItem("-- 选择应用或输入包名 --", "")
            for display, package in self.app_options:
                package_combo.addItem(display, package)
            if current_package:
                index = package_combo.findData(current_package)
                if index >= 0:
                    package_combo.setCurrentIndex(index)
                else:
                    package_combo.setEditText(current_package)
            package_layout.addWidget(package_combo)
            package_widget = QWidget()
            package_widget.setLayout(package_layout)
            self.params_form.addRow("包名:", package_widget)
            self.params_widgets = {"package": package_combo}

    def _collect_params(self) -> dict:
        action = self.action_combo.currentData()
        w = self.params_widgets
        if action == TaskAction.TAP:
            return {"x": w["x"].value(), "y": w["y"].value()}
        elif action == TaskAction.SWIPE:
            return {
                "x1": w["x1"].value(), "y1": w["y1"].value(),
                "x2": w["x2"].value(), "y2": w["y2"].value(),
                "duration": w["duration"].value(),
            }
        elif action == TaskAction.INPUT_TEXT:
            return {"text": w["text"].text()}
        elif action == TaskAction.INPUT_KEY:
            data = w["combo"].currentData()
            if data == "custom" or data is None:
                return {"keycode": w["custom_spin"].value()}
            return {"keycode": data}
        elif action == TaskAction.SCREENSHOT:
            return {"output_path": w["output_path"].text()}
        elif action in (TaskAction.START_APP, TaskAction.STOP_APP):
            package = w["package"].currentData() or w["package"].currentText().strip()
            return {"package": package}
        return {}

    def on_accept(self):
        self.step["action"] = self.action_combo.currentData()
        self.step["params"] = self._collect_params()
        self.accept()
