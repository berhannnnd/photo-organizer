"""Shared host-neutral tool boundary. No transport owns business logic."""

import platform

from photo_organizer.core.errors import CapabilityError
from photo_organizer.interfaces.operations import OPERATIONS as EXTENSIONS
from photo_organizer.library.lifecycle import synchronize as scan
from photo_organizer.organizing.execution import apply
from photo_organizer.organizing.planning import plan
from photo_organizer.search.results import create, page
from photo_organizer.storage.catalog import connect, report

API_VERSION = "2"
OPERATIONS = (
    "operation-schema",
    "capabilities",
    "status",
    "scan",
    "search",
    "results",
    "plan",
    "apply",
    "embed-index",
    "describe-index",
    "retrieve",
    "review",
)


def dispatch(state, operation, arguments):
    if not isinstance(arguments, dict):
        return failure("invalid_request", "arguments must be an object")
    try:
        if operation not in (*OPERATIONS, *EXTENSIONS):
            return failure("unsupported_operation", "unknown operation")
        from jsonschema import Draft202012Validator

        from photo_organizer.interfaces.discovery import operation_schema

        schema = operation_schema(state, operation)["input_schema"]
        error = next(Draft202012Validator(schema).iter_errors(arguments), None)
        if error:
            location = ".".join(str(x) for x in error.absolute_path) or "arguments"
            return failure(
                "invalid_request", location + " does not satisfy " + str(error.validator)
            )
        if operation == "capabilities":
            if arguments:
                raise ValueError("capabilities takes no arguments")
            data = {
                "api_version": API_VERSION,
                "platform": platform.system(),
                "operations": list(OPERATIONS) + list(EXTENSIONS),
                "outputs": ["album", "copy", "compress"],
                "query": [
                    "metadata",
                    "indexed_facts",
                    "and",
                    "or",
                    "not",
                    "saved_semantic_judgments",
                    "image_text_candidates",
                ],
                "result_snapshots": True,
                "models_required_for_metadata": False,
                "vision_protocols": ["anthropic", "openai", "ollama", "host"],
                "limitations": [
                    "POSIX only; Windows unsupported",
                    "legacy direct calls are synchronous; use job-start for durable execution",
                    "independent human quality and cross-host release acceptance pending",
                ],
            }
        elif operation == "operation-schema":
            from photo_organizer.interfaces.discovery import operation_schema

            data = operation_schema(state, **arguments)
        elif operation in EXTENSIONS:
            data = EXTENSIONS[operation](state, **arguments)
        elif operation == "status":
            if arguments:
                raise ValueError("status takes no arguments")
            with connect(state) as c:
                data = report(c)
        elif operation in ("embed-index", "describe-index", "retrieve"):
            from photo_organizer.search import embeddings, retrieval

            data = {
                "embed-index": embeddings.index,
                "describe-index": embeddings.index_descriptions,
                "retrieve": retrieval.search,
            }[operation](state, **arguments)
        elif operation == "review":
            from photo_organizer.vision.provider import Provider
            from photo_organizer.vision.semantic import enrich

            if set(arguments) - {"result_set_id", "condition", "config"} or not {
                "result_set_id",
                "condition",
            } <= set(arguments):
                raise ValueError("review requires result_set_id and condition")
            if arguments.get("config"):
                provider = Provider.from_config(arguments["config"])
            else:
                from photo_organizer.capabilities.registry import vision

                provider = vision(state)
            data = enrich(
                state,
                provider,
                arguments["condition"],
                workers=2,
                result_set_id=arguments["result_set_id"],
            )
        elif operation == "scan":
            data = scan(state, **arguments)
        elif operation == "search":
            data = create(state, **arguments)
        elif operation == "results":
            data = page(state, **arguments)
        elif operation == "plan":
            data = plan(state, **arguments)
        elif operation == "apply":
            data = apply(state, **arguments)
        else:
            return failure("unsupported_operation", "unknown operation")
        status = (
            "partial_failed"
            if data.get("errors") or data.get("file_errors") or data.get("failed_now")
            else "completed"
        )
        return {"api_version": API_VERSION, "status": status, "data": data, "error": None}
    except CapabilityError as error:
        return {
            "api_version": API_VERSION,
            "status": "failed",
            "data": None,
            "error": {"code": error.code, "message": str(error), "retryable": error.retryable},
        }
    except PermissionError:
        return failure("permission_denied", "filesystem permission denied")
    except FileNotFoundError:
        return failure("not_found", "requested file or directory is unavailable")
    except (ValueError, TypeError) as error:
        return failure("invalid_request", str(error))
    except OSError:
        return failure(
            "io_error", "filesystem operation failed; inspect source availability and permissions"
        )


def failure(code, message):
    return {
        "api_version": API_VERSION,
        "status": "failed",
        "data": None,
        "error": {"code": code, "message": message, "retryable": False},
    }
