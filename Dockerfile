FROM python:3.11-slim

# Run privileged commands as root
USER root

# Install dependencies
RUN apt-get update
RUN apt-get install -y curl build-essential
RUN pip install uv

# Install Node.js and npm
RUN curl -fsSL https://deb.nodesource.com/setup_22.x -o nodesource_setup.sh
RUN bash nodesource_setup.sh
RUN apt-get install -y nodejs

# Install Claude CLI
RUN npm install -g @anthropic-ai/claude-code

# Add work user
RUN useradd -ms /bin/bash work

# Set work directory
WORKDIR /home/work/app

# Copy project files
COPY . /home/work/app
RUN chown -R work:work /home/work/app

# Switch to work user
USER work

# Install Python dependencies
RUN uv sync
RUN uv pip install -e .
RUN uv add requests

# Expose API port
EXPOSE 8000

# Start API server in production mode
CMD ["uv", "run", "uvicorn", "claude_code_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
