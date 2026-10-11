from typing import Callable, Dict, Any
from .base_test import BaseTest
from ..privilege_manager import PrivilegeManager

class RootIntegrityTest(BaseTest):
    async def run(self, pm: PrivilegeManager, log_cb: Callable[[str], None], **kwargs) -> Dict[str, Any]:
        log_cb("[INFO] Running Root Integrity Test...")
        
        is_rooted = await pm.check_root()
        
        if is_rooted:
            log_cb(f"[SUCCESS] Functional root verified.")
            log_cb(f"[INFO] SU Implementation: {pm.su_impl}")
            log_cb(f"[INFO] SELinux Mode: {pm.selinux_mode}")
            return {
                "confidence": "VERIFIED",
                "is_rooted": True,
                "su_impl": pm.su_impl,
                "selinux_mode": pm.selinux_mode
            }
        else:
            log_cb("[WARNING] Device is not rooted or su is broken.")
            log_cb("[INFO] SU Implementation: None")
            log_cb(f"[INFO] SELinux Mode: {pm.selinux_mode}")
            return {
                "confidence": "ESTIMATED",
                "is_rooted": False,
                "su_impl": "None",
                "selinux_mode": pm.selinux_mode
            }
