"""Compatibility entrypoint for existing stdio host registrations."""

from .interfaces.mcp_server import main

if __name__ == "__main__":
    main()
