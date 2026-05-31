"""
Build TradeNexus into a single self-contained executable using PyInstaller.

Usage:
    .venv/bin/python build.py          # build + smoke-test
    .venv/bin/python build.py --build  # build only
    .venv/bin/python build.py --test   # test only (executable must already exist)
"""

import os
import subprocess
import sys
import pathlib
import time
import urllib.request
import urllib.error

ROOT    = pathlib.Path(__file__).parent
BACKEND = ROOT / "backend"
DIST    = ROOT / "dist"
EXE     = DIST / "tradenexus"
PORT    = 8765

# uvicorn dynamically imports these via importlib — PyInstaller can't see them
HIDDEN_IMPORTS = [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.loops.uvloop",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.protocols.websockets.wsproto_impl",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "anyio._backends._asyncio",
    "anyio._backends._trio",
    # yfinance runtime dependencies that static analysis may miss
    "html5lib",
    "html5lib.treebuilders",
    "html5lib.treebuilders.etree",
    "html5lib.treebuilders.etree_lxml",
    "multitasking",
    "peewee",
    "frozendict",
    "platformdirs",
    "appdirs",
    "bs4",
    "pytz",
]

# Packages whose C extensions, data files, and submodules require --collect-all
# because PyInstaller's static import-graph walk misses them.
COLLECT_ALL = [
    "yfinance",   # submodules and JSON data files
    "pandas",     # C extensions loaded via importlib internally
    "numpy",      # C extensions and .pyi stubs
    "lxml",       # compiled parser extensions
    "curl_cffi",  # libcurl binary — optional but yfinance prefers it
    # FastAPI imports these lazily inside ensure_multipart_is_installed(), so the
    # static import graph misses them. Needed for the /settings/restore upload.
    "python_multipart",
    "multipart",
]


def build():
    print("Building TradeNexus executable ...")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name",     "tradenexus",
        "--distpath", str(DIST),
        "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT),
        "--paths",    str(BACKEND),
        # Bundle schema.sql so ensure_initialized() can create the DB on first run.
        "--add-data", f"{BACKEND / 'schema.sql'}{os.pathsep}.",
    ]
    for mod in HIDDEN_IMPORTS:
        cmd += ["--hidden-import", mod]
    for pkg in COLLECT_ALL:
        cmd += ["--collect-all", pkg]
    cmd.append(str(BACKEND / "entrypoint.py"))

    subprocess.run(cmd, check=True)
    print(f"\nBuild complete -> {EXE}")


def test():
    if not EXE.exists():
        sys.exit(f"Executable not found: {EXE}  (run build first)")

    print(f"\nStarting {EXE} ...")
    proc = subprocess.Popen(
        [str(EXE)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    # --onefile extracts to /tmp on first run, so give it a moment
    deadline = time.monotonic() + 15
    url = f"http://localhost:{PORT}/users"
    connected = False

    while time.monotonic() < deadline:
        time.sleep(0.5)
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                body = resp.read().decode()
            print(f"GET /users -> {resp.status}  {body[:120]}")
            connected = True
            break
        except urllib.error.URLError:
            pass  # still starting

    if not connected:
        out, _ = proc.communicate(timeout=3)
        print("Server output:\n", out.decode())
        proc.terminate()
        sys.exit("Server did not respond within 15 s")

    proc.terminate()
    proc.wait()
    print("Server stopped cleanly.")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or "--build" in args:
        build()
    if not args or "--test" in args:
        test()
