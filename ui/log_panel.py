from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView, QPushButton, QHBoxLayout
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from core.log_entry import LogEntry


class LogPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["时间", "操作内容", "操作结果"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 145)
        self.table.setColumnWidth(2, 160)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setDefaultSectionSize(22)
        self.table.verticalHeader().setVisible(False)
        compact = QFont("Menlo", 10)
        self.table.setFont(compact)
        self.table.horizontalHeader().setFont(QFont("PingFang SC", 10))
        layout.addWidget(self.table)

        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)
        clear_btn = QPushButton("清空日志")
        clear_btn.setMaximumHeight(24)
        clear_btn.clicked.connect(self.clear_logs)
        btn_layout.addStretch()
        btn_layout.addWidget(clear_btn)
        layout.addLayout(btn_layout)

    def add_log(self, timestamp: str, operation: str, result: str):
        row = self.table.rowCount()
        self.table.insertRow(row)

        self.table.setItem(row, 0, QTableWidgetItem(timestamp))
        self.table.setItem(row, 1, QTableWidgetItem(operation))
        self.table.setItem(row, 2, QTableWidgetItem(result))

        self.table.scrollToBottom()

    def add_log_entry(self, entry: LogEntry):
        self.add_log(entry.timestamp, entry.operation, entry.result)

    def clear_logs(self):
        self.table.setRowCount(0)
