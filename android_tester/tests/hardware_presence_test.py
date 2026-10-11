from typing import Callable, Dict, Any
from .base_test import BaseTest
from ..privilege_manager import PrivilegeManager

class HardwarePresenceTest(BaseTest):
    # Universal presence oracle: service list + dumpsys. Catches dead camera/mic/vibrator/gps/nfc.
    async def run(self, pm: PrivilegeManager, log_cb: Callable[[str], None], **kwargs) -> Dict[str, Any]:
        log_cb("[INFO] Starting Hardware Presence Check (universal)...")
        results = {"confidence": "VERIFIED", "method": "service-list"}
        code, out, _ = await pm.run("service list 2>&1", privileged=False)
        low = out.lower()
        # Minimal robustness: 0 services means system_server unready (booting/crashed), not absent hardware
        if "found 0 services" in low or not low.strip():
            _, boot, _ = await pm.run("getprop sys.boot_completed", privileged=False)
            results['system_unready'] = True
            results['confidence'] = "ESTIMATED"
            log_cb(f"[WARNING] Service manager unready (boot_completed={boot.strip()}). Device booting or system_server distressed - retry after stabilize.")
            return results
        checks = {
            'camera': ['media.camera', 'android.hardware.camera'],
            'audio': ['audio:', 'media.audio_flinger'],
            'vibrator': ['vibrator'],
            'bluetooth': ['bluetooth_manager'],
            'wifi': ['wifi'],
            'nfc': ['nfc'],
            'fingerprint': ['fingerprint:'],
            'biometric': ['biometric:'],
            'sensors': ['sensorservice'],
            'display': ['display:'],
            'battery': ['battery:'],
            'location': ['location:'],
        }
        for name, keys in checks.items():
            present = any(k in low for k in keys)
            results[f'{name}_present'] = present
            log_cb(f"[{'INFO' if present else 'WARNING'}] {name}: {'present' if present else 'ABSENT/no service'}")
        # Camera lens count (Back/Front) - real user value
        code, out, _ = await pm.run("dumpsys media.camera 2>&1", privileged=False)
        backs = out.count("Facing: Back")
        fronts = out.count("Facing: Front")
        # Fallback for A13+ format
        if backs + fronts == 0:
            import re
            ids = len(re.findall(r'Device version|deviceId|CameraId', out))
            if ids:
                backs, fronts = ids, 0
        results['camera_back'] = backs
        results['camera_front'] = fronts
        log_cb(f"[INFO] Camera HAL devices: {backs} back + {fronts} front")
        if backs == 0:
            log_cb("[ERROR] No back camera detected.")
        # Location providers (GPS) - everything-minimal: 1 dumpsys
        code, out, _ = await pm.run("dumpsys location 2>&1", privileged=False)
        import re as _re
        providers = _re.findall(r'(\w+) provider:', out)
        if providers:
            log_cb(f"[INFO] Location providers: {', '.join(sorted(set(providers)))}")
            results['location_providers'] = sorted(set(providers))
        log_cb("[SUCCESS] Presence Check Complete.")
        return results
