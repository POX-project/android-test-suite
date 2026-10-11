import abc
from typing import Callable, Dict, Any
from ..privilege_manager import PrivilegeManager

class BaseTest(abc.ABC):
    @property
    def name(self) -> str:
        return self.__class__.__name__

    @abc.abstractmethod
    async def run(self, pm: PrivilegeManager, log_cb: Callable[[str], None], **kwargs) -> Dict[str, Any]:
        """
        Execute the test logic.
        Returns a dictionary containing test results and a 'confidence' key 
        which should be either 'VERIFIED' (ran with root) or 'ESTIMATED' (ran without root).
        """
        pass
