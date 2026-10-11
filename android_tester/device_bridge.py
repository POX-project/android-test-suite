import asyncio
import shlex
from typing import Optional, Tuple

class DeviceBridge:
    def __init__(self):
        self.device_id: Optional[str] = None
        self.is_rooted: bool = False

    async def run_adb(self, cmd: str, timeout: float = 30) -> Tuple[int, str, str]:
        """Universal ADB runner via exec (no host-shell expansion).
        cmd like 'shell <device-cmd>' or 'devices' or 'logcat -c'.
        Returns (returncode, stdout, stderr)."""
        argv = self._to_argv(cmd)
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                return 1, "", f"ADB timeout after {timeout}s: {cmd[:120]}"
            return process.returncode or 0, stdout.decode('utf-8', errors='replace'), stderr.decode('utf-8', errors='replace')
        except Exception as e:
            return 1, "", f"ADB exec failed: {e}"

    def _to_argv(self, cmd: str) -> list:
        cmd = cmd.strip()
        base = ["adb"]
        # devices / logcat -c / etc. (no -s needed for devices)
        if cmd == "devices" or cmd.startswith("devices "):
            return base + shlex.split(cmd)
        if cmd.startswith("logcat"):
            if self.device_id:
                return base + ["-s", self.device_id] + shlex.split(cmd)
            return base + shlex.split(cmd)
        if cmd.startswith("-s "):
            return base + shlex.split(cmd)
        if cmd.startswith("shell"):
            rest = cmd[5:].strip()
            # Strip one outer double-quote layer from privileged wrapper: shell "su -c '...'"
            if len(rest) >= 2 and rest[0] == '"' and rest[-1] == '"':
                rest = rest[1:-1]
            if self.device_id:
                return base + ["-s", self.device_id, "shell", rest]
            return base + ["shell", rest]
        # fallback
        if self.device_id:
            return base + ["-s", self.device_id] + shlex.split(cmd)
        return base + shlex.split(cmd)

    async def check_connection(self) -> bool:
        """Universal: handles device/unauthorized/offline/no device."""
        code, out, _ = await self.run_adb("devices", timeout=10)
        if code != 0:
            self.device_id = None
            return False
        devices = []
        for line in out.strip().split('\n')[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                devices.append(parts[0])
        if not devices:
            self.device_id = None
            return False
        self.device_id = devices[0]
        return True

    async def get_hardware_info(self) -> dict:
        info = {}
        _, out, _ = await self.run_adb("shell getprop ro.product.model", timeout=10)
        info['Model'] = out.strip()
        _, out, _ = await self.run_adb("shell getprop ro.build.version.release", timeout=10)
        info['Android Version'] = out.strip()
        _, out, _ = await self.run_adb("shell getprop ro.soc.model", timeout=10)
        if not out.strip():
            _, out, _ = await self.run_adb("shell getprop ro.hardware", timeout=10)
        if not out.strip():
            _, out, _ = await self.run_adb("shell getprop ro.board.platform", timeout=10)
        soc = out.strip()
        if soc:
            info['SoC'] = soc
        _, out, _ = await self.run_adb("shell dumpsys battery", timeout=10)
        for line in out.split('\n'):
            s = line.strip()
            if s.startswith('level:'):
                try:
                    info['Battery Level'] = s.split(':', 1)[1].strip() + "%"
                except IndexError:
                    pass
                break
        return info

    async def listen_logcat(self, queue: asyncio.Queue, stop_event: asyncio.Event, is_rooted: bool = False):
        await self.run_adb("logcat -c", timeout=10)
        if is_rooted:
            await self.run_adb("shell su -c 'dmesg -c' > /dev/null", timeout=10)
        # streaming still needs shell (continuous); use shell string here only
        import asyncio as _aio
        cmd = f"adb -s {self.device_id} logcat -v time" if self.device_id else "adb logcat -v time"
        tasks = [self._stream_process(cmd, queue, stop_event, prefix="[LOGCAT] ")]
        if is_rooted:
            dmesg_cmd = f"adb -s {self.device_id} shell su -c 'dmesg -w'" if self.device_id else "adb shell su -c 'dmesg -w'"
            tasks.append(self._stream_process(dmesg_cmd, queue, stop_event, prefix="[DMESG] "))
        await _aio.gather(*tasks)

    async def _stream_process(self, cmd: str, queue: asyncio.Queue, stop_event: asyncio.Event, prefix: str = ""):
        try:
            process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
        except Exception:
            return
        try:
            while not stop_event.is_set():
                try:
                    line = await asyncio.wait_for(process.stdout.readline(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                if not line:
                    break
                decoded = line.decode('utf-8', errors='replace').strip()
                if decoded:
                    try:
                        queue.put_nowait(prefix + decoded)
                    except asyncio.QueueFull:
                        pass
        finally:
            try:
                if process.returncode is None:
                    process.terminate()
            except Exception:
                pass
