# 工程法律顾问 - 后端 Dockerfile（基于 uv）

FROM python:3.11-slim

# 安装 uv（从官方镜像复制，二进制方式最快）
COPY --from=ghcr.io/astral-sh/uv:0.5.14 /uv /uvx /usr/local/bin/

WORKDIR /app

# 系统依赖（pdfplumber + pymupdf 需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 利用 uv 缓存层（先复制 manifest + lockfile，依赖变化时才重新安装）
COPY pyproject.toml uv.lock* .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

# 复制应用代码
COPY . .

# 安装项目本身（editable 模式，不需要也行，uv sync 已包含）
RUN uv sync --frozen --no-dev

# 暴露端口
EXPOSE 8000

# 通过 uv run 激活虚拟环境运行
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]