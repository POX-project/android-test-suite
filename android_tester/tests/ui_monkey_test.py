from typing import Callable, Dict, Any
from .base_test import BaseTest
from ..privilege_manager import PrivilegeManager
import re

class UIMonkeyTest(BaseTest):
    async def run(self, pm: PrivilegeManager, log_cb: Callable[[str], None], event_count: int = 1000, **kwargs) -> Dict[str, Any]:
        log_cb(f"[INFO] Starting Stability Test (monkey {event_count} events)...")
        # Clear crash buffers first so we attribute only new crashes
        await pm.run("logcat -c", privileged=False)
        code, out, err = await pm.run(f"monkey -v {event_count} --throttle 5 2>&1", privileged=False)
        combined = out + err
        injected = re.search(r'Events injected:\s*(\d+)', combined)
        crashes = len(re.findall(r'// (CRASH|NOT RESPONDING|ANR)', combined))
        log_cb(f"[INFO] Events injected: {injected.group(1) if injected else '?'}")
        # Tombstones since test (native crashes monkey misses)
        code2, out2, _ = await pm.run("ls /data/tombstones 2>/dev/null | wc -l; dumpsys dropbox --print data_app_crash 2>&1 | grep -c 'FATAL'", privileged=False)
        results = {"confidence": "ESTIMATED", "method": "monkey",
                   "events": int(injected.group(1)) if injected else 0,
                   "monkey_crashes": crashes, "tombstone_hint": out2.strip()[:100]}
        if crashes > 0:
            log_cb(f"[ERROR] Monkey triggered {crashes} app crashes/ANRs.")
        else:
            log_cb("[SUCCESS] Monkey completed with no app crashes.")
        return results
