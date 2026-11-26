"""Build PCVH's wheel and serve its HTML routes outside the source checkout."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from urllib.request import ProxyHandler, build_opener
import venv

ROOT = Path(__file__).resolve().parents[1]


def check_installed(workspace: Path) -> None:
    import pcvh
    from pcvh.studio.server import create_studio_server

    if not Path(pcvh.__file__).is_relative_to(Path(sys.prefix)):
        raise AssertionError(f"PCVH was not imported from the installed wheel: {pcvh.__file__}")

    pages = {
        "/": ("PCVH Studio", 'href="/showcase"', 'href="/eval"'),
        "/showcase": ("Eight Verified Engineering Specifications", "nav-eval-link"),
        "/eval": ("40-Invariant Benchmark Report", "ev-showcase-link"),
    }
    opener = build_opener(ProxyHandler({}))
    with create_studio_server(workspace, port=0) as studio:
        server_thread = threading.Thread(target=studio.serve_forever, daemon=True)
        server_thread.start()
        try:
            for route, markers in pages.items():
                url = f"http://127.0.0.1:{studio.server_port}{route}"
                with opener.open(url, timeout=10) as response:
                    assert response.status == 200, f"{route} returned {response.status}"
                    assert response.headers.get_content_type() == "text/html", route
                    body = response.read().decode("utf-8")
                    assert all(marker in body for marker in markers), route
                    print(f"Wheel Studio route {route}: OK")
        finally:
            studio.shutdown()
            server_thread.join()


def check_wheel(*, offline: bool) -> None:
    with tempfile.TemporaryDirectory(prefix="pcvh-wheel-") as scratch:
        work = Path(scratch)
        wheel_dir = work / "wheels"
        build_flags = ["--no-index", "--no-build-isolation"] if offline else []
        subprocess.run(
            [
                sys.executable, "-m", "pip", "wheel", "--no-deps", *build_flags,
                "--wheel-dir", str(wheel_dir), str(ROOT / "pcvh"),
            ],
            cwd=work,
            check=True,
        )
        env_dir = work / "env"
        venv.EnvBuilder(with_pip=True, system_site_packages=offline).create(env_dir)
        python = env_dir / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        (wheel,) = wheel_dir.glob("pcvh-*.whl")
        install_flags = ["--no-index"] if offline else []
        subprocess.run(
            [str(python), "-m", "pip", "install", *install_flags, str(wheel)],
            cwd=work,
            check=True,
        )
        subprocess.run(
            [str(python), "-I", str(Path(__file__).resolve()), "--installed", str(work)],
            cwd=work,
            check=True,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="use already installed build tools and runtime dependencies")
    parser.add_argument("--installed", type=Path, help=argparse.SUPPRESS)
    options = parser.parse_args()
    if options.installed is None:
        check_wheel(offline=options.offline)
    else:
        check_installed(options.installed)
