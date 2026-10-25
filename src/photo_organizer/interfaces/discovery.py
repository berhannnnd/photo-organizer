"""Transport-independent operation discovery."""

import inspect

from photo_organizer.interfaces.operations import OPERATIONS
from photo_organizer.library.lifecycle import synchronize
from photo_organizer.organizing.execution import apply
from photo_organizer.organizing.planning import plan
from photo_organizer.search import embeddings, results, retrieval


def operation_schema(state, operation):
    """Describe accepted arguments without performing the operation."""
    functions = {
        **OPERATIONS,
        "scan": synchronize,
        "search": results.create,
        "results": results.page,
        "plan": plan,
        "apply": apply,
        "embed-index": embeddings.index,
        "describe-index": embeddings.index_descriptions,
        "retrieve": retrieval.search,
    }
    if operation in ("capabilities", "status"):
        parameters = []
        description = "Read current engine capabilities or catalog status."
    elif operation == "review":
        parameters = [
            {"name": "result_set_id", "required": True},
            {"name": "condition", "required": True},
            {"name": "config", "required": False, "default": None},
        ]
        description = "Review a visual criterion within a frozen result set."
    else:
        function = functions.get(operation)
        if function is None:
            raise ValueError("unknown operation")
        description = function.__doc__
        parameters = [
            {
                "name": p.name,
                "required": p.default is inspect.Parameter.empty,
                **({} if p.default is inspect.Parameter.empty else {"default": p.default}),
            }
            for p in inspect.signature(function).parameters.values()
            if p.name != "state"
        ]
    return {"operation": operation, "description": description, "arguments": parameters}
