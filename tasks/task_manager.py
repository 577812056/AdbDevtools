from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from typing import List, Dict, Optional
from datetime import datetime
import json
import os


action_names = {
    "tap": "点击屏幕",
    "swipe": "滑动屏幕",
    "input_text": "输入文本",
    "input_key": "按键",
    "screenshot": "截屏",
    "start_app": "启动应用",
    "stop_app": "停止应用",
}

KEY_MAP = {
    "主页": 3,
    "返回": 4,
    "拨号": 5,
    "音量+": 24,
    "音量-": 25,
    "电源": 26,
    "相机": 27,
    "清除": 28,
    "确认/回车": 66,
    "菜单": 82,
    "搜索": 84,
    "音量静音": 164,
    "媒体播放/暂停": 85,
    "媒体下一首": 87,
    "媒体上一首": 88,
}

KEY_MAP_REVERSE = {v: k for k, v in KEY_MAP.items()}


class TaskAction:
    TAP = "tap"
    SWIPE = "swipe"
    INPUT_TEXT = "input_text"
    INPUT_KEY = "input_key"
    SCREENSHOT = "screenshot"
    START_APP = "start_app"
    STOP_APP = "stop_app"


class ScheduledTask:
    def __init__(self, task_id: str, name: str, action: str, serial: str, 
                 params: Dict, schedule_type: str, schedule_time: Optional[str] = None,
                 interval_seconds: int = 0, enabled: bool = True,
                 steps: Optional[List[Dict]] = None, target_scope: str = "single"):
        self.task_id = task_id
        self.name = name
        self.action = action
        self.serial = serial
        self.target_scope = target_scope
        self.params = params
        self.steps = steps if steps else [{"action": action, "params": params}]
        self.schedule_type = schedule_type
        self.schedule_time = schedule_time
        self.interval_seconds = interval_seconds
        self.enabled = enabled
        self.last_run = None
        self.run_count = 0

    def to_dict(self):
        return {
            "task_id": self.task_id,
            "name": self.name,
            "action": self.action,
            "serial": self.serial,
            "target_scope": self.target_scope,
            "params": self.params,
            "steps": self.steps,
            "schedule_type": self.schedule_type,
            "schedule_time": self.schedule_time,
            "interval_seconds": self.interval_seconds,
            "enabled": self.enabled,
            "last_run": self.last_run,
            "run_count": self.run_count,
        }

    @classmethod
    def from_dict(cls, data):
        steps = data.get("steps")
        if not steps:
            steps = [{"action": data["action"], "params": data["params"]}]
        task = cls(
            task_id=data["task_id"],
            name=data["name"],
            action=data["action"],
            serial=data["serial"],
            target_scope=data.get("target_scope", "all" if data.get("serial") == "__all__" else "single"),
            params=data["params"],
            steps=steps,
            schedule_type=data["schedule_type"],
            schedule_time=data.get("schedule_time"),
            interval_seconds=data.get("interval_seconds", 0),
            enabled=data.get("enabled", True),
        )
        task.last_run = data.get("last_run")
        task.run_count = data.get("run_count", 0)
        return task


class TaskManager(QObject):
    task_executed = pyqtSignal(str, str, bool, list, list)

    def __init__(self, adb_manager, tasks_file: str = "tasks.json"):
        super().__init__()
        self.adb_manager = adb_manager
        self.tasks_file = tasks_file
        self.tasks: Dict[str, ScheduledTask] = {}
        self.timers: Dict[str, QTimer] = {}
        self.scheduled_tasks: Dict[str, QTimer] = {}
        self.check_timer = QTimer()
        self.check_timer.timeout.connect(self._check_scheduled_tasks)
        self.check_timer.start(10000)
        self.load_tasks()

    def load_tasks(self):
        if os.path.exists(self.tasks_file):
            try:
                with open(self.tasks_file, "r") as f:
                    data = json.load(f)
                    for task_data in data:
                        task = ScheduledTask.from_dict(task_data)
                        self.tasks[task.task_id] = task
            except:
                pass

    def save_tasks(self):
        data = [task.to_dict() for task in self.tasks.values()]
        with open(self.tasks_file, "w") as f:
            json.dump(data, f, indent=2)

    def add_task(self, task: ScheduledTask):
        self.tasks[task.task_id] = task
        self.save_tasks()
        if task.enabled:
            if task.schedule_type == "interval":
                self._start_interval_timer(task)
            elif task.schedule_type == "scheduled":
                self._schedule_task(task)

    def remove_task(self, task_id: str):
        if task_id in self.timers:
            self.timers[task_id].stop()
            del self.timers[task_id]
        if task_id in self.scheduled_tasks:
            self.scheduled_tasks[task_id].stop()
            del self.scheduled_tasks[task_id]
        if task_id in self.tasks:
            del self.tasks[task_id]
            self.save_tasks()

    def update_task(self, task: ScheduledTask):
        if task.task_id in self.tasks:
            old = self.tasks[task.task_id]
            if task.task_id in self.timers:
                self.timers[task.task_id].stop()
                del self.timers[task.task_id]
            if task.task_id in self.scheduled_tasks:
                self.scheduled_tasks[task.task_id].stop()
                del self.scheduled_tasks[task.task_id]
            task.last_run = old.last_run
            task.run_count = old.run_count
            self.tasks[task.task_id] = task
            self.save_tasks()
            if task.enabled:
                if task.schedule_type == "interval":
                    self._start_interval_timer(task)
                elif task.schedule_type == "scheduled":
                    self._schedule_task(task)

    def toggle_task(self, task_id: str):
        if task_id in self.tasks:
            task = self.tasks[task_id]
            task.enabled = not task.enabled
            self.save_tasks()
            if task.enabled:
                if task.schedule_type == "interval":
                    self._start_interval_timer(task)
                elif task.schedule_type == "scheduled":
                    self._schedule_task(task)
            else:
                if task_id in self.timers:
                    self.timers[task_id].stop()
                    del self.timers[task_id]
                if task_id in self.scheduled_tasks:
                    self.scheduled_tasks[task_id].stop()
                    del self.scheduled_tasks[task_id]

    def _execute_step(self, serial: str, step: Dict) -> bool:
        action = step["action"]
        params = step["params"]
        try:
            if action == TaskAction.TAP:
                result = self.adb_manager.tap(params["x"], params["y"], serial)
                return result.returncode == 0
            elif action == TaskAction.SWIPE:
                result = self.adb_manager.swipe(
                    params["x1"], params["y1"],
                    params["x2"], params["y2"],
                    params.get("duration", 300), serial,
                )
                return result.returncode == 0
            elif action == TaskAction.INPUT_TEXT:
                result = self.adb_manager.input_text(params["text"], serial)
                return result.returncode == 0
            elif action == TaskAction.INPUT_KEY:
                result = self.adb_manager.input_key(params["keycode"], serial)
                return result.returncode == 0
            elif action == TaskAction.SCREENSHOT:
                return self.adb_manager.take_screenshot(
                    serial, params.get("output_path", "/tmp/screenshot.png")
                )
            elif action == TaskAction.START_APP:
                result = self.adb_manager.start_app(params["package"], serial)
                return result.returncode == 0
            elif action == TaskAction.STOP_APP:
                result = self.adb_manager.stop_app(params["package"], serial)
                return result.returncode == 0
        except Exception as e:
            print(f"Step execution failed: {e}")
        return False

    def _get_task_serials(self, task: ScheduledTask) -> List[str]:
        if task.target_scope == "all" or task.serial == "__all__":
            serials = []
            for device in self.adb_manager.list_devices():
                if device.state == "device" and self.adb_manager.is_android_device(device.serial):
                    serials.append(device.serial)
            return serials
        return [task.serial] if task.serial else []

    def execute_task(self, task_id: str):
        if task_id not in self.tasks:
            return

        task = self.tasks[task_id]
        success = True
        target_serials = self._get_task_serials(task)
        success_serials = []
        failed_serials = []

        if not target_serials:
            success = False

        for serial in target_serials:
            serial_success = True
            for step in task.steps:
                if not self._execute_step(serial, step):
                    serial_success = False
                    success = False
                    break
            if serial_success:
                success_serials.append(serial)
            else:
                failed_serials.append(serial)

        task.last_run = datetime.now().isoformat()
        task.run_count += 1
        self.save_tasks()

        self.task_executed.emit(task_id, task.name, success, success_serials, failed_serials)

    def _start_interval_timer(self, task: ScheduledTask):
        if task.task_id in self.timers:
            self.timers[task.task_id].stop()
        timer = QTimer()
        timer.timeout.connect(lambda: self.execute_task(task.task_id))
        timer.start(task.interval_seconds * 1000)
        self.timers[task.task_id] = timer

    def _schedule_task(self, task: ScheduledTask):
        if task.task_id in self.scheduled_tasks:
            self.scheduled_tasks[task.task_id].stop()
        if not task.schedule_time:
            return
        try:
            scheduled_time = datetime.fromisoformat(task.schedule_time)
            now = datetime.now()
            if scheduled_time <= now:
                scheduled_time = scheduled_time.replace(day=scheduled_time.day + 1)
            delay_ms = int((scheduled_time - now).total_seconds() * 1000)
            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(lambda: self.execute_task(task.task_id))
            timer.start(delay_ms)
            self.scheduled_tasks[task.task_id] = timer
        except Exception as e:
            print(f"Failed to schedule task: {e}")

    def _check_scheduled_tasks(self):
        now = datetime.now()
        for task_id, task in self.tasks.items():
            if task.enabled and task.schedule_type == "scheduled" and task.schedule_time:
                try:
                    scheduled_time = datetime.fromisoformat(task.schedule_time)
                    if now.hour == scheduled_time.hour and now.minute == scheduled_time.minute:
                        if task.last_run:
                            last_run = datetime.fromisoformat(task.last_run)
                            if last_run.date() < now.date():
                                self.execute_task(task_id)
                                self._schedule_task(task)
                        else:
                            self.execute_task(task_id)
                            self._schedule_task(task)
                except:
                    pass

    def get_tasks(self) -> List[ScheduledTask]:
        return list(self.tasks.values())

    def get_task(self, task_id: str) -> Optional[ScheduledTask]:
        return self.tasks.get(task_id)
