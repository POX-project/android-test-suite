from typing import Callable, Dict, Any
from .base_test import BaseTest
from ..privilege_manager import PrivilegeManager
import re

class GpuTest(BaseTest):
    async def run(self, pm: PrivilegeManager, log_cb: Callable[[str], None], **kwargs) -> Dict[str, Any]:
        log_cb("[INFO] Starting GPU Stress & Render Test...")

        is_rooted = await pm.check_root()
        results = {"confidence": "ESTIMATED", "ui_smoothness_note": "SystemUI history only, not 3D stress"}

        log_cb("[INFO] Collecting gfxinfo from system UI (smoothness proxy)...")
        code, out, _ = await pm.run("dumpsys gfxinfo com.android.systemui 2>&1", privileged=False)

        jank_count = 0
        total_frames = 0
        for line in out.split('\n'):
            line = line.strip()
            if line.startswith("Total frames rendered:"):
                try:
                    total_frames = int(line.split(':')[1].strip())
                    log_cb(f"[INFO] Total SystemUI Frames Rendered: {total_frames}")
                except ValueError:
                    pass
            elif line.startswith("Janky frames:") and "legacy" not in line:
                try:
                    jank_str = line.split(':')[1].split('(')[0].strip()
                    jank_count = int(jank_str)
                    log_cb(f"[INFO] Janky SystemUI Frames: {jank_count}")
                except (ValueError, IndexError):
                    pass

        if total_frames > 0:
            results['gfx_jank_percent'] = round((jank_count / total_frames) * 100, 1)
        else:
            # No frames = SystemUI dead/unready, not 0% jank. Omit metric.
            results['gfx_state'] = "unavailable-systemui-unready"
            log_cb("[WARNING] No gfxinfo frames (SystemUI unready) - jank omitted, not 0%.")

        if is_rooted:
            log_cb("[INFO] Running Root-Enhanced GPU Telemetry (universal Adreno/Mali)...")
            found = False
            # Adreno (Snapdragon): kgsl-3d0
            code, out, _ = await pm.run("cat /sys/class/kgsl/kgsl-3d0/gpuclk 2>/dev/null; cat /sys/class/kgsl/kgsl-3d0/max_gpuclk 2>/dev/null", privileged=True)
            if out.strip() and out.strip()[0].isdigit():
                clk = out.strip().split()[0]
                mhz = self._to_mhz(clk)
                log_cb(f"[INFO] Adreno GPU Clock: {clk} Hz ({mhz:.0f} MHz)")
                results['gpu_clock'] = clk
                results['gpu_clock_mhz'] = mhz
                results['gpu_vendor'] = "adreno"
                found = True
            code, out, _ = await pm.run("cat /sys/class/kgsl/kgsl-3d0/gpubusy 2>/dev/null", privileged=True)
            if out.strip():
                log_cb(f"[INFO] Adreno GPU Busy: {out.strip()[:120]}")
                results['gpu_busy'] = out.strip()[:120]

            # Mali legacy: /sys/class/misc/mali0 (Exynos 7904 / older)
            if not found:
                code, out, _ = await pm.run("cat /sys/class/misc/mali0/device/clock 2>/dev/null", privileged=True)
                clk = out.strip().split()[0] if out.strip() else ""
                if clk.lstrip('-').isdigit() and int(clk) > 0:
                    mhz = self._to_mhz(clk)
                    log_cb(f"[INFO] Mali GPU Clock: {clk} KHz ({mhz:.0f} MHz, legacy mali0)")
                    results['gpu_clock'] = clk
                    results['gpu_clock_mhz'] = mhz
                    results['gpu_vendor'] = "mali-legacy"
                    found = True
                else:
                    # Clock-gated when idle (0) is normal: report dvfs table + gpu model + time_in_state proof instead of 0
                    _, dvfs, _ = await pm.run("cat /sys/class/misc/mali0/device/dvfs_table 2>/dev/null", privileged=True)
                    _, ginfo, _ = await pm.run("cat /sys/class/misc/mali0/device/gpuinfo 2>/dev/null", privileged=True)
                    _, tis, _ = await pm.run("cat /sys/class/misc/mali0/device/time_in_state 2>/dev/null", privileged=True)
                    if dvfs.strip() or ginfo.strip():
                        log_cb(f"[INFO] Mali idle (clock-gated, normal). Model: {ginfo.strip()[:60]} DVFS(KHz): {dvfs.strip()[:80]}")
                        results['gpu_vendor'] = "mali-legacy"
                        results['gpu_state'] = "idle-gated"
                        results['gpu_idle'] = True
                        if tis.strip():
                            log_cb(f"[INFO] GPU time_in_state (proof it runs): {tis.strip().splitlines()[0][:60]}...")
                            results['gpu_time_in_state'] = tis.strip()[:200]
                        if dvfs.strip():
                            try:
                                mx = max(int(x) for x in dvfs.strip().split() if x.isdigit())
                                results['gpu_max_mhz'] = round(self._to_mhz(str(mx)), 0)
                            except ValueError:
                                pass
                        found = True
                code, out, _ = await pm.run("cat /sys/class/misc/mali0/device/utilization 2>/dev/null", privileged=True)
                if out.strip():
                    u = out.strip().split()[0]
                    if u == "0" and results.get('gpu_state') == "idle-gated":
                        log_cb("[INFO] GPU Utilization: 0% (idle, expected - see time_in_state for proof of function)")
                    else:
                        log_cb(f"[INFO] Mali GPU Utilization: {u}%")
                    results['gpu_util_pct'] = u
                    results['gpu_util'] = u
            # Mali modern: /sys/devices/.../mali*/ (Exynos 2100+, Tensor, Dimensity)
            if not found:
                code, out, _ = await pm.run("cat /sys/devices/platform/*/mali*/utilization 2>/dev/null; cat /sys/devices/*/mali*/utilization 2>/dev/null | head -n 3", privileged=True)
                if out.strip() and out.strip()[0].isdigit():
                    log_cb(f"[INFO] Mali GPU Utilization (modern): {out.strip().split()[0]}%")
                    results['gpu_util'] = out.strip().split()[0]
                    found = True
                code, out, _ = await pm.run("cat /sys/devices/platform/*/mali*/clock 2>/dev/null; cat /sys/devices/platform/*gpu/clock 2>/dev/null | head -n 3", privileged=True)
                if out.strip() and out.strip().split()[0].isdigit():
                    mhz = self._to_mhz(out.strip().split()[0])
                    log_cb(f"[INFO] GPU Clock (modern): {mhz:.0f} MHz")
                    results['gpu_clock_mhz'] = mhz
                    found = True
            if found:
                results["confidence"] = "VERIFIED"
                results["gpu_method"] = results.get("gpu_vendor", "modern")
            else:
                log_cb("[INFO] No GPU clock node found (checked kgsl + mali legacy + mali modern).")
                results["gpu_method"] = "none"

        log_cb("[SUCCESS] GPU Test Complete.")
        return results

    def _to_mhz(self, hz_str: str) -> float:
        try:
            hz = float(hz_str.strip().split()[0])
            # Some nodes report KHz, some Hz. Heuristic: >100000 => Hz? Actually both big.
            # mali0 legacy reports e.g. 343000 (Hz? =343MHz? or KHz?). 343000 Hz=0.34MHz wrong, so must be KHz->343MHz.
            # kgsl reports Hz e.g. 650000000=650MHz. Distinguish by magnitude:
            if hz < 10000:  # already MHz
                return hz
            if hz < 5000 * 1000:  # <5M -> treat as KHz
                return hz / 1000.0
            return hz / 1_000_000.0
        except ValueError:
            return 0.0
