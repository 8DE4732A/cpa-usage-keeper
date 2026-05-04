.PHONY: dev build-web install verify clean

# Install Python dependencies
install:
	uv sync

# Run backend in development mode
dev:
	uv run python -m cpa_usage_keeper

# Install frontend dependencies
web-install:
	npm --prefix ./web ci

# Run frontend dev server
web-dev:
	npm --prefix ./web run dev -- --host 127.0.0.1

# Build frontend production assets
build-web:
	npm --prefix ./web run build

# Run all verifications
verify: web-install
	npm --prefix ./web run test
	npm --prefix ./web run lint
	npm --prefix ./web run typecheck
	npm --prefix ./web run build

# Clean build artifacts
clean:
	rm -rf static/
	rm -rf .venv/
	rm -rf src/cpa_usage_keeper/__pycache__/
