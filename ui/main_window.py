from PyQt6.QtWidgets import QMainWindow, QSplitter, QStatusBar, QMessageBox
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QIcon
from core.adb_manager import AdbManager
from tasks.task_manager import TaskManager
from ui.device_panel import DevicePanel
from ui.control_panel import ControlPanel
from ui.log_panel import LogPanel
from datetime import datetime
from pathlib import Path


APP_NAME = "ADB设备管理工具"
APP_ICON = Path(__file__).resolve().parent.parent / "assets" / "app_icon.png"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.adb_manager = AdbManager()
        self.task_manager = TaskManager(self.adb_manager)
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle(APP_NAME)
        if APP_ICON.exists():
            self.setWindowIcon(QIcon(str(APP_ICON)))
        self.setGeometry(100, 100, 1200, 800)

        self.device_panel = DevicePanel(self.adb_manager)
        self.control_panel = ControlPanel(self.adb_manager, self.task_manager)

        self.device_panel.device_selected.connect(self.control_panel.set_current_device)

        top_splitter = QSplitter(Qt.Orientation.Horizontal)
        top_splitter.addWidget(self.device_panel)
        top_splitter.addWidget(self.control_panel)
        top_splitter.setSizes([350, 850])

        self.log_panel = LogPanel()
        self.control_panel.log_emitted.connect(self.log_panel.add_log)
        self.device_panel.log_emitted.connect(self.log_panel.add_log)

        main_splitter = QSplitter(Qt.Orientation.Vertical)
        main_splitter.addWidget(top_splitter)
        main_splitter.addWidget(self.log_panel)
        main_splitter.setSizes([450, 350])
        self.log_panel.setMinimumHeight(150)

        self.setCentralWidget(main_splitter)

        self.create_menu_bar()
        self.create_status_bar()

    def create_menu_bar(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu("文件")

        refresh_action = QAction("刷新设备", self)
        refresh_action.setShortcut("Ctrl+R")
        refresh_action.triggered.connect(self.device_panel.refresh_devices)
        file_menu.addAction(refresh_action)

        file_menu.addSeparator()

        exit_action = QAction("退出", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        tools_menu = menubar.addMenu("工具")

        restart_adb_action = QAction("重启ADB", self)
        restart_adb_action.triggered.connect(self.on_restart_adb_menu)
        tools_menu.addAction(restart_adb_action)

        help_menu = menubar.addMenu("帮助")

        about_action = QAction("关于", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def create_status_bar(self):
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪")

    def on_restart_adb_menu(self):
        self.adb_manager.restart_adb()
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log_panel.add_log(ts, "重启ADB服务", "成功")

    def show_about(self):
        QMessageBox.about(
            self, "关于",
            f"{APP_NAME}\n\n"
            "适用于Mac M系列芯片的ADB设备管理工具\n"
            "支持多设备管理、设备操作、应用管理和定时任务"
        )
