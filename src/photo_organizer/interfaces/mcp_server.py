"""Optional local stdio transport using the official MCP SDK."""

import argparse

from photo_organizer.interfaces.service import dispatch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True)
    parser.add_argument(
        "--vision-config",
        help="Explicit provider JSON config; credentials remain environment references",
    )
    args = parser.parse_args()
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        parser.error('install the mcp extra: pip install ".[mcp]"')
    mcp = FastMCP("photo-organizer")

    @mcp.tool()
    def photo_capabilities() -> dict:
        """List actual supported capabilities and unfinished features. No model calls."""
        return dispatch(args.state, "capabilities", {})

    @mcp.tool()
    def photo_status() -> dict:
        """Read library counts and visual indexing coverage."""
        return dispatch(args.state, "status", {})

    @mcp.tool()
    def photo_scan(root: str, verify: bool = False) -> dict:
        """Synchronize a user-authorized local photo root. May take time; no remote calls."""
        return dispatch(args.state, "scan", {"root": root, "verify": verify})

    @mcp.tool()
    def photo_search(rule: dict, parent_id: str | None = None) -> dict:
        """Freeze matching evidence into a persistent result. parent_id restricts scope; absent tags are unknown."""
        return dispatch(args.state, "search", {"rule": rule, "parent_id": parent_id})

    @mcp.tool()
    def photo_results(
        result_id: str, limit: int = 50, offset: int = 0, verdict: str | None = None
    ) -> dict:
        """Read a snapshot page; pagination never changes membership. Inspect stale_members before planning."""
        return dispatch(
            args.state,
            "results",
            {"result_id": result_id, "limit": limit, "offset": offset, "verdict": verdict},
        )

    @mcp.tool()
    def photo_plan(spec: dict, target: str | None = None, mode: str = "album") -> dict:
        """Freeze an organization plan. Pass result_set_id in spec to organize ALL selected members."""
        return dispatch(args.state, "plan", {"spec": spec, "target": target, "mode": mode})

    @mcp.tool()
    def photo_apply(plan_id: str) -> dict:
        """Execute an authorized plan, preserving originals and refusing destination overwrite."""
        return dispatch(args.state, "apply", {"plan_id": plan_id})

    @mcp.tool()
    def photo_retrieve(
        text: str,
        top_k: int = 30,
        parent_id: str | None = None,
        model: str = "embeddinggemma-2:latest",
    ) -> dict:
        """Rank image/text candidates from the local Ollama index. This does not prove semantic matches."""
        return dispatch(
            args.state,
            "retrieve",
            {"text": text, "top_k": top_k, "parent_id": parent_id, "model": model},
        )

    @mcp.tool()
    def photo_enrich(result_set_id: str, condition: str) -> dict:
        """Review a criterion only within a selected result, using the host-configured vision provider. May take time."""
        return dispatch(
            args.state,
            "review",
            {
                "result_set_id": result_set_id,
                "condition": condition,
                **({"config": args.vision_config} if args.vision_config else {}),
            },
        )

    @mcp.tool()
    def photo_call(operation: str, arguments: dict) -> dict:
        """Call a discovered engine operation. Use photo_operation_schema for its accepted arguments."""
        return dispatch(args.state, operation, arguments)

    @mcp.tool()
    def photo_operation_schema(operation: str) -> dict:
        """Discover accepted arguments through the same contract as CLI."""
        return dispatch(args.state, "operation-schema", {"operation": operation})

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
