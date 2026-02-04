#!/usr/bin/bash

docker build -t serena .

docker run -it --rm -v "$(pwd)":/workspace serena

<serena> start-mcp-server --transport streamable-http --port 9121