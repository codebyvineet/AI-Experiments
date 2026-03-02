FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

ENV PYTHONPATH=/app
ENV MCP_SERVER_PORT=8001
ENV BACKEND_URL=http://app:8000

EXPOSE 8001

# Use the new FastMCP-based app
CMD ["python", "-m", "uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "8001"]
