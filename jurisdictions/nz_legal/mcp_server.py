"""MCP server entry point for the NZ Legal jurisdiction.

Run via stdio (for Claude Desktop / Claude Code):
    python -m jurisdictions.nz_legal.mcp_server

Claude Desktop config (~/.claude_desktop_config.json):
    {
      "mcpServers": {
        "nz-legal": {
          "command": "python3",
          "args": ["-m", "jurisdictions.nz_legal.mcp_server"],
          "cwd": "/path/to/astraea"
        }
      }
    }

Tools exposed:
    legal_search          - search NZ court decisions (NZHC, NZCA, NZSC, NZERA, NZEmpC, NZTT)
    legal_ask             - full RAG answer with citations
    legal_get_source      - fetch a decision by ID
    legal_get_legislation - fetch a legislation section by ID
"""

from core.mcp import create_mcp_server
from jurisdictions.nz_legal.jurisdiction import NZLegalJurisdiction

server = create_mcp_server(NZLegalJurisdiction())

if __name__ == "__main__":
    server.run("stdio")
