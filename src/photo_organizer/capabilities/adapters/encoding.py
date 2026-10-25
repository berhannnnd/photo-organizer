"""Explicit vector-space contract for image/text, local or remote."""

import hashlib
import json

from photo_organizer.capabilities.adapters.http import request
from photo_organizer.core.errors import CapabilityError


class Encoder:
    def __init__(self, config):
        if config["protocol"] == "host":
            raise CapabilityError(
                "host_action_required", "Submit host vectors and use vector-search"
            )
        self.config = config
        self.model = config["model"]
        self.endpoint = config["endpoint"]
        if config["protocol"] == "ollama":
            rows = request(config, None, "/api/tags").get("models", [])
            installed = next(
                (r for r in rows if r.get("name") == self.model or r.get("model") == self.model),
                None,
            )
            if not installed or not installed.get("digest"):
                raise CapabilityError(
                    "model_missing",
                    "Configured Ollama artifact is not installed; no automatic download",
                )
            self.digest = installed["digest"]
        else:
            self.digest = config["revision"]
        self.space = hashlib.sha256(
            json.dumps(
                [
                    self.endpoint,
                    self.model,
                    self.digest,
                    config.get("space"),
                    config["protocol"],
                    "pillow-orient-rgb-1280-q82-v1",
                ]
            ).encode()
        ).hexdigest()

    def encode(self, value):
        from photo_organizer.search.embeddings import pack

        protocol = self.config["protocol"]
        if protocol == "openai-text" and not isinstance(value, str):
            raise CapabilityError("unsupported_input", "Text embedding cannot encode images")
        if protocol == "ollama":
            rows = request(self.config, None, "/api/tags").get("models", [])
            if not any(
                r.get("digest") == self.digest
                and (r.get("name") == self.model or r.get("model") == self.model)
                for r in rows
            ):
                raise CapabilityError("version_conflict", "Installed model changed")
            response = request(
                self.config, {"model": self.model, "input": value, "truncate": False}, "/api/embed"
            )
            vectors = response.get("embeddings")
        elif protocol == "openai-text":
            response = request(self.config, {"model": self.model, "input": value})
            vectors = [r["embedding"] for r in response.get("data", [])]
        else:
            response = request(
                self.config, {"operation": "embed", "model": self.model, "input": value}
            )
            if response.get("space") != self.config["space"]:
                raise CapabilityError(
                    "version_conflict", "Returned embedding space differs from configured space"
                )
            vectors = response.get("embeddings")
        if not isinstance(vectors, list) or len(vectors) != 1:
            raise CapabilityError("invalid_response", "Expected one embedding vector")
        return pack(vectors[0])
