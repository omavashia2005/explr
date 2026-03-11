"""
sys.settrace instrumentation for explr.

Strategy: generate a bootstrap Python script that installs the trace,
runs the target, then serializes edge data to a temp JSON file.
The main process reads that file and builds a CallGraph.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

from .models import CallGraph


# ---------------------------------------------------------------------------
# Bootstrap script template
# ---------------------------------------------------------------------------
# Written to a temp file and executed by a fresh Python interpreter so that
# the trace covers the target from first import.
# ---------------------------------------------------------------------------

_BOOTSTRAP_TMPL = '''
import sys as _sys
import json as _json
import atexit as _atexit
import os as _os
import sysconfig as _sc

# --- injected config ---
_MAX_DEPTH  = {max_depth}
_NO_STDLIB  = {no_stdlib}
_OUTPUT     = {output!r}
_RUN_MODE   = {run_mode!r}   # "path" | "module"
_TARGET     = {target!r}
# -----------------------

_stdlib_paths = tuple(filter(None, [
    _sc.get_paths().get("stdlib", ""),
    _sc.get_paths().get("platstdlib", ""),
    _sc.get_paths().get("purelib", ""),
    _sc.get_paths().get("platlib", ""),
    _os.path.dirname(_os.__file__),
]))

def _is_stdlib(filename):
    if not filename:
        return True
    fn = _os.path.normcase(_os.path.abspath(filename))
    return any(fn.startswith(_os.path.normcase(p)) for p in _stdlib_paths if p)

_seq_ctr = [0]
_edges = {{}}   # (cm, cf, em, ef) -> [count, seq]
_stack = []    # [(module, func)]

def _trace(frame, event, arg):
    if event == "call":
        module   = frame.f_globals.get("__name__", "")
        func     = frame.f_code.co_name
        filename = frame.f_code.co_filename or ""
        depth    = len(_stack)

        if _NO_STDLIB and _is_stdlib(filename):
            return None
        if _MAX_DEPTH is not None and depth >= _MAX_DEPTH:
            return None

        caller = _stack[-1] if _stack else ("<root>", "<root>")
        key    = (caller[0], caller[1], module, func)
        if key not in _edges:
            _edges[key] = [0, _seq_ctr[0]]
            _seq_ctr[0] += 1
        _edges[key][0] += 1
        _stack.append((module, func))
        return _trace

    elif event in ("return", "exception"):
        if _stack:
            _stack.pop()
    return _trace


def _save():
    _sys.settrace(None)
    data = [
        {{"caller_module": cm, "caller_func": cf,
          "callee_module": em, "callee_func": ef,
          "count": v[0], "seq": v[1]}}
        for (cm, cf, em, ef), v in _edges.items()
    ]
    try:
        with open(_OUTPUT, "w") as _f:
            _json.dump(data, _f)
    except Exception as _exc:
        _sys.stderr.write(f"[explr] failed to save trace: {{_exc}}\\n")


_atexit.register(_save)

# Rewrite argv so the target sees itself as sys.argv[0]
_sys.argv[0] = _TARGET

# Mirror what `python script.py` does: put the script's directory first on sys.path
if _RUN_MODE == "path":
    _script_dir = _os.path.dirname(_os.path.abspath(_TARGET))
    if not _sys.path or _sys.path[0] != _script_dir:
        _sys.path.insert(0, _script_dir)

_sys.settrace(_trace)

import runpy as _runpy
if _RUN_MODE == "path":
    _runpy.run_path(_TARGET, run_name="__main__")
elif _RUN_MODE == "module":
    _runpy.run_module(_TARGET, run_name="__main__", alter_sys=True)
else:
    raise ValueError(f"Unknown run mode: {{_RUN_MODE!r}}")

# Stop tracing now so atexit callbacks (including _save) are not captured
_sys.settrace(None)
'''


def _detect_run_mode(target: str):
    """
    Returns (run_mode, resolved_target).
    run_mode: "path" for a .py file, "module" for a module name.
    """
    p = Path(target)
    if p.suffix == ".py" or p.is_file():
        return "path", str(p.resolve())
    # treat as module (pytest, flask, etc.)
    return "module", target


def run_trace(
    target: str,
    target_args: List[str],
    *,
    max_depth: Optional[int] = None,
    no_stdlib: bool = False,
) -> CallGraph:
    """
    Inject a trace into *target*, execute it with *target_args*,
    collect the call graph, and return a :class:`CallGraph`.
    """
    run_mode, resolved_target = _detect_run_mode(target)

    # temp file for trace output
    fd, trace_path = tempfile.mkstemp(suffix=".json", prefix="explr_trace_")
    os.close(fd)

    # temp file for bootstrap script
    fdb, bootstrap_path = tempfile.mkstemp(suffix=".py", prefix="explr_boot_")
    try:
        bootstrap_src = _BOOTSTRAP_TMPL.format(
            max_depth=repr(max_depth),
            no_stdlib=repr(no_stdlib),
            output=trace_path,
            run_mode=run_mode,
            target=resolved_target,
        )
        with os.fdopen(fdb, "w") as f:
            f.write(bootstrap_src)

        cmd = [sys.executable, bootstrap_path] + target_args
        result = subprocess.run(cmd)
        if result.returncode != 0:
            print(
                f"[explr] target exited with code {result.returncode}",
                file=sys.stderr,
            )
    finally:
        try:
            os.unlink(bootstrap_path)
        except OSError:
            pass

    # read trace
    try:
        with open(trace_path) as f:
            trace_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"[explr] could not read trace data: {exc}", file=sys.stderr)
        trace_data = []
    finally:
        try:
            os.unlink(trace_path)
        except OSError:
            pass

    return CallGraph.from_trace_data(trace_data)
