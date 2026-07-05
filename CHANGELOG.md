# Changelog

## [2026-07-04] Phase 3: 统一制式

### 基础设施
- pyproject.toml 引入 src/ 布局
- uv.lock 依赖锁定（32 包）
- .pre-commit-config.yaml 本地钩子配置（ruff + ruff-format + gitleaks）

### CI
- bridge-ci.yml：ruff lint + ruff format check + bandit 安全扫描
