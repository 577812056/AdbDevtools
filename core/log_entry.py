from dataclasses import dataclass
from datetime import datetime


@dataclass
class LogEntry:
    timestamp: str
    operation: str
    result: str
