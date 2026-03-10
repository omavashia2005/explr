"""
Call graph rendering via graphviz.

Renders a clean top-to-bottom flow diagram showing only user-defined
function calls.  Stdlib, dunder methods, and synthetic names (<module>,
<listcomp>, etc.) are filtered out before rendering.
"""

import importlib.util
import os
import sysconfig
import sys
from pathlib import Path
from typing import Optional

from .models import CallGraph, CallNode

try:
    import graphviz
except ImportError:
    graphviz = None  # type: ignore

# ── stdlib detection ──────────────────────────────────────────────────────────

def _stdlib_prefix() -> str:
    return os.path.normcase(sysconfig.get_paths()["stdlib"])


def _is_stdlib_module(module: str) -> bool:
    """True if *module* is part of the standard library or a built-in."""
    if not module:
        return True
    top = module.split(".")[0]
    # Fast path: Python 3.10+
    if hasattr(sys, "stdlib_module_names"):
        return top in sys.stdlib_module_names  # type: ignore[attr-defined]
    # Fallback: check via importlib
    try:
        spec = importlib.util.find_spec(top)
        if spec is None:
            return False
        if spec.origin in ("built-in", "frozen", None):
            return True
        return os.path.normcase(spec.origin).startswith(_stdlib_prefix())
    except Exception:
        return False


# ── display-worthiness ────────────────────────────────────────────────────────

def _is_display_node(node: CallNode) -> bool:
    """Return True if this node should appear in the simplified flow diagram."""
    if node.module in ("<root>",):
        return False
    if node.func.startswith("<"):          # catches all <...> synthetics
        return False
    if node.func.startswith("__") and node.func.endswith("__"):
        return False                       # skip dunder methods
    if node.func.startswith("_"):
        return False                       # skip private functions
    top_module = node.module.split(".")[0]
    if top_module.startswith("_") and node.module != "__main__":
        return False                       # skip private/internal modules
    # __main__ is always user code even though it appears in stdlib_module_names
    if node.module != "__main__" and _is_stdlib_module(node.module):
        return False
    return True


# ── filtering ─────────────────────────────────────────────────────────────────

def _filter_for_display(call_graph: CallGraph) -> CallGraph:
    """
    Return a new CallGraph containing only display-worthy nodes/edges.

    Rules:
    - Include an edge only when both endpoints pass _is_display_node.
    - Include a node as an "entry point" when it is a display node called
      *from* a non-display node (e.g. called at module level).
    """
    from .models import CallGraph as CG

    display_keys = {
        key for key, node in call_graph.nodes.items()
        if _is_display_node(node)
    }

    filtered = CG()
    # Add edges that connect two display nodes
    for edge in call_graph.edges.values():
        ck = (edge.caller.module, edge.caller.func)
        ek = (edge.callee.module, edge.callee.func)
        if ck in display_keys and ek in display_keys:
            filtered.add_call(ck[0], ck[1], ek[0], ek[1], edge.count)

    # Ensure entry-point nodes (display nodes called from noise) exist
    for edge in call_graph.edges.values():
        ck = (edge.caller.module, edge.caller.func)
        ek = (edge.callee.module, edge.callee.func)
        if ck not in display_keys and ek in display_keys:
            if ek not in filtered.nodes:
                filtered.nodes[ek] = CallNode(ek[0], ek[1])

    return filtered


# ── label helpers ─────────────────────────────────────────────────────────────

def _node_label(node: CallNode) -> str:
    if node.module in ("__main__", "", None):
        return node.func
    # Show last segment of module for brevity
    short = node.module.split(".")[-1]
    return f"{short}.{node.func}"


# ── main render ───────────────────────────────────────────────────────────────

def render(
    call_graph: CallGraph,
    output_path: str,
    target_name: str,
    _graphviz_path: Optional[str] = None,
) -> None:
    """
    Render a simplified flow diagram of *call_graph* to *output_path* (.png).

    Only user-defined, non-stdlib, non-dunder functions are shown.
    If nothing remains after filtering, exits with a message and no file.
    """
    if graphviz is None:
        raise RuntimeError(
            "graphviz Python package not found. Install it with: pip install graphviz"
        )

    cg = _filter_for_display(call_graph)

    if not cg.nodes:
        print(
            "[explr] no user-defined function calls found after filtering – "
            "no diagram created"
        )
        return

    dot = graphviz.Digraph(comment=f"explr: {target_name}")
    dot.attr(
        rankdir="TB",
        fontname="Helvetica",
        label=f"explr  ·  {target_name}",
        fontsize="13",
        labelloc="t",
        bgcolor="white",
        splines="polyline",
    )
    dot.attr(
        "node",
        shape="box",
        style="rounded,filled",
        fillcolor="#EEF4FB",
        color="#5B8DB8",
        fontname="Helvetica",
        fontsize="11",
        margin="0.2,0.1",
    )
    dot.attr("edge", color="#888888", fontname="Helvetica", fontsize="9", arrowsize="0.7")

    # Identify entry-point nodes (no display-node callers)
    has_display_caller = {
        (e.callee.module, e.callee.func)
        for e in cg.edges.values()
    }
    entry_keys = {k for k in cg.nodes if k not in has_display_caller}

    for key, node in cg.nodes.items():
        nid = node.node_id()
        label = _node_label(node)
        if key in entry_keys:
            dot.node(nid, label, fillcolor="#D4EDDA", color="#3A7D44", fontsize="12")
        else:
            dot.node(nid, label)

    for edge in cg.edges.values():
        label = str(edge.count) if edge.count > 1 else ""
        dot.edge(edge.caller.node_id(), edge.callee.node_id(), label=label)

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    base = str(out.with_suffix(""))

    if _graphviz_path:
        old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = _graphviz_path + os.pathsep + old_path
    else:
        old_path = None

    try:
        dot.render(filename=base, format="png", cleanup=True)
    except graphviz.ExecutableNotFound:
        raise RuntimeError(
            "Graphviz 'dot' binary not found in PATH.\n"
            "Install Graphviz: https://graphviz.org/download/\n"
            "On macOS with Homebrew: brew install graphviz"
        )
    finally:
        if old_path is not None:
            os.environ["PATH"] = old_path

    print(f"[explr] diagram written to {out}")
