import asyncio
from typing import Callable, Dict, Any
from .device_bridge import DeviceBridge
from .privilege_manager import PrivilegeManager
from .audit_engine import AuditEngine
from .tests.network_test import NetworkTest
from .tests.ui_monkey_test import UIMonkeyTest
from .tests.thermal_test import ThermalTest
from .tests.oom_test import OOMTest
from .tests.sensor_test import SensorTest
from .tests.storage_test import StorageTest
from .tests.root_integrity_test import RootIntegrityTest
from .tests.cpu_test import CpuTest
from .tests.battery_test import BatteryTest
from .tests.gpu_test import GpuTest
from .tests.display_touch_test import DisplayTouchTest
from .tests.authenticity_test import AuthenticityTest
from .tests.biometric_test import BiometricTest
from .tests.hardware_presence_test import HardwarePresenceTest

class TestEngine:
    def __init__(self, bridge: DeviceBridge):
        self.bridge = bridge
        self.pm = PrivilegeManager(bridge)
        self.is_running = False
        self.auditor = AuditEngine()
        
        # Instantiate test modules
        self.root_integrity_test = RootIntegrityTest()
        self.storage_test = StorageTest()
        self.cpu_test = CpuTest()
        self.thermal_test = ThermalTest()
        self.battery_test = BatteryTest()
        self.sensor_test = SensorTest()
        self.gpu_test = GpuTest()
        self.display_touch_test = DisplayTouchTest()
        self.network_test = NetworkTest()
        self.authenticity_test = AuthenticityTest()
        self.biometric_test = BiometricTest()
        self.hardware_presence_test = HardwarePresenceTest()
        
        # Keep auxiliary tests
        self.ui_monkey_test = UIMonkeyTest()
        self.oom_test = OOMTest()
        
    def _intercept_log(self, log_cb: Callable[[str], None], msg: str):
        self.auditor.add_log(msg)
        log_cb(msg)

    async def _run_test(self, test_instance, log_cb: Callable[[str], None], **kwargs):
        test_name = test_instance.name
        self._intercept_log(log_cb, f"\n=== [START] {test_name} ===")
        try:
            # Most tests have signature: (pm, log_cb, **kwargs)
            # Legacy ones (oom/monkey) we'll patch or just pass bridge if they haven't been updated.
            # We updated base_test so all inherit from it and take pm.
            if hasattr(test_instance, 'run'):
                 results = await test_instance.run(self.pm, lambda m: self._intercept_log(log_cb, m), **kwargs)
                 if results:
                     self.auditor.add_test_results(test_name, results)
        except Exception as e:
            self._intercept_log(log_cb, f"[FATAL] Test {test_name} crashed: {str(e)}")
        finally:
            self._intercept_log(log_cb, f"=== [END] {test_name} ===\n")

    async def run_network_test(self, log_cb: Callable[[str], None]):
        await self._run_test(self.network_test, log_cb)
            
    async def run_ui_monkey_test(self, log_cb: Callable[[str], None], event_count: int = 50000):
        # We need to hack around legacy tests not using PM if they haven't been updated yet, 
        # but we updated BaseTest so they might fail if not updated. We assume they can take pm.
        await self._run_test(self.ui_monkey_test, log_cb, event_count=event_count)

    async def run_thermal_stress(self, log_cb: Callable[[str], None], duration_sec: int = 15):
        await self._run_test(self.thermal_test, log_cb, duration_sec=duration_sec)

    async def run_oom_test(self, log_cb: Callable[[str], None]):
        await self._run_test(self.oom_test, log_cb)
        
    async def run_sensor_test(self, log_cb: Callable[[str], None]):
        await self._run_test(self.sensor_test, log_cb)
        
    async def run_storage_test(self, log_cb: Callable[[str], None]):
        await self._run_test(self.storage_test, log_cb)
        
    async def run_cpu_test(self, log_cb: Callable[[str], None]):
        await self._run_test(self.cpu_test, log_cb)

    async def run_battery_test(self, log_cb: Callable[[str], None]):
        await self._run_test(self.battery_test, log_cb)

    async def run_gpu_test(self, log_cb: Callable[[str], None]):
        await self._run_test(self.gpu_test, log_cb)

    async def run_display_touch_test(self, log_cb: Callable[[str], None]):
        await self._run_test(self.display_touch_test, log_cb)
        
    async def run_authenticity_test(self, log_cb: Callable[[str], None]):
        await self._run_test(self.authenticity_test, log_cb)

    async def run_biometric_test(self, log_cb: Callable[[str], None]):
        await self._run_test(self.biometric_test, log_cb)

    async def run_hardware_presence_test(self, log_cb: Callable[[str], None]):
        await self._run_test(self.hardware_presence_test, log_cb)

    async def run_memory_test(self, log_cb: Callable[[str], None]):
        await self._run_test(self.oom_test, log_cb)

    async def run_full_scale(self, log_cb: Callable[[str], None]):
        self.is_running = True
        try:
            self._intercept_log(log_cb, "=== STARTING DEEP SCALE SYSTEM AUDIT ===")
            
            # 1. Root Integrity (must be first)
            await self._run_test(self.root_integrity_test, log_cb)
            
            # 2. Hardware / Authenticity
            await self.run_authenticity_test(log_cb)
            
            # 3. Core Compute & Storage
            await self.run_storage_test(log_cb)
            await self.run_cpu_test(log_cb)
            await self.run_gpu_test(log_cb)
            
            # 4. Thermal & Battery
            await self.run_thermal_stress(log_cb, duration_sec=15)
            await self.run_battery_test(log_cb)
            
            # 5. Sensors & Inputs
            await self.run_sensor_test(log_cb)
            await self.run_display_touch_test(log_cb)
            await self.run_biometric_test(log_cb)
            await self.run_hardware_presence_test(log_cb)
            await self.run_memory_test(log_cb)
            
            # 6. Connectivity
            await self.run_network_test(log_cb)
            
            self._intercept_log(log_cb, "=== DEEP SCALE AUDIT COMPLETED ===")
            
            # Note: auditor needs pm info for the report now
            self.auditor.generate_report("AuditReport.md", self.pm)
            self._intercept_log(log_cb, "[SUCCESS] AuditReport.md generated in the current directory.")
        finally:
            self.is_running = False

