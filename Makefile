.PHONY: install lint test demo bench live serve docker
install:; pip install -e ".[dev]"
lint:; ruff check src tests && ruff format --check src tests
test:; pytest
demo:; bridge demo
bench:; bridge bench -n 2000
live:; bridge demo --live
serve:; bridge serve
docker:; docker build -t agentforce-bridge .
