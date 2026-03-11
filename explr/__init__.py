import os
import sys
from typing import Callable, Optional

from .tracer import trace_func
from .renderer import render


def trace(
    func: Callable,
    args: tuple = (),
    kwargs: Optional[dict] = None,
    *,
    output: Optional[str] = None,
    depth: Optional[int] = None,
    no_stdlib: bool = False,
) -> Optional[str]:
    """
    Trace *func* and write a call graph diagram to ./explr_diagrams/.

    Usage::

        import explr

        explr.trace(my_function, args=(1, 2))
        explr.trace(my_function, args=(x,), kwargs={"flag": True}, output="my_graph")

    Args:
        func:       The callable to trace.
        args:       Positional arguments to pass to func.
        kwargs:     Keyword arguments to pass to func.
        output:     Output filename stem (no extension). Defaults to func.__name__.
        depth:      Limit call depth captured (default: unlimited).
        no_stdlib:  Exclude stdlib calls from the diagram.

    Returns:
        Path to the generated PNG, or None if no calls were captured.
    """
    call_graph = trace_func(func, args=args, kwargs=kwargs,
                            max_depth=depth, no_stdlib=no_stdlib)

    node_count = len(call_graph.nodes)
    edge_count = len(call_graph.edges)
    print(f"[explr] captured {node_count} nodes, {edge_count} edges")

    if node_count == 0:
        print("[explr] nothing to render – no calls were captured")
        return None

    out_dir = os.path.join(os.getcwd(), "explr_diagrams")
    os.makedirs(out_dir, exist_ok=True)

    name = output or func.__name__
    out_path = os.path.join(out_dir, f"{name}_diagram.png")

    _gv_extra = "/opt/homebrew/bin" if sys.platform == "darwin" else None
    render(call_graph, out_path, target_name=func.__name__, _graphviz_path=_gv_extra)

    return out_path
