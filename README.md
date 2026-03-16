# explr

Trace any Python process and generate a clean call graph diagram.

Best suited for debugging small-to-medium synchronous Python programs (for now).

```mermaid
---
title: test_files/branching.py
---
flowchart LR
	__start__(("S"))
	__end__(("E"))
	__main____run["run"]
	__main____process["process"]
	__main____validate["validate"]
	__main____handle_even["handle_even"]
	__main____handle_odd["handle_odd"]
	__start__ --> __main____run
	__main____run --> __end__
	__main____run --> __main____process
	__main____process --> __main____validate
	__main____process --> __main____handle_even
	__main____process --> __main____handle_odd
```


[Example PNG Diagram](https://github.com/omavashia2005/explr/blob/main/explr_diagrams/t6_cross_module_diagram.png)

[Example Mermaid Diagram](https://github.com/omavashia2005/explr/blob/main/explr_diagrams/mermaid/main_diagram.mmd)


## How it works

`explr` injects Python's `sys.settrace` at runtime, records every function call, filters out noise (stdlib, dunders, private functions), and renders a flow diagram showing how control moves through your code.

Only your own code is traced — stdlib and third-party packages are always excluded.

The diagram has a **horizontal spine** of entry points in execution order, with each node's sub-calls hanging below it:

```
(S) → run → (E)
       ├── auth.register → db.save_user
       │                 → db.get_user
       ├── auth.login    → db.get_user
       └── report        → db.all_users
```

- **S / E** = start and end of execution
- **Green nodes** = entry points (called from top-level code), in the order they ran
- **Blue nodes** = sub-calls


## Installation

### Prerequisites

The `--graph` PNG output requires **Graphviz**. Install it for your OS:

| OS | Command |
|---|---|
| macOS (Homebrew) | `brew install graphviz` |
| Ubuntu / Debian | `sudo apt install graphviz` |
| Fedora / RHEL | `sudo dnf install graphviz` |
| Windows | [Download installer](https://graphviz.org/download/) — make sure `dot` is added to PATH |

> Default Mermaid output does not require Graphviz.

### Install explr

```bash
pip install explr
```


## CLI usage

```
explr [options] <target> [target-args ...]
```

### Examples

```bash
# Default: Mermaid output, local-only tracing
explr myscript.py

# Trace with the python prefix (same result)
explr python myscript.py
explr python3 myscript.py

# Pass arguments through to your script
explr myscript.py --config dev

# Trace a module-style tool (e.g. pytest, flask)
explr pytest tests/
explr python -m mypackage

# Trace any shell command that resolves to Python
# (PATH scripts, shell aliases, shell functions)
explr my_tool --some-arg

# PNG output instead of Mermaid (requires Graphviz)
explr --graph myscript.py

# Exclude noisy modules or functions from the diagram
explr --exclude-module requests myscript.py
explr --exclude-module requests --exclude-module pandas myscript.py
explr --exclude-func connect --exclude-func close myscript.py
```

### Resolving shell commands

`explr` automatically resolves commands that aren't directly a Python file or interpreter.
It walks the following chain until it finds a Python target:

1. **PATH scripts** — executable files with a `#!/usr/bin/env python3` shebang
2. **Shell aliases** — e.g. `alias my_tool='python3 /path/to/tool.py'`
3. **Shell functions** — defined in your `.bashrc` / `.zshrc`
4. **Wrapper scripts** — shell scripts that `exec python3 ...` internally

```bash
# If 'mtgs_viewer' is a shell alias for 'python3 viewer.py --theme dark':
explr mtgs_viewer

# explr prints what it resolved to:
# [explr] resolved 'mtgs_viewer' → viewer.py (extra args: ['--theme', 'dark'])
```

### Options

| Flag | Description |
|---|---|
| `--graph` | Output a PNG diagram (graphviz) instead of Mermaid |
| `--depth N` | Limit call depth (default: unlimited) |
| `--output NAME` | Override output filename (no extension needed) |
| `--exclude-module NAME` | Exclude all nodes from a module (repeatable) |
| `--exclude-func NAME` | Exclude all nodes with a function name (repeatable) |

```bash
explr --depth 5 myscript.py
explr --output my_graph myscript.py
explr --exclude-module requests --exclude-module boto3 myscript.py
```

### Output formats

**Default — Mermaid** (no dependencies):
```
explr_diagrams/
  myscript_diagram.mmd
```

**PNG** (`--graph`, requires Graphviz):
```
explr_diagrams/
  myscript_diagram.png
```

The `.mmd` file contains a standard [Mermaid](https://mermaid.js.org) flowchart that renders in:
- VS Code (Markdown preview / Mermaid extension)
- GitHub Markdown (fenced ` ```mermaid ` blocks)
- [mermaid.live](https://mermaid.live) — paste and view instantly


## Python API

Trace a specific function from within your own code using `explr.trace()`. Works with both **sync and async** functions.

```python
import explr

# Sync function
explr.trace(my_function, args=(1, 2))

# Async function — explr handles the event loop automatically
explr.trace(my_async_function, kwargs={"url": "...", "headers": {}})

# With keyword args
explr.trace(my_function, args=(x,), kwargs={"flag": True})

# All options
explr.trace(
    my_function,
    args=(x,),
    output="my_graph",                  # custom output filename (no extension)
    depth=5,                            # limit call depth
    graph=True,                         # output .png instead of .mmd
    exclude_modules=("requests",),      # exclude noisy modules
    exclude_funcs=("connect", "close"), # exclude specific functions
)

# Returns the path to the generated file (or None if nothing was captured)
path = explr.trace(my_function, args=(x,))
```

Diagrams are written to `./explr_diagrams/<func_name>_diagram.mmd` (or `.png` with `graph=True`).

`explr.trace()` runs entirely in-process using `sys.settrace` — no subprocess or temp files. Any existing trace hook is saved and restored around the call.

### Async functions

For async functions, `explr.trace()` automatically runs the coroutine via `asyncio.run()`. Mock out any network/IO calls so the function executes without side effects:

```python
import explr

# Mock the network call
async def fetch(url, headers):
    return b"mock response"

async def my_pipeline(url: str, headers: dict):
    raw = await fetch(url=url, headers=headers)
    result = process(raw)
    return result

explr.trace(
    my_pipeline,
    kwargs={"url": "https://example.com", "headers": {}},
    output="my_pipeline",
)
```

> **Jupyter / running event loop:** `asyncio.run()` cannot be called from inside an already-running loop. Install `nest_asyncio` to work around this:
> ```bash
> pip install nest_asyncio
> ```
> ```python
> import nest_asyncio
> nest_asyncio.apply()
> explr.trace(my_async_function, kwargs={...})
> ```

---

## What gets shown

| Included | Excluded |
|---|---|
| User-defined functions | stdlib functions |
| Cross-module calls | Dunder methods (`__init__`, etc.) |
| Recursive calls (self-loops) | Private functions/modules (leading `_`) |
| Class methods | Synthetic names (`<listcomp>`, `<lambda>`, etc.) |
| | Third-party packages (site-packages) |

If a function has no user-defined sub-calls, it still appears on the spine as `S → fn → E`.

---

## Test files

The `test_files/` directory contains examples covering common patterns:

```bash
explr test_files/simple.py             # linear call chain
explr test_files/recursive.py          # recursive functions
explr test_files/classes.py            # class methods
explr test_files/branching.py          # conditional branches
explr test_files/multi_module/main.py  # calls across multiple files
explr test_files/no_calls.py           # no sub-calls (spine only)
```

---

## Project structure

```
explr/
  __init__.py   # explr.trace() Python API
  cli.py        # entry point, argument parsing, command resolution
  tracer.py     # sys.settrace bootstrap (CLI), in-process tracer (API), shell resolution
  renderer.py   # graphviz PNG and Mermaid diagram rendering
  models.py     # CallNode / CallEdge / CallGraph dataclasses
test_files/     # example scripts for testing
pyproject.toml
```
