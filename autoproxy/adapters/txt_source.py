from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class TxtProxySource:
    path: Path

    def fetch_proxy(self) -> dict[str, str]:
        for line in self.path.read_text().splitlines():
            entry = line.strip()
            if not entry or entry.startswith("#"):
                continue
            digest = hashlib.sha1(entry.encode("utf-8")).hexdigest()[:12]
            return {
                "id": f"txt-{digest}",
                "raw_uri": entry,
                "provider": "txt",
            }
        raise ValueError("No proxy entries found in txt source")
