# Changelog

## 0.1.1

- fix: **`import docs_core` 不再依赖数据根**。`kb_migration_audit` 的审计路径此前是模块级常量
  （`AUDIT_PATH = resolve_data_root() / "ops" / ...`），import 期就解析路径——独立安装（wheel）里
  若还没配 `KNOWLEDGE_BASE_DIR` / `ANGINEER_DATA_ROOT` / `ANGINEER_REPO_ROOT`，`import docs_core`
  直接抛 `RuntimeError`（发布后 PyPI 实装验收抓到）。现改为 `audit_path()` 延迟解析，只有真正读写审计时才解析。
- chore: 两处测试随之从 patch 常量改为 patch 函数；`test_kb_migrator_preview` 里"审计路径在 import 期就绑死、
  conftest 的环境隔离拦不住"那条注释作废（该坑随本版修复消失）。
- 说明：数据根仍须在**使用解析/审计前**配好，只是报错点从 import 期挪到了调用点（错误信息不变，仍会明确提示给哪个变量）。

## 0.1.0（对外发布基线）

首个对外发布版本：AnGIneer 的文档解析入库引擎从主仓库（`services/docs-core`）独立成包。
纯 Python 库，覆盖「源文件准备 → 格式转换 → MinerU 解析 → PoPo 强化 → 结构化 → 图描述 →
SQLite+FTS → 向量索引 → 知识图谱」九阶段管线，外加五路检索、text2sql 与产物导出；
不含 HTTP 服务与前端，大算力（版面解析 / 视觉强化 / 图描述 / embedding / rerank）全部走外部端点。

### 能力
- **九阶段管线**：`hard`/`soft` 两类阶段 + 依赖拓扑（`hard` 失败中止、`soft` 失败降级留痕），阶段级重跑与断点续跑（`resolve_stage_order` / `validate_stage_retry` / `compute_resume_stages`）；
- **结构构建**：Solo 是唯一构建者，PoPo 信号作为增强注入（对齐 / 合并 / 层级融合 / 续表/ 跨页表格续接）；
- **数据面**：canonical 七表 + FTS 全文索引（`documents/pages/blocks/outlines/chunks/tables/citation_targets`）、块级引用可溯源；
- **向量**：qdrant（默认）/ sqlite / chroma 三种 provider；
- **检索**：dense / sparse / clause / table / formula 五路召回 + 融合 + 重排，text2sql 保留入口；
- **知识图谱**：实体与关系抽取、证据包构建；
- **产物导出**：按册导 markdown / 图片 / 索引 / 图谱（`step10_export`）。

### 随包发布的内容
- **PoPo fork 随包**：上游 MinerU-Popo 的定制版（`post_processing/model_utils.py` 的 POPO_CONFIGS 多端点定制），
  以**顶层导入名 `popo`** 安装（上游无 `__init__.py`，按命名空间包收集）；产物目录（figures / output_cases / outputs）不入包。
  缺失时第 4 步按「软阶段」跳过，结构由 Solo 单独构建，链路不断；可用 `POPO_REPO_PATH` 指向自定义位置。
- **依赖**：`angineer-tree-core`（树表底座）、`angineer-ai-inference`（LLM 客户端）随 pip 自动带上。

### 发布前的包装改造（记入基线）
- **依赖对账**：源码里 13 个第三方顶层 import → 显式声明 9 个（补 `angineer-ai-inference` / `pydantic` / `PyMuPDF` / `numpy` / `python-dateutil`；
  `angineer-tree-core` 钉 `>=0.1.0,<0.2.0`）；`chromadb`、`PyYAML` 拆成 extras（`[chroma]` / `[text2sql]`），
  避免"旧向量后端 / text2sql 用不上也强装"。
- **路径注入**：`paths.resolve_repo_root()` 去掉「往上数第 6 层」的兜底（该近似只在仓库树里碰巧成立、装到 site-packages 必错），
  改为 `ANGINEER_REPO_ROOT` 显式指定 > 仓库标记探测 > 抛错并提示改用 `KNOWLEDGE_BASE_DIR` / `ANGINEER_DATA_ROOT`。
- **PoPo 随包的构建配置**：`tool.setuptools.packages.find` 开 `namespaces = true` 并按白名单收 `docs_core*` / `popo*`、
  排除 `popo.figures* / popo.output_cases* / popo.outputs*`（默认配置收不到无 `__init__.py` 的 popo）。
- **测试可独立运行**：`tests/conftest.py` 先按 dotenv 规则加载 `.env`（有则用），再补缺省——向量后端默认 `sqlite`、
  数据根指向临时目录、仅当不在仓库树内时给 `ANGINEER_REPO_ROOT`；跨服务用例（需要 docs-api）自动跳过；
  两处依赖环境变量的用例改为自带配置。独立环境基线：**507 passed / 17 skipped**（无外部服务、无网络）。

### 已知边界
- `DOCS_VECTORSTORE_PROVIDER` 必填（不设直接报错，防静默连空库）；
- 非 PDF 输入需要系统安装 LibreOffice（`LIBREOFFICE_BIN` 或 PATH）；
- 部分文档类型 / 表格续接效果依赖 MinerU 与 PoPo 端点质量，换端点后建议重跑一遍解析回归。
