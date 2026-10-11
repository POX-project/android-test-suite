from typing import Callable, Dict, Any
from .base_test import BaseTest
from ..privilege_manager import PrivilegeManager
import time

class CpuTest(BaseTest):
    async def run(self, pm: PrivilegeManager, log_cb: Callable[[str], None], **kwargs) -> Dict[str, Any]:
        log_cb("[INFO] Starting CPU Benchmark and Throttle Test...")
        is_rooted = await pm.check_root()
        results = {"confidence": "ESTIMATED", "method": "on-device-sha256"}

        # Universal SoC info (no root needed)
        code, out, _ = await pm.run("getprop ro.soc.model", privileged=False)
        soc = out.strip()
        if not soc:
            _, out, _ = await pm.run("getprop ro.hardware", privileged=False)
            soc = out.strip()
        if soc:
            log_cb(f"[INFO] SoC: {soc}")
            results["soc"] = soc
        code, out, _ = await pm.run("nproc", privileged=False)
        try:
            results["cores"] = int(out.strip())
            log_cb(f"[INFO] Cores: {results['cores']}")
        except ValueError:
            pass

        # Universal benchmark: single on-device shell loop removes adb RTT noise.
        # 30MB file + 8x sha256 gives ~0.5-2s per iter on mid-range, measurable on all SoCs.
        # NOTE: $ escaped so host shell does not expand before adb.
        log_cb("[INFO] Running on-device CPU benchmark (30MB sha256 x8, timed inside device)...")
        await pm.run("dd if=/dev/urandom of=/data/local/tmp/cpu_bench.bin bs=1M count=30 2>/dev/null", privileged=False)
        code, out, _ = await pm.run(
            "for i in 1 2 3 4 5 6 7 8; do start=$(date +%s%N); sha256sum /data/local/tmp/cpu_bench.bin > /dev/null; end=$(date +%s%N); echo $(( (end-start)/1000000 )); done",
            privileged=False)
        await pm.run("rm /data/local/tmp/cpu_bench.bin", privileged=False)

        times = []
        for line in out.strip().split('\n'):
            line = line.strip()
            if line.isdigit():
                times.append(int(line) / 1000.0)  # ms -> s
        if times:
            for i, t in enumerate(times):
                log_cb(f"[INFO] Iteration {i+1} time: {t:.2f}s (device-measured)")
            avg = sum(times) / len(times)
            # Universal score: 1000/avg calibrated so ~1s avg = 1000 pts, flagship ~0.3s=3333, low-end ~3s=333
            score = int(1000 / max(avg, 0.05))
            log_cb(f"[SUCCESS] CPU Score: {score} (avg {avg:.2f}s over {len(times)} iters)")
            results["multi_core_score"] = score
            results["avg_time_s"] = round(avg, 3)
            results["iters"] = len(times)
            if len(times) >= 4 and times[-1] > times[0] * 1.25 and times[-1] > 0.3:
                log_cb(f"[WARNING] Throttle suspected: first {times[0]:.2f}s -> last {times[-1]:.2f}s")
                results["throttle_detected"] = True
            else:
                log_cb("[SUCCESS] No significant CPU throttling detected.")
                results["throttle_detected"] = False
        else:
            log_cb(f"[WARNING] Could not parse on-device timings: {out[:200]!r}")
            results["throttle_detected"] = False

        if is_rooted:
            results["confidence"] = "VERIFIED"
            log_cb("[INFO] Running Root-Enhanced CPU Telemetry (universal)...")
            code, out, _ = await pm.run("cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null", privileged=True)
            if out.strip():
                log_cb(f"[INFO] CPU0 Governor: {out.strip()}")
                results["cpu_governor"] = out.strip()
            code, out, _ = await pm.run("cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq 2>/dev/null", privileged=True)
            if out.strip():
                freqs = [f.strip() for f in out.strip().split('\n') if f.strip().isdigit()]
                if freqs:
                    mhz = [f"{int(f)//1000}MHz" for f in freqs]
                    log_cb(f"[INFO] Core freqs: {', '.join(mhz)}")
                    results["core_frequencies"] = freqs
                    results["core_mhz"] = mhz
            code, out, _ = await pm.run("cat /sys/devices/system/cpu/cpu*/cpufreq/cpuinfo_max_freq 2>/dev/null | sort -u", privileged=True)
            if out.strip():
                results["max_freqs"] = out.strip().split()

        log_cb("[SUCCESS] CPU Test Complete.")
        return results
