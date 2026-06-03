"""MCP server entry point for the NZ Employment jurisdiction.

Run via stdio (for Claude Desktop / Claude Code):
    python -m jurisdictions.nz_employment.mcp_server

Claude Desktop config (~/.claude_desktop_config.json):
    {
      "mcpServers": {
        "nz-employment": {
          "command": "python3",
          "args": ["-m", "jurisdictions.nz_employment.mcp_server"],
          "cwd": "/path/to/astraea"
        }
      }
    }

Tools exposed:
    legal_search          - search NZ ERA and Employment Court decisions
    legal_ask             - full RAG answer with citations
    legal_get_source      - fetch a decision by ID
    legal_get_legislation - fetch an ERA 2000 section by ID
"""

from core.mcp import create_mcp_server
from jurisdictions.nz_employment.jurisdiction import NZEmploymentJurisdiction

server = create_mcp_server(NZEmploymentJurisdiction())

if __name__ == "__main__":
    server.run("stdio")
