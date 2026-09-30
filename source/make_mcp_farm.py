#!/usr/bin/env python3
"""Build MCP content-farm videos with separate assets and data pools."""
import os


os.environ["SG_FARM_FORMAT"] = "mcp_farm"

import make_farm


if __name__ == "__main__":
    make_farm.main()
