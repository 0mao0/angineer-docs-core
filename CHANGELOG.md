# Changelog

## 0.1.6

- feat: **`KB_STACK=pg` 档位（PostgreSQL + pgvector 存储后端）**——`pg_support` 把 sqlite3 连接协议翻译成 PG 方言（占位符 / `INSERT OR REPLACE`→`ON CONFLICT` / `LIKE`→`ILIKE` / `PRAGMA table_info`→information_schema / `AUTOINCREMENT`→`BIGSERIAL`），`KB_STACK=legacy|pg` 一个键原子切换、禁半迁移；新增 `PgVectorStore`（`collection_name` 复刻组隔离、`score=1-<=>`）；meta/index/canonical PG 子类，FTS 对等走 bigram 写入侧展开 + tsvector 生成列（bm25 升序语义以 `-ts_rank` 保持）；registry / parse_records / 壳 `/health` 按档位分支
- feat: **知识库并入业务库同 database，独立 schema `dredge_knowledge`**——所有连接注入 `-c search_path=dredge_knowledge,public`，核心代码裸表名零改写（`KNOWLEDGE_PG_SCHEMA` 可覆盖）；建库时 `CREATE SCHEMA IF NOT EXISTS` + 扩展显式装 `public`；information_schema 的主键/列清单查询加 `current_schemas(false)` 过滤，同库并存业务表不误命中
- feat: **中性语料包 v2（`format=neutral-v2`）**——canonical 模型形状 jsonl.gz + doc_blocks/segments 行级 + vectors parquet + sha256/计数 manifest；导出/导入走存储抽象，legacy/pg 双源双目标；导入支持 stages 断点续跑、`allow_existing`、index 段每 2000 行分批提交（48 万行单事务在远程实例断连即全盘失败），收尾自动 ANALYZE（无统计时检索 1.5s→16s）
- feat: 系统不再自动创建 default 库（空注册表保持空清单），default 删除保护放开——任何注册库都可删；PG 档位删库清理补全（canonical / 块表 / parse_records / meta 全清，此前只清向量 / 文件 / 注册表）
- fix(pg): 导入链路四连修——长 chunk 触发 PG btree 单行 2704 字节上限（改 `substring(text_clean for 500)` 前缀函数索引）；短连接在远程实例第 3328 个点撞超时（thread-local 长连接 + ping 重建 + 连接重试 3 次）；小盘实例并行查询/建索引动态共享内存 DiskFull（会话禁并行）；HNSW 索引删除判据不再依赖 DDL rowcount（恒 -1 致删而不建）
- fix(registry): 自定义库组查表按 search_path——`information_schema` 写死 `table_schema='public'` 致建组回读恒判「表不存在」（`create_group` 断言必挂、`list_custom_groups` 恒空、往自定义组建库被判未知组）
- fix: 读穿与导出两修——`get_node` 改读穿 meta（导入后不重启壳，回源/引用不再 404）；中性包导出向量按库直筛 `iter_records(library_id=...)`，不再整 collection 扫描后过滤

## 0.1.5

- feat: 图谱存储按库拆分（一库一文件）——全局 `graph.sqlite` 改为每库 `knowledge/libraries/<库>/graph.sqlite`，启动首跑自动拆分迁移（备份改名、逐表对账、幂等可重跑；失败不阻塞启动、读写回退全局文件）；图谱页签与 API、维护任务、导出产物查找全部改按库解析；拆并适配跨文件迁移
- feat: 导入闭包实体闸移除——带图谱语料包跨环境导入不再被目标实例同名词实体阻断，图谱阶段整文件按库落位（冲突闸只查库/组/文档/索引文件碰撞）
- fix(export) 三修（生产实跑实踩）：无 graph 文件的库导出整包 failed（`closing(...).close()` 在 Py3.11 无此方法）；组路由下本库图谱静默清零（导出自查改走全站唯一解析器 `resolve_graph_db_for_library`）；库根 graph/index sqlite 及 WAL/SHM 边车不再随 files/ 扫描进包（流式拷贝中途边车被 checkpoint 回收即断流）
- fix(graph): `get_graph_snapshot` 不带 doc_id 必 500——else 分支历史裸名 `store` 改 `self.store`，补回归测试钉住两形态
- chore: PoPo 解耦收官——删除内化副本，改依赖 popo-client（dgx-spark-popo 独立库）文档级 HTTP API；popo-client 依赖撤 git 直引、降为 `[popo]` extra（PEP 508 git 直引下构建容器无 git 即必败）
- fix(并发): 向量入库加并发闸（`VECTORS_MAX_CONCURRENCY` 默认 8，按到达序排队）；图谱存储 sqlite busy 超时 5s→30s——修补跑并发下 `database is locked` 失败风暴
- feat(import): 语料包 v2 导入链（上传/预检/应用/进度路由 + CLI + dry-run 预览）；retired 同 id 允许重新导入；导入补 parse_records 上传台账、library_id 正则与图谱逐表对账；支持库根级文件
- fix(retrieval): 引用解析表默认覆盖全部 cite 标记（修第 6 条以后前端回退 doc_id）；doc_search 时间维度（sort_by/date_after/date_before）与 entity_contains、doc_read section 章节读（与检索壳六端口同步）；多行表头压成单行、数据行带序号
- fix(ops): 删库 Windows 文件锁重试与 deleting 重试兜底、清 parse_records 台账；拆并拒绝同组异构桶、非空库跨桶改组拒绝、独立桶 retired 引用保护；零向量包不查 qdrant collection；PyMuPDF 钉 1.28.2 并切腾讯云 pip 镜像


## 0.1.4

- feat: **engine 端口 HTTP 面**（`docs_core.server.engine_ports`）——新增 5 个内部端点：`/internal/normalize-query`（条款号归一化）、`/internal/rerank`（phrase rerank）、`/internal/relevant-citations`（引用挑选）、`/internal/table-blocks`（canonical 表格块批量取数）、`/internal/engtool-run`（外部工具执行，404=工具不存在 / 503=注册表不可用 / 500=执行异常 三态）；复用 agent_port / reranker 同一份实现，供 chat 壳 `http_ports` 适配器消费（citations 修单）；主仓库 docs-api 同批挂载保持两端面镜像
- chore: `docs_core.server` 惰性导出（docs-api 导入 engine_ports 不再构造壳应用）；壳启动即配 `logging.basicConfig`（同 docs-api/aichat-api）

## 0.1.3

- feat: **独立宿主壳 `[server]` extra（retrieval-api）**——`docs_core.server:app` 提供只读检索面：`POST /api/knowledge/internal/retrieve`、`/internal/entity-search`、`GET /internal/doc-nodes`、`/libraries`、`/stats`、`GET /documents/{doc_id}/download`（`?disposition=inline`）、`GET /health`（含数据根 / 注册表挂载状态）。数据面全参数化（`ANGINEER_DATA_ROOT` / `KNOWLEDGE_BASE_DIR` / `QDRANT_URL` / `EMBEDDING_CONFIGS`…），不依赖仓库树；可选 `ANGINEER_API_TOKEN` 门；fastapi / uvicorn 只进 extra
- feat: **语料包（corpus package）**——新增 `docs_core.corpus_package`：按库打包（registry 行 + meta 摘行 + 组 sqlite checkpoint + documents 树 + qdrant snapshot + sha256 manifest），`iter_package_zip` 流式产出供服务端不落盘，`ExportTasks` 任务态封装（管理后台与导入侧配套在主仓库）
- feat: 库组定版换名——系统库组 `standards → system`（`DEFAULT_GROUP` 随之）、规范库组（原自建 `guifan`）→ `standards`；`GROUP_DEFAULTS` 的 collection / sqlite_file / qdrant 集合随名互换归属（迁移脚本在主仓库 `scripts/migrate_group_rename.py`）
- fix: `parse_records` 库路径改经 `resolve_data_root()` 解析——`ANGINEER_DATA_ROOT` 参数化，wheel 树外安装不再因找不到仓库树抛错（此前该路径直接 `resolve_repo_root()`）
- chore: 知识库统计聚合抽为 `docs_core.knowledge_stats`（主仓库 docs-api 与检索薄壳共用单一实现）；若干「已完结清理」注释勘误

## 0.1.2

- fix: 拆分产物的「组文件」桶在任务开始时从已注册侧钉定。拆到新库的执行全程目的地尚未注册，`_relabel_group_tables` 按 `to_lib` 现查 `resolve_index_db_path` 会回退到 `knowledge_index` 桶、把 UPDATE 写进陈年副本，组文件纹丝不动——对账「组文件改标 0/5」必败（2026-10-07 生产 `mig-cd0e1350f7fe` 实踩）。组桶现沿 P0-2 collection 同款纪律随 `migrate_doc` / `rollback_doc` / `_compensate` / `_verify` 显式传递，回滚分支从原源库钉定
- fix: 门禁与回滚注册表的收尾改走 `set_status_if_registered`——未注册的新库没有行可挂门禁、也无需 retire，原 `set_status` 缺行必 `KeyError`，会让「全部回滚」在门禁一步即崩
- chore: 新增 `tests/test_kb_migrator_group_bucket.py`——复刻生产形态（无 `group_db` 注入 + 目的地未注册 + 回退桶陈年副本）两例，修复前逐字复现 0/5 与 `KeyError`

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
