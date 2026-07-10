#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
BUILD_DIR = ROOT / ".eval_build"


def _compiler_command() -> tuple[list[str], Path] | None:
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    executable = BUILD_DIR / ("frame_parser_tests.exe" if os.name == "nt" else "frame_parser_tests")
    include_dir = ROOT / "include"
    source = ROOT / "src" / "frame_parser.cpp"
    tests = ROOT / "tests" / "frame_parser_tests.cpp"

    cl = shutil.which("cl")
    if cl:
        return (
            [
                cl,
                "/nologo",
                "/W4",
                "/WX",
                "/EHsc",
                f"/I{include_dir}",
                str(source),
                str(tests),
                f"/Fe:{executable}",
            ],
            executable,
        )

    compiler = shutil.which("clang++") or shutil.which("g++")
    if compiler:
        return (
            [
                compiler,
                "-std=c++11",
                "-Wall",
                "-Wextra",
                "-Werror",
                f"-I{include_dir}",
                str(source),
                str(tests),
                "-o",
                str(executable),
            ],
            executable,
        )
    return None


def main() -> int:
    selected = _compiler_command()
    if selected is None:
        print("No supported local C++ compiler was found (MSVC, clang++, or g++).", file=sys.stderr)
        return 2
    command, executable = selected
    compiled = subprocess.run(command, cwd=str(BUILD_DIR), text=True, capture_output=True, check=False)
    if compiled.stdout:
        print(compiled.stdout, end="")
    if compiled.stderr:
        print(compiled.stderr, end="", file=sys.stderr)
    if compiled.returncode != 0:
        return 1
    tested = subprocess.run([str(executable)], cwd=str(ROOT), text=True, capture_output=True, check=False)
    if tested.stdout:
        print(tested.stdout, end="")
    if tested.stderr:
        print(tested.stderr, end="", file=sys.stderr)
    return 0 if tested.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
