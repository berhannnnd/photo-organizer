"""JSON Schema contracts shared by CLI, MCP and validation."""

import copy

STRING = {"type": "string", "minLength": 1}
NUMBER = {"type": "number"}
INTEGER = {"type": "integer"}
BOOL = {"type": "boolean"}


def array(item, maximum=1000, minimum=0):
    return {"type": "array", "items": item, "minItems": minimum, "maxItems": maximum}


def obj(properties, required=(), extra=False):
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": extra,
    }


SOURCE = obj(
    {
        "kind": {"enum": ["host", "provider", "user"], "type": "string"},
        "model": STRING,
        "version": STRING,
    },
    ["kind"],
)
CONFIG = obj(
    {
        k: v
        for k, v in {
            "protocol": STRING,
            "endpoint": STRING,
            "model": STRING,
            "revision": STRING,
            "space": STRING,
            "api_key_env": STRING,
            "timeout": {"type": "number", "minimum": 1, "maximum": 300},
            "concurrency": {"type": "integer", "minimum": 1, "maximum": 8},
            "language": STRING,
            "detector_path": STRING,
            "recognizer_path": STRING,
        }.items()
    },
    ["protocol"],
)
RULE = obj(
    {
        "formats": array(STRING, 20, 1),
        **{
            name: {"type": "integer", "minimum": 0}
            for name in (
                "min_width",
                "max_width",
                "min_height",
                "max_height",
                "min_bytes",
                "max_bytes",
            )
        },
        "and": array({"$ref": "#/$defs/rule"}, 50, 1),
        "or": array({"$ref": "#/$defs/rule"}, 50, 1),
        "not": {"$ref": "#/$defs/rule"},
        "date_from": STRING,
        "date_to": STRING,
        "date_basis": {"type": "string", "enum": ["capture", "import", "modified"]},
        "roots": array(STRING, 100, 1),
        "path_prefix": STRING,
        "person_ids": array(STRING, 100, 1),
        "location_box": {**array(NUMBER, 4, 4)},
        "orientation": {"type": "string", "enum": ["landscape", "portrait", "square"]},
        "all_tags": array(STRING, 100),
        "any_tags": array(STRING, 100),
        "not_tags": array(STRING, 100),
        "caption_text": STRING,
        "category": STRING,
        "semantic": {"type": "string", "minLength": 1, "maxLength": 2000},
    }
)
GROUP = obj({"path": array(STRING, 8, 1), "ids": array(INTEGER, 100000)}, ["path", "ids"])
RULE_GROUP = obj({"name": STRING, "where": {"$ref": "#/$defs/rule"}}, ["name", "where"])
LEVEL = obj(
    {
        "field": {"type": "string", "enum": ["year", "month", "category", "orientation", "none"]},
        "rules": array(RULE_GROUP, 200),
        "overlap": {"type": "string", "enum": ["error", "first", "multi"]},
    }
)
PLAN = obj(
    {
        "filter": {"$ref": "#/$defs/rule"},
        "result_set_id": STRING,
        "group_spec_id": STRING,
        "accept_candidates": BOOL,
        "group_by": STRING,
        "groups": array(RULE_GROUP, 200),
        "levels": array(LEVEL, 8, 1),
        "overlap": {"type": "string", "enum": ["error", "first", "multi"]},
        "name_template": STRING,
        "date_basis": {"type": "string", "enum": ["capture", "import", "modified"]},
        "quality": {"type": "integer", "minimum": 1, "maximum": 95},
        "long_edge": {"type": "integer", "minimum": 64, "maximum": 8192},
        "max_bytes": {"type": "integer", "minimum": 1024},
    }
)
BUDGET = obj(
    {
        k: {
            "type": "integer" if k in ("max_images", "max_requests") else "number",
            "exclusiveMinimum": 0,
        }
        for k in ("max_images", "max_requests", "max_seconds", "max_cost", "max_request_cost")
    }
)
RECORD = {"file_id": INTEGER, "hash": STRING}
RECORDS = {
    "vector-submit": obj({**RECORD, "vector": array(NUMBER, 100000, 1)}, [*RECORD, "vector"]),
    "face-submit": obj(
        {**RECORD, "box": array(NUMBER, 4, 4), "vector": array(NUMBER, 100000, 1)},
        [*RECORD, "box", "vector"],
    ),
    "analysis-submit": obj(
        {
            **RECORD,
            "text": {"type": "string", "maxLength": 100000},
            "regions": array({"type": "object"}),
            "coordinate_system": STRING,
        },
        [*RECORD, "text"],
    ),
    "evidence-submit": obj(
        {
            **RECORD,
            "verdict": {"type": "string", "enum": ["yes", "no", "uncertain"]},
            "evidence": STRING,
            "observation": obj(
                {"caption": STRING, "category": STRING, "tags": array(STRING, 100)},
                ["caption", "category", "tags"],
            ),
        },
        list(RECORD),
    ),
    "metadata-correct": obj(
        {
            **RECORD,
            "changes": obj(
                {
                    k: {"anyOf": [v, {"type": "null"}]}
                    for k, v in {
                        "taken": STRING,
                        "category": STRING,
                        "caption": STRING,
                        "notes": STRING,
                        "latitude": NUMBER,
                        "longitude": NUMBER,
                        "tags": array(STRING, 100),
                    }.items()
                }
            ),
        },
        [*RECORD, "changes"],
    ),
}
ENUMS = {
    "role": ["vision", "image_text", "description_text", "ocr", "faces"],
    "overlap": ["error", "first", "multi"],
    "identity": ["file", "content"],
    "ranking": ["image", "hybrid"],
    "field": ["ocr", "caption"],
    "metric": ["edge_variance", "mean_luminance", "dark_fraction", "bright_fraction"],
    "method": ["theme", "event", "person", "duplicates", "similar"],
}
STRINGS = set(
    "operation role task_id result_id result_set_id parent_id group_spec_id collection_id plan_id recipe_id preference person_id target verdict version overlap space_id text query model revision space endpoint condition expected_version reason name group root name_template metric method identity field ranking mode action protocol".split()
)
INTS = {
    "file_id",
    "reference_id",
    "limit",
    "offset",
    "top_k",
    "long_edge",
    "workers",
    "interval",
    "retention_days",
}
BOOLS = {
    "background",
    "verify",
    "rebind",
    "descending",
    "apply",
    "enabled",
    "allow_text_fallback",
    "finalize",
    "reindex",
}


def argument_schema(operation, parameter):
    name = parameter["name"]
    if name == "expected_version" and operation == "recipe-save":
        return {
            "type": ["integer", "null"],
            "minimum": 1,
            "default": None,
            "description": "Prior recipe version required for updates",
        }
    if name == "rule":
        schema = {"$ref": "#/$defs/rule"}
    elif name == "spec":
        schema = PLAN
    elif name == "config":
        schema = STRING if operation == "review" else CONFIG
    elif name == "source":
        schema = {"type": "string", "enum": ["agent", "user"]} if operation == "select" else SOURCE
    elif name == "records":
        schema = array(RECORDS[operation], 100, 0 if operation == "vector-submit" else 1)
    elif name == "budget":
        schema = BUDGET
    elif name == "arguments":
        schema = obj(
            {
                "result_id": STRING,
                "condition": STRING,
                "root": STRING,
                "verify": BOOL,
                "plan_id": STRING,
            }
        )
    elif name == "groups":
        schema = array(GROUP, 200, 1)
    elif name in (
        "ids",
        "face_ids",
        "merge_ids",
        "result_ids",
        "verdicts",
        "required",
        "action_ids",
    ):
        schema = array(INTEGER if name == "ids" else STRING, 100000)
    elif name in ("crop", "query_vector"):
        schema = array(NUMBER, 4 if name == "crop" else 100000, 4 if name == "crop" else 1)
    elif name in INTS:
        schema = {"type": "integer", "minimum": 0 if name == "offset" else 1}
    elif name in BOOLS:
        schema = BOOL
    elif name in ("threshold", "gap_hours"):
        schema = NUMBER
    elif name == "kind":
        schema = {
            "type": "string",
            "enum": ["ocr"] if operation == "analysis-submit" else ["quality", "ocr"],
        }
    elif name == "expected_text":
        schema = {"type": "string"}
    elif name in STRINGS:
        schema = {"type": "string"} if name == "reason" else STRING
    else:
        raise ValueError("missing schema for " + operation + "." + name)
    schema = copy.deepcopy(schema)
    enums = ENUMS.get(name)
    if name == "mode":
        enums = (
            ["keep", "exclude", "order"] if operation == "select" else ["album", "copy", "compress"]
        )
    if name == "operation" and operation in ("combine", "job-start"):
        enums = (
            ["union", "intersection", "difference"]
            if operation == "combine"
            else ["index", "review", "embed", "ocr", "quality", "faces", "scan", "apply"]
        )
    if name == "action":
        enums = {
            "people": ["list", "faces", "rename", "merge", "assign", "split"],
            "watch": ["start", "stop", "status"],
            "job-control": ["pause", "cancel", "resume", "retry"],
        }.get(operation)
    if enums:
        schema["enum"] = enums
    if parameter.get("default", False) is None:
        schema = {"anyOf": [schema, {"type": "null"}], "default": None}
    elif "default" in parameter:
        schema["default"] = parameter["default"]
    schema["description"] = name.replace("_", " ") + (
        "; immutable engine identifier" if name.endswith("_id") else ""
    )
    return schema
