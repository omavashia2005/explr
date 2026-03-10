"""
explr – trace any Python process and output a call graph diagram.

Usage:
    explr [--depth N] [--no-stdlib] [--output NAME] <target> [target-args ...]

Flags consumed by explr (anything with --depth/--no-stdlib/--output):
    --depth N        Limit call depth (default: unlimited)
    --no-stdlib      Exclude stdlib calls from the graph
    --output NAME    Override output filename (without extension)

All other arguments are passed through to the target process.
"""

import argparse
import os
import shutil
import sys
from pathlib import Path
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Python-process detection
# ---------------------------------------------------------------------------

def _has_python_shebang(path: str) -> bool:
    """Return True if *path* has a #!...python... shebang line."""
    try:
        with open(path, "rb") as f:
            first = f.read(200)
    except OSError:
        return False
    if not first.startswith(b"#!"):
        return False
    line = first.split(b"\n", 1)[0].decode("utf-8", errors="ignore")
    return "python" in line.lower()


def _is_python_target(target: str) -> bool:
    """
    Decide whether *target* refers to a Python process.

    Rules (in order):
    1. Ends with .py → yes
    2. Is python / python3 (or path to them) → yes (caller strips these)
    3. Resolves to an executable with a python shebang → yes
    """
    p = Path(target)
    if p.suffix == ".py":
        return True
    base = p.name.lower()
    if base in ("python", "python3") or base.startswith("python3."):
        return True
    exe = shutil.which(target)
    if exe and _has_python_shebang(exe):
        return True
    return False


def _resolve_target(argv: List[str]) -> Tuple[str, List[str]]:
    """
    Given the positional args list (target + target_args), strip any leading
    python/python3 invocation and return (actual_target, remaining_args).

    Examples:
        ["abc.py"]              -> ("abc.py", [])
        ["python", "abc.py"]   -> ("abc.py", [])
        ["pytest", "tests/"]   -> ("pytest", ["tests/"])
    """
    if not argv:
        return "", []

    target = argv[0]
    rest = argv[1:]

    base = Path(target).name.lower()
    if base in ("python", "python3") or base.startswith("python3."):
        if rest:
            return rest[0], rest[1:]
        return target, []  # bare python – nothing to trace

    return target, rest


# ---------------------------------------------------------------------------
# Output path
# ---------------------------------------------------------------------------

def _output_path(target: str, output_override: Optional[str]) -> str:
    out_dir = Path("explr_diagrams")
    out_dir.mkdir(exist_ok=True)
    if output_override:
        name = output_override
    else:
        stem = Path(target).stem or target.replace(os.sep, "_")
        name = f"{stem}_diagram"
    return str(out_dir / f"{name}.png")


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="explr",
        description="Trace a Python process and output a call graph diagram.",
        add_help=True,
    )
    p.add_argument(
        "--depth",
        metavar="N",
        type=int,
        default=None,
        help="Limit call depth (default: unlimited)",
    )
    p.add_argument(
        "--no-stdlib",
        action="store_true",
        default=False,
        help="Exclude stdlib calls from the graph",
    )
    p.add_argument(
        "--output",
        metavar="NAME",
        default=None,
        help="Override output filename (without extension)",
    )
    p.add_argument(
        "target",
        nargs=argparse.REMAINDER,
        help="Python target to trace, plus any args for it",
    )
    return p


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    raw_target: List[str] = args.target or []
    if not raw_target:
        parser.print_help()
        sys.exit(1)

    target, target_args = _resolve_target(raw_target)

    if not target:
        print("explr: no target specified", file=sys.stderr)
        sys.exit(1)

    if not _is_python_target(target):
        print(
            f"explr: '{target}' does not appear to be a Python process.\n"
            "explr supports: .py files, python/python3 invocations, and\n"
            "executables with a Python shebang line.",
            file=sys.stderr,
        )
        sys.exit(2)

    out_path = _output_path(target, args.output)

    print(f"[explr] tracing: {target} {' '.join(target_args)}")
    print(f"[explr] output:  {out_path}")

    # lazy imports so startup stays fast for error paths
    from .tracer import run_trace
    from .renderer import render

    call_graph = run_trace(
        target,
        target_args,
        max_depth=args.depth,
        no_stdlib=args.no_stdlib,
    )

    edge_count = len(call_graph.edges)
    node_count = len(call_graph.nodes)
    print(f"[explr] captured {node_count} nodes, {edge_count} edges")

    if node_count == 0:
        print("[explr] nothing to render – no calls were captured", file=sys.stderr)
        sys.exit(3)

    # Ensure Homebrew graphviz is findable on macOS even if not in shell PATH
    _gv_extra = "/opt/homebrew/bin" if sys.platform == "darwin" else None
    render(call_graph, out_path, target_name=target, _graphviz_path=_gv_extra)


if __name__ == "__main__":
    main()
