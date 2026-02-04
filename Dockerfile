# JDK stage
FROM eclipse-temurin:17-jdk-jammy AS temurin

# основной базовый образ остаётся python:3.11-slim
FROM python:3.11-slim AS base

# копируем JDK из temurin
COPY --from=temurin /opt/java/openjdk /opt/java/openjdk
ENV JAVA_HOME=/opt/java/openjdk
ENV PATH="${JAVA_HOME}/bin:${PATH}"

SHELL ["/bin/bash", "-c"]

# Set environment variables to make Python print directly to the terminal and avoid .pyc files.
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Install system dependencies required for package manager and build tools.
# sudo, wget, zip needed for some assistants, like junie
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    git \
    ssh \
    sudo \
    wget \
    zip \
    unzip \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install pipx.
RUN python3 -m pip install --no-cache-dir pipx \
    && pipx ensurepath

# Install nodejs with retry logic
ENV NVM_VERSION=0.40.3
ENV NODE_VERSION=22.18.0

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && set -euo pipefail \
    && export NVM_DIR=/root/.nvm \
    && mkdir -p "$NVM_DIR" \
    && curl -o- --retry 5 --retry-delay 3 --connect-timeout 30 --max-time 300 \
          https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash \
    && . "$NVM_DIR/nvm.sh" \
    && nvm install 22.18.0 \
    && nvm use 22.18.0 \
    && nvm alias default 22.18.0 \
    && echo 'export NVM_DIR=/root/.nvm' >> /etc/profile.d/nvm.sh \
    && echo '. "$NVM_DIR/nvm.sh"' >> /etc/profile.d/nvm.sh

# standard location
ENV NVM_DIR=/root/.nvm
RUN . "$NVM_DIR/nvm.sh" && nvm install ${NODE_VERSION}
RUN . "$NVM_DIR/nvm.sh" && nvm use v${NODE_VERSION}
RUN . "$NVM_DIR/nvm.sh" && nvm alias default v${NODE_VERSION}
ENV PATH="${NVM_DIR}/versions/node/v${NODE_VERSION}/bin/:${PATH}"

# Add local bin to the path
ENV PATH="${PATH}:/root/.local/bin"

# Install the latest version of uv with retry logic and fallback to pip
RUN curl -LsSf --retry 5 --retry-delay 3 --connect-timeout 30 --max-time 300 \
    https://astral.sh/uv/install.sh | sh || \
    (echo "⚠️  Failed to install uv via curl, falling back to pip..." && \
     python3 -m pip install --no-cache-dir uv && \
     echo "✅ uv installed successfully via pip")

# Install Rust and rustup for rust-analyzer support (minimal profile) with retry logic
# Rust + rust-analyzer (устойчивее к обрывам)
RUN apt-get update && apt-get install -y --no-install-recommends \
    rustc cargo rust-analyzer \
    && rm -rf /var/lib/apt/lists/*
    
# Set BSL Language Server JAR path and create directory
ENV BSL_LANGUAGE_SERVER_JAR=/opt/tools/bsl-language-server.jar
RUN mkdir -p /opt/tools    

# Set the working directory
WORKDIR /workspaces/serena

# Development target
FROM base AS development
# Copy all files for development
COPY . /workspaces/serena/

# Create virtual environment and install dependencies with dev extras
RUN uv venv
RUN . .venv/bin/activate
RUN uv pip install --all-extras -r pyproject.toml -e .
ENV PATH="/workspaces/serena/.venv/bin:${PATH}"

# Entrypoint to ensure environment is activated
ENTRYPOINT ["/bin/bash", "-c", "source .venv/bin/activate && $0 $@"]

# Production target
FROM base AS production
# Copy only necessary files for production
COPY pyproject.toml /workspaces/serena/
COPY serena_config.docker.yml /workspaces/serena/
COPY README.md /workspaces/serena/
COPY src/ /workspaces/serena/src/
COPY tools/ /workspaces/serena/tools/

RUN mkdir -p /workspaces/serena/tmp

# Create virtual environment and install dependencies (production only)
RUN uv venv
RUN . .venv/bin/activate
RUN uv pip install -r pyproject.toml -e .
ENV PATH="/workspaces/serena/.venv/bin:${PATH}"

# Entrypoint to ensure environment is activated
ENTRYPOINT ["/bin/bash", "-c", "source .venv/bin/activate && $0 $@"]

