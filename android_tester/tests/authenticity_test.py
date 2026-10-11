from typing import Callable, Dict, Any
from .base_test import BaseTest
from ..privilege_manager import PrivilegeManager

class AuthenticityTest(BaseTest):
    async def run(self, pm: PrivilegeManager, log_cb: Callable[[str], None], **kwargs) -> Dict[str, Any]:
        log_cb("[INFO] Starting Authenticity & Anti-Spoofing Check (universal)...")

        is_rooted = await pm.check_root()
        results = {"confidence": "ESTIMATED"}

        # Universal props (all Android): separate calls (semicolon would run locally, not on device).
        code, fp, _ = await pm.run("getprop ro.build.fingerprint", privileged=False)
        _, model, _ = await pm.run("getprop ro.product.model", privileged=False)
        _, device, _ = await pm.run("getprop ro.product.device", privileged=False)
        _, tags, _ = await pm.run("getprop ro.build.tags", privileged=False)
        _, btype, _ = await pm.run("getprop ro.build.type", privileged=False)
        _, release, _ = await pm.run("getprop ro.build.version.release", privileged=False)
        _, sdk, _ = await pm.run("getprop ro.build.version.sdk", privileged=False)
        _, fp_system, _ = await pm.run("getprop ro.system.build.fingerprint", privileged=False)
        _, fp_vendor, _ = await pm.run("getprop ro.vendor.build.fingerprint", privileged=False)
        _, fp_vdlkm, _ = await pm.run("getprop ro.vendor_dlkm.build.fingerprint", privileged=False)
        _, fp_odm, _ = await pm.run("getprop ro.odm.build.fingerprint", privileged=False)
        fp, model, device, tags, btype = fp.strip(), model.strip(), device.strip(), tags.strip(), btype.strip()
        release, sdk = release.strip(), sdk.strip()
        log_cb(f"[INFO] Fingerprint: {fp}")
        log_cb(f"[INFO] Model: {model} / Device: {device} / Tags: {tags} / Type: {btype}")
        log_cb(f"[INFO] Android release: {release} (SDK {sdk})")
        results.update({'fingerprint': fp, 'model': model, 'device': device, 'build_tags': tags, 'build_type': btype, 'android_release': release, 'sdk': sdk})
        # Accuracy: fingerprint Android version vs release mismatch = custom ROM with retained stock fingerprint
        import re as _re
        m = _re.search(r':(\d+)/', fp)
        if m and release and m.group(1) != release.split('.')[0]:
            log_cb(f"[WARNING] Fingerprint Android {m.group(1)} != release {release} (custom ROM, fingerprint retained).")
            results['fingerprint_mismatch'] = True
            results['fingerprint_android'] = m.group(1)
        if "test-keys" in tags or "dev-keys" in tags:
            log_cb(f"[WARNING] {tags} build (custom/unofficial ROM).")
            results['custom_keys'] = True
        # Accuracy: partition fingerprint consistency - mixed stock/custom breaks closed-source HALs (fingerprint!)
        parts = {'system': fp_system.strip(), 'vendor': fp_vendor.strip(), 'vendor_dlkm': fp_vdlkm.strip(), 'odm': fp_odm.strip()}
        uniq = {v for v in parts.values() if v}
        if len(uniq) > 1:
            log_cb(f"[WARNING] Partition fingerprints MIXED ({len(uniq)} distinct): vendor_dlkm={parts['vendor_dlkm'][:50]}... vs system={parts['system'][:50]}... Closed-source HALs (egis fingerprint) often break on such hybrids.")
            results['partition_mismatch'] = True
            results['partition_fps'] = parts
        elif len(uniq) == 1:
            results['partition_match'] = True

        code, out, _ = await pm.run("getprop ro.serialno", privileged=False)
        serials = [out.strip()] if out.strip() else []
        _, out2, _ = await pm.run("getprop ro.boot.serialno", privileged=False)
        if out2.strip():
            serials.append(out2.strip())
        if serials:
            log_cb(f"[INFO] Serial: {serials[0]}")
            results['serial'] = serials[0]

        log_cb("[INFO] IMEI blocked by OS permissions on Android 10+ (expected).")

        if is_rooted:
            results["confidence"] = "VERIFIED"
            log_cb("[INFO] Root-Enhanced checks (universal paths)...")
            _, vb_state, _ = await pm.run("getprop ro.boot.verifiedbootstate", privileged=True)
            _, verity, _ = await pm.run("getprop ro.boot.veritymode", privileged=True)
            _, vbmeta, _ = await pm.run("getprop ro.boot.vbmeta.digest", privileged=True)
            vb = [x.strip() for x in [vb_state, verity, vbmeta] if x.strip()]
            if vb:
                log_cb(f"[INFO] VerifiedBoot: {' / '.join(vb)} (orange/red=enforcing-off/unlocked)")
                results['verified_boot'] = vb[0]
                if len(vb) > 1:
                    results['veritymode'] = vb[1]
            # Partition hash: try by-name then mapped (Samsung super, A/B slot suffix)
            code, out, _ = await pm.run("ls /dev/block/by-name/ 2>/dev/null", privileged=True)
            if "boot" in out:
                code2, out2, _ = await pm.run("sha256sum /dev/block/by-name/boot 2>&1", privileged=True)
                parts = out2.strip().split()
                if code2 == 0 and len(parts) >= 2 and len(parts[0]) == 64:
                    log_cb("[INFO] Boot hash readable (baseline comparison needs known-good).")
                    results['boot_hash'] = parts[0]
                else:
                    log_cb(f"[INFO] Boot hash not readable: {out2.strip()[:100]}")
            else:
                log_cb("[INFO] No by-name mapping on this vendor (super/dynamic partitions).")

        log_cb("[SUCCESS] Authenticity Test Complete.")
        return results
