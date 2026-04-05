"""
CDP v3.4.2 — Launcher
=====================
Responsibilities:
  1. Verify AppCore directory exists.
  2. Generate a time-bound HMAC token and pass it via env var.
  3. Launch AppCore/CDP-v3.4.2.exe and hand over the console.
  4. Wait for AppCore to finish, then exit with the same code.
"""

import os
import sys
import hmac
import time
import hashlib
import subprocess
from pathlib import Path

# ── Shared secret (same in both files, split to reduce naive string search) ───
_S = [0x43, 0x44, 0x50, 0x5F, 0x4C, 0x41, 0x55,
      0x4E, 0x43, 0x48, 0x5F, 0x4B, 0x45, 0x59,
      0x5F, 0x76, 0x33, 0x34, 0x32, 0x5F, 0x53,
      0x45, 0x43, 0x52, 0x45, 0x54, 0x5F, 0x58]
_SECRET = bytes(_S)

_ENV_TOKEN = 'CDP_LAUNCH_TOKEN'
_ENV_PID   = 'CDP_LAUNCHER_PID'


def _make_token() -> str:
    """HMAC-SHA256(secret, floor(epoch/30))  — valid for ~90 seconds."""
    slot = str(int(time.time()) // 30).encode()
    return hmac.new(_SECRET, slot, hashlib.sha256).hexdigest()


def _get_appcore_exe() -> Path:
    here = Path(sys.executable).parent
    return here / 'AppCore' / 'CDP-v3.4.2.exe'


def main():
    appcore = _get_appcore_exe()

    if not appcore.is_file():
        print(f"[Launcher] ERROR: AppCore not found at:")
        print(f"           {appcore}")
        print()
        print("  Make sure the folder structure is:")
        print("    Launcher.exe")
        print("    AppCore/")
        print("    └── CDP-v3.4.2.exe")
        input("\nPress Enter to exit...")
        sys.exit(1)

    env = os.environ.copy()
    env[_ENV_TOKEN]      = _make_token()
    env[_ENV_PID]        = str(os.getpid())
    # Tell AppCore where Root is so tools/ output/ logs/ temp/ resolve correctly
    env['CDP_ROOT_DIR']  = str(Path(sys.executable).resolve().parent)

    try:
        proc = subprocess.Popen(
            [str(appcore)],
            env=env,
        )
        proc.wait()
        sys.exit(proc.returncode or 0)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"[Launcher] Failed to start AppCore: {e}")
        input("\nPress Enter to exit...")
        sys.exit(1)


if __name__ == '__main__':
    main()
