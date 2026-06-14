# Marvis Bridge — 任务桥接调度器 开发工具链
# 用法: make setup / make lint / make test / make ci

PYTHON := $(shell which python3)
PYTEST := $(PYTHON) -m pytest

.PHONY: help setup lint format test test-cov ci type-check verify

help: ## 显示帮助
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

setup: ## 初始化开发环境
	$(PYTHON) -m pip install pre-commit ruff mypy pytest pytest-cov bandit
	pre-commit install --hook-type pre-commit --hook-type commit-msg
	@echo "✅ Marvis Bridge 开发环境就绪"

lint: ## 运行 lint (ruff)
	ruff check scripts/ --fix
	ruff format scripts/ --check

format: ## 格式化代码
	ruff format scripts/

test: ## 运行测试
	$(PYTEST) tests/ -v --tb=short

test-cov: ## 测试 + 覆盖率
	$(PYTEST) tests/ -v --tb=short \
		--cov=scripts \
		--cov-report=term-missing --cov-fail-under=50

type-check: ## 运行 mypy 类型检查
	mypy scripts/ --ignore-missing-imports --check-untyped-defs

verify: ## 验证所有质量门禁
	ruff check scripts/
	ruff format scripts/ --check
	$(PYTEST) tests/ -v --tb=short
	@echo "✅ 质量门禁通过"

ci: ## 模拟完整 CI 流水线
	$(MAKE) lint
	$(MAKE) test
	$(MAKE) type-check
	@echo "✅ CI 通过"
