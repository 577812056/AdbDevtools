from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QListWidget, 
                             QListWidgetItem, QPushButton, QLabel, QGroupBox,
                             QSplitter, QMessageBox, QLineEdit, QSpinBox, QComboBox,
                             QInputDialog)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon
from core.adb_manager import AdbManager, AdbDevice
from datetime import datetime
import json
import os


class DevicePanel(QWidget):
    device_selected = pyqtSignal(str)
    log_emitted = pyqtSignal(str, str, str)
    
    def __init__(self, adb_manager: AdbManager):
        super().__init__()
        self.adb_manager = adb_manager
        self.selected_device = None
        self.config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "device_config.json")
        self.manual_devices = self.load_manual_devices()
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.refresh_devices)
        self.init_ui()
        
    def _log(self, operation: str, result: str):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log_emitted.emit(timestamp, operation, result)

    def load_manual_devices(self):
        try:
            with open(self.config_path, "r", encoding="utf-8") as file:
                data = json.load(file)
            devices = data.get("manual_devices", [])
            return [device for device in devices if isinstance(device, str) and device.strip()]
        except Exception:
            return []

    def save_manual_devices(self):
        try:
            with open(self.config_path, "w", encoding="utf-8") as file:
                json.dump(
                    {"manual_devices": self.manual_devices},
                    file,
                    ensure_ascii=False,
                    indent=2
                )
        except Exception as exc:
            self._log("保存设备配置", f"失败 - {exc}")
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        header_layout = QHBoxLayout()
        title = QLabel("设备列表")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        header_layout.addWidget(title)
        
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self.refresh_devices)
        header_layout.addWidget(self.refresh_btn)

        self.add_device_btn = QPushButton("添加设备")
        self.add_device_btn.clicked.connect(self.add_device)
        header_layout.addWidget(self.add_device_btn)
        
        self.auto_refresh_btn = QPushButton("自动刷新")
        self.auto_refresh_btn.setCheckable(True)
        self.auto_refresh_btn.clicked.connect(self.toggle_auto_refresh)
        header_layout.addWidget(self.auto_refresh_btn)
        
        layout.addLayout(header_layout)
        
        self.device_list = QListWidget()
        self.device_list.itemClicked.connect(self.on_device_selected)
        layout.addWidget(self.device_list)
        
        device_info_group = QGroupBox("设备信息")
        info_layout = QVBoxLayout()
        
        self.info_label = QLabel("请选择设备查看详细信息")
        self.info_label.setWordWrap(True)
        info_layout.addWidget(self.info_label)
        
        device_info_group.setLayout(info_layout)
        layout.addWidget(device_info_group)
        
        button_layout = QHBoxLayout()
        
        self.restart_adb_btn = QPushButton("重启ADB")
        self.restart_adb_btn.clicked.connect(self.restart_adb)
        button_layout.addWidget(self.restart_adb_btn)
        
        layout.addLayout(button_layout)
        
        self.refresh_devices()
        
    def refresh_devices(self):
        self.device_list.clear()
        devices = self._merge_manual_devices(self.adb_manager.list_devices())
        
        if not devices:
            item = QListWidgetItem("未检测到设备")
            item.setForeground(Qt.GlobalColor.gray)
            self.device_list.addItem(item)
            self.selected_device = None
            self.device_selected.emit("")
            self.info_label.setText("未检测到设备，请检查连接后点击刷新")
            return
            
        for device in devices:
            status_icon = "✓" if device.state == "device" else "✗"
            item_text = f"{status_icon} {device.serial}"
            if device.name:
                item_text += f" - {device.name}"
            if device.serial in self.manual_devices:
                item_text += " (手动)"
                
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, device)
            
            if device.state == "device":
                item.setForeground(Qt.GlobalColor.darkGreen)
            else:
                item.setForeground(Qt.GlobalColor.red)
                
            self.device_list.addItem(item)

    def _merge_manual_devices(self, devices):
        device_map = {device.serial: device for device in devices}
        for serial in self.manual_devices:
            if serial not in device_map:
                device_map[serial] = AdbDevice(serial=serial, state="offline", name="手动添加")
        return list(device_map.values())

    def _connect_output(self, result):
        output = (result.stdout or result.stderr).strip()
        return output or "无输出"

    def _connect_failed(self, result):
        output = self._connect_output(result).lower()
        failure_words = ("failed", "unable", "cannot", "refused", "timed out", "no route")
        return result.returncode != 0 or any(word in output for word in failure_words)

    def _normalize_device_address(self, address: str):
        address = address.strip()
        if address.isdigit():
            port = int(address)
            if 1 <= port <= 65535:
                return f"127.0.0.1:{port}"
            return ""
        return address

    def add_device(self):
        address, ok = QInputDialog.getText(
            self,
            "添加设备",
            "请输入端口号、设备序列号或 host:port（例如 16384 / 127.0.0.1:5555）:"
        )
        if not ok:
            return

        address = self._normalize_device_address(address)
        if not address:
            QMessageBox.warning(self, "输入无效", "请输入有效端口号、设备序列号或 host:port。")
            return

        if address not in self.manual_devices:
            self.manual_devices.append(address)
            self.save_manual_devices()

        if ":" in address:
            result = self.adb_manager.connect_device(address)
            output = self._connect_output(result)
            if self._connect_failed(result):
                self._log(f"连接设备: {address}", f"失败 - {output}")
            else:
                self._log(f"连接设备: {address}", output)
        else:
            self._log(f"添加设备: {address}", "已加入设备列表")

        self.refresh_devices()
        self.select_device(address)

    def select_device(self, serial: str):
        for row in range(self.device_list.count()):
            item = self.device_list.item(row)
            device = item.data(Qt.ItemDataRole.UserRole)
            if device and device.serial == serial:
                self.device_list.setCurrentItem(item)
                self.on_device_selected(item)
                return
            
    def on_device_selected(self, item):
        device = item.data(Qt.ItemDataRole.UserRole)
        if not device:
            return

        if device.state != "device" and device.serial in self.manual_devices and ":" in device.serial:
            result = self.adb_manager.connect_device(device.serial)
            output = self._connect_output(result)
            if not self._connect_failed(result):
                self._log(f"连接设备: {device.serial}", output)
                refreshed = {d.serial: d for d in self.adb_manager.list_devices()}
                device = refreshed.get(device.serial, device)
            else:
                self._log(f"连接设备: {device.serial}", f"失败 - {output}")

        if device.state != "device":
            self.selected_device = None
            self.device_selected.emit("")
            self.info_label.setText(f"设备不可用: {device.serial}\n状态: {device.state}")
            self._log(f"选择设备: {device.serial}", f"失败 - 状态为 {device.state}")
            QMessageBox.warning(self, "设备不可用", f"{device.serial} 当前状态为 {device.state}，无法选择。")
            return

        if not self.adb_manager.is_android_device(device.serial):
            self.selected_device = None
            self.device_selected.emit("")
            self.info_label.setText(f"设备校验失败: {device.serial}\n未检测到有效 Android 系统属性")
            self._log(f"选择设备: {device.serial}", "失败 - 不是可用的 Android 设备")
            QMessageBox.warning(self, "设备校验失败", f"{device.serial} 不是可用的 Android 设备，或尚未授权调试。")
            return
            
        self.selected_device = device
        self.device_selected.emit(device.serial)
        
        info = self.adb_manager.get_device_info(device.serial)
        screen_size = self.adb_manager.get_screen_size(device.serial)
        
        info_text = f"""
序列号: {device.serial}
型号: {info.get('ro.product.model', 'N/A')}
品牌: {info.get('ro.product.brand', 'N/A')}
Android版本: {info.get('ro.build.version.release', 'N/A')}
SDK版本: {info.get('ro.build.version.sdk', 'N/A')}
CPU架构: {info.get('ro.product.cpu.abi', 'N/A')}
屏幕分辨率: {screen_size[0]} x {screen_size[1]}
屏幕密度: {info.get('ro.sf.lcd_density', 'N/A')} DPI
状态: {device.state}
        """
        
        self.info_label.setText(info_text.strip())
        
    def toggle_auto_refresh(self):
        if self.auto_refresh_btn.isChecked():
            self.refresh_timer.start(5000)
            self.auto_refresh_btn.setText("停止刷新")
        else:
            self.refresh_timer.stop()
            self.auto_refresh_btn.setText("自动刷新")
            
    def restart_adb(self):
        reply = QMessageBox.question(
            self, "确认", "确定要重启ADB服务吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.adb_manager.restart_adb()
            self.refresh_devices()
            self._log("重启ADB服务", "成功")
