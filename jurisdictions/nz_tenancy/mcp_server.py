"""MCP server entry point for the NZ Tenancy jurisdiction.

Run via stdio (for Claude Desktop / Claude Code):
    python -m jurisdictions.nz_tenancy.mcp_server

Claude Desktop config (~/.claude_desktop_config.json):
    {
      "mcpServers": {
        "nz-tenancy": {
          "command": "python3",
          "args": ["-m", "jurisdictions.nz_tenancy.mcp_server"],
          "cwd": "/home/wdha/proj/priv/astraea"
        }
      }
    }

Tools exposed:
    legal_search          - search NZ Tenancy Tribunal decisions
    legal_ask             - full RAG answer with citations
    legal_get_source      - fetch a tribunal decision by ID
    legal_get_legislation - fetch an RTA section by ID (e.g. NZLEG/RTA/s42A)
"""

from core.mcp import create_mcp_server
from jurisdictions.nz_tenancy.jurisdiction import NZTenancyJurisdiction

server = create_mcp_server(NZTenancyJurisdiction())

if __name__ == "__main__":
    server.run("stdio")
