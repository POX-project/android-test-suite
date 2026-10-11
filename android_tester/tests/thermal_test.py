from typing import Callable, Dict, Any
from .base_test import BaseTest
from ..privilege_manager import PrivilegeManager
import asyncio

class ThermalTest(BaseTest):
    async def run(self, pm: PrivilegeManager, log_cb: Callable[[str], None], duration_sec: int = 10, **kwargs) -> Dict[str, Any]:
        log_cb("[INFO] Starting Thermal Test (universal)...")

        is_rooted = await pm.check_root()
        results = {"confidence": "ESTIMATED", "method": "unknown"}

        code, core_out, _ = await pm.run("nproc", privileged=False)
        try:
            cores = max(1, min(int(core_out.strip()), 16))
        except ValueError:
            cores = 4

        if is_rooted:
            results["confidence"] = "VERIFIED"
            # Universal baseline BEFORE load (all vendors expose thermal_zone*/type+temp)
            # NOTE: $ escaped so host shell does not expand before adb.
            code, out, _ = await pm.run("for z in /sys/class/thermal/thermal_zone*; do t=$(cat $z/type 2>/dev/null); v=$(cat $z/temp 2>/dev/null); echo \"$t=$v\"; done", privileged=True)
            before = self._parse_zones(out)
            log_cb(f"[INFO] Baseline zones: {self._fmt(before)}")

            # Non-blocking load: start in background, poll temps concurrently
            log_cb(f"[INFO] CPU load {cores} cores x {duration_sec}s + 1s temp polling...")
            await pm.run(f"for i in $(seq 1 {cores}); do (md5sum /dev/urandom &>/dev/null & echo $! >> /data/local/tmp/thermal_pids); done; echo STARTED", privileged=False)
            peak = dict(before)
            for _ in range(duration_sec):
                await asyncio.sleep(1)
                code, out, _ = await pm.run("for z in /sys/class/thermal/thermal_zone*; do t=$(cat $z/type 2>/dev/null); v=$(cat $z/temp 2>/dev/null); echo \"$t=$v\"; done", privileged=True)
                cur = self._parse_zones(out)
                for k, v in cur.items():
                    if v > peak.get(k, 0):
                        peak[k] = v
            await pm.run("kill -9 $(cat /data/local/tmp/thermal_pids 2>/dev/null) 2>/dev/null; rm -f /data/local/tmp/thermal_pids", privileged=False)

            log_cb(f"[INFO] Peak zones: {self._fmt(peak)}")
            for k, v in peak.items():
                log_cb(f"Thermal Zone: {k} {v:.1f}C")
            # Overall max for audit_engine compat (also keep "Thermal Zone: X" generic line)
            mx = max(peak.values()) if peak else 0
            log_cb(f"Thermal Zone: {mx:.1f}C")
            results["zones_peak_c"] = {k: round(v, 1) for k, v in peak.items()}
            results["max_temp_c"] = round(mx, 1)
            results["method"] = "thermal_zone-poll"
            results["status"] = "success"
        else:
            log_cb("[INFO] No-root: thermalservice + battery temp...")
            code, out, _ = await pm.run("dumpsys thermalservice 2>&1 | head -n 20", privileged=False)
            throttle = "throttling" in out.lower()
            if throttle:
                log_cb("[WARNING] thermalservice reports throttling.")
            results["throttling"] = throttle
            code, out, _ = await pm.run("dumpsys battery 2>&1 | grep temperature", privileged=False)
            for line in out.split('\n'):
                if 'temperature' in line:
                    try:
                        t = int(line.split(':')[1].strip()) / 10.0
                        log_cb(f"Thermal Zone: {t:.1f}C")
                        results["battery_temp"] = t
                        results["max_temp_c"] = t
                    except (ValueError, IndexError):
                        pass
            results["method"] = "dumpsys"

        log_cb("[SUCCESS] Thermal Test complete.")
        return results

    def _parse_zones(self, text: str) -> dict:
        zones = {}
        for line in text.strip().split('\n'):
            if '=' in line:
                k, v = line.split('=', 1)
                k, v = k.strip(), v.strip()
                if k and v.lstrip('-').isdigit():
                    raw = int(v)
                    # Universal: some kernels report milli-C (43000), some C (43)
                    c = raw / 1000.0 if raw > 200 else float(raw)
                    if -20 < c < 150:
                        zones[k] = c
        return zones

    def _fmt(self, zones: dict) -> str:
        return ", ".join(f"{k} {v:.0f}C" for k, v in list(zones.items())[:8])
