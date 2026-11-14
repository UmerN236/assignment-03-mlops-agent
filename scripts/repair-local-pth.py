"""Clear inherited macOS hidden flags only on this workspace's venv .pth files.

Python 3.12 skips hidden .pth files, breaking editable imports when a hidden
workspace/cache causes uv's generated files to inherit UF_HIDDEN.
"""

import os
import stat
from pathlib import Path

root = Path(__file__).resolve().parents[1]
if hasattr(os, "chflags"):
    for path in (root / ".venv/lib/python3.12/site-packages").glob("*.pth"):
        if not path.is_symlink():
            os.chflags(path, path.stat().st_flags & ~stat.UF_HIDDEN)
