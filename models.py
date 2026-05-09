from dataclasses import dataclass
from pathlib import Path
from typing import Optional

OUTPUT_DIR = Path(__file__).parent / "downloads"
RECOMMENDED_DIR = OUTPUT_DIR / "recommended"
PLAYLISTS_DIR = Path(__file__).parent / "playlists"


@dataclass
class SearchResult:
    display: str
    local_path: Optional[Path] = None
    yt_url: Optional[str] = None
    view_count: int = 0

    @property
    def is_local(self) -> bool:
        return self.local_path is not None

    def __hash__(self):
        return hash(self.local_path or self.yt_url)

    def __eq__(self, other):
        if isinstance(other, SearchResult):
            return (self.local_path or self.yt_url) == (other.local_path or other.yt_url)
        return False
