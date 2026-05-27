#!/usr/bin/env python3
import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from ui.main_window import MainWindow
from pathlib import Path


APP_NAME = "ADB设备管理工具"
APP_ICON = Path(__file__).resolve().parent / "assets" / "app_icon.png"


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName("AdbDevtools")
    if APP_ICON.exists():
        app.setWindowIcon(QIcon(str(APP_ICON)))
    app.setStyle("Fusion")
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
