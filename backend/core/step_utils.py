from __future__ import annotations

from collections import OrderedDict
from typing import Any, Dict, Iterable, List, Tuple
from uuid import uuid4

def group_steps(steps: Iterable[Dict[str, Any]]) -> List[Tuple[str, List[Dict[str, Any]]]]:
    groups: "OrderedDict[str, List[Dict[str, Any]]]" = OrderedDict()
    for step in steps:
        group_key = step.get("parallel_group") or step.get("id") or str(uuid4())
        groups.setdefault(group_key, []).append(step)
    return list(groups.items())

