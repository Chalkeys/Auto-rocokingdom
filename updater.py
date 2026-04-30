"""增量更新器：从 GitHub Releases 检查版本并按文件下载。"""
from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, List, Optional

REPO = "chalkeys/auto-rocokingdom"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RAW_VERSION = f"https://raw.githubusercontent.com/{REPO}/main/version.py"
REQUEST_TIMEOUT = 15
CHUNK = 65536

_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "Auto-Roco-Updater/1.0",
}


@dataclass
class Asset:
    name: str
    url: str
    size: int


@dataclass
class ReleaseInfo:
    version: str
    notes: str
    assets: List[Asset] = field(default_factory=list)


def _vt(v: str) -> tuple:
    return tuple(int(x) for x in v.split(".") if x.isdigit())


def is_newer(remote: str, local: str) -> bool:
    return _vt(remote) > _vt(local)


def fetch_release() -> ReleaseInfo:
    """Fetch latest GitHub release. Raises on network/parse error."""
    req = urllib.request.Request(API_LATEST, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as r:
        data = json.loads(r.read().decode())

    version = data.get("tag_name", "").lstrip("v")
    notes = data.get("body", "").strip()
    assets = [
        Asset(name=a["name"], url=a["browser_download_url"], size=a["size"])
        for a in data.get("assets", [])
    ]
    return ReleaseInfo(version=version, notes=notes, assets=assets)


def fetch_remote_version() -> str:
    """Lightweight check: fetch only version.py from main branch."""
    req = urllib.request.Request(RAW_VERSION, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as r:
        text = r.read().decode()
    import re
    m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', text)
    return m.group(1) if m else ""


def download_file(
    url: str,
    dest: str,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> None:
    """Download url to dest, calling progress_cb(downloaded_bytes, total_bytes)."""
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=60) as r:
        total = int(r.info().get("Content-Length") or 0)
        done = 0
        with open(dest, "wb") as f:
            while True:
                chunk = r.read(CHUNK)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress_cb:
                    progress_cb(done, total)


def download_assets(
    assets: List[Asset],
    dest_dir: str,
    progress_cb: Optional[Callable[[str, int, int], None]] = None,
) -> List[str]:
    """Download each asset to dest_dir. Returns list of saved file paths.

    progress_cb(asset_name, bytes_done, bytes_total)
    """
    os.makedirs(dest_dir, exist_ok=True)
    saved = []
    for asset in assets:
        dest = os.path.join(dest_dir, asset.name)
        cb = (lambda d, t, n=asset.name: progress_cb(n, d, t)) if progress_cb else None
        download_file(asset.url, dest, cb)
        saved.append(dest)
    return saved
