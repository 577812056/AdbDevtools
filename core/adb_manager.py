import struct
import subprocess
import json
import re
import os
import tempfile
import zipfile
import shutil
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass


@dataclass
class AdbDevice:
    serial: str
    state: str
    name: str = ""
    
    def __str__(self):
        return f"{self.serial} ({self.state})"


class AdbManager:
    def __init__(self, adb_path: str = "adb"):
        self.adb_path = adb_path
        self.app_name_cache = {}
        
    def run_command(self, args: List[str], serial: Optional[str] = None, timeout: int = 30) -> subprocess.CompletedProcess:
        cmd = [self.adb_path]
        if serial:
            cmd.extend(["-s", serial])
        cmd.extend(args)
        
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        
    def list_devices(self) -> List[AdbDevice]:
        result = self.run_command(["devices", "-l"])
        devices = []
        
        if result.returncode == 0:
            lines = result.stdout.strip().split("\n")[1:]
            for line in lines:
                if line.strip():
                    parts = line.split()
                    if len(parts) >= 2:
                        serial = parts[0]
                        state = parts[1]
                        
                        name = ""
                        for part in parts[2:]:
                            if part.startswith("model:"):
                                name = part.split(":")[1]
                            elif part.startswith("device:"):
                                if not name:
                                    name = part.split(":")[1]
                                    
                        devices.append(AdbDevice(serial=serial, state=state, name=name))
                        
        return devices

    def connect_device(self, address: str) -> subprocess.CompletedProcess:
        return self.run_command(["connect", address], timeout=15)

    def is_android_device(self, serial: str) -> bool:
        try:
            result = self.run_command(
                ["shell", "getprop", "ro.build.version.sdk"],
                serial=serial,
                timeout=8
            )
            sdk = result.stdout.strip()
            return result.returncode == 0 and sdk.isdigit()
        except Exception:
            return False
    
    def get_device_info(self, serial: str) -> Dict[str, str]:
        info = {}
        
        props = [
            "ro.product.model",
            "ro.product.brand",
            "ro.build.version.release",
            "ro.build.version.sdk",
            "ro.product.cpu.abi",
            "ro.sf.lcd_density"
        ]
        
        for prop in props:
            result = self.run_command(["shell", "getprop", prop], serial=serial)
            if result.returncode == 0:
                info[prop] = result.stdout.strip()
                
        return info
    
    def get_screen_size(self, serial: str) -> tuple:
        result = self.run_command(["shell", "wm", "size"], serial=serial)
        if result.returncode == 0:
            try:
                size_str = result.stdout.strip().split(":")[1].strip()
                width, height = map(int, size_str.split("x"))
                return (width, height)
            except:
                pass
        return (1080, 1920)
    
    def tap(self, x: int, y: int, serial: str):
        return self.run_command(["shell", "input", "tap", str(x), str(y)], serial=serial)
    
    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: int = 300, serial: str = None):
        return self.run_command(
            ["shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration)],
            serial=serial
        )
    
    def input_text(self, text: str, serial: str):
        return self.run_command(["shell", "input", "text", text], serial=serial)
    
    def input_key(self, keycode: int, serial: str):
        return self.run_command(["shell", "input", "keyevent", str(keycode)], serial=serial)
    
    def take_screenshot(self, serial: str, output_path: str = "/tmp/screenshot.png"):
        remote_path = "/sdcard/screenshot.png"
        
        self.run_command(["shell", "screencap", "-p", remote_path], serial=serial)
        
        result = self.run_command(["pull", remote_path, output_path], serial=serial)
        
        self.run_command(["shell", "rm", remote_path], serial=serial)
        
        return result.returncode == 0
    
    def install_app(self, apk_path: str, serial: str):
        self.app_name_cache = {
            key: value for key, value in self.app_name_cache.items()
            if key[0] != serial
        }
        return self.run_command(["install", "-r", apk_path], serial=serial)
    
    def uninstall_app(self, package_name: str, serial: str):
        self.app_name_cache.pop((serial, package_name), None)
        return self.run_command(["uninstall", package_name], serial=serial)
    
    def list_packages(self, serial: str, third_party_only: bool = False) -> List[str]:
        args = ["shell", "pm", "list", "packages"]
        if third_party_only:
            args.append("-3")
        result = self.run_command(args, serial=serial)
        packages = []
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if line.startswith("package:"):
                    packages.append(line.split(":")[1])
        return packages

    def get_app_names(self, serial: str) -> dict:
        names = {}
        path_names = {}

        # Attempt 1: newer package managers may expose labels directly.
        for args in (
            ["shell", "pm", "list", "packages", "--show-applicationlabel"],
            ["shell", "cmd", "package", "list", "packages", "--show-application-label"],
        ):
            try:
                result = self.run_command(args, serial=serial, timeout=60)
                if result.returncode == 0:
                    names.update(self._parse_package_label_output(result.stdout))
            except Exception:
                pass

        # Attempt 2: full dumpsys package. Prefer localized Chinese labels when present.
        try:
            raw = self.run_command(
                ["shell", "dumpsys", "package"], serial=serial, timeout=60
            )
            if raw.stdout.strip():
                labels = self._parse_dumpsys_labels(raw.stdout)
                if labels:
                    names.update(labels)
                path_names = self._parse_apk_paths(raw.stdout)
        except Exception:
            pass

        # Attempt 3: query packages individually via shell script
        try:
            script = (
                "pm list packages 2>/dev/null | cut -d: -f2 | "
                "while read pkg; do "
                "  dumpsys package \"$pkg\" 2>/dev/null | "
                "    grep -E \"application-label(-[A-Za-z0-9_-]+)?[=:]\" | "
                "    sed \"s/^/${pkg}\t/\"; "
                "  cmd package dump \"$pkg\" 2>/dev/null | "
                "    grep -E \"application-label(-[A-Za-z0-9_-]+)?[=:]\" | "
                "    sed \"s/^/${pkg}\t/\"; "
                "done"
            )
            result = self.run_command(["shell", script], serial=serial, timeout=120)
            candidates = {}
            for line in result.stdout.split("\n"):
                if "\t" not in line:
                    continue
                pkg, label_line = line.split("\t", 1)
                label_info = self._extract_application_label(label_line)
                if not label_info:
                    continue
                label, priority = label_info
                current = candidates.get(pkg)
                if not current or priority < current[1]:
                    candidates[pkg] = (label, priority)
            names.update({pkg: label for pkg, (label, _) in candidates.items()})
        except Exception:
            pass

        for package, label in path_names.items():
            names.setdefault(package, label)

        return names

    def get_app_name(self, serial: str, package_name: str) -> str:
        cache_key = (serial, package_name)
        if cache_key in self.app_name_cache:
            return self.app_name_cache[cache_key]

        candidates = {}
        for args in (
            ["shell", "dumpsys", "package", package_name],
            ["shell", "cmd", "package", "dump", package_name],
        ):
            try:
                result = self.run_command(args, serial=serial, timeout=20)
                if result.returncode != 0:
                    continue
                labels = self._parse_label_lines(result.stdout)
                for label, priority in labels:
                    current = candidates.get(package_name)
                    if not current or priority < current[1]:
                        candidates[package_name] = (label, priority)
            except Exception:
                pass

        candidate_label = ""
        if package_name in candidates:
            candidate_label = candidates[package_name][0]
            if not self._looks_like_package_fallback(candidate_label, package_name):
                self.app_name_cache[cache_key] = candidate_label
                return candidate_label

        apk_label = self.get_app_name_from_apk(serial, package_name)
        if apk_label:
            self.app_name_cache[cache_key] = apk_label
            return apk_label

        self.app_name_cache[cache_key] = candidate_label
        return candidate_label

    def get_app_name_from_apk(self, serial: str, package_name: str) -> str:
        apk_path = self.get_package_apk_path(serial, package_name)
        if not apk_path:
            return ""

        aapt_path = self._find_android_tool("aapt")

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                local_path = os.path.join(tmpdir, f"{package_name}.apk")
                pull_result = self.run_command(["pull", apk_path, local_path], serial=serial, timeout=60)
                if pull_result.returncode != 0 or not os.path.exists(local_path):
                    return ""

                label = self._read_apk_label(local_path)
                if label:
                    return label

                if not aapt_path:
                    return ""

                result = subprocess.run(
                    [aapt_path, "dump", "badging", local_path],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if result.returncode != 0:
                    return ""

                labels = self._parse_aapt_badging_labels(result.stdout)
                if labels:
                    labels.sort(key=lambda item: item[1])
                    return labels[0][0]
        except Exception:
            return ""

        return ""

    def _read_apk_label(self, apk_path: str) -> str:
        try:
            with zipfile.ZipFile(apk_path) as apk_file:
                manifest_data = apk_file.read("AndroidManifest.xml")
                manifest_label = self._extract_manifest_label(manifest_data)
                if isinstance(manifest_label, str):
                    return manifest_label
                if isinstance(manifest_label, int):
                    resources_data = apk_file.read("resources.arsc")
                    return self._resolve_resource_string(resources_data, manifest_label)
        except Exception:
            return ""

        return ""

    def _extract_manifest_label(self, manifest_data: bytes):
        strings = []
        offset = 8
        while offset + 8 <= len(manifest_data):
            chunk_type = self._read_u16(manifest_data, offset)
            header_size = self._read_u16(manifest_data, offset + 2)
            chunk_size = self._read_u32(manifest_data, offset + 4)
            if chunk_size <= 0:
                break

            if chunk_type == 0x0001:
                strings = self._parse_string_pool(manifest_data, offset)
            elif chunk_type == 0x0102 and strings:
                element_name_index = self._read_u32(manifest_data, offset + 20)
                if self._string_at(strings, element_name_index) == "application":
                    attribute_start = self._read_u16(manifest_data, offset + 24)
                    attribute_size = self._read_u16(manifest_data, offset + 26)
                    attribute_count = self._read_u16(manifest_data, offset + 28)
                    attributes_offset = offset + 16 + attribute_start
                    for attribute_index in range(attribute_count):
                        attribute_offset = attributes_offset + attribute_index * attribute_size
                        name_index = self._read_u32(manifest_data, attribute_offset + 4)
                        raw_value_index = self._read_u32(manifest_data, attribute_offset + 8)
                        value_type = manifest_data[attribute_offset + 15]
                        value_data = self._read_u32(manifest_data, attribute_offset + 16)
                        if self._string_at(strings, name_index) != "label":
                            continue

                        if raw_value_index != 0xFFFFFFFF:
                            raw_value = self._string_at(strings, raw_value_index)
                            resource_id = self._parse_resource_reference(raw_value)
                            if resource_id:
                                return resource_id
                            if raw_value and not raw_value.startswith("@"):
                                return raw_value

                        if value_type == 0x03:
                            return self._string_at(strings, value_data)
                        if value_type in (0x01, 0x02) and value_data:
                            return value_data

            offset += chunk_size if chunk_size >= header_size else header_size

        return ""

    def _resolve_resource_string(self, resources_data: bytes, resource_id: int) -> str:
        package_id = (resource_id >> 24) & 0xFF
        type_id = (resource_id >> 16) & 0xFF
        entry_id = resource_id & 0xFFFF
        labels = []

        if self._read_u16(resources_data, 0) != 0x0002:
            return ""

        table_header_size = self._read_u16(resources_data, 2)
        offset = table_header_size
        value_strings = []

        while offset + 8 <= len(resources_data):
            chunk_type = self._read_u16(resources_data, offset)
            header_size = self._read_u16(resources_data, offset + 2)
            chunk_size = self._read_u32(resources_data, offset + 4)
            if chunk_size <= 0:
                break

            if chunk_type == 0x0001 and not value_strings:
                value_strings = self._parse_string_pool(resources_data, offset)
            elif chunk_type == 0x0200:
                labels.extend(
                    self._parse_package_resource_strings(
                        resources_data,
                        offset,
                        package_id,
                        type_id,
                        entry_id,
                        value_strings,
                        set()
                    )
                )

            offset += chunk_size if chunk_size >= header_size else header_size

        labels = [(label, priority) for label, priority in labels if label]
        if not labels:
            return ""

        labels.sort(key=lambda item: item[1])
        return labels[0][0]

    def _parse_package_resource_strings(
        self,
        resources_data: bytes,
        package_offset: int,
        package_id: int,
        type_id: int,
        entry_id: int,
        value_strings: List[str],
        seen_resource_ids: set
    ) -> List[Tuple[str, int]]:
        current_package_id = self._read_u32(resources_data, package_offset + 8)
        if current_package_id != package_id:
            return []

        labels = []
        package_header_size = self._read_u16(resources_data, package_offset + 2)
        package_size = self._read_u32(resources_data, package_offset + 4)
        offset = package_offset + package_header_size
        package_end = package_offset + package_size

        while offset + 8 <= package_end:
            chunk_type = self._read_u16(resources_data, offset)
            header_size = self._read_u16(resources_data, offset + 2)
            chunk_size = self._read_u32(resources_data, offset + 4)
            if chunk_size <= 0:
                break

            if chunk_type == 0x0201 and offset + chunk_size <= len(resources_data):
                type_chunk_id = resources_data[offset + 8]
                if type_chunk_id == type_id:
                    label = self._parse_type_chunk_entry(
                        resources_data,
                        offset,
                        entry_id,
                        value_strings,
                        seen_resource_ids
                    )
                    if label:
                        labels.append(label)

            offset += chunk_size if chunk_size >= header_size else header_size

        return labels

    def _parse_type_chunk_entry(
        self,
        resources_data: bytes,
        type_offset: int,
        entry_id: int,
        value_strings: List[str],
        seen_resource_ids: set
    ) -> Optional[Tuple[str, int]]:
        header_size = self._read_u16(resources_data, type_offset + 2)
        entry_count = self._read_u32(resources_data, type_offset + 12)
        entries_start = self._read_u32(resources_data, type_offset + 16)
        if entry_id >= entry_count:
            return None

        entry_offsets_offset = type_offset + header_size
        entry_offset = self._read_u32(resources_data, entry_offsets_offset + entry_id * 4)
        if entry_offset == 0xFFFFFFFF:
            return None

        entry_position = type_offset + entries_start + entry_offset
        entry_size = self._read_u16(resources_data, entry_position)
        entry_flags = self._read_u16(resources_data, entry_position + 2)
        if entry_flags & 0x0001:
            return None

        value_offset = entry_position + entry_size
        value_type = resources_data[value_offset + 3]
        value_data = self._read_u32(resources_data, value_offset + 4)
        locale_name = self._parse_config_locale(resources_data, type_offset + 20)
        priority = self._label_priority(locale_name)

        if value_type == 0x03 and value_data < len(value_strings):
            return value_strings[value_data], priority

        if value_type == 0x01 and value_data not in seen_resource_ids:
            seen_resource_ids.add(value_data)
            nested_label = self._resolve_resource_string(resources_data, value_data)
            if nested_label:
                return nested_label, priority

        return None

    def _parse_config_locale(self, data: bytes, config_offset: int) -> str:
        if config_offset + 12 > len(data):
            return ""

        language_bytes = data[config_offset + 8:config_offset + 10]
        country_bytes = data[config_offset + 10:config_offset + 12]
        if language_bytes == b"\x00\x00":
            return ""
        if language_bytes[0] & 0x80:
            return ""

        language = language_bytes.decode("ascii", errors="ignore").strip("\x00").lower()
        country = country_bytes.decode("ascii", errors="ignore").strip("\x00").lower()
        if not language:
            return ""
        return f"{language}-{country}" if country else language

    def _parse_string_pool(self, data: bytes, offset: int) -> List[str]:
        string_count = self._read_u32(data, offset + 8)
        flags = self._read_u32(data, offset + 16)
        strings_start = self._read_u32(data, offset + 20)
        header_size = self._read_u16(data, offset + 2)
        is_utf8 = bool(flags & 0x00000100)
        strings = []

        for string_index in range(string_count):
            string_offset = self._read_u32(data, offset + header_size + string_index * 4)
            absolute_offset = offset + strings_start + string_offset
            if is_utf8:
                text = self._read_utf8_string(data, absolute_offset)
            else:
                text = self._read_utf16_string(data, absolute_offset)
            strings.append(text)

        return strings

    def _read_utf8_string(self, data: bytes, offset: int) -> str:
        _, offset = self._read_length8(data, offset)
        byte_length, offset = self._read_length8(data, offset)
        return data[offset:offset + byte_length].decode("utf-8", errors="replace")

    def _read_utf16_string(self, data: bytes, offset: int) -> str:
        char_length, offset = self._read_length16(data, offset)
        byte_length = char_length * 2
        return data[offset:offset + byte_length].decode("utf-16le", errors="replace")

    def _read_length8(self, data: bytes, offset: int) -> Tuple[int, int]:
        first = data[offset]
        offset += 1
        if first & 0x80:
            second = data[offset]
            offset += 1
            return ((first & 0x7F) << 8) | second, offset
        return first, offset

    def _read_length16(self, data: bytes, offset: int) -> Tuple[int, int]:
        first = self._read_u16(data, offset)
        offset += 2
        if first & 0x8000:
            second = self._read_u16(data, offset)
            offset += 2
            return ((first & 0x7FFF) << 16) | second, offset
        return first, offset

    @staticmethod
    def _parse_resource_reference(value: str) -> int:
        if not value or not value.startswith("@"):
            return 0
        value = value[1:]
        if value.startswith("+"):
            value = value[1:]
        try:
            if value.startswith("0x"):
                return int(value, 16)
            if value.isdigit():
                return int(value)
        except ValueError:
            return 0
        return 0

    @staticmethod
    def _string_at(strings: List[str], index: int) -> str:
        if 0 <= index < len(strings):
            return strings[index]
        return ""

    @staticmethod
    def _read_u16(data: bytes, offset: int) -> int:
        if offset + 2 > len(data):
            return 0
        return struct.unpack_from("<H", data, offset)[0]

    @staticmethod
    def _read_u32(data: bytes, offset: int) -> int:
        if offset + 4 > len(data):
            return 0
        return struct.unpack_from("<I", data, offset)[0]

    def get_package_apk_path(self, serial: str, package_name: str) -> str:
        try:
            result = self.run_command(["shell", "pm", "path", package_name], serial=serial, timeout=20)
            if result.returncode != 0:
                return ""

            paths = []
            for line in result.stdout.split("\n"):
                line = line.strip()
                if line.startswith("package:"):
                    paths.append(line[len("package:"):])

            for path in paths:
                if path.endswith("/base.apk"):
                    return path
            return paths[0] if paths else ""
        except Exception:
            return ""

    def _parse_apk_paths(self, text: str) -> dict:
        names = {}
        current_pkg = None
        for line in text.split("\n"):
            s = line.rstrip()
            if s.startswith("  Package [") or s.startswith("Package ["):
                try:
                    current_pkg = s.split("[")[1].split("]")[0]
                except:
                    current_pkg = None
                continue
            if current_pkg and s.startswith("    codePath="):
                path = s.split("=", 1)[1]
                label = self._path_to_label(path, current_pkg)
                if label:
                    names[current_pkg] = label
                current_pkg = None
        return names

    @staticmethod
    def _path_to_label(path: str, package: str) -> str:
        if path:
            if path.startswith("/system/app/") or path.startswith("/system/priv-app/"):
                name = path.rstrip("/").split("/")[-1]
                if name and not name.startswith("."):
                    if name.endswith(".apk"):
                        name = name[:-4]
                    return name
        parts = package.split(".")
        for part in reversed(parts):
            if len(part) >= 3 and part[0].isupper():
                return part
        return parts[-1].capitalize() if len(parts) >= 1 else ""

    @staticmethod
    def _label_priority(locale_name: str) -> int:
        locale_name = (locale_name or "").lower().replace("_", "-")
        if locale_name in ("zh-cn", "zh-hans", "zh-hans-cn"):
            return 0
        if locale_name.startswith("zh"):
            return 1
        if not locale_name:
            return 2
        return 3

    def _parse_package_label_output(self, text: str) -> dict:
        names = {}
        current_pkg = None
        pending_label = None

        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue

            if line.startswith("package:"):
                content = line[len("package:"):].strip()
                current_pkg = content.split()[0] if content else None
                label_info = self._extract_application_label(line)
                if label_info and current_pkg:
                    names[current_pkg] = label_info[0]
                elif pending_label and current_pkg:
                    names[current_pkg] = pending_label
                    pending_label = None
                continue

            label_info = self._extract_application_label(line)
            if label_info and current_pkg:
                names[current_pkg] = label_info[0]
            elif label_info:
                pending_label = label_info[0]

        return names

    def _parse_label_lines(self, text: str) -> List[Tuple[str, int]]:
        labels = []
        for line in text.split("\n"):
            label_info = self._extract_application_label(line)
            if label_info:
                labels.append(label_info)
        return labels

    @staticmethod
    def _looks_like_package_fallback(label: str, package_name: str) -> bool:
        normalized_label = (label or "").strip().lower()
        package_parts = [part.lower() for part in package_name.split(".") if part]
        return normalized_label in package_parts

    def _parse_aapt_badging_labels(self, text: str) -> List[Tuple[str, int]]:
        labels = []
        for line in text.split("\n"):
            line = line.strip()
            label_info = self._extract_application_label(line)
            if label_info:
                labels.append(label_info)
                continue

            m = re.search(r"\bapplication:\s+label='(.+?)'", line)
            if m:
                label = m.group(1).strip()
                if label and not label.startswith("@"):
                    labels.append((label, self._label_priority("")))

        return labels

    @staticmethod
    def _find_android_tool(tool_name: str) -> str:
        direct_path = shutil.which(tool_name)
        if direct_path:
            return direct_path

        roots = [
            os.environ.get("ANDROID_HOME"),
            os.environ.get("ANDROID_SDK_ROOT"),
            os.path.expanduser("~/Library/Android/sdk"),
        ]
        for root in roots:
            if not root:
                continue
            build_tools = os.path.join(root, "build-tools")
            if not os.path.isdir(build_tools):
                continue
            versions = sorted(os.listdir(build_tools), reverse=True)
            for version in versions:
                path = os.path.join(build_tools, version, tool_name)
                if os.path.exists(path) and os.access(path, os.X_OK):
                    return path

        return ""

    def _extract_application_label(self, line: str) -> Optional[Tuple[str, int]]:
        m = re.search(
            r"application-label(?:-([A-Za-z0-9_-]+))?\s*[:=]\s*['\"]?(.+?)['\"]?\s*$",
            line.strip()
        )
        if not m:
            return None

        label = m.group(2).strip().strip("'\"")
        if not label or label.startswith("@") or label.startswith("<"):
            return None

        return label, self._label_priority(m.group(1) or "")

    def _parse_dumpsys_labels(self, text: str) -> dict:
        names = {}
        candidates = {}
        current_pkg = None
        for line in text.split("\n"):
            s = line.rstrip()

            if s.startswith("  Package [") or s.startswith("Package ["):
                current_pkg = s.split("[")[1].split("]")[0]
                continue

            if current_pkg is None:
                continue

            label = None
            priority = 99
            label_info = self._extract_application_label(s)
            if label_info:
                label, priority = label_info
            # format: applicationInfo=ApplicationInfo{... label=AppName ...}
            if not label:
                m = re.search(r"\bapplicationInfo=.*\blabel=([^,}\s]+)", s)
                if m:
                    label = m.group(1)
                    priority = 4
            # format: label='App Name' on its own line within package block
            if not label:
                m = re.search(r"^\s*label\s*=\s*['\"](.+?)['\"]", s)
                if m:
                    label = m.group(1)
                    priority = 4

            if label and len(label) >= 2:
                current = candidates.get(current_pkg)
                if not current or priority < current[1]:
                    candidates[current_pkg] = (label, priority)

        names.update({pkg: label for pkg, (label, _) in candidates.items()})
        return names
    
    def start_app(self, package_name: str, serial: str):
        return self.run_command(["shell", "monkey", "-p", package_name, "-c", "android.intent.category.LAUNCHER", "1"], serial=serial)
    
    def stop_app(self, package_name: str, serial: str):
        return self.run_command(["shell", "am", "force-stop", package_name], serial=serial)
    
    def get_current_app(self, serial: str) -> str:
        result = self.run_command(["shell", "dumpsys", "window", "|", "grep", "-E", "mCurrentFocus"], serial=serial)
        if result.returncode == 0:
            output = result.stdout.strip()
            if "/" in output:
                try:
                    return output.split("{")[1].split("}")[0].split("/")[0]
                except:
                    pass
        return ""
    
    def restart_adb(self):
        subprocess.run([self.adb_path, "kill-server"], capture_output=True)
        subprocess.run([self.adb_path, "start-server"], capture_output=True)
