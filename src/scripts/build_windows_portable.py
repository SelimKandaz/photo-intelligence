from __future__ import annotations

import argparse
import fnmatch
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST_ROOT = ROOT / "dist" / "PhotoIntelligence"


def run(cmd: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None) -> None:
    print(" ".join(str(part) for part in cmd))
    subprocess.run(cmd, cwd=str(cwd), env=env, check=True)


def ensure_pyinstaller() -> None:
    try:
        import PyInstaller  # noqa: F401
    except Exception:
        run([sys.executable, "-m", "pip", "install", "pyinstaller>=6.11"])


def reset_dist() -> None:
    target = DIST_ROOT.resolve()
    expected_parent = (ROOT / "dist").resolve()
    if target.exists():
        if expected_parent not in target.parents:
            raise RuntimeError(f"Refusing to delete unexpected path: {target}")
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)


def ignore_source(_directory: str, names: list[str]) -> set[str]:
    ignored = {
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".venv",
        "data",
        "dist",
        "build",
        "work",
        "outputs",
        "logs",
    }
    patterns = ("*.pyc", "*.pyo", "*.pyd", "*.log", "*.tmp", "*.db", "*.db-wal", "*.db-shm")
    return {
        name
        for name in names
        if name in ignored or any(fnmatch.fnmatch(name, pattern) for pattern in patterns)
    }


def remove_python_caches(root: Path) -> None:
    for cache_dir in root.rglob("__pycache__"):
        shutil.rmtree(cache_dir, ignore_errors=True)
    for pattern in ("*.pyc", "*.pyo"):
        for file_path in root.rglob(pattern):
            file_path.unlink(missing_ok=True)


def copy_source() -> None:
    src_root = DIST_ROOT / "src"
    src_root.mkdir(parents=True, exist_ok=True)
    for directory in ("app", "scripts", "tests", "docs"):
        shutil.copytree(ROOT / directory, src_root / directory, ignore=ignore_source, dirs_exist_ok=True)
    for file_name in ("requirements.txt", ".env.example"):
        shutil.copy2(ROOT / file_name, src_root / file_name)
    shutil.copy2(ROOT / "run_app.bat", src_root / "run_app.bat")
    shutil.copy2(ROOT / "README.md", DIST_ROOT / "README.md")
    shutil.copy2(ROOT / "run_app.bat", DIST_ROOT / "run_app.bat")
    shutil.copy2(ROOT / ".env.example", DIST_ROOT / ".env.example")
    remove_python_caches(src_root)


def write_portable_env() -> None:
    env_text = "\n".join(
        [
            "APP_MODE=desktop",
            "DATABASE_URL=sqlite:///data/photo_inventory.db",
            "HOST=127.0.0.1",
            "PORT=8001",
            "PHOTO_STORAGE_ROOT=storage/photos",
            "THUMBNAIL_ROOT=data/thumbnails",
            "IMPORT_FOLDER=photos",
            "EXPORT_ROOT=data/exports",
            "LOG_ROOT=logs",
            "STORAGE_MODE=copy",
            "EXTRACTOR_NAME=v7_modular_audit",
            "EXTRACTOR_VERSION=0.1.0",
            "OCR_BACKEND=audit",
            r"TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe",
            "WORKER_MODE=local-thread",
            "",
        ]
    )
    (DIST_ROOT / ".env").write_text(env_text, encoding="utf-8")


def create_data_dirs() -> None:
    for relative in (
        "data",
        "data/thumbnails",
        "data/exports",
        "storage/photos",
        "photos",
        "logs",
    ):
        (DIST_ROOT / relative).mkdir(parents=True, exist_ok=True)


def build_launcher() -> None:
    ensure_pyinstaller()
    build_root = ROOT / "work" / "pyinstaller"
    py_dist = build_root / "dist"
    if build_root.exists():
        shutil.rmtree(build_root)
    run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onedir",
            "--windowed",
            "--name",
            "PhotoIntelligence",
            "--distpath",
            str(py_dist),
            "--workpath",
            str(build_root / "build"),
            "--specpath",
            str(build_root),
            str(ROOT / "scripts" / "desktop_launcher.py"),
        ]
    )
    launcher_dir = py_dist / "PhotoIntelligence"
    shutil.copy2(launcher_dir / "PhotoIntelligence.exe", DIST_ROOT / "PhotoIntelligence.exe")
    internal = launcher_dir / "_internal"
    if internal.exists():
        shutil.copytree(internal, DIST_ROOT / "_internal", dirs_exist_ok=True)


def create_runtime_venv() -> None:
    venv_dir = DIST_ROOT / ".venv"
    run([sys.executable, "-m", "venv", str(venv_dir)])
    python = venv_dir / "Scripts" / "python.exe"
    run([str(python), "-m", "pip", "install", "-U", "pip"])
    run([str(python), "-m", "pip", "install", "-r", str(DIST_ROOT / "src" / "requirements.txt")])


def init_database() -> None:
    python = DIST_ROOT / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        return
    env = os.environ.copy()
    env["PHOTO_INTELLIGENCE_ROOT"] = str(DIST_ROOT)
    env["PYTHONPATH"] = str(DIST_ROOT / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    run([str(python), str(DIST_ROOT / "src" / "scripts" / "init_db.py")], cwd=DIST_ROOT, env=env)


def verify_build(skip_runtime: bool) -> dict[str, str]:
    required = {
        "launcher_exe": DIST_ROOT / "PhotoIntelligence.exe",
        "source_app": DIST_ROOT / "src" / "app",
        "env": DIST_ROOT / ".env",
        "run_app_bat": DIST_ROOT / "run_app.bat",
        "data": DIST_ROOT / "data",
        "storage": DIST_ROOT / "storage",
        "photos": DIST_ROOT / "photos",
        "logs": DIST_ROOT / "logs",
    }
    if not skip_runtime:
        required["runtime_python"] = DIST_ROOT / ".venv" / "Scripts" / "python.exe"
    missing = [name for name, path in required.items() if not path.exists()]
    if missing:
        detail = "\n".join(f"{name}: {required[name]}" for name in missing)
        raise RuntimeError(f"Portable build verification failed:\n{detail}")
    pyc_files = list((DIST_ROOT / "src").rglob("*.pyc"))
    cache_dirs = list((DIST_ROOT / "src").rglob("__pycache__"))
    if pyc_files or cache_dirs:
        raise RuntimeError("Portable src contains Python cache artifacts.")
    return {name: str(path) for name, path in required.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build portable Windows PhotoIntelligence folder.")
    parser.add_argument(
        "--skip-runtime",
        action="store_true",
        help="Do not create dist .venv or install requirements. Useful for quick source/launcher builds.",
    )
    args = parser.parse_args()

    reset_dist()
    copy_source()
    write_portable_env()
    create_data_dirs()
    build_launcher()
    if not args.skip_runtime:
        create_runtime_venv()
        init_database()

    remove_python_caches(DIST_ROOT / "src")
    summary = verify_build(args.skip_runtime)
    print(f"\nPortable app created at: {DIST_ROOT}")
    print(f"Launcher EXE: {DIST_ROOT / 'PhotoIntelligence.exe'}")
    print(f"Visible source: {DIST_ROOT / 'src'}")
    print("\nBuild verification:")
    for name, path in summary.items():
        print(f"  {name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
