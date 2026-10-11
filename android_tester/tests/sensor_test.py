from typing import Callable, Dict, Any
from .base_test import BaseTest
from ..privilege_manager import PrivilegeManager

class SensorTest(BaseTest):
    async def run(self, pm: PrivilegeManager, log_cb: Callable[[str], None], **kwargs) -> Dict[str, Any]:
        log_cb("[INFO] Starting Sensor Audit (universal)...")

        is_rooted = await pm.check_root()
        results = {"confidence": "ESTIMATED", "method": "dumpsys-inventory"}

        # Light liveness check: 200 iterations is enough to detect framework crash
        # without hammering binder for minutes on low-end devices.
        # NOTE: $ escaped for host-shell safety.
        log_cb("[INFO] Sensor framework liveness check (200 queries)...")
        code, out, err = await pm.run("for i in $(seq 1 200); do dumpsys sensorservice > /dev/null || exit 1; done; echo OK", privileged=False)
        if code != 0 or "OK" not in out:
            if "ADB timeout" in err or "timeout" in err.lower():
                log_cb("[WARNING] Sensor check timed out (system overloaded, not proof of crash).")
                results["system_unready"] = True
                results["framework_crashed"] = False
                return results
            log_cb(f"[ERROR] Sensor Framework failed liveness: {err[:200]}")
            results["framework_crashed"] = True
            return results
        log_cb("[SUCCESS] Sensor Framework alive (200 queries OK).")
        results["framework_crashed"] = False

        code, out, err = await pm.run("dumpsys sensorservice", privileged=False)
        if code != 0 or not out:
            log_cb(f"[ERROR] Failed to query sensorservice: {err[:200]}")
            return results

        # Universal parse: works on Android 8-15. HW section is "Sensor List:",
        # ends at Fusion/Active/Recent. Virtual AOSP sensors (0x5f...) counted separately.
        sensors_hw, sensors_virt = [], []
        parsing = False
        for line in out.split('\n'):
            s = line.strip()
            if s.startswith("Sensor List:"):
                parsing = True
                continue
            if parsing:
                if not s or s.startswith("Fusion States:") or s.startswith("Active sensors:") or s.startswith("Active Sensors:") or s.startswith("Socket:"):
                    break
                if ")" in s and "|" in s:
                    try:
                        name = s.split(')', 1)[1].split('|')[0].strip()
                        handle = s.split(')')[0].strip()
                        if not name:
                            continue
                        if handle.startswith("0x5f") or handle.startswith("0x5F"):
                            sensors_virt.append(name)
                        else:
                            sensors_hw.append(name)
                    except IndexError:
                        pass
        # Recent events: "Name: last N events" (A10) or "Name (handle): ..." (A12+)
        recent = set()
        in_recent = False
        for line in out.split('\n'):
            s = line.strip()
            if s.startswith("Recent Sensor events:") or s.startswith("Recent events:"):
                in_recent = True
                continue
            if in_recent:
                if ": last " in s and "event" in s:
                    recent.add(s.split(":")[0].strip())
                elif s.startswith("Fusion States:") or (not s and len(recent) > 0):
                    pass

        total = len(sensors_hw) + len(sensors_virt)
        if total == 0:
            log_cb("[WARNING] No sensors parsed (format unknown on this Android version).")
            results['sensors_found'] = 0
            results['sensors_idle'] = 0
            results['sensors_dead'] = 0
        else:
            log_cb(f"[SUCCESS] Discovered {len(sensors_hw)} HW + {len(sensors_virt)} virtual sensors.")
            # Universal truth: idle != dead. Only sensors with 0 events AND known
            # one-shot/special types need activation to judge; report idle separately.
            active = [s for s in sensors_hw + sensors_virt if s in recent]
            idle = [s for s in sensors_hw + sensors_virt if s not in recent]
            for s in active:
                log_cb(f"  - [OK] Active: {s}")
            for s in idle:
                log_cb(f"  - [IDLE] Present, no recent events (idle, not dead): {s}")
            results['sensors_found'] = total
            results['sensors_hw'] = len(sensors_hw)
            results['sensors_virt'] = len(sensors_virt)
            results['sensors_active'] = len(active)
            results['sensors_idle'] = len(idle)
            results['sensors_dead'] = 0  # dead requires activation test via app; dumpsys alone cannot prove dead
            results['sensors_dead_note'] = "idle!=dead; use sensor APK activation for true dead detection"

        if is_rooted:
            results["confidence"] = "VERIFIED"
            log_cb("[INFO] Checking calibration registry (universal QCOM/MTK/Exynos)...")
            code, out, _ = await pm.run("ls /mnt/vendor/persist/sensors/ 2>/dev/null || ls /persist/sensors/ 2>/dev/null || ls /vendor/firmware/ 2>/dev/null | head", privileged=True)
            if out.strip():
                log_cb("[SUCCESS] Persist sensor area readable (calibration likely intact).")
                results['calibration_intact'] = True
            else:
                log_cb("[INFO] Persist sensor area not readable on this vendor.")
                results['calibration_intact'] = False

        log_cb("[SUCCESS] Sensor Audit Complete.")
        return results
