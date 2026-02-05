# Claude Code API - Simple & Working

SHELL := /bin/bash
.DEFAULT_GOAL := help

# Directory structure
ARTIFACTS_DIR ?= dist/artifacts
QUALITY_DIR ?= dist/quality
SECURITY_DIR ?= dist/security
TESTS_DIR ?= dist/tests

BUILD_DIR := $(ARTIFACTS_DIR)/bin
COVERAGE_DIR := $(QUALITY_DIR)/coverage
SONAR_DIR := $(QUALITY_DIR)/sonar
SBOM_DIR := $(SECURITY_DIR)/sbom
GITLEAKS_DIR := $(SECURITY_DIR)/gitleaks

# Version info
VERSION_FILE := $(shell cat VERSION 2>/dev/null || echo "1.0.0")
VERSION ?= $(VERSION_FILE)
COMMIT ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo "unknown")
BUILD_DATE ?= $(shell date -u +'%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || "")

# Dependency-Track settings
DTRACK_BASE_URL ?=
DTRACK_API_KEY ?=
DTRACK_PROJECT ?= claude-code-api
DTRACK_PROJECT_VERSION ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo "dev")

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

# Quality and Security targets
.PHONY: sonar sonar-cloud coverage-sonar sbom sbom-upload gitleaks fmt lint vet
.PHONY: docker-validate

sonar: ## Run sonar-scanner for SonarQube analysis
	@SONAR_DIR=$(SONAR_DIR) COVERAGE_DIR=$(COVERAGE_DIR) VERSION=$(VERSION) ./scripts/run-sonar.sh

sonar-cloud: ## Run sonar-scanner for SonarCloud (uses different token/env)
	@echo "Running SonarCloud scanner..."
	@./scripts/run-sonar-cloud.sh

coverage-sonar: ## Generate coverage for SonarQube
	@mkdir -p $(COVERAGE_DIR) $(SONAR_DIR)
	@python -m pytest --cov=claude_code_api --cov-report=xml:$(COVERAGE_DIR)/coverage.xml --cov-report=term-missing --junitxml=$(SONAR_DIR)/xunit-report.xml -v tests/
	@echo "Coverage XML generated: $(COVERAGE_DIR)/coverage.xml"

sbom: ## Generate SBOM with syft
	@mkdir -p $(SBOM_DIR)
	@if command -v syft >/dev/null 2>&1; then \
		syft dir:. -o cyclonedx-json=$(SBOM_DIR)/sbom.json; \
		echo "SBOM generated: $(SBOM_DIR)/sbom.json"; \
	else \
		echo "syft not found. Install with: brew install syft or visit https://github.com/anchore/syft"; \
		exit 1; \
	fi

sbom-upload: sbom ## Generate (if needed) and upload SBOM to Dependency-Track
	@./scripts/upload-sbom.sh $(SBOM_DIR)/sbom.json

gitleaks: ## Run gitleaks to detect secrets
	@mkdir -p $(GITLEAKS_DIR)
	@if command -v gitleaks >/dev/null 2>&1; then \
		gitleaks detect --source . --report-path $(GITLEAKS_DIR)/gitleaks-report.json; \
	else \
		echo "gitleaks not found. Install with: brew install gitleaks"; \
		exit 1; \
	fi

fmt: ## Format Python code with black
	@if command -v black >/dev/null 2>&1; then \
		black claude_code_api/ tests/; \
	else \
		echo "black not found. Install with: pip install black"; \
	fi

lint: ## Run Python linters (flake8, isort)
	@if command -v flake8 >/dev/null 2>&1; then \
		flake8 claude_code_api/ tests/; \
	else \
		echo "flake8 not found. Install with: pip install flake8"; \
	fi
	@if command -v isort >/dev/null 2>&1; then \
		isort --check-only claude_code_api/ tests/; \
	else \
		echo "isort not found. Install with: pip install isort"; \
	fi

vet: ## Run type checking with mypy
	@if command -v mypy >/dev/null 2>&1; then \
		mypy claude_code_api/; \
	else \
		echo "mypy not found. Install with: pip install mypy"; \
	fi

docker-validate: ## Build Docker image and validate docker-compose
	@./scripts/validate-docker.sh

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
	@echo "Quality & Security:"
	@echo "  make sonar         - Run SonarQube analysis (generates coverage + scans)"
	@echo "  make sonar-cloud   - Run SonarCloud scanner (uses SONAR_CLOUD_TOKEN)"
	@echo "  make coverage-sonar - Generate coverage XML for SonarQube"
	@echo "  make sbom          - Generate SBOM with syft"
	@echo "  make sbom-upload   - Upload SBOM to Dependency-Track"
	@echo "  make gitleaks      - Run gitleaks to detect secrets"
	@echo "  make fmt           - Format Python code with black"
	@echo "  make lint          - Run Python linters (flake8, isort)"
	@echo "  make vet           - Run type checking with mypy"
	@echo ""
	@echo "General:"
	@echo "  make clean       - Clean up Python cache files"
	@echo "  make kill PORT=X - Kill process on specific port"
	@echo ""
	@echo "IMPORTANT: Both implementations are functionally equivalent!"
	@echo "Use Python or TypeScript - both provide the same OpenAI-compatible API."
