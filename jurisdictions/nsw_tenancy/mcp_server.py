"""MCP server entry point for the NSW Tenancy jurisdiction.

Run via stdio (for Claude Desktop / Claude Code):
    python -m jurisdictions.nsw_tenancy.mcp_server

Claude Desktop config (~/.claude_desktop_config.json):
    {
      "mcpServers": {
        "nsw-tenancy": {
          "command": "python3",
          "args": ["-m", "jurisdictions.nsw_tenancy.mcp_server"],
          "cwd": "/path/to/astraea"
        }
      }
    }

Tools exposed:
    legal_search - search NSW NCAT tenancy decisions
    legal_ask    - full RAG answer with citations
    legal_get_source - fetch a decision by ID
"""

from core.mcp import create_mcp_server
from jurisdictions.nsw_tenancy.jurisdiction import NSWTenancyJurisdiction

server = create_mcp_server(NSWTenancyJurisdiction())

if __name__ == "__main__":
    server.run("stdio")
