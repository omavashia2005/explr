from dataclasses import dataclass, field
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class CallNode:
    module: str
    func: str

    def label(self) -> str:
        if self.module in ("<root>", "__main__", ""):
            return self.func
        return f"{self.module}.{self.func}"

    def node_id(self) -> str:
        import re
        raw = f"{self.module}__{self.func}"
        return re.sub(r"[^A-Za-z0-9_]", "_", raw)


@dataclass
class CallEdge:
    caller: CallNode
    callee: CallNode
    count: int = 1
    seq: int = 0   # sequence number of first occurrence


@dataclass
class CallGraph:
    nodes: Dict[Tuple[str, str], CallNode] = field(default_factory=dict)
    edges: Dict[Tuple, CallEdge] = field(default_factory=dict)

    def add_call(self, caller_module: str, caller_func: str,
                 callee_module: str, callee_func: str,
                 count: int = 1, seq: int = 0) -> None:
        caller_key = (caller_module, caller_func)
        callee_key = (callee_module, callee_func)
        if caller_key not in self.nodes:
            self.nodes[caller_key] = CallNode(caller_module, caller_func)
        if callee_key not in self.nodes:
            self.nodes[callee_key] = CallNode(callee_module, callee_func)
        edge_key = (caller_key, callee_key)
        if edge_key in self.edges:
            self.edges[edge_key].count += count
        else:
            self.edges[edge_key] = CallEdge(
                self.nodes[caller_key],
                self.nodes[callee_key],
                count,
                seq,
            )

    @classmethod
    def from_trace_data(cls, trace_data: List[dict]) -> "CallGraph":
        graph = cls()
        for entry in trace_data:
            graph.add_call(
                entry["caller_module"],
                entry["caller_func"],
                entry["callee_module"],
                entry["callee_func"],
                entry.get("count", 1),
                entry.get("seq", 0),
            )
        return graph
