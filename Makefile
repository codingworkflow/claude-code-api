# Claude Code API - Simple & Working

# Python targets
install:
	pip install -e .
	pip install requests

install-dev:
	pip install -e ".[test,dev]"
	pip install requests

test:
	python -m pytest --cov=claude_code_api --cov-report=html tests/ -v

test-no-cov:
	python -m pytest tests/ -v

coverage:
	@echo "Opening coverage report..."
	@if [ "$$(uname)" = "Darwin" ]; then \
		open htmlcov/index.html; \
	elif [ "$$(uname)" = "Linux" ]; then \
		xdg-open htmlcov/index.html || echo "Please open htmlcov/index.html in your browser"; \
	else \
		echo "Please open htmlcov/index.html in your browser"; \
	fi

test-real:
	python tests/test_real_api.py

start:
	uvicorn claude_code_api.main:app --host 0.0.0.0 --port 8000 --reload --reload-exclude="*.db*" --reload-exclude="*.log"

start-prod:
	uvicorn claude_code_api.main:app --host 0.0.0.0 --port 8000

clean:
	find . -name "*.pyc" -delete
	find . -name "__pycache__" -delete

kill:
	@if [ -z "$(PORT)" ]; then \
		echo "Error: PORT parameter is required. Usage: make kill PORT=8001"; \
	else \
		echo "Looking for processes on port $(PORT)..."; \
		if [ "$$(uname)" = "Darwin" ] || [ "$$(uname)" = "Linux" ]; then \
			PID=$$(lsof -iTCP:$(PORT) -sTCP:LISTEN -t); \
			if [ -n "$$PID" ]; then \
				echo "Found process(es) with PID(s): $$PID"; \
				kill -9 $$PID && echo "Process(es) killed successfully."; \
			else \
				echo "No process found listening on port $(PORT)."; \
			fi; \
		else \
			echo "This command is only supported on Unix-like systems (Linux/macOS)."; \
		fi; \
	fi

help:
	@echo "Claude Code API Commands:"
	@echo ""
	@echo "Python API:"
	@echo "  make install     - Install Python dependencies"
	@echo "  make install-dev - Install Python development dependencies"
	@echo "  make test        - Run Python unit tests with coverage"
	@echo "  make test-no-cov - Run Python unit tests without coverage"
	@echo "  make coverage    - Open HTML coverage report"
	@echo "  make test-real   - Run REAL end-to-end tests (curls actual API)"
	@echo "  make start       - Start Python API server (development with reload)"
	@echo "  make start-prod  - Start Python API server (production)"
	@echo ""
	@echo "TypeScript API:"
	@echo "  make install-js     - Install TypeScript dependencies" 
	@echo "  make test-js        - Run TypeScript unit tests"
	@echo "  make test-js-real   - Run Python test suite against TypeScript API"
	@echo "  make start-js       - Start TypeScript API server (production)"
	@echo "  make start-js-dev   - Start TypeScript API server (development with reload)"
	@echo "  make start-js-prod  - Build and start TypeScript API server (production)"
	@echo "  make build-js       - Build TypeScript project"
	@echo ""
	@echo "General:"
	@echo "  make clean       - Clean up Python cache files"
	@echo "  make kill PORT=X - Kill process on specific port"
	@echo ""
	@echo "IMPORTANT: Both implementations are functionally equivalent!"
	@echo "Use Python or TypeScript - both provide the same OpenAI-compatible API."