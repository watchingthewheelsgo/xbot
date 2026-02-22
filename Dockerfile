FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install dependencies first (cache layer)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy application code
COPY server/ server/
COPY main.py ./

# Ensure data directory and db file exist
VOLUME /app/data
CMD ["sh", "-c", "touch /app/data/xbot.db && DATABASE_URL=sqlite+aiosqlite:///./data/xbot.db uv run python main.py"]
