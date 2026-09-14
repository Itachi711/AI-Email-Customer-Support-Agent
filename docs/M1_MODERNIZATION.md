# M1 Modernization — 验收记录

日期：2026-09-15。项目：`D:\workspace\langgraph-email-automation-main`。
范围：Modernization + Compatibility + Baseline Reproduction。未开展 M2/M3/M4。

## Repository Audit

业务代码修改前已读取全部 10 个 Python 文件、requirements.txt、README、prompts 和 data/agency.txt，并检查目录、环境文件、Git、索引及凭据。

| 审计对象 | 原始状态 / 发现 |
| --- | --- |
| 目录 | 根目录入口 main.py / create_index.py / deploy_api.py；src 下 agents、graph、nodes、state、structure_outputs、prompts、tools/GmailTools.py |
| 文档 | data/agency.txt；workflow.png。README 的持续监听、自动发送、Python 3.7+ 描述与源码或现代依赖不符 |
| Git / tests | 无 .git、无测试、无 .gitignore、无 pyproject 或锁文件；未发现适用 AGENTS.md |
| 配置 / secrets | 项目无 .env / .env.example / credentials.json / token.json；进程无 OPENAI_API_KEY；源码扫描未发现真实 key、OAuth credential、token |
| Graph | 已使用 StateGraph；构造 Workflow -> Nodes -> Agents/GmailTools 就初始化外部服务 |
| State / 重写 | 路由直接 pop 队列、修改历史；向 add_messages 返回整段历史；重试耗尽后直达 categorize，最后一封会访问空队列；跨邮件重试状态清理不完整 |
| Schema | 原来已经直接 import pydantic.BaseModel；未发现 pydantic.v1、parse_obj、.dict 等旧写法。问题是依赖未锁定、输出约束和状态边界验证不足 |
| Pipelines / prompts | 5 条 LCEL 管道；四种分类；最多 3 条 RAG 查询；writer/proofreader 循环。原 prompts 原样保留 |
| RAG | TextLoader 加载 agency.txt；RecursiveCharacterTextSplitter(300, 50)；Dense similarity Top-K=3；每条 query 检索后生成文本，再汇总给 writer |
| Chroma | 已有 db/chroma.sqlite3 及 4 个 HNSW .bin 文件；只读 SQLite 查询确认 collection=langchain、dimension=768 |
| Gmail | gmail.modify scope；最近 8 小时、最多 50 条全邮箱候选；按 thread 去重、排除 draft 和自己发信；只读第一页 draft；异常被吞掉 |
| Gmail headers | API id 与 RFC Message-ID 分开；回复使用 threadId、In-Reply-To、References。缺失 Message-ID 曾返回 None，违反 Email 的 str 字段 |
| 入口 | main / create_index 无 main guard，import 即执行；deploy_api import 即编译外部依赖图 |
| API/import 清单 | Groq、Google Gemini 为旧 provider；Chroma 已使用独立 integration，但无版本约束；text-splitters 为未声明直接依赖；未发现旧 LLMChain / RetrievalQA 等已删除类 |

扫描只输出文件位置/是否存在，不打印 secret。旧索引、agency.txt、prompts.py、workflow.png 共 8 个文件的 SHA-256 在验收时与修改前一致。

## Original Stack

依赖全部未锁版本，无法声称曾成功复现原环境。原 requirements 包括 langchain-core、langchain_community、langgraph、langchain-groq、langchain_google_genai、langchain_chroma、chromadb、Google API/OAuth 库、beautifulsoup4、dotenv、colorama、langserve、sse_starlette、uvicorn、gunicorn、fastapi。

实际源码的五条工作流管道使用 Groq `llama-3.3-70b-versatile`，不是 README 中的 llama-3.1。
`gemini-1.5-flash` 在 Agents 中构造但未用于工作流，在旧 create_index 的 QA smoke 中使用。
Embedding 是 `models/text-embedding-004`。配置依赖当前工作目录下的 db、credentials.json、token.json。

## Modernized Stack

| 组件 | 本次成功版本 |
| --- | --- |
| Python | CPython 3.11.16，Windows x64 |
| 项目环境 | .venv/Scripts/python.exe |
| 包管理器 | pip 24.0；uv 0.12.13 仅用于取得独立 Python |
| LangGraph | 1.2.11 |
| LangChain / core | 1.4.0 / 1.6.3 |
| langchain-openai / OpenAI SDK | 1.6.2 / 3.13.0 |
| langchain-chroma / Chroma | 1.1.0 / 1.5.9 |
| langchain-text-splitters | 1.1.2 |
| Pydantic / python-dotenv | 2.13.5 / 1.2.3 |
| Google API client / auth | 2.200.0 / 2.58.0 |
| Google auth-oauthlib / auth-httplib2 | 1.4.1 / 0.4.2 |
| LangServe / FastAPI / Uvicorn | 0.3.3 / 0.141.1 / 0.53.0 |
| sse-starlette / Starlette / AnyIO | 3.4.11 / 1.6.0 / 4.15.1 |
| pytest / Ruff | 9.1.1 / 0.16.7 |

requirements.txt 记录 22 项直接依赖的精确版本；requirements.lock.txt 固定全部 130 项应用/传递依赖。
pip 自身版本另在本报告记录。锁文件针对本次 Windows / Python 3.11 环境；3.12 为允许的替代目标，未实际运行验证。

本机 launcher 原来只有 Python 3.14，未直接将其用于应用。通过官方 uv 的 python-build-standalone 支持取得项目内 Python 3.11.16，并建立 .venv，未修改 PATH、注册表或系统 Python。基础解释器位于 `work/python/cpython-3.11.16-windows-x86_64-none/python.exe`；当前 .venv 依赖该目录，不要把它当作可删除临时文件。另一台机器有 Python 3.11 时可直接按 README 用 `py -3.11 -m venv .venv` 重建。

删除已不使用的 Groq/Google AI integration、langchain-community 和仅 Unix 使用的 gunicorn。保留 Google Gmail SDK。简单 UTF-8 文本读取生成 LangChain Document，替代仅用于一个文本文件的 community TextLoader；来源、内容与分块算法不变。

## Compatibility Changes

1. **Provider / 配置**：src/config.py 集中加载项目 .env，环境变量优先且不覆盖已有 secret。默认 Chat=`gpt-5.6-luna`，Embedding=`text-embedding-3-small`，允许用户显式修改；无任何模型自动 fallback。模型、索引路径、Top-K、Gmail 路径和 MY_EMAIL 均集中管理。
2. **结构化输出**：ChatOpenAI 使用 Responses API 和 `with_structured_output(schema, method="json_schema", strict=True)`。四个 Pydantic v2 输出模型保留业务字段；分类为有限 StrEnum，查询为 1–3 条非空字符串，writer email 非空、proofreader send 为严格 bool，拒绝额外字段。无 JSON 字符串手工解析。SDK 和节点边界分别验证无效输出。
3. **采样参数**：旧 temperature=0.1 不盲目带入新模型。默认不发送 temperature，避免模型兼容性问题；OPENAI_CHAT_TEMPERATURE 可显式设定支持的值。这一 provider 行为差异已记录，未调整 prompts 或 retrieval。
4. **惰性初始化 / 注入**：导入、Agents/GmailTools 构造、Workflow compile 不调用模型、embedding 或 OAuth；只有显式执行对应操作才要求配置。模型、retriever、Gmail service、nodes 均可注入测试替身。
5. **StateGraph**：保留原节点和分类边。路由改为纯函数；成功草稿后才移除当前邮件。只增加 `discard_unsendable_email` 清理节点，将耗尽路径送回 inbox check，修复最后一封邮件崩溃。每封邮件仍最多 3 次 writer；第三次通过可建草稿，第三次失败跳过。
6. **历史 reducer**：AIMessage 保存 writer 结果，HumanMessage 保存审阅意见，节点只返回增量；用 RemoveMessage(REMOVE_ALL_MESSAGES) 清空历史。修复重复历史、跨邮件上下文及 retry budget 泄漏。
7. **Chroma**：新默认目录 db_openai_m1，collection email_support_openai_m1；旧 db 及其子路径被显式保护。manifest 记录 provider/model/collection、原文 SHA、300/50 分块参数和 chunk count。配置或来源改变时要求新目录，不自动删除/迁移索引。相同来源重跑不重复写入。
8. **入口**：main.py / create_index.py 增加 main guard；main --check 离线编译，main --openai-smoke 仅做一条合成分类调用；create_index 默认只建 embedding index，原索引后 QA smoke 改为显式 --smoke-query。
9. **Gmail**：OAuth lazy、可注入 service、绝对路径；draft 完整分页；精确比较 sender；缺失 RFC ID 转为空串；不重复追加 References。正文解析处理嵌套 MIME、plain 优先、缺失 body/base64 padding、UTF-8；HTML 转义并加入真实 plain fallback。异常明确抛出，避免把 OAuth/草稿失败当作空邮箱或成功。
10. **LangServe**：通过公开 RunnableBinding 适配其 config schema 获取，避免直接调用 LangGraph 废弃 config_schema；同步/异步执行和流式行为继续委派给原 compiled graph。保留 LangServe、FastAPI 和原路由，已实际验证 SSE，未重构成 create_agent。

## Preserved Baseline Behavior

```text
Gmail candidates -> inbox empty check -> categorization
  product_enquiry -> up to 3 RAG queries -> dense retrieval/answer -> writer
  customer_complaint/customer_feedback -> writer
  unrelated -> skip -> inbox check
writer -> proofreader
  approved -> Gmail draft -> inbox check
  rejected, attempts < 3 -> rewrite
  rejected, attempts = 3 -> cleanup/skip -> inbox check
```

- 原 agency.txt、300 字符 chunk size、50 overlap、最多 3 条 decomposition queries、Dense similarity、Top-K=3 均不变；原文产生 24 个 chunks。
- 每个 query 仍独立执行 retrieval -> QA generation，拼接 query/answer，再给 writer；未增加检索算法。
- 原四种业务分类、邮件队列从末尾处理、writer/proofreader prompts 保留。
- Gmail 仍为单次候选拉取，最近 8 小时最多 50 条；没有新增持续监听服务，也未加入 unread/in:inbox 条件。
- `send_email` 只是保留的历史图节点名称，实际连接 `create_draft_response`。原显式 send helper 保留，但不接入图。自动测试无真实 draft/send。
- 未加入 Supervisor、Memory、HITL、risk routing、multi-agent、MCP、UI 或数据库迁移。

## Verification

以下均在项目目录以 `.\.venv\Scripts\python.exe` 执行；没有用全局 Python 运行应用。

| 实际命令 | 真实结果 |
| --- | --- |
| `py -0p`（环境选择前后） | 仅系统 3.14；未改变系统注册 |
| `.\.venv\Scripts\python.exe --version` | Python 3.11.16 |
| `.\.venv\Scripts\python.exe -m pip install -r requirements.txt --disable-pip-version-check` | 成功，exit 0；安装日志 work/pip-install.log |
| `.\.venv\Scripts\python.exe -m pip freeze` | 记录 130 项到 requirements.lock.txt |
| `.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt --disable-pip-version-check` | 成功，exit 0；精确版本均满足；不是声称另建一个全新环境验证 |
| `.\.venv\Scripts\python.exe -m pip check` | No broken requirements found. |
| `.\.venv\Scripts\python.exe -m compileall -q src tests main.py create_index.py deploy_api.py` | exit 0 |
| `.\.venv\Scripts\python.exe -m pytest -q` | **95 passed, 1 warning in 3.38s** |
| `.\.venv\Scripts\python.exe -m ruff check .` | All checks passed! |
| `.\.venv\Scripts\python.exe main.py --check` | PASS: imports and StateGraph compile (no external services) |
| importlib.import_module 循环导入 12 模块 | PASS: 12 module imports（见下方完整命令） |
| `.\.venv\Scripts\python.exe main.py --openai-smoke` | NOT RUN - OPENAI_API_KEY unavailable |
| 8 个原始保护文件 SHA-256 对比 | 全部 unchanged |
| `git diff --check` | exit 0；无空白错误，只有 Git 的 Windows LF/CRLF 提示 |

完整 import smoke 命令：

```powershell
.\.venv\Scripts\python.exe -c "import importlib; modules=['src.config','src.state','src.structure_outputs','src.prompts','src.agents','src.rag','src.tools.GmailTools','src.nodes','src.graph','main','create_index','deploy_api']; [importlib.import_module(m) for m in modules]; print('PASS: 12 module imports')"
```

测试分布：workflow + schema 54；Gmail 21；OpenAI pipelines 6；config 5；RAG 5；imports / LangServe 4，总计 95。

OpenAI pipeline 测试使用真实 ChatOpenAI/OpenAI SDK 的 Responses 请求构造和 Pydantic 解析，HTTP 由 httpx.MockTransport 在内存返回；既验证 schema/模型配置，也验证非法 category 抛出 ValidationError，**不是 live API 成功**。
RAG 测试使用真实 Chroma 和临时目录，32 维 deterministic fake embeddings，完成 24 chunks 建库、重开、Top-K 查询、重复建库和不兼容索引拒绝。它证明工程建库路径可执行，**不是已经生成 OpenAI 的真实新索引**。

conftest 在 collection 阶段禁用真实 key/.env/tracing，在执行阶段阻断外部 socket/OAuth，仅允许 Windows asyncio 内部 socketpair 构造。Gmail 全部使用 fake/mock；凭据不存在也不影响 test collection。

开发中首轮执行曾为 32 passed / 1 failed：测试的网络屏蔽误拦 Windows asyncio 内部 socketpair。修正测试隔离边界后 API 测试通过；没有为通过测试放开任何外部网络。后续整体结果如上，不隐藏该开发期失败。

## Live API Status

- **OpenAI：NOT RUN — OPENAI_API_KEY unavailable**。保留用户指定模型；未验证账户授权、额度、线上 schema 接受或真实 embedding 请求。
- **Gmail：NOT RUN**。机器没有项目 OAuth credentials/token，且本阶段默认禁止真实 side-effect test；即使存在也不会自动 draft/send。未创建伪造 credentials。
- **真实新 index：NOT RUN**。无 OpenAI Key；运行 create_index.py 即可按已验证路径创建，旧 db 未读取为新模型的查询库。

## Known Limitations

1. Starlette 1.6.0 TestClient 引用 AnyIO 4.15.1 已弃用的 BlockingPortal 别名，产生 1 个第三方 DeprecationWarning；测试通过。LangGraph config_schema 警告已由适配器消除。没有修改第三方包或隐藏警告。
2. 无 API key/OAuth 凭据，真实 OpenAI、Gmail 和 OpenAI embedding 索引尚未经在线验收；账户不可用模型会明确失败，不自动换模型。
3. 保留近期邮件/首条 thread 的“未答复”启发式；不检查完整 thread 历史。已有任意 draft 会排除该 thread，可能跳过后续新客户消息。
4. 缺少 RFC Message-ID 的邮件无法保证完整 RFC 回复关联，仍提交 threadId；非 UTF-8 特殊编码正文使用替换字符解码。
5. main.py 保留 recursion_limit=100；高负载批次/多次重写可能触发 GraphRecursionError。未把这项旧运行策略改为新的批调度设计。
6. 重试耗尽仍跳过邮件，不持久化处理记录；重复执行与并发运行缺少事务级去重，属于原工程限制。
7. 可选 API 保留原无认证、宽 CORS 和 0.0.0.0 监听行为，仅宜在受信本地环境使用；生产部署加固未实施。
8. 新索引改变了 embedding provider，因此检索结果不应声称与旧向量数值一致。原数据、chunking、Top-K 和处理流程保留以形成可比较 Baseline。
9. 新索引失败或来源/模型发生变化时不会自动删除/覆盖旧目录，应选择新的 VECTOR_DB_PATH。锁文件实际验证平台为 Windows/Python 3.11。

## Git Protection

- 原目录非 Git repository；首次业务修改前创建安全 .gitignore，再提交 `61d2214 baseline-before-m1`。
- .gitignore 排除 .env、credentials/token/client_secret 文件、secrets/、.venv、Python/test/lint cache、旧/新向量库、IDE 和本地 work 资源。
- 在干净 baseline 上创建 `m1-modernization`；未 reset、force checkout、改写历史或删除用户索引。
- M1 改动留待人工验收；最终 status/diff/log 原样列于交付报告。

## Deferred to M2

仅候选：Evaluation 设计、检索/回答质量评估数据与基准。未构建 evaluation dataset 或 benchmark。

## Deferred to M3

仅候选：RAG optimization（Hybrid/BM25、reranker、检索策略实验等）。全部未实施。

## Deferred to M4

仅候选：Risk-aware routing 和相应风险策略。未实施路由、人工升级或风险 agent。

## Official References

- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)：native JSON Schema 和类型化输出。
- [OpenAI GPT-5.6 guidance](https://developers.openai.com/api/docs/guides/latest-model?model=gpt-5.6)：保留明确指定的 gpt-5.6-luna，使用 Responses API；不代表账户可调用。
- [OpenAI text-embedding-3-small](https://developers.openai.com/api/docs/models/text-embedding-3-small)：配置默认 embedding model。
- [LangChain ChatOpenAI](https://docs.langchain.com/oss/python/integrations/chat/openai)：langchain-openai / with_structured_output。
- [LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)：StateGraph 和状态更新。
- [LangChain Chroma](https://docs.langchain.com/oss/python/integrations/vectorstores/chroma)：独立 Chroma integration。
- [Google Gmail Python quickstart](https://developers.google.com/workspace/gmail/api/quickstart/python)、[threads](https://developers.google.com/workspace/gmail/api/guides/threads)、[draft list](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.drafts/list)：OAuth、回复关联、分页。
- [uv Python installation](https://docs.astral.sh/uv/guides/install-python/)：隔离的 managed Python。
