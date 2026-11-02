# 发布 honesty-scan 到 PyPI

`honesty-scan` 已配置为标准 PyPI 包（见 [`pyproject.toml`](pyproject.toml)），本地一条命令即可发布。

## 包信息

| 项 | 值 |
|---|---|
| 包名 | `honesty-scan` |
| 入口命令 | `honesty-scan`（= `honesty_scan:main`） |
| Python | >= 3.8 |
| 许可 | MIT |
| 仓库 | https://github.com/TrueFurina/honesty-ci-patterns |

发布后，任何人可以：

```bash
pip install honesty-scan
honesty-scan ./docs --registry number_registry.json
honesty-scan . --init ci          # 生成 GitHub Actions 门禁
honesty-scan . --init precommit   # 生成 pre-commit 钩子
honesty-scan ./docs --json        # JSON 输出
```

## 发布步骤（首次）

1. **装构建工具**（仅本地需要一次）：

```bash
python -m pip install --upgrade build twine
```

2. **构建 sdist + wheel**：

```bash
python -m build
# 产物在 dist/：honesty_scan-1.1.0.tar.gz + honesty_scan-1.1.0-py3-none-any.whl
```

3. **（可选）本地试装验证**：

```bash
pip install dist/*.whl
honesty-scan --help
```

4. **发布**：

- **TestPyPI 先试**（推荐）：

```bash
twine upload --repository testpypi dist/*
# 然后验证: pip install --index-url https://test.pypi.org/simple/ honesty-scan
```

- **正式 PyPI**：

```bash
twine upload dist/*
```

> `twine` 会提示输入 PyPI 用户名/Token。建议用 **API Token**（PyPI → Account settings → API tokens），
> 用户名填 `__token__`，密码填 token。**不要把 token 写进任何文件或命令历史。**

## 后续发版

1. 改 `pyproject.toml` 里的 `version`
2. `rm -rf dist/ build/ && python -m build`
3. `twine upload dist/*`

## 为什么用 py-modules 而不是 packages

本工具是**单文件模块** `honesty_scan.py`，不是目录包。`pyproject.toml` 里用的是：

```toml
[tool.setuptools]
py-modules = ["honesty_scan"]
```

如果误写成 `packages = ["honesty_scan"]`，setuptools 会去找 `honesty_scan/` 目录、找不到、构建出**空包**（装上去 `honesty-scan` 命令报 `ModuleNotFoundError`）。这是 Python 打包最常见的坑之一，特此记录。

## CI 集成（装包后）

仓库里已有 [`​.github/workflows/honesty-gate.yml`](.github/workflows/honesty-gate.yml) 直接用源码跑门禁。
若想用 PyPI 版本（避免维护 vendored 脚本）：

```yaml
- name: Install honesty-scan
  run: pip install honesty-scan
- name: Run honesty gate
  run: honesty-scan . --registry number_registry.json
```
