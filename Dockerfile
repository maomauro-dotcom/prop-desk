FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY backend ./backend
COPY data ./data
RUN pip install --no-cache-dir -e ".[mcp]"
ENV DATABASE_URL=sqlite:////data/propdesk.db PROPDESK_ROOT=/app
EXPOSE 8000
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
