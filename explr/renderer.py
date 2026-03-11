"""
Call graph rendering via graphviz.

Layout: a horizontal spine of top-level entry points in execution order
        (S) → (A) → (B) → ... → (E)
with each spine node's sub-calls hanging below it as a subtree.
"""

import importlib.util
import os
import sysconfig
import sys
from pathlib import Path
from typing import List, Optional, Set, Tuple

from .models import CallGraph, CallNode

try:
    import graphviz
except ImportError:
    graphviz = None  # type: ignore


# ── stdlib detection ──────────────────────────────────────────────────────────

def _is_stdlib_module(module: str) -> bool:
    if not module:
        return True
    top = module.split(".")[0]
    if hasattr(sys, "stdlib_module_names"):
        return top in sys.stdlib_module_names  # type: ignore[attr-defined]
    try:
        spec = importlib.util.find_spec(top)
        if spec is None:
            return False
        if spec.origin in ("built-in", "frozen", None):
            return True
        stdlib = sysconfig.get_paths().get("stdlib", "")
        return os.path.normcase(spec.origin).startswith(os.path.normcase(stdlib))
    except Exception:
        return False


# ── display-worthiness ────────────────────────────────────────────────────────

def _is_display_node(node: CallNode) -> bool:
    if node.module in ("<root>",):
        return False
    if node.func.startswith("<"):
        return False
    if node.func.startswith("__") and node.func.endswith("__"):
        return False
    top_module = node.module.split(".")[0]
    if top_module.startswith("_") and node.module != "__main__":
        return False
    if node.func.startswith("_"):
        return False
    if node.module != "__main__" and _is_stdlib_module(node.module):
        return False
    return True


# ── filtering ─────────────────────────────────────────────────────────────────

def _filter_for_display(call_graph: CallGraph) -> CallGraph:
    from .models import CallGraph as CG

    display_keys = {
        key for key, node in call_graph.nodes.items()
        if _is_display_node(node)
    }

    filtered = CG()
    for edge in call_graph.edges.values():
        ck = (edge.caller.module, edge.caller.func)
        ek = (edge.callee.module, edge.callee.func)
        if ck in display_keys and ek in display_keys:
            filtered.add_call(ck[0], ck[1], ek[0], ek[1], edge.count, edge.seq)

    # Ensure spine nodes (display nodes called from non-display callers) exist
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
    short = node.module.split(".")[-1]
    return f"{short}.{node.func}"


# ── spine ordering ────────────────────────────────────────────────────────────

def _ordered_spine(
    original: CallGraph,
    display_keys: Set[Tuple[str, str]],
    has_display_caller: Set[Tuple[str, str]],
) -> List[Tuple[str, str]]:
    """
    Return spine keys sorted by the seq of their first call from a
    non-display caller in the original (unfiltered) graph.
    """
    spine_keys = [k for k in display_keys if k not in has_display_caller]

    def entry_seq(k: Tuple[str, str]) -> int:
        return min(
            (e.seq for e in original.edges.values()
             if (e.callee.module, e.callee.func) == k
             and (e.caller.module, e.caller.func) not in display_keys),
            default=0,
        )

    return sorted(spine_keys, key=entry_seq)


# ── main render ───────────────────────────────────────────────────────────────

def render(
    call_graph: CallGraph,
    output_path: str,
    target_name: str,
    _graphviz_path: Optional[str] = None,
) -> None:
    if graphviz is None:
        raise RuntimeError(
            "graphviz Python package not found. Install it with: pip install graphviz"
        )

    original = call_graph
    cg = _filter_for_display(call_graph)

    if not cg.nodes:
        print(
            "[explr] no user-defined function calls found after filtering – "
            "no diagram created"
        )
        return

    display_keys: Set[Tuple[str, str]] = set(cg.nodes.keys())
    has_display_caller: Set[Tuple[str, str]] = {
        (e.callee.module, e.callee.func) for e in cg.edges.values()
    }

    spine_keys = _ordered_spine(original, display_keys, has_display_caller)

    # Fallback: no clear entry points (e.g. all nodes in a cycle)
    if not spine_keys:
        spine_keys = sorted(
            display_keys,
            key=lambda k: min(
                (e.seq for e in cg.edges.values()
                 if (e.callee.module, e.callee.func) == k),
                default=0,
            ),
        )

    # ── build DOT ─────────────────────────────────────────────────────────────
    dot = graphviz.Digraph(comment=f"explr: {target_name}")
    dot.attr(
        rankdir="TB",
        fontname="Helvetica",
        label=f"explr  ·  {target_name}",
        fontsize="13",
        labelloc="t",
        bgcolor="white",
        nodesep="0.7",
        ranksep="0.8",
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

    # ── START / END terminal nodes ────────────────────────────────────────────
    _term = dict(
        shape="circle",
        style="filled",
        fillcolor="#333333",
        fontcolor="white",
        fontname="Helvetica",
        fontsize="11",
        width="0.35",
        fixedsize="true",
        margin="0",
    )
    dot.node("__START__", "S", **_term)
    dot.node("__END__", "E", **_term)

    # ── Spine row: same rank so they sit on one horizontal line ───────────────
    with dot.subgraph() as s:
        s.attr(rank="same")
        s.node("__START__")
        for k in spine_keys:
            node = cg.nodes[k]
            s.node(
                node.node_id(),
                _node_label(node),
                fillcolor="#D4EDDA",
                color="#3A7D44",
                fontsize="12",
            )
        s.node("__END__")

    # Invisible weighted edges enforce left-to-right ordering within the rank
    prev = "__START__"
    for k in spine_keys:
        nid = cg.nodes[k].node_id()
        dot.edge(prev, nid, style="invis", weight="10")
        prev = nid
    dot.edge(prev, "__END__", style="invis", weight="10")

    # Visible spine arrows — constraint=false keeps them from affecting layout
    prev = "__START__"
    for k in spine_keys:
        nid = cg.nodes[k].node_id()
        dot.edge(prev, nid, constraint="false", color="#333333",
                 arrowsize="0.9", penwidth="1.8")
        prev = nid
    dot.edge(prev, "__END__", constraint="false", color="#333333",
             arrowsize="0.9", penwidth="1.8")

    # ── Non-spine display nodes ───────────────────────────────────────────────
    spine_set = set(spine_keys)
    for key, node in cg.nodes.items():
        if key not in spine_set:
            dot.node(node.node_id(), _node_label(node))

    # ── Sub-call edges (flow downward from spine into subtrees) ───────────────
    for edge in cg.edges.values():
        label = str(edge.count) if edge.count > 1 else ""
        dot.edge(edge.caller.node_id(), edge.callee.node_id(), label=label)

    # ── Render to PNG ─────────────────────────────────────────────────────────
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
