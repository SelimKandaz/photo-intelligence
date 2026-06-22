from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path


APP_NAME = "Photo Intelligence"


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def message_box(title: str, message: str) -> None:
    try:
        ctypes.windll.user32.MessageBoxW(None, message, title, 0x10)
    except Exception:
        print(f"{title}\n{message}", file=sys.stderr)


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def source_root(root: Path) -> Path:
    src = root / "src"
    return src if (src / "app" / "desktop" / "main.py").exists() else root


def _candidate_commands(root: Path) -> list[list[str]]:
    commands: list[list[str]] = []
    bundled = root / ".venv" / "Scripts" / "python.exe"
    if bundled.exists():
        commands.append([str(bundled)])
    py_launcher = shutil.which("py")
    if py_launcher:
        commands.append([py_launcher, "-3.12"])
    for name in ("python", "python3"):
        found = shutil.which(name)
        if found:
            commands.append([found])
    return commands


def _python_is_usable(command: list[str], env: dict[str, str]) -> tuple[bool, str]:
    probe = (
        "import sys; "
        "raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 12)"
    )
    try:
        result = subprocess.run(
            [*command, "-c", probe],
            cwd=env.get("PHOTO_INTELLIGENCE_ROOT") or None,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as exc:
        return False, f"{' '.join(command)} -> {exc}"
    if result.returncode == 0:
        return True, ""
    output = (result.stdout + result.stderr).strip()
    return False, f"{' '.join(command)} -> exit {result.returncode}: {output}"


def find_python(root: Path, env: dict[str, str]) -> list[str]:
    errors: list[str] = []
    for command in _candidate_commands(root):
        ok, detail = _python_is_usable(command, env)
        if ok:
            return command
        errors.append(detail)
    detail_text = "\n".join(errors) if errors else "No Python candidates found."
    raise FileNotFoundError(
        "Could not find a usable Python 3.12 runtime.\n\n"
        "This package includes the dependency folder, but Windows venv launchers are not truly portable. "
        "Run Repair_Runtime.bat once on this computer, or install Python 3.12 and then start again.\n\n"
        f"Checks tried:\n{detail_text}"
    )


def configure_runtime_env(root: Path, src: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PHOTO_INTELLIGENCE_ROOT"] = str(root)
    python_path_parts = [
        str(src),
        str(root / ".venv" / "Lib" / "site-packages"),
    ]
    existing_pythonpath = env.get("PYTHONPATH")
    if existing_pythonpath:
        python_path_parts.append(existing_pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(python_path_parts)

    path_parts = [
        str(root / ".venv" / "Scripts"),
        str(root / ".venv" / "Lib" / "site-packages"),
        str(root / ".venv" / "Lib" / "site-packages" / "PySide6"),
        str(root / ".venv" / "Lib" / "site-packages" / "PySide6" / "Qt6" / "bin"),
        env.get("PATH", ""),
    ]
    env["PATH"] = os.pathsep.join(part for part in path_parts if part)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def main() -> int:
    root = app_root()
    logs = root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log_path = logs / "desktop_app.log"
    launcher_log = logs / "launcher.log"

    try:
        env_path = root / ".env"
        example_path = root / ".env.example"
        if not env_path.exists() and example_path.exists():
            env_path.write_text(example_path.read_text(encoding="utf-8"), encoding="utf-8")
        load_dotenv(env_path)

        src = source_root(root)
        script = src / "app" / "desktop" / "main.py"
        if not script.exists():
            raise FileNotFoundError(f"Desktop entrypoint not found: {script}")

        env = configure_runtime_env(root, src)
        python = find_python(root, env)
        with log_path.open("a", encoding="utf-8") as log_file:
            log_file.write("\n--- Photo Intelligence desktop startup ---\n")
            log_file.write(f"Root: {root}\n")
            log_file.write(f"Python: {' '.join(python)}\n")
            log_file.flush()
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            process = subprocess.Popen(
                [*python, "-m", "app.desktop.main"],
                cwd=str(root),
                env=env,
                stdout=log_file,
                stderr=log_file,
                creationflags=creationflags,
            )
        time.sleep(2)
        if process.poll() not in (None, 0):
            tail = log_path.read_text(encoding="utf-8", errors="replace")[-3000:]
            raise RuntimeError(f"Desktop app exited during startup.\n\n{tail}")
        return 0
    except Exception as exc:
        details = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        launcher_log.write_text(details, encoding="utf-8")
        message_box(f"{APP_NAME} startup failed", details[:4000])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
