from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

class VCSAdapter(ABC):
    @abstractmethod
    async def list_pull_requests(self, owner: str, repo: str, state: str = "open") -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    async def get_pull_request(self, owner: str, repo: str, number: int) -> Dict[str, Any]:
        pass

    @abstractmethod
    async def list_pull_request_files(self, owner: str, repo: str, number: int) -> List[str]:
        pass

    @abstractmethod
    async def get_file_text(self, owner: str, repo: str, path: str, ref: Optional[str] = None) -> Optional[str]:
        pass

    @abstractmethod
    async def list_repositories(self, owner: str) -> List[Dict[str, Any]]:
        pass
