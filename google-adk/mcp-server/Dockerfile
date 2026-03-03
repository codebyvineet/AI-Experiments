FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y gcc && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

# Expose MCP server port
EXPOSE 8001

# FastAPI + FastMCP — JSON-RPC at /message, streamable-http at /mcp
CMD ["python", "src/app.py"]
