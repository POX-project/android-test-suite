from typing import Callable, Dict, Any
from .base_test import BaseTest
from ..privilege_manager import PrivilegeManager
import re

class NetworkTest(BaseTest):
    async def run(self, pm: PrivilegeManager, log_cb: Callable[[str], None], **kwargs) -> Dict[str, Any]:
        log_cb("[INFO] Starting Network & Connectivity Test (universal)...")
        results = {"confidence": "VERIFIED"}  # No root needed

        ping_ok = False
        for host in ["8.8.8.8", "1.1.1.1"]:
            log_cb(f"[INFO] Ping {host} (4x, 3s timeout)...")
            code, out, err = await pm.run(f"ping -c 4 -W 3 {host} 2>&1", privileged=False)
            combined = out + err
            if "Network is unreachable" in combined:
                log_cb(f"[INFO] {host}: no route (device offline/VPN).")
                results[f'loss_pct_{host}'] = 100
                results['route_state'] = "no-route"
                continue
            loss_m = re.search(r'(\d+)% packet loss', combined)
            rtt_m = re.search(r'min/avg/max/mdev = [\d.]+?/([\d.]+?)/', combined)
            if loss_m:
                loss = int(loss_m.group(1))
                results[f'loss_pct_{host}'] = loss
                if rtt_m:
                    avg = float(rtt_m.group(1))
                    log_cb(f"[INFO] {host}: loss={loss}% avg={avg}ms")
                    if loss < 100:
                        results['avg_latency_ms'] = avg
                        ping_ok = True
                else:
                    log_cb(f"[INFO] {host}: loss={loss}% (no RTT, ICMP filtered)")
                if loss < 100:
                    ping_ok = True
                    break
            elif code == 0:
                log_cb(f"[SUCCESS] Ping {host} OK.")
                ping_ok = True
                break
        if not ping_ok:
            # No -1 placeholder: omit latency, explain why. Interface state is the real signal.
            results['icmp_blocked'] = True
            results['latency_state'] = "unavailable-no-route-or-filtered"
            log_cb("[WARNING] No ICMP path (offline or carrier-filtered). Checking interfaces...")
            code, out, _ = await pm.run("ip route 2>&1", privileged=False)
            if out.strip():
                routes = out.strip().splitlines()[0][:100]
                log_cb(f"[INFO] Route: {routes}")
                results['route'] = routes

        log_cb("[INFO] Checking WiFi/cell (dumpsys)...")
        code, out, _ = await pm.run("dumpsys wifi 2>&1", privileged=False)
        if "Wifi" in out or "mState" in out:
            log_cb("[SUCCESS] WiFi stack alive.")
            results['wifi_stack'] = True

        dl_ok = False
        for url in ["https://speed.cloudflare.com/__down?bytes=1000000",
                    "https://connectivitycheck.gstatic.com/generate_204"]:
            code, out, _ = await pm.run(f"curl -o /dev/null -s -w '%{{speed_download}} %{{http_code}}' --max-time 15 '{url}' 2>&1", privileged=False)
            parts = out.strip().split()
            if len(parts) >= 2 and parts[1].startswith("2"):
                try:
                    bps = float(parts[0])
                    if bps > 1000 and "cloudflare" in url:
                        mbps = (bps * 8) / (1024 * 1024)
                        log_cb(f"[INFO] Download Throughput: {mbps:.1f} Mbps (1MB cloudflare)")
                        results['download_mbps'] = round(mbps, 1)
                        dl_ok = True
                        break
                    elif "generate_204" in url:
                        log_cb(f"[INFO] HTTP connectivity OK (code {parts[1]}).")
                        results['http_ok'] = True
                except ValueError:
                    pass
        if not dl_ok and 'http_ok' not in results:
            log_cb("[INFO] Throughput skipped (offline).")
            results['throughput_state'] = "skipped-offline"

        log_cb("[SUCCESS] Network Test Complete.")
        return results
