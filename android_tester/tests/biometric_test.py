from typing import Callable, Dict, Any
from .base_test import BaseTest
from ..privilege_manager import PrivilegeManager
import re

class BiometricTest(BaseTest):
    # Universal: fingerprint (egis/fpc/goodix), face, iris via dumpsys + sysfs.
    # Detects PRESENT_BROKEN (HAL dead/driver missing) vs PRESENT_UNTESTED (no enrollments).
    async def run(self, pm: PrivilegeManager, log_cb: Callable[[str], None], **kwargs) -> Dict[str, Any]:
        log_cb("[INFO] Starting Biometric Health Check (universal)...")
        is_rooted = await pm.check_root()
        results = {"confidence": "ESTIMATED", "method": "dumpsys"}

        # Fingerprint service (all Android 6+)
        code, out, _ = await pm.run("dumpsys fingerprint 2>&1", privileged=False)
        if "Can't find service" in out or (not out.strip()):
            # Distinguish system down from hardware absent via service manager
            _, svc, _ = await pm.run("service list 2>&1", privileged=False)
            if "Found 0 services" in svc or not svc.strip():
                log_cb("[WARNING] Fingerprint unknown - system_server unready, not proof of absent hardware.")
                results['system_unready'] = True
                results['verdict'] = "UNKNOWN_UNREADY"
                log_cb("[SUCCESS] Biometric Check Complete.")
                return results
            log_cb("[INFO] No fingerprint service (device has no FP reader or service disabled).")
            results['fingerprint_present'] = False
        else:
            fp_present = "Fingerprint" in out or "sensorId" in out or "prints" in out
            if not fp_present:
                log_cb("[INFO] No fingerprint service (device has no FP reader or service disabled).")
                results['fingerprint_present'] = False
            else:
                results['fingerprint_present'] = True
            deaths = re.search(r'HAL deaths.*?(\d+)', out)
            if deaths:
                results['hal_deaths'] = int(deaths.group(1))
                log_cb(f"[INFO] Fingerprint HAL deaths: {deaths.group(1)}")
            # Enrolled count: "prints":[{"id":0,"count":0...}] or "Enrolled: N"
            enrolled = 0
            m = re.search(r'"count":\s*(\d+)', out)
            if m:
                enrolled = int(m.group(1))
            m2 = re.search(r'fingerprints?\s*enrolled[:\s]+(\d+)', out, re.I)
            if m2:
                enrolled = max(enrolled, int(m2.group(1)))
            results['fingerprints_enrolled'] = enrolled
            log_cb(f"[INFO] Fingerprints enrolled: {enrolled}")
            # Error counters
            for key in ["reject", "lockout", "acquire"]:
                mm = re.search(rf'"{key}":\s*(\d+)', out)
                if mm and int(mm.group(1)) > 0:
                    log_cb(f"[INFO] FP {key}: {mm.group(1)}")
                    results[f'fp_{key}'] = int(mm.group(1))

        # Face / biometric (Android 10+)
        code2, out2, _ = await pm.run("dumpsys biometric 2>&1", privileged=False)
        if "modality" in out2 or "Sensors:" in out2:
            log_cb(f"[INFO] Biometric service present.")
            results['biometric_service'] = True
        code3, out3, _ = await pm.run("dumpsys face 2>&1", privileged=False)
        if "Can't find service" in out3:
            results['face_present'] = False
        elif out3.strip():
            results['face_present'] = True
            log_cb("[INFO] Face HAL present.")

        if is_rooted:
            results["confidence"] = "VERIFIED"
            # Driver nodes: egis (Samsung M20), fpc, goodix, focaltech - check all universally
            code, out, _ = await pm.run("ls /dev/esfp0 /dev/fingerprint* /dev/fpc* /dev/goodix* 2>&1; ls -d /sys/class/egis* /sys/class/fingerprint* /sys/class/fpc* /sys/class/goodix* 2>&1", privileged=True)
            drv_lines = [l for l in out.strip().splitlines() if l.strip() and not l.strip().startswith("ls:")]
            if "/dev/esfp0" in out or "egis" in out or "fpc" in out or "goodix" in out or any("/sys/class" in l for l in drv_lines):
                log_cb(f"[SUCCESS] FP driver nodes present: {'; '.join(drv_lines)[:150]}")
                results['driver_present'] = True
            else:
                log_cb("[WARNING] No FP driver nodes found.")
                results['driver_present'] = False
            # Kernel errors: egis/fpc auth failures indicate broken reader
            code, out, _ = await pm.run("dmesg 2>/dev/null | grep -i -E 'egis|fpc|goodix|fingerprint.*(fail|error|timeout|dead)' | tail -n 10", privileged=True)
            if out.strip():
                errs = [l for l in out.strip().split('\n') if any(k in l.lower() for k in ["fail", "error", "timeout", "dead", "firmware"])]
                if errs:
                    log_cb(f"[WARNING] FP kernel errors: {errs[0][:150]}")
                    results['kernel_errors'] = errs[:3]
                else:
                    log_cb("[INFO] FP driver active, no kernel errors (interrupts OK).")

        # Verdict (universal logic)
        if not results.get('fingerprint_present', False) and not results.get('face_present', False):
            results['verdict'] = "ABSENT"
            log_cb("[INFO] No biometric hardware detected.")
        elif results.get('hal_deaths', 0) > 0 or results.get('driver_present') is False:
            results['verdict'] = "PRESENT_BROKEN"
            log_cb("[ERROR] Biometric present but HAL dead or driver missing - reader likely broken.")
        elif results.get('fingerprints_enrolled', 0) == 0:
            results['verdict'] = "PRESENT_UNTESTED"
            log_cb("[WARNING] Fingerprint reader present but 0 enrolled - enroll a finger in Settings to test. If enroll fails on custom ROM with mixed fingerprints, vendor HAL mismatch is the cause.")
        else:
            results['verdict'] = "PRESENT_WORKING"
            log_cb("[SUCCESS] Biometric working (enrollments present, HAL alive).")

        log_cb("[SUCCESS] Biometric Check Complete.")
        return results
