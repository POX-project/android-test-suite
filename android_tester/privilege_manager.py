from typing import Tuple
from .device_bridge import DeviceBridge

class PrivilegeManager:
    # Universal: Magisk (/product/bin/su->magisk, /sbin/su), KernelSU (ksu),
    # APatch (apd), SuperSU, vendor su. Functional probe works for all.
    def __init__(self, bridge: DeviceBridge):
        self.bridge = bridge
        self.is_rooted = False
        self.su_impl = "None"
        self.selinux_mode = "Unknown"
        self._root_checked = False

    def reset(self):
        self.is_rooted = False
        self.su_impl = "None"
        self.selinux_mode = "Unknown"
        self._root_checked = False

    async def check_root(self, force: bool = False) -> bool:
        if self._root_checked and not force:
            return self.is_rooted

        code, out, err = await self.bridge.run_adb("shell su -c 'id'", timeout=15)
        combined = (out + err).lower()
        if code == 0 and "uid=0" in out:
            self.is_rooted = True
        else:
            # Universal deny reasons: Magisk "Permission denied" = not granted yet,
            # "not found" = no su binary
            self.is_rooted = False
            self.su_impl = "None"
            self._root_checked = True
            return False

        # Identify implementation: try su --version, ksu, magisk -v, apd -v (all harmless)
        impl = ""
        for probe in ["shell su --version", "shell ksu --version 2>/dev/null", "shell magisk -v 2>/dev/null", "shell apd -v 2>/dev/null"]:
            try:
                _, o, _ = await self.bridge.run_adb(probe, timeout=10)
                if o.strip():
                    impl += o.strip() + " "
            except Exception:
                pass
        low = impl.lower()
        if "magisk" in low:
            ver = impl.strip().split()[0] if impl.strip() else ""
            self.su_impl = f"Magisk ({ver})" if ver else "Magisk"
        elif "kernelsu" in low or "ksu" in low:
            self.su_impl = f"KernelSU ({impl.strip()[:40]})"
        elif "apatch" in low or "apd" in low:
            self.su_impl = f"APatch ({impl.strip()[:40]})"
        elif "supersu" in low:
            self.su_impl = f"SuperSU ({impl.strip()[:40]})"
        else:
            self.su_impl = impl.strip()[:60] if impl.strip() else "Unknown/Vendor"

        code, out, _ = await self.bridge.run_adb("shell getenforce", timeout=10)
        if code == 0 and out.strip():
            self.selinux_mode = out.strip()

        self._root_checked = True
        return self.is_rooted

    async def run(self, cmd: str, privileged: bool = False) -> Tuple[int, str, str]:
        if privileged:
            if not self._root_checked:
                await self.check_root()
            if not self.is_rooted:
                return 1, "", "Privilege execution requested but device is not rooted or su not granted (grant Shell in Magisk/KernelSU app)."
            escaped_cmd = cmd.replace("'", "'\\''")
            cmd_to_run = f'shell "su -c \'{escaped_cmd}\'"'
        else:
            cmd_to_run = f"shell {cmd}"
        return await self.bridge.run_adb(cmd_to_run)
