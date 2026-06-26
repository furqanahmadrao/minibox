.PHONY: dev build run stop logs clean test lint

# Development
dev:
	uvicorn src.main:app --reload --host 0.0.0.0 --port 8080

# Build
build:
	docker build -t minibox .

# Run
run:
	docker run -d \
		--name minibox \
		--cap-add SYS_ADMIN \
		-p 8080:8080 \
		-v minibox-workspaces:/data/workspaces \
		-v minibox-snapshots:/data/snapshots \
		-e MINIBOX_AUTH_ENABLED=true \
		minibox

# Stop
stop:
	docker stop minibox && docker rm minibox

# Logs
logs:
	docker logs -f minibox

# Clean
clean:
	docker rmi minibox 2>/dev/null || true
	rm -rf src/static/ __pycache__ .pytest_cache

# Test
test:
	pytest tests/ -v

# Lint
lint:
	ruff check src/ cli/
	ruff format src/ cli/

# Format
format:
	ruff format src/ cli/

# Install dev deps
install:
	pip install -e ".[cli,dev]"

# Show server info
info:
	@echo "Server: http://localhost:8080"
	@echo "API Docs: http://localhost:8080/docs"
	@echo "MCP: http://localhost:8080/mcp/sse"
