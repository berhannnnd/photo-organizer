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
    if operation == "operation-schema":
        parameters = [{"name": "operation", "required": True}]
        description = "Return JSON Schema and argument discovery for a named operation."
    elif operation in ("capabilities", "status"):
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
    from photo_organizer.interfaces.schemas import RULE, argument_schema, obj

    properties = {p["name"]: argument_schema(operation, p) for p in parameters}
    if operation == "group-propose":
        properties["parent_id"]["description"] = (
            "Optional predecessor group_spec_id when editing a grouping proposal; never a result ID."
        )
        properties["result_id"]["description"] = (
            "Exact current selection result_set_id; after select/refinement, use its NEW result ID."
        )
    schema = obj(properties, [p["name"] for p in parameters if p["required"]])
    schema.update(
        {"$schema": "https://json-schema.org/draft/2020-12/schema", "$defs": {"rule": RULE}}
    )
    return {
        "operation": operation,
        "description": description,
        "arguments": parameters,
        "input_schema": schema,
    }
