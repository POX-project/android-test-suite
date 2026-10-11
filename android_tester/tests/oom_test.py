from typing import Callable, Dict, Any
from .base_test import BaseTest
from ..privilege_manager import PrivilegeManager
import re

class OOMTest(BaseTest):
    # Deep audit: was just "drop caches", useless. Now real RAM health.
    async def run(self, pm: PrivilegeManager, log_cb: Callable[[str], None], **kwargs) -> Dict[str, Any]:
        log_cb("[INFO] Starting Memory Health Check (universal)...")
        is_rooted = await pm.check_root()
        results = {"confidence": "VERIFIED", "method": "meminfo"}

        code, out, _ = await pm.run("cat /proc/meminfo", privileged=False)
        mem = {}
        for line in out.split('\n'):
            m = re.match(r'(\w+):\s+(\d+)', line)
            if m:
                mem[m.group(1)] = int(m.group(2))
        total = mem.get('MemTotal', 0)
        avail = mem.get('MemAvailable', mem.get('MemFree', 0))
        if total > 0:
            pct = avail / total * 100
            log_cb(f"[INFO] RAM: {total//1024}MB total, {avail//1024}MB available ({pct:.0f}%)")
            results.update({'ram_total_mb': total // 1024, 'ram_avail_mb': avail // 1024, 'ram_avail_pct': round(pct, 1)})
            if pct < 10:
                log_cb("[ERROR] Critically low RAM (<10% available).")
                results['verdict'] = "CRITICAL"
            elif pct < 20:
                log_cb("[WARNING] Low RAM (<20%).")
                results['verdict'] = "WARN"
            else:
                results['verdict'] = "OK"
        # Swap / zram (universal low-RAM indicator)
        code, out, _ = await pm.run("cat /proc/swaps 2>/dev/null; cat /sys/block/zram0/disksize 2>/dev/null", privileged=False)
        if out.strip():
            results['swap_info'] = out.strip()[:200]
        # LMK kills since boot (root: vmpressure / lowmemorykiller)
        if is_rooted:
            code, out, _ = await pm.run("dmesg 2>/dev/null | grep -i -c 'lowmemorykiller\\|lmk.*kill'", privileged=True)
            if out.strip().isdigit():
                kills = int(out.strip())
                log_cb(f"[INFO] LMK kills since boot: {kills}")
                results['lmk_kills'] = kills
                if kills > 50:
                    log_cb("[WARNING] Frequent LMK kills - RAM pressure.")
        log_cb("[SUCCESS] Memory Check Complete.")
        return results

# Alias: file is oom_test.py for compat, class is memory health.
MemoryTest = OOMTest
