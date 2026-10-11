from typing import Callable, Dict, Any
from .base_test import BaseTest
from ..privilege_manager import PrivilegeManager
import re

class DisplayTouchTest(BaseTest):
    # Universal: getevent -i prints hex codes on most devices (0035=X, 0036=Y),
    # names on some (ABS_MT_POSITION_X). Samsung uses sec_touchscreen + INPUT_PROP_DIRECT.
    # MT_SLOT=0x2f, MT_POSITION_X=0x35, MT_POSITION_Y=0x36, MT_TRACKING_ID=0x39
    async def run(self, pm: PrivilegeManager, log_cb: Callable[[str], None], **kwargs) -> Dict[str, Any]:
        log_cb("[INFO] Starting Display & Touch Panel Test...")

        results = {"confidence": "VERIFIED"}  # Fully capable without root

        # Universal display metrics (works on all Android 5+)
        code, out, _ = await pm.run("wm size; wm density; dumpsys display | grep -i -m5 'mBaseDisplayInfo\\|refreshRate\\|density'", privileged=False)
        if out.strip():
            for line in out.strip().split('\n')[:6]:
                log_cb(f"[INFO] Display: {line.strip()}")
            results['display_wm'] = out.strip()[:500]

        log_cb("[INFO] Probing touch input devices (getevent)...")
        code, out, _ = await pm.run("getevent -i 2>&1", privileged=False)
        touch_found = False
        touch_name = ""
        method = "none"
        if code == 0 and out:
            # Split per-device blocks
            blocks = re.split(r'add device \d+:', out)
            for b in blocks:
                name_m = re.search(r'name:\s*"([^"]+)"', b)
                name = name_m.group(1) if name_m else ""
                has_direct = "INPUT_PROP_DIRECT" in b
                # Hex-code form (most devices incl. Samsung sec_touchscreen):
                # 002f=SLOT, 0035=X, 0036=Y, 0039=TRACKING_ID
                has_hex_mt = ("0035" in b and "0036" in b) or "002f" in b or "0039" in b
                # Named form (some QCOM/MTK):
                has_named_mt = "ABS_MT_POSITION_X" in b or "ABS_MT_POSITION_Y" in b or "ABS_MT_SLOT" in b
                is_touch_name = any(k in name.lower() for k in ["touch", "synaptics", "atmel", "sec_touch", "fts_", "goodix", "novatek", "ilitek", "elan"])
                if (has_hex_mt or has_named_mt or (has_direct and ("touch" in name.lower() or "sec_" in name.lower()))) and (is_touch_name or has_hex_mt or has_named_mt):
                    # Exclude pure sensors that coincidentally have REL codes (gyro/accel use REL, not ABS MT)
                    if has_hex_mt or has_named_mt:
                        touch_found = True
                        touch_name = name
                        method = "hex" if has_hex_mt else "named"
                        break
            if touch_found:
                log_cb(f"[SUCCESS] Digitizer identified: \"{touch_name}\" multi-touch (method={method}).")
                results['touch_device_found'] = True
                results['touch_device_name'] = touch_name
                results['touch_method'] = method
            else:
                # Fallback: InputReader dump lists TouchInputMapper universally
                code2, out2, _ = await pm.run("dumpsys input | grep -i -m10 'TouchInputMapper\\|sec_touchscreen\\| touchscreen'", privileged=False)
                if out2.strip():
                    log_cb(f"[SUCCESS] Touch mapper found via dumpsys input: {out2.strip().splitlines()[0][:120]}")
                    results['touch_device_found'] = True
                    results['touch_method'] = "dumpsys-input"
                else:
                    log_cb("[WARNING] No multi-touch digitizer identified (checked hex 0035/0036, named ABS_MT, dumpsys input).")
                    results['touch_device_found'] = False
                    results['touch_method'] = "none"
        else:
            log_cb("[WARNING] getevent -i failed or empty.")
            results['touch_device_found'] = False

        log_cb("[SUCCESS] Display & Touch Test Complete.")
        return results
