import json
import os
import re
from datetime import datetime
from .privilege_manager import PrivilegeManager

class AuditEngine:
    # Universal: structured results preferred, log-scraping kept as fallback.
    # thresholds.yaml loaded without external deps so scoring is fair per-SoC.
    def __init__(self, thresholds_path: str = "config/thresholds.yaml"):
        self.logs = []
        self.crashes = []
        self.max_temp = 0.0
        self.sensors_found = 0
        self.sensors_idle = 0
        self.sensors_dead = 0
        self.storage_write_speed = 0.0
        self.storage_read_speed = 0.0
        self.framework_crashed = False
        self.test_results = {}
        self.thresholds = self._load_thresholds(thresholds_path)
        self.active_profile = "default"

    def _load_thresholds(self, path: str) -> dict:
        data, cur = {}, None
        for base in [path, os.path.join(os.path.dirname(__file__), "..", path), "/mnt/9f4d8733-a954-435d-b92f-f33c068c3b1e/TSF/AndroidTestSuite/config/thresholds.yaml"]:
            if os.path.exists(base):
                path = base
                break
        try:
            with open(path) as f:
                for line in f:
                    if not line.strip() or line.strip().startswith("#"):
                        continue
                    if re.match(r'^\S.*:$', line.strip()):
                        cur = line.strip()[:-1]
                        data[cur] = {}
                    elif cur and ":" in line:
                        k, v = line.strip().split(":", 1)
                        try:
                            data[cur][k.strip()] = float(v.strip())
                        except ValueError:
                            data[cur][k.strip()] = v.strip()
        except FileNotFoundError:
            pass
        if "default" not in data:
            data["default"] = {"max_temp_warning_c": 80.0, "max_temp_critical_c": 90.0,
                               "min_storage_write_mbps": 30.0, "min_battery_wear_pct": 80.0,
                               "critical_battery_wear_pct": 60.0}
        return data

    def _profile_for(self, soc: str) -> dict:
        s = (soc or "").lower().replace(" ", "_").replace("-", "_")
        for key in self.thresholds:
            if key != "default" and key in s:
                self.active_profile = key
                return self.thresholds[key]
        # Exynos 7904 (M20) contains "7904" but not full key -> map low-end
        if "7904" in s or "exynos" in s:
            self.active_profile = "exynos_7904" if "exynos_7904" in self.thresholds else "default"
            return self.thresholds[self.active_profile]
        self.active_profile = "default"
        return self.thresholds["default"]

    def add_log(self, message: str):
        self.logs.append(f"[{datetime.now().time()}] {message}")
        if "FATAL" in message or "ANR in" in message or "CRASH" in message:
            self.crashes.append(message)
        if "Thermal Zone:" in message:
            try:
                # Handles "Thermal Zone: 52.0C", "Thermal Zone: BIG 52.0C"
                nums = re.findall(r'([\d.]+)\s*C', message)
                for n in nums:
                    t = float(n)
                    if 0 < t < 150 and t > self.max_temp:
                        self.max_temp = t
            except ValueError:
                pass
        if "Discovered" in message and "sensor" in message.lower():
            try:
                nums = re.findall(r'(\d+)\s*(?:HW|hardware|virtual|\+)?', message)
                if nums:
                    self.sensors_found = max(self.sensors_found, int(nums[0]))
            except ValueError:
                pass
        if "[IDLE]" in message:
            self.sensors_idle += 1
        if "Storage Write Speed:" in message:
            try:
                self.storage_write_speed = float(message.split(":")[1].replace("MB/s", "").strip().split()[0])
            except (ValueError, IndexError):
                pass
        if "Storage Read Speed:" in message or "Raw Storage Read Speed:" in message:
            try:
                v = float(re.search(r'([\d.]+)\s*MB/s', message).group(1))
                if v > self.storage_read_speed:
                    self.storage_read_speed = v
            except (AttributeError, ValueError):
                pass
        if "[ERROR] Sensor Framework" in message:
            self.framework_crashed = True

    def add_test_results(self, test_name: str, results: dict):
        self.test_results[test_name] = results
        # Structured overrides (authoritative over log scraping)
        if isinstance(results, dict):
            if "max_temp_c" in results and isinstance(results["max_temp_c"], (int, float)):
                self.max_temp = max(self.max_temp, float(results["max_temp_c"]))
            if "write_speed_mb" in results:
                try:
                    self.storage_write_speed = max(self.storage_write_speed, float(results["write_speed_mb"]))
                except (ValueError, TypeError):
                    pass
            if "read_speed_mb" in results:
                try:
                    self.storage_read_speed = max(self.storage_read_speed, float(results["read_speed_mb"]))
                except (ValueError, TypeError):
                    pass
            if "sensors_found" in results:
                self.sensors_found = max(self.sensors_found, int(results.get("sensors_found", 0) or 0))
            if "sensors_idle" in results:
                self.sensors_idle = max(self.sensors_idle, int(results.get("sensors_idle", 0) or 0))
            # Only true dead counts (framework crash path), idle is not dead
            if results.get("framework_crashed"):
                self.framework_crashed = True

    def calculate_score(self) -> tuple:
        soc = ""
        if 'CpuTest' in self.test_results:
            soc = self.test_results['CpuTest'].get('soc', '')
        th = self._profile_for(soc)
        score = 100
        score -= min(50, len(self.crashes) * 5)
        if self.max_temp >= th.get("max_temp_critical_c", 90):
            score -= 20
        elif self.max_temp >= th.get("max_temp_warning_c", 80):
            score -= 10
        min_w = th.get("min_storage_write_mbps", 30)
        if self.storage_write_speed > 0 and self.storage_write_speed < min_w:
            score -= 10
        # Idle sensors are NOT penalized (universal fix); only framework crash is
        if self.framework_crashed:
            score -= 20
        if 'CpuTest' in self.test_results and self.test_results['CpuTest'].get('throttle_detected'):
            score -= 10
        if 'BatteryTest' in self.test_results and 'wear_pct' in self.test_results['BatteryTest']:
            try:
                wear = float(self.test_results['BatteryTest']['wear_pct'])
                if wear < th.get("critical_battery_wear_pct", 60):
                    score -= 25
                elif wear < th.get("min_battery_wear_pct", 80):
                    score -= 10
            except (ValueError, TypeError):
                pass
        if 'NetworkTest' in self.test_results and self.test_results['NetworkTest'].get('icmp_blocked'):
            pass  # not penalized: carrier filtering is not device fault
        if 'BiometricTest' in self.test_results and self.test_results['BiometricTest'].get('verdict') == 'PRESENT_BROKEN':
            score -= 10
        if 'AuthenticityTest' in self.test_results and self.test_results['AuthenticityTest'].get('partition_mismatch'):
            score -= 5  # hybrid ROM risks closed-source HALs
        if 'OOMTest' in self.test_results and self.test_results['OOMTest'].get('verdict') == 'CRITICAL':
            score -= 15
        elif 'OOMTest' in self.test_results and self.test_results['OOMTest'].get('verdict') == 'WARN':
            score -= 5
        if 'HardwarePresenceTest' in self.test_results and self.test_results['HardwarePresenceTest'].get('camera_back', 1) == 0:
            score -= 10
        if 'StorageTest' in self.test_results and self.test_results['StorageTest'].get('wear_consumed_pct', 0) >= 90:
            score -= 15
        health = max(0, score)
        applicable = sum(1 for r in self.test_results.values() if isinstance(r, dict) and 'confidence' in r)
        verified = sum(1 for r in self.test_results.values() if isinstance(r, dict) and r.get('confidence') == 'VERIFIED')
        conf = int(verified / applicable * 100) if applicable else 0
        return health, conf

    def recommendations(self) -> list:
        recs = []
        r = self.test_results
        if r.get('BatteryTest', {}).get('wear_pct', 100) < 80:
            recs.append("Battery worn (<80%) - consider replacement.")
        if r.get('StorageTest', {}).get('wear_consumed_pct', 0) >= 70:
            recs.append(f"Storage worn ({r['StorageTest']['wear_consumed_pct']}% consumed) - back up data, replace board soon.")
        if self.max_temp >= 80:
            recs.append(f"Peak {self.max_temp}C - clean fans/paste, check throttling.")
        if r.get('CpuTest', {}).get('throttle_detected'):
            recs.append("CPU throttles under load - thermal issue.")
        if r.get('BiometricTest', {}).get('verdict') == 'PRESENT_BROKEN':
            recs.append("Fingerprint reader broken - check HAL/driver.")
        if r.get('BiometricTest', {}).get('verdict') == 'PRESENT_UNTESTED' and r.get('AuthenticityTest', {}).get('partition_mismatch'):
            recs.append("FP untested + hybrid ROM - enroll will likely fail; restore matching vendor.")
        if r.get('AuthenticityTest', {}).get('partition_mismatch'):
            recs.append("Hybrid fingerprints (stock+Lineage) - reflash matching vendor for closed-source HALs.")
        if r.get('OOMTest', {}).get('verdict') in ('WARN', 'CRITICAL'):
            recs.append("Low RAM - close apps, consider lighter ROM.")
        if r.get('HardwarePresenceTest', {}).get('camera_back', 1) == 0:
            recs.append("No back camera detected - check camera HAL/connection.")
        if self.crashes:
            recs.append(f"{len(self.crashes)} crashes/ANRs - inspect logcat/tombstones.")
        if not recs:
            recs.append("No action required - device healthy.")
        return recs

    def generate_report(self, filepath: str, pm: PrivilegeManager):
        score, confidence = self.calculate_score()
        with open(filepath, "w") as f:
            f.write("# Android Testing Suite - Deep Audit Report\n\n")
            f.write(f"**Date Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write("## Test Conditions\n")
            f.write(f"- **Root Status:** {'Rooted' if pm.is_rooted else 'Not Rooted'}\n")
            f.write(f"- **SU Implementation:** {pm.su_impl}\n")
            f.write(f"- **SELinux Mode:** {pm.selinux_mode}\n")
            f.write(f"- **Confidence Score:** {confidence}% VERIFIED\n")
            f.write(f"- **Scoring Profile:** {self.active_profile}\n\n")
            f.write("## Overall Health Rating\n")
            if score >= 90:
                f.write(f"> **Score: {score}/100 - EXCELLENT**\n\n")
            elif score >= 70:
                f.write(f"> **Score: {score}/100 - FAIR**\n\n")
            else:
                f.write(f"> **Score: {score}/100 - POOR**\n\n")
            f.write("### Key Metrics\n")
            f.write(f"- **Peak Temperature:** {self.max_temp}C\n")
            f.write(f"- **Storage Write:** {self.storage_write_speed} MB/s\n")
            f.write(f"- **Storage Read:** {self.storage_read_speed} MB/s\n")
            f.write(f"- **Sensors Found:** {self.sensors_found} (Idle: {self.sensors_idle}, Dead: {self.sensors_dead})\n")
            f.write(f"- **Fatal Crashes:** {len(self.crashes)}\n\n")
            f.write("## Recommendations\n")
            for rec in self.recommendations():
                f.write(f"- {rec}\n")
            f.write("\n## Detailed Test Results\n")
            for name, res in self.test_results.items():
                f.write(f"**{name} [{res.get('confidence', 'ESTIMATED')}]**\n")
                for k, v in res.items():
                    if k != 'confidence':
                        f.write(f"- {k}: {v}\n")
                f.write("\n")
            f.write("## System Stability\n")
            if not self.crashes:
                f.write("No crashes or ANRs detected.\n\n")
            else:
                for c in self.crashes:
                    f.write(f"- `{c}`\n")
            f.write("\n## Full Execution Log\n```text\n")
            for log in self.logs:
                f.write(log + "\n")
            f.write("```\n")
        # Universal machine-readable export alongside MD
        try:
            jpath = filepath.rsplit(".", 1)[0] + ".json"
            with open(jpath, "w") as jf:
                json.dump({"date": datetime.now().isoformat(), "score": score,
                           "confidence": confidence, "profile": self.active_profile,
                           "rooted": pm.is_rooted, "su": pm.su_impl,
                           "recommendations": self.recommendations(),
                           "results": self.test_results}, jf, indent=2, default=str)
        except Exception:
            pass
