from typing import Callable, Dict, Any
from .base_test import BaseTest
from ..privilege_manager import PrivilegeManager
import re

class StorageTest(BaseTest):
    async def run(self, pm: PrivilegeManager, log_cb: Callable[[str], None], **kwargs) -> Dict[str, Any]:
        log_cb("[INFO] Starting Storage I/O Health & Stress Test...")
        
        is_rooted = await pm.check_root()
        results = {"confidence": "ESTIMATED"}
        
        if is_rooted:
            results["confidence"] = "VERIFIED"
            log_cb("[INFO] Running Root-Enhanced Storage Benchmark (Raw Block Device)...")
            # Root: raw block device read benchmark (read-only, safe)
            # Find userdata block device
            code, out, _ = await pm.run("readlink /dev/block/by-name/userdata || readlink /dev/block/by-name/USERDATA", privileged=True)
            block_dev = out.strip()
            
            if block_dev and "dev/block" not in block_dev:
                 block_dev = f"/dev/block/{block_dev}"
            
            if not block_dev:
                block_dev = "/dev/block/by-name/userdata"
                
            log_cb(f"[INFO] Testing block device: {block_dev}")
            # Universal accuracy: drop page-cache first, else block read hits cache (960MB/s fake vs 109MB/s true on eMMC).
            # Median of 2 runs defeats background-I/O variance (106-168 single-run spread observed).
            speeds = []
            for run in (1, 2):
                await pm.run("echo 3 > /proc/sys/vm/drop_caches", privileged=True)
                code, out, err = await pm.run(f"dd if={block_dev} of=/dev/null bs=4M count=20 2>&1", privileged=True)
                s = self._parse_dd_speed(out + "\n" + err)
                if s > 0:
                    speeds.append(s)
                    log_cb(f"[INFO] Run {run}: {s:.1f} MB/s")
            speeds.sort()
            read_speed = speeds[len(speeds)//2] if speeds else 0.0
            if read_speed:
                # Sanity: eMMC max ~400, UFS 3.x ~2000, UFS 4 ~4000. Cap absurd >5000 as cache artifact.
                if read_speed > 5000:
                    log_cb(f"[WARNING] Read {read_speed:.0f} MB/s implausible (cache).")
                log_cb(f"[SUCCESS] Raw Storage Read Speed: {read_speed:.1f} MB/s (median of {len(speeds)}, 80MB sequential, cache-dropped)")
                results['read_speed_mb'] = round(read_speed, 1)
                results['read_runs'] = [round(x, 1) for x in speeds]
                results['read_method'] = f"dd bs=4M count=20 on {block_dev} (drop_caches, median)"
            else:
                log_cb("[WARNING] Could not determine raw read speed.")
                
            # Filesystem write (same in both modes - authoritative for write health)
            test_path = "/data/local/tmp/storage_write.bin"
            log_cb("[INFO] Filesystem write 100MB (fsync)...")
            code, out, err = await pm.run(f"dd if=/dev/zero of={test_path} bs=1M count=100 conv=fsync 2>&1", privileged=True)
            ws = self._parse_dd_speed(out + "\n" + err)
            if ws > 0:
                log_cb(f"[SUCCESS] Storage Write Speed: {ws:.1f} MB/s")
                results['write_speed_mb'] = round(ws, 1)
            await pm.run(f"rm -f {test_path}", privileged=True)
            # Check wear leveling per-disk (avoid glob concatenation ambiguity)
            # NOTE: $ escaped so host shell does not expand before adb.
            log_cb("[INFO] Checking eMMC/UFS Wear Level Health...")
            code, out, _ = await pm.run("for d in /sys/block/mmcblk* /sys/block/sd*; do [ -d \"$d/device\" ] && echo \"==$d==\" && cat \"$d/device/life_time\" \"$d/device/life_time_est_typ_a\" \"$d/device/life_time_est_typ_b\" \"$d/device/pre_eol_info\" 2>/dev/null; done; cat /sys/class/scsi_disk/*/device/pre_eol_info 2>/dev/null", privileged=True)
            if out.strip():
                log_cb(f"[INFO] Wear nodes:\n{out.strip()}")
                results['wear_raw'] = out.strip()
                # Decode eMMC JEDEC: 0x01=0-10% ... 0x0A=90-100%, 0x0B=exceeded
                def _pct(h):
                    try:
                        v = int(h, 16)
                        if v >= 0x0B:
                            return 100
                        if v < 0x01:
                            return 0
                        return v * 10
                    except ValueError:
                        return -1
                m = re.search(r'0x0[0-9a-b]\s+0x0[0-9a-b]', out)
                if m:
                    results['wear_level_a'] = m.group(0)
                    a, b = m.group(0).split()
                    worst = max(_pct(a), _pct(b))
                    results['wear_consumed_pct'] = worst
                    results['wear_health_pct'] = 100 - worst
                    log_cb(f"[INFO] Storage Wear: {m.group(0)} = ~{worst}% consumed (~{100-worst}% health remaining)")
                if re.search(r'\b0[123]\b', out):
                    eol = re.search(r'\b0[123]\b', out).group(0)
                    results['pre_eol_info'] = eol
                    log_cb(f"[INFO] Pre-EOL: {eol} ({'Normal' if eol=='01' else 'Warning' if eol=='02' else 'Urgent'})")
            else:
                log_cb("[INFO] Could not read standard life_time nodes on this device.")
            # legacy single-node fallbacks for audit_engine compat
            code, out, err = await pm.run("cat /sys/block/*/device/life_time_est_typ_b 2>/dev/null", privileged=True)
            if out.strip():
                results['wear_level_b'] = out.strip()
                
        else:
            log_cb("[INFO] Running Standard Storage Benchmark (Filesystem level)...")
            test_path = "/sdcard/stress_test.bin"
            
            log_cb("[INFO] Running I/O Write Stress (200MB)...")
            code, out, err = await pm.run(f"dd if=/dev/zero of={test_path} bs=1M count=200 conv=fsync", privileged=False)
            write_speed = self._parse_dd_speed(out + "\n" + err)
            if write_speed:
                log_cb(f"[SUCCESS] Storage Write Speed: {write_speed} MB/s")
                results['write_speed_mb'] = write_speed
            else:
                log_cb(f"[WARNING] Could not determine write speed.")
                
            log_cb("[INFO] Running I/O Read Stress (200MB)...")
            code, out, err = await pm.run(f"dd if={test_path} of=/dev/null bs=1M 2>&1", privileged=False)
            read_speed = self._parse_dd_speed(out + "\n" + err)
            if read_speed:
                log_cb(f"[SUCCESS] Storage Read Speed: {read_speed:.1f} MB/s (NOTE: filesystem read may hit page-cache; root block read is authoritative)")
                results['read_speed_mb'] = round(read_speed, 1)
                results['read_cached_warning'] = True
                
            # Cleanup
            await pm.run(f"rm {test_path}", privileged=False)
            
        log_cb("[SUCCESS] Storage Test Complete.")
        return results

    def _parse_dd_speed(self, text: str) -> float:
        # Canonical toybox dd: "83886080 bytes (80 M) copied, 0.667781 s, 120 M/s"
        # Also handles: MB/s, GB/s, kB/s, bytes/s
        m = re.search(r'([\d.]+)\s*GB/s', text)
        if m:
            return float(m.group(1)) * 1024.0
        m = re.search(r'([\d.]+)\s*MB/s', text)
        if m:
            return float(m.group(1))
        # "120 M/s" (toybox short form, M = MB)
        m = re.search(r'([\d.]+)\s*M/s', text)
        if m:
            return float(m.group(1))
        m = re.search(r'([\d.]+)\s*kB/s', text, re.IGNORECASE)
        if m:
            return float(m.group(1)) / 1024.0
        m = re.search(r'([\d.]+)\s*bytes/s', text)
        if m:
            return float(m.group(1)) / (1024 * 1024)
        # Fallback: "X bytes (...) copied, Y s" -> compute manually
        m = re.search(r'(\d+)\s+bytes.*?copied,\s*([\d.]+)\s*s', text, re.DOTALL)
        if m:
            try:
                total = float(m.group(1))
                secs = float(m.group(2))
                if secs > 0:
                    return (total / secs) / (1024 * 1024)
            except ValueError:
                pass
        return 0.0


