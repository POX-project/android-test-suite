from typing import Callable, Dict, Any
from .base_test import BaseTest
from ..privilege_manager import PrivilegeManager

class BatteryTest(BaseTest):
    async def run(self, pm: PrivilegeManager, log_cb: Callable[[str], None], **kwargs) -> Dict[str, Any]:
        log_cb("[INFO] Starting Battery Health Test...")

        is_rooted = await pm.check_root()
        results = {"confidence": "ESTIMATED", "method": "dumpsys"}

        log_cb("[INFO] Reading live snapshot (No-Root)...")
        code, out, _ = await pm.run("dumpsys battery", privileged=False)
        for line in out.split('\n'):
            line = line.strip()
            if line.startswith('level:'):
                log_cb(f"[INFO] Charge Level: {line.split(':')[1].strip()}%")
                results['charge_level'] = line.split(':')[1].strip()
            elif line.startswith('status:'):
                log_cb(f"[INFO] Status: {line.split(':')[1].strip()}")
                results['status'] = line.split(':')[1].strip()
            elif line.startswith('health:'):
                log_cb(f"[INFO] Health: {line.split(':')[1].strip()}")
                results['health'] = line.split(':')[1].strip()
            elif line.startswith('temperature:'):
                try:
                    t = int(line.split(':')[1].strip()) / 10.0
                    log_cb(f"[INFO] Battery Temp (dumpsys): {t:.1f}C")
                    results['temp_c'] = t
                except ValueError:
                    pass
            elif line.startswith('voltage:'):
                try:
                    v = int(line.split(':')[1].strip())
                    results['voltage_mv'] = v
                except ValueError:
                    pass

        # Universal current: try battery/current_now then fg variants (uA, some negative=charging)
        for node in ["cat /sys/class/power_supply/battery/current_now",
                     "cat /sys/class/power_supply/battery/batt_current_ua_now",
                     "cat /sys/class/power_supply/bms/current_now"]:
            code, out, _ = await pm.run(node, privileged=False)
            if code == 0 and out.strip().lstrip('-').isdigit():
                try:
                    current_ma = abs(int(out.strip())) / 1000.0
                    log_cb(f"[INFO] Current (abs): {current_ma:.0f} mA via {node.split()[-1]}")
                    results['current_draw_ma'] = round(current_ma, 1)
                    break
                except ValueError:
                    pass

        if is_rooted:
            log_cb("[INFO] Running Root-Enhanced Battery Wear Check (universal)...")
            wear_found = False
            # Path 1: standard AOSP (Pixel, Moto, OnePlus)
            code, full, _ = await pm.run("cat /sys/class/power_supply/battery/charge_full 2>/dev/null", privileged=True)
            code2, design, _ = await pm.run("cat /sys/class/power_supply/battery/charge_full_design 2>/dev/null", privileged=True)
            if full.strip().isdigit() and design.strip().isdigit() and int(design.strip()) > 0:
                wear = int(full.strip()) / int(design.strip()) * 100
                # sanity: wear 50-105% else units mismatch (nAh vs uAh) -> skip
                if 50 <= wear <= 105:
                    wear = min(wear, 100.0)
                    log_cb(f"[SUCCESS] Battery Health: {wear:.1f}% ({full.strip()}/{design.strip()} uAh, AOSP gauge)")
                    results['wear_pct'] = round(wear, 1)
                    results['method'] = "charge_full/design"
                    wear_found = True
                    results["confidence"] = "VERIFIED"
            # Path 2: Samsung (batt_capacity_max=1000 means 100%, battery_cycle, charge_full alone)
            if not wear_found:
                code, capmax, _ = await pm.run("cat /sys/class/power_supply/battery/batt_capacity_max 2>/dev/null", privileged=True)
                code3, bcount, _ = await pm.run("cat /sys/class/power_supply/battery/charge_counter 2>/dev/null; cat /sys/class/power_supply/battery/batt_read_adj_soc 2>/dev/null", privileged=True)
                if capmax.strip().isdigit():
                    # Samsung capmax is 0-1000 scale
                    pct = int(capmax.strip()) / 10.0
                    if 50 <= pct <= 100:
                        log_cb(f"[SUCCESS] Battery Health (Samsung gauge batt_capacity_max): {pct:.1f}%")
                        results['wear_pct'] = round(pct, 1)
                        results['method'] = "samsung-batt_capacity_max"
                        wear_found = True
                        results["confidence"] = "VERIFIED"
            # Path 3: charge_full vs design from power_profile or fixed known (fallback: report full only)
            if not wear_found and full.strip().isdigit():
                try:
                    mah = int(full.strip()) / 1000.0
                    log_cb(f"[INFO] charge_full={mah:.0f} mAh but no design reference on this vendor; reporting capacity only.")
                    results['charge_full_mah'] = round(mah, 0)
                    results['method'] = "charge_full-only"
                    results["confidence"] = "ESTIMATED"
                except ValueError:
                    pass
            if not wear_found and 'wear_pct' not in results:
                log_cb("[INFO] No calibrated wear node on this vendor (checked AOSP + Samsung). Wear=ESTIMATED.")
            # Cycle: try all known nodes universally
            for node in ["cat /sys/class/power_supply/battery/cycle_count 2>/dev/null",
                         "cat /sys/class/power_supply/battery/battery_cycle 2>/dev/null",
                         "cat /sys/class/power_supply/bms/cycle_count 2>/dev/null"]:
                code, cc, _ = await pm.run(node, privileged=True)
                cc = cc.strip()
                if cc.lstrip('-').isdigit() and int(cc) >= 0:
                    log_cb(f"[INFO] Cycle Count: {cc} via {node.split()[-1]}")
                    results['cycle_count'] = cc
                    break

        log_cb("[SUCCESS] Battery Test Complete.")
        return results
