"""
sys.settrace instrumentation for explr.

Strategy: generate a bootstrap Python script that installs the trace,
runs the target, then serializes edge data to a temp JSON file.
The main process reads that file and builds a CallGraph.
"""

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

from .models import CallGraph


# ---------------------------------------------------------------------------
# Shell command resolution
# ---------------------------------------------------------------------------

def _is_python_interp(name: str) -> bool:
    """Return True if name looks like a python interpreter binary."""
    n = Path(name).name.lower()
    return n in ("python", "python3") or bool(re.match(r"^python3?\.\d+$", n))


def _python_args_from_parts(parts: List[str]) -> Optional[Tuple[str, List[str]]]:
    """
    Given a tokenised command like ['python3', '-m', 'myapp', '--flag'],
    extract (python_target, extra_args) where target is the script path or
    module name, and extra_args are the args that follow.

    Returns None if parts don't start with a python interpreter.
    """
    if not parts:
        return None

    idx = 0
    # Skip the interpreter itself
    if _is_python_interp(parts[idx]):
        idx += 1
    else:
        return None

    # Consume interpreter flags: -u, -O, -W default, -c '...', -m mod, script.py
    extra: List[str] = []
    while idx < len(parts):
        tok = parts[idx]
        if tok == "-m" and idx + 1 < len(parts):
            return parts[idx + 1], parts[idx + 2:]   # module mode
        if tok.startswith("-"):
            # Single-char flags with an attached or separate value
            if tok in ("-W", "-X", "-c"):
                idx += 2
            else:
                idx += 1
            continue
        # First non-flag token is the script path
        return tok, parts[idx + 1:]

    return None


def _inspect_file_for_python(path: str) -> Optional[Tuple[str, List[str]]]:
    """
    Read up to the first 40 lines of *path* looking for evidence that it
    invokes Python.

    Returns (python_target, extra_args) where:
      - python_target is the script path (for shebang scripts) or module name
      - extra_args are any args baked into the shebang / exec line

    Returns None if no Python invocation is found.
    """
    try:
        with open(path, "rb") as f:
            raw = f.read(4096)
    except OSError:
        return None

    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception:
        return None

    lines = text.splitlines()
    if not lines:
        return None

    # ── shebang check ──────────────────────────────────────────────────────
    first = lines[0]
    if first.startswith("#!"):
        shebang_parts = first[2:].split()
        if shebang_parts:
            interp = shebang_parts[0]
            interp_name = Path(interp).name.lower()

            # #!/usr/bin/python3  or  #!/usr/bin/env python3
            if _is_python_interp(interp_name):
                return path, []
            if interp_name == "env" and len(shebang_parts) > 1 and _is_python_interp(shebang_parts[1]):
                return path, []

        # It's a shell script — scan the body for `exec python ...` patterns
        if any(sh in first for sh in ("bash", "sh", "zsh", "dash")):
            for line in lines[1:40]:
                stripped = line.strip()
                if stripped.startswith("#") or not stripped:
                    continue
                # match: exec python3 ..., python3 script.py "$@", etc.
                m = re.match(r"(?:exec\s+)?(python3?(?:\.\d+)?)\s+(.*)", stripped)
                if m:
                    rest = shlex.split(m.group(2)) if m.group(2) else []
                    result = _python_args_from_parts([m.group(1)] + rest)
                    if result:
                        return result

    return None


def _shell_resolve_command(cmd: str) -> Optional[Tuple[str, List[str]]]:
    """
    Ask the user's interactive shell to expand *cmd* (handles aliases and
    shell functions).  Returns (python_target, extra_args) or None.

    Spawns  shell -i -c "type -a <cmd>"  and parses the output.
    Falls back to bash if $SHELL is not set.
    """
    shell = os.environ.get("SHELL", "/bin/bash")

    try:
        result = subprocess.run(
            [shell, "-i", "-c", f"type -a {shlex.quote(cmd)} 2>/dev/null"],
            capture_output=True, text=True, timeout=5,
        )
        type_out = result.stdout.strip()
    except Exception:
        return None

    if not type_out:
        return None

    # ── alias ──────────────────────────────────────────────────────────────
    # bash: "cmd is aliased to `python3 /path/script.py'"
    # zsh:  "cmd is an alias for python3 /path/script.py"
    alias_m = re.search(
        r"aliased to [`'\"]?(.*?)[`'\"]?\s*$|alias for (.+)$",
        type_out, re.MULTILINE
    )
    if alias_m:
        raw = (alias_m.group(1) or alias_m.group(2) or "").strip().strip("'\"")
        try:
            parts = shlex.split(raw)
        except ValueError:
            parts = raw.split()
        result2 = _python_args_from_parts(parts)
        if result2:
            return result2

    # ── shell function ─────────────────────────────────────────────────────
    if "function" in type_out.lower() or "shell function" in type_out.lower():
        try:
            # get function body: works in bash; zsh uses 'functions cmd'
            fb_result = subprocess.run(
                [shell, "-i", "-c",
                 f"declare -f {shlex.quote(cmd)} 2>/dev/null || "
                 f"functions {shlex.quote(cmd)} 2>/dev/null"],
                capture_output=True, text=True, timeout=5,
            )
            body = fb_result.stdout
        except Exception:
            body = ""

        for line in body.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                continue
            m = re.match(r"(?:exec\s+)?(python3?(?:\.\d+)?(?:\s+\S+)?)\s*(.*)", stripped)
            if m:
                try:
                    parts = shlex.split(m.group(1) + " " + m.group(2))
                except ValueError:
                    parts = (m.group(1) + " " + m.group(2)).split()
                r = _python_args_from_parts(parts)
                if r:
                    return r

    # ── plain file on PATH ─────────────────────────────────────────────────
    # "cmd is /usr/local/bin/cmd"
    file_m = re.search(r" is (/\S+)", type_out)
    if file_m:
        file_path = file_m.group(1)
        r = _inspect_file_for_python(file_path)
        if r:
            return r

    return None


def resolve_to_python(cmd: str) -> Optional[Tuple[str, List[str]]]:
    """
    Public entry point: resolve *cmd* to a (python_target, extra_args) tuple.

    Resolution order:
      1. Already a .py file → return as-is
      2. Executable on PATH → inspect shebang / body
      3. Interactive-shell expansion (aliases, shell functions)

    Returns None if *cmd* cannot be resolved to a Python program.
    The caller is responsible for prepending extra_args to the target_args list.
    """
    # 1. bare .py file
    if Path(cmd).suffix == ".py":
        return cmd, []

    # 2. look on PATH first (avoids spawning a shell for the common case)
    exe = shutil.which(cmd)
    if exe:
        r = _inspect_file_for_python(exe)
        if r:
            return r

    # 3. shell expansion (aliases / functions / anything the shell knows)
    return _shell_resolve_command(cmd)


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


def trace_func(
    func,
    args: tuple = (),
    kwargs: Optional[dict] = None,
    *,
    max_depth: Optional[int] = None,
    no_stdlib: bool = False,
) -> CallGraph:
    """
    Trace a single callable in-process and return a CallGraph.

    Unlike run_trace, this does not spawn a subprocess — it installs
    sys.settrace directly, calls func(*args, **kwargs), then restores
    whatever trace was in place before.
    """
    import sysconfig as _sc

    if kwargs is None:
        kwargs = {}

    stdlib_paths = tuple(filter(None, [
        _sc.get_paths().get("stdlib", ""),
        _sc.get_paths().get("platstdlib", ""),
        os.path.dirname(os.__file__),
    ]))

    def _is_stdlib(filename: str) -> bool:
        if not filename:
            return True
        fn = os.path.normcase(os.path.abspath(filename))
        return any(fn.startswith(os.path.normcase(p)) for p in stdlib_paths if p)

    edges: dict = {}   # (cm, cf, em, ef) -> [count, seq]
    stack: list = []
    seq_ctr = [0]

    def _tracer(frame, event, _arg):
        if event == "call":
            module    = frame.f_globals.get("__name__", "")
            func_name = frame.f_code.co_name
            filename  = frame.f_code.co_filename or ""
            depth     = len(stack)

            if no_stdlib and _is_stdlib(filename):
                return None
            if max_depth is not None and depth >= max_depth:
                return None

            caller = stack[-1] if stack else ("<root>", "<root>")
            key = (caller[0], caller[1], module, func_name)
            if key not in edges:
                edges[key] = [0, seq_ctr[0]]
                seq_ctr[0] += 1
            edges[key][0] += 1
            stack.append((module, func_name))
            return _tracer
        elif event in ("return", "exception"):
            if stack:
                stack.pop()
        return _tracer

    import asyncio
    import inspect

    old_trace = sys.gettrace()
    sys.settrace(_tracer)
    try:
        result = func(*args, **kwargs)
        if inspect.iscoroutine(result):
            try:
                asyncio.get_running_loop()
                # Already inside a running loop (e.g. Jupyter) — can't use asyncio.run()
                raise RuntimeError(
                    "explr.trace() cannot be called from within a running event loop.\n"
                    "Call it from a synchronous context, e.g. wrap with asyncio.run():\n"
                    "  asyncio.run(explr.trace_async(func, args=...))"
                )
            except RuntimeError as exc:
                if "no running event loop" in str(exc).lower() or \
                   "no current event loop" in str(exc).lower():
                    asyncio.run(result)
                else:
                    raise
    finally:
        sys.settrace(old_trace)

    trace_data = [
        {"caller_module": cm, "caller_func": cf,
         "callee_module": em, "callee_func": ef,
         "count": v[0], "seq": v[1]}
        for (cm, cf, em, ef), v in edges.items()
    ]
    return CallGraph.from_trace_data(trace_data)


def _detect_run_mode(target: str) -> Tuple[str, str]:
    """
    Returns (run_mode, resolved_target).
    run_mode: "path" for a script file, "module" for a dotted module name.

    Handles:
    - Explicit .py file
    - Any executable file on disk (resolved via resolve_to_python → already a file path)
    - Dotted module names (e.g. "mypackage.cli")
    """
    p = Path(target)
    if p.suffix == ".py" or (p.is_file() and not p.suffix):
        return "path", str(p.resolve())
    # treat as module (pytest, flask, mypackage.cli, etc.)
    return "module", target


def run_trace(
    target: str,
    target_args: List[str],
    *,
    max_depth: Optional[int] = None,
    no_stdlib: bool = False,
    _resolved: Optional[Tuple[str, List[str]]] = None,
) -> CallGraph:
    """
    Inject a trace into *target*, execute it with *target_args*,
    collect the call graph, and return a :class:`CallGraph`.

    If *_resolved* is provided as (python_target, extra_args) — e.g. from
    resolve_to_python() — those extra_args are prepended to target_args and
    python_target is used instead of target.
    """
    if _resolved is not None:
        python_target, extra_args = _resolved
        target_args = extra_args + target_args
        run_mode, resolved_target = _detect_run_mode(python_target)
    else:
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
