# Review — `docs/testing/e2e-playwright-plan.md`（P13 Dashboard Playwright E2E 测试计划）

> 审查日期：2026-09-23
> 被审对象：`docs/testing/e2e-playwright-plan.md`（状态标注为"已按 review-20260923 两轮修订"）
> 关联代码：`tests/e2e/test_console_dashboard.py`、`tests/e2e/conftest.py`、`tools/call_load_generator.py`、`src/console/main.py`
>
> **审查结论：Request changes —— 不建议按现状定稿。**
> 阻塞项 3 条、重要项 9 条、笔误/小项 5 条。其中 2 条属于"照此计划写出来的测试必然是红的"（B-1、B-2），必须先行修正。

---

## 1. 审查方法与依据

本 review 不评价"该不该有 Playwright E2E"（结论：应该有，且计划整体方向正确），而是把文档中的每一条**可验证陈述**对照下列权威来源核了一遍：

| 类别 | 依据 |
|---|---|
| 工程规范 | `AGENT.md` §3（gap register）、§4.2（必备文档集）、§4.4（console 标准）、§4.7（CI 分层）、§4.8（验收证据四类）、§11（三层测试 + 端口可配置）、§12（英文规范）、§13（变更文档链）、§16（DoD） |
| 需求/验收 | `docs/requirements/functional-and-nonfunctional.md` L56–64、`docs/acceptance/criteria.md` L117–139、`docs/acceptance/report.md` L3347–3459 |
| 设计 | `docs/architecture/hld.md` §11.4、`docs/architecture/adr/0013-*`（L15–118）、`docs/phase3-plan.md` §P13 Stage 4（L611–659）、§6 风险表（L702–710） |
| 配置/门禁 | `pyproject.toml`（L26–87）、`Makefile`（L41–66）、`.github/workflows/ci.yml`（L125–148） |
| 实现 | `src/console/main.py`（L218–521 JS + L525–598 app）、`tools/call_load_generator.py`（L83–112、L238–252、L699–796）、`tests/e2e/conftest.py`、`tests/unit/test_call_pool.py` L198–221 |

---

## 2. 阻塞项（Blocker）

### B-1 — §5.1「最高优先」给出的 binding-constraint 配方方向写反，照抄必红

**位置**：`e2e-playwright-plan.md` L300

计划建议：PUT `call_rate=1.0` → 断言 `binding_constraint == "concurrency"`；PUT `call_rate=3.0`（concurrency=20）→ 断言 `"rate"`。

**代码实际判定**（`tools/call_load_generator.py` L238–243）：

```python
def compute_binding_constraint(self) -> str:
    theoretical = self._config.call_rate * DurationModel.AVG_DURATION_SECONDS
    if theoretical >= self._config.target_concurrency:
        return "concurrency"
    return "rate"
```

即 **`call_rate` 越大越倾向于 `"concurrency"`**，与计划文字中的括号推导（"1.0 低于 concurrency/10.4"、"3.0 高于 concurrency/10.4≈1.9 → rate"）方向相反。现有单测已把语义钉死（`tests/unit/test_call_pool.py` L198–221）：`target=10, rate=10.0 → "concurrency"`；`target=50, rate=1.0 → "rate"`。

用计划第二组参数实算：`3.0 × 10.4 = 31.2 >= 20` → 返回 `"concurrency"`，断言 `"rate"` 必失败。第一组参数巧合正确（`1.0 × 10.4 = 10.4 >= 10`），但理由写反（1.0 > 0.96，且判据是 `>=` 而非 `<=`）。"巧合正确 + 理由错误"恰恰最危险 —— 下一个人调整参数时立刻爆掉。

**建议改写**（字段合法区间见 `_LoadConfigRequest` L699–701：`target_concurrency ∈ [1,50]`、`call_rate ∈ [0.1,10]`）：

| 目标 | PUT body | 判定依据 |
|---|---|---|
| `"rate"` 绑定 | `{target_concurrency: 10, call_rate: 0.1, enabled_call_types: [...]}` | `0.1 × 10.4 = 1.04 < 10` |
| `"concurrency"` 绑定 | `{target_concurrency: 10, call_rate: 2.0, enabled_call_types: [...]}` | `2.0 × 10.4 = 20.8 >= 10` |

另一个必须写进计划的坑：**`PUT /load/config` 的响应体不含 `binding_constraint`**（L776 只回 `{"status":"configured","config": <echo>}`），所以新测试必须 PUT 后再 `GET /load/status` 读取该字段，不能只断言 PUT 返回值。

### B-2 — P0-2 的依赖清单写错了包：只声明 `playwright` 拿不到 `page` fixture

**位置**：计划 L11（P0-2）、L51、L56

计划要求把 `playwright` / `requests` 写进 `pyproject.toml` 的 dev 组，并把验收口径定为「`make e2e` 收集 37 测试」。

事实核对：

- 测试签名是 `def test_x(self, page, demo_stack)`，**`page` fixture 由 `pytest-playwright` 提供，不是 `playwright`**。系统 Python 之所以能跑，是因为同时装了 `playwright 1.60.0` **和 `pytest-playwright 0.8.0`**；
- 项目 `.venv` 里两者都没有（`.venv/bin/python -m pip list | grep -i playwright` 为空），而 `make e2e`（`Makefile` L65）跑的是 `uv run pytest tests/e2e -m e2e`；
- 因此：即使补上 `pytestmark = pytest.mark.e2e`，`make e2e` 也**不会**"收集 37"，而是报 `fixture 'page' not found`。

**建议**：P0-2 的依赖行改为 `pytest-playwright`（提供 `page` fixture 与 `--browser`/`--headed`）+ `playwright`（driver 与 `playwright install chromium` CLI），并补一条安装浏览器二进制的步骤。§2.2 选型表的"测试框架：系统 Python `playwright 1.60.0`"应改为"pytest 风格 + `pytest-playwright 0.8.0`（`page` fixture）"。

> 附带事实：今天该文件之所以能被静默跳过而不报错，是因为它**从不 `import playwright`**，只依赖注入的 fixture。也就是说"缺 marker"和"缺依赖"是两个独立缺陷，修一个不够。

### B-3 — 完全没有考虑 CI；补 marker 会把已经绿的 e2e job 打红

**位置**：缺失章节（计划全文无 CI 段）

`.github/workflows/ci.yml` L125–142 的 e2e job 是：checkout → clone `../as_platform` → `uv sync --frozen` → `uv run pytest tests/e2e -m e2e -q`。

按计划 P0-2 修完之后该 job 必然失败，三条原因都未被提及：**(a)** `uv sync --frozen` 在 `uv.lock` 未更新时会直接拒绝；**(b)** runner 上没有 playwright/pytest-playwright；**(c)** runner 上没有 chromium（还需 `playwright install --with-deps chromium`）。这违反 `AGENT.md` §4.7「CI workflow running the gates in layers: lint, type check, unit, integration, e2e」。

**建议**：计划新增一节「CI 接入」，明确二选一并由 maintainer 拍板：

1. **正式接入**：dev 组加 `pytest-playwright` + `playwright` → 更新 `uv.lock` → e2e job 增加 `uv run playwright install --with-deps chromium` → 28 个浏览器测试并入 CI（建议 job 级重试或单列可选 job）；
2. **显式豁免**：浏览器 E2E 作为本地人工门禁，在 `Makefile` 中拆出 `make e2e-ui`，并在 `docs/production-gaps.md` 登记"浏览器 E2E 未进 CI"这一简化（`AGENT.md` §3：任何 POC 简化必须登记，不能静默忽略）。

无论选哪条，都要同步 `Makefile`、`pyproject.toml`、`README.md`、`docs/README.md`（`AGENT.md` §13 的 structural change 同提交更新要求）。

## 3. 重要项（Major）

### M-1 — `avg_duration` 的 9.5 / 10.4 分歧不能只改一处注释，需 maintainer 裁决

**位置**：计划 L13（R2-P0-1）、L102

计划发现 `tools/call_load_generator.py` L105 行尾注释 `# = 9.5` 与算式结果 10.4 不符，行动项是"注释 9.5 → 10.4"。**算术判断正确，但行动项不完整** —— 9.5 同时出现在四份可作准的设计/测试文档里：

| # | 位置 | 表述 |
|---|---|---|
| 1 | `tools/call_load_generator.py` L105 | 行尾注释 `# = 9.5` |
| 2 | `docs/architecture/adr/0013-*.md` L74–79 | 同一算式后写 `= 9.5 seconds  # not published, only used internally` |
| 3 | `docs/architecture/hld.md` §11.4 | 同一算式下写 `= 9.5 seconds`，并声明 "This is a **design constant**, not a runtime measurement (ADR-0013)" |
| 4 | `docs/testing/unit-plan.md` L291 | `test_duration_model_avg_duration_constant` 描述为 `AVG = 9.5s（加权平均）` |
| 5 | `tests/unit/test_call_pool.py` L200、L208 | 注释 `10.0 * 9.5 = 95 >= 10`、`1.0 * 9.5 = 9.5 < 50` |

即：这是 **ADR-0013 + HLD 共同确认的设计常量**，不是某处写错的行尾注释。改它等于改 Little's Law 演示的判定阈值（`rate × avg_duration >= target_concurrency`），按 `AGENT.md` §13 的文档链规则必须整链走一遍。

**建议**：把该项从"代码注释纠错"升级为 **escalate to maintainer**，列出两个候选方案：

- **方案 A（承认 10.4）**：同步修订 ADR-0013 L79、HLD §12.4、`unit-plan.md` L291、`test_call_pool.py` L200/L208 两处注释、代码注释，并在 `CHANGELOG.md` 记一条 `fix`/`docs`。
- **方案 B（保留 9.5）**：说明设计意图对应的 `MIDPOINTS` 取值，反推并修正 `DurationModel.MIDPOINTS`/`WEIGHTS` 让算式真等于 9.5 —— 这会改变通话时长分布，需重跑 P12 单测与 `ACC-P12-004`。

顺带必须同步：`tests/unit/test_call_pool.py` L72–75 的 `test_duration_model_avg_duration_constant` 是把同一算式重算一遍再比对，**属于恒真断言**，无论 `MIDPOINTS` 怎么改都过。修 9.5/10.4 时请改为断言字面量（方案 A 即 `assert AVG_DURATION_SECONDS == 10.4`），否则下一次漂移同样抓不住。

### M-2 — §三 的 REQ/ACC 映射列大面积错位，且 `REQ-F-051` 是凭空造的 ID

**位置**：计划 L138–195

这是本次最需要整体返工的一列。权威依据（`requirements` L56–64 与 `criteria.md` L131–139）：

| REQ | 含义 | ACC |
|---|---|---|
| REQ-F-012 | console 展示 live message flow / matched rule / configuration / statistics / SVG topology，rules 只读 | ACC-P13-008、ACC-M3-001 |
| REQ-F-042 | 两个 AS 的 per-call event stream + generator 的 `pool_status_update`（含 binding constraint） | ACC-P12-005 |
| REQ-F-044 | generator REST 控制面 + WebSocket feed | ACC-P12-007 |
| REQ-F-045 | **滚动 live call-count 折线图**（vendored Chart.js） | ACC-P13-001 |
| REQ-F-046 | **call-state 分布环形图** | ACC-P13-002 |
| REQ-F-047 | **容量仪表盘 gauge**（active/target） | ACC-P13-003 |
| REQ-F-048 | **动态 SVG 拓扑** | ACC-P13-004 |
| REQ-F-049 | **generator 控件**（slider、toggles、Start/Stop） | ACC-P13-005 |
| REQ-F-050 | **vendored Chart.js UMD**（`/static/`，无 CDN/npm/build） | ACC-P13-006 |

据此，**28 行里只有 9 行准确**（#5、#10、#14、#15、#16、#20、#23、#27、#28），**19 行需更正**。典型例子：

- `#1` 断言 `typeof Chart === "function"` —— 这是 **REQ-F-050 / ACC-P13-006**（vendored bundle 能从 `/static/` 加载并跑起来）的证据，而非 REQ-F-045 折线图；
- `#2` 导航按钮存在 —— 属 **REQ-F-012 / ACC-P13-008**，计划标的 REQ-F-045 无关；
- `#7` Rules 视图有内容 —— 计划标 REQ-F-050（Chart.js vendoring），正确应为 REQ-F-012 / ACC-P13-008；
- `#8` Screening 视图 —— 计划标 **`REQ-F-051`**；全仓库检索该 ID 只命中本计划这一份文件，**这是不存在的标识符**（`AGENT.md` §14.1「Never guess」与 §4.2 的可追溯性要求都不允许引入未注册 ID）；
- `#18` 折线图积累点 —— 计划 `REQ-F-046 / ACC-P13-003`（那是饼图和 gauge），应为 REQ-F-045 / ACC-P13-001；
- `#25` `GET /api/v1/rules` —— 计划 REQ-F-050，错；
- `#26` `GET /api/v1/traces` —— 计划 REQ-F-047，应为 REQ-F-042 / ACC-P12-005。

修正后的完整映射见本文 §6。另请注意：上述 ACC 项在 `criteria.md` 里登记的**验证命令都是集成测试**（`tests/integration/test_console.py`），所以本 E2E 在文档链上的正确定位是"**附加证据**"，而非替换那些验证命令 —— 计划目前的表述容易让人误以为浏览器 E2E 就是这些 ACC 的验证手段。

### M-3 — B3 的根因没被真正"钉"住：缺 DOM 唯一性断言，WS 重连/降级路径零覆盖

计划的动机章（§一）说得很清楚：三个致命 bug 里有两个是"console 读了一个不存在的字段"和"同一份视图 DOM 有两份拷贝"。验收判据应当是：

> 同样的 bug 再次发生时，这 28 个测试能不能变红？

按此判据有两处没守住：

1. **DOM 唯一性**：每个 `#vw-*` 容器必须全局唯一。当前测试都用 `page.locator("#vw-rules").evaluate(...)`，而 `locator.evaluate` **只作用于首个匹配元素** —— 若明天 `.vw` 又被复制一份（正是 B3 的历史根因），28 个测试照样全绿。
   **建议补断言**：`assert page.locator("#vw-rules").count() == 1`（可参数化到 5 个视图，约 6 行），这是唯一能防止 B3 复发的测试。

2. **故障路径零覆盖**：console JS 实现了两条优雅降级，28 个测试一条都没碰：
   - WS 断线重连：`ewsEv()` / `ewsLd()`（`src/console/main.py` L423、L445），3s 后重连并把 `#wsEv`/`#wsLd` 文本切成 `"offline"`；
   - AS 不可达：`fh()` 的 catch 分支把 `#aSt` 置为 `"unreachable"`、`#aDot` 加 `er` class（L452）。
   **建议**：用 `page.context().set_offline(True/False)` 做一条纯前端重连测试（`#wsEv`：`live` → `offline` → `live`），零额外进程成本，覆盖"演示进行中抖一下网会不会白屏"这个真实评审场景。AS 宕机降级可作可选项单列。

### M-4 — #17 污染后续测试的全局状态，且 `requests` 完全没必要引入

**位置**：计划 L166、`test_console_dashboard.py` L306–319

- `#17` 用 `PUT /load/config` 把 generator 改成 `{target_concurrency:10, call_rate:3.0, enabled_call_types:[T1,T2,T3,T5,T6,F1..F4]}`（**永久禁掉 T4**），且**从不恢复**。由于 `demo_stack` 是 session scope，之后的 `TestDashboardLive`（5 个）与 `TestConcurrent`（2 个）都继承这份被篡改的配置 —— 名义上跑的是 phase3 Stage 4 的完整 journey，实际是 T4 被阉割过的场景。
- `try: import requests; requests.put(...) except Exception: pass`（L307–319）把**所有**失败吞掉：依赖缺失、连接失败、400/422 都表现为"静默继续"，因此这条测试通过或失败的原因都不可信。
- `requests` 本身多余：同文件 `_gen_status` / `_as_get` 已用标准库 `urllib.request`，PUT 也能用 `urlrequest.urlopen(..., method="PUT", data=...)` 完成。去掉它可以**直接消掉 P0-2 里"声明 requests 依赖"这一整项争议**。

**建议**：把配置写入抽成带恢复语义的 fixture，helper 必须校验状态码而不是吞异常：

```python
@pytest.fixture
def gen_config(demo_stack):
    """Apply a generator config for one test, restore the original afterwards."""
    original = _gen_status(demo_stack["gen"])
    yield lambda **body: _put_config(demo_stack["gen"], body, expect_status=200)
    _put_config(demo_stack["gen"], {
        "target_concurrency": original["target_concurrency"],
        "call_rate": original["call_rate"],
        "enabled_call_types": original["enabled_call_types"],
    })
```

（`_put_config` 也是 B-1 里新测试要用的同一个 helper。）

### M-5 — `_reset_gen` 吞掉一切异常 + 确证存在两份实现

计划已在 §2.3、§六 B2 提到 `.get("running", True)` 掩盖缺字段的问题，但还有一个更宽的坑没提：`test_console_dashboard.py` L25–38 的 `_reset_gen` 把 `urlopen` 异常整体 `except Exception: pass`。后果是 **generator 进程已经死了** 与 **generator 只是慢** 在这段代码里完全同形 —— 10s 后静默返回，接着 `page.goto` 依然成功（console 是另一个进程），最终失败点落在 `#gaugeVal` 或某个 `running` 断言上，报出来的信息会把排查方向带偏。

**建议**：

1. 区分"前置条件不可达"与"轮询超时"：前者应直接 `pytest.fail("generator REST unreachable at {url}")`，而不是继续跑；
2. 把 session fixture 的健康检查升级为**持续可用**（现有 `_wait_http` 只在上电时查一次）；
3. 两份 `_reset_gen` 的处理：全仓检索已确认 `conftest.py` L79 的副本**从未被调用**（唯一命中是其自身定义），确证为死代码。建议**直接删除 conftest 版本**，把测试文件里那份（更强：同时等 `running=false` 且 `active_calls==0`）上移到 conftest 共用。计划里"两份对齐或删 conftest 版本"的犹豫可以去掉。

### M-6 — §2.5 的耗时估算（~130s）与 `timeout 360` 都不成立

按实际 sleep / deadline 逐条累加（每测试固定开销 = `_reset_gen` + `goto` + `networkidle` + `wait_for_timeout(2000)` + 两次 WS 等待 ≈ 3–5s；若上一个测试留下了 running 的 generator，`_reset_gen` 还要额外几秒）：

| 类 | 固定 sleep 上限 | 常规（估） | 最坏（估） |
|---|---|---|---|
| T1 PageLoad（5） | 3s | ~18s | ~56s |
| T2 Navigation（8） | ~7s | ~45s | ~120s |
| T3 GeneratorLifecycle（4） | 20+20+15+10s 轮询预算 | ~45s | ~110s |
| T4 DashboardLive（5） | 6+8+20+8+8 = 50s | ~50s | ~116s |
| T5 AsRest（4） | 0 | ~1s | ~2s |
| T6 Concurrent（2） | ~10s | ~25s | ~30s |
| 4 进程启动 | — | ~15s | ~20s |
| **合计** | | **~200s** | **~450s** |

即：常规路径约 **200s**（不是 130s），所有 deadline 同时走满时 **~450s > `timeout 360`** —— 那条命令在最坏情况下会把绿线裁成红。

**建议**：估算改为「常规 ~200s / 最坏 ~450s」，`timeout 360` 提到 `timeout 900`，并点名可削减的纯等待块（T4 五个测试的 `wait_for_timeout(6000/8000)` 合计 30s，是全套件最大一块）。

### M-7 — 命名漂移只对照了 phase3-plan，漏了 normative 的验收文档

计划 §4.2 的"命名漂移"注只说 `phase3-plan.md` 写 `/ws/events`、`/ws/load`。但 **`docs/acceptance/criteria.md` ACC-P12-007**（验收基线）也写着 `Also WebSocket feed for pool_status_update events on /ws/load`，而实际实现是 `/ws/pool`（`tools/call_load_generator.py` L778、`src/console/main.py` L224）。

按 `AGENT.md` §4.2，`criteria.md` 是**正式验收列表**，比 phase3-plan 更权威。计划目前的写法（"本文档才是实际端点名"）等于在文档里把漂移固化下来。

**建议**：扩展成明确待办 —— 要么修 `criteria.md` ACC-P12-007 的端点名（同步 `report.md` 与 `CHANGELOG`），要么按 `AGENT.md` §3 在 gap register / 该 ACC 行内标注"文档与实际端点不一致，已确认实现为准"。不要让 reviewer 猜哪份是真值。

### M-8 — 端口硬编码、`kill -9`、Chromium 依赖都还没进 gap register

计划 §2.2 的"已知缺口"写得很好（我逐条核实属实，见 §7），但它们只是**本文档内部的批注**。按 `AGENT.md` §3 与 §14.7「Log the gaps」，下列三条必须在 `docs/production-gaps.md` 里成为正式行：

| Area | POC behaviour | Production requirement |
|---|---|---|
| Test ports | E2E 栈硬编码 5061/5060/8080/8765/8081 | 端口可配置（`AGENT.md` §11），CI 并行不冲突 |
| Test isolation | 启动前 `lsof -ti :PORT` 后 `kill -9`，不区分进程归属 | 只清理自己拉起的进程；不得误杀开发机上的服务 |
| Browser E2E | 依赖系统 Python 的 playwright/chromium，不入 CI | 依赖走 `uv` 提交 `uv.lock`，CI 可复现（`AGENT.md` §4.7） |

每行 "why it differs" 里交叉引用本计划，评审者从 register 一步就能到测试计划（呼应 `AGENT.md` §4.3 的 design traceability）。

### M-9 — 没有 evidence 落地路径（`AGENT.md` §4.8）

`docs/acceptance/report.md` L3347–3459 里 ACC-P13-001…009 的证据全部是集成测试输出。浏览器 E2E 跑完之后：

- 结果写在哪？（计划没说 —— 建议明确规定把这 28 条的运行输出追加到 `report.md` 对应 ACC 行作为附加证据）
- 失败时留什么？（建议失败截图 + `page.on("console")` 日志落到 `artifacts/`，正好接上 CI 里已存在的 `e2e-trace` artifact job，`ci.yml` L143–148）
- 现在的 E2E **不产出任何 Call-ID 可索引的产物**，与 `AGENT.md` §11 对 E2E 层「Output a human-readable, Call-ID keyed trace usable as demo evidence」的期待不符。建议至少让 `TestDashboardLive` 把 `#tlist .ti` 里前若干条 Call-ID dump 进 artifacts。

## 4. 笔误与小项

| # | 位置 | 问题 | 建议 |
|---|---|---|---|
| N-1 | §2.1 L41 | Console `GET /healthz` 描述为 `{"status":"ok"}`，实际返回还含 `component`/`as_api_url`/`load_api_url`/`started_at`（`src/console/main.py` L549–555） | 补全返回体，或对健康检查做字段断言（现在只探活不断字段） |
| N-2 | `conftest.py` L109 | `tempfile.mkdtemp(prefix="e2e-rules-")` 每次会话泄漏一个临时目录，从不清理 | 改用 `tempfile.TemporaryDirectory()` context manager |
| N-3 | `conftest.py` L134 | 只有 AS 的 stdout 落到 `/tmp/e2e-as.log`，另外 3 个进程继承 pytest stdout；排障时信息不对称 | 4 个进程统一落到 per-session tmpdir，失败时 attach |
| N-4 | 全文 | 本计划（及其余 3 份 `docs/testing/*-plan.md`）为中文，而 `AGENT.md` §12 要求 "English everywhere: ... **docs**, commit messages" | 这是**仓库级**既有冲突，不是本文件单独的缺陷。建议作为独立议题提给 maintainer（改规范，或把四份测试计划英文化），不要由本 review 单方面定调 |
| N-5 | 全文 | `docs/testing/` 下 4 份计划均未被 `README.md` 或 `docs/README.md` 索引 | 按 `AGENT.md` §4.2 中 `docs/README.md` 的 "documentation navigation by audience" 要求把 testing 目录加入导航；未索引的文档对 reviewer 等于不存在 |

---

## 5. 建议并入计划头部追踪表的行动项

| 项 | 位置 | 内容 | 优先级 | 验收口径 |
|---|---|---|---|---|
| R3-P0-1 | §5.1 L300 | 修正 binding-constraint 配方为 `rate → {10, 0.1}` / `concurrency → {10, 2.0}`，并注明 PUT 响应不含该字段、须再 GET | Blocker | 新测试在 `test_call_pool.py` L198–221 的语义下稳定变绿 |
| R3-P0-2 | P0-2 / §2.2 | 依赖声明改为 `pytest-playwright` + `playwright`（去掉 `requests`，改用 stdlib `urllib` 做 PUT） | Blocker | 裸环境（无系统 playwright）下 `uv run pytest tests/e2e/test_console_dashboard.py -v` 可运行 |
| R3-P0-3 | 新增 §CI | 明确浏览器 E2E 是否进 CI；进则补 `uv.lock` + `playwright install --with-deps chromium`，否则在 `Makefile` 拆出 `make e2e-ui` 并在 gap register 登记 | Blocker | `ci.yml` e2e job 保持绿，且行为与本文档一致 |
| R3-P1-1 | §三 全表 | 按本文 §6 重写 REQ/ACC 映射列；删除不存在的 `REQ-F-051`；声明本套件是"附加证据"而非替换 `criteria.md` 的验证命令 | Major | 28 行映射可与 requirements / criteria 双向 grep 对应 |
| R3-P1-2 | 新增 | 补视图 DOM 唯一性断言 `#vw-{view}` count == 1，以及 WS 离线重连测试 | Major | 人为引入第二份 `#vw-rules` 时测试变红 |
| R3-P1-3 | #17 | `gen_config` fixture：写入前记录原配置、teardown 恢复；`_put_config` 校验状态码 | Major | 任意顺序运行（含 `-k` 单跑）结果一致 |
| R3-P1-4 | L13 / M-1 | `avg_duration` 9.5 vs 10.4 升级为 maintainer 裁决项；同步 ADR-0013、HLD §12.4、`unit-plan.md`、2 处单测注释 | Major | 五处取值一致；`test_duration_model_avg_duration_constant` 改为断言字面量 |
| R3-P2-1 | §2.5 | 耗时估算改为「常规 ~200s / 最坏 ~450s」，`timeout 360` → `timeout 900` | Major | 冷跑三次均在 timeout 内完成 |
| R3-P2-2 | §4.2 | 命名漂移补充 `criteria.md` ACC-P12-007 的 `/ws/load` | Major | 或修 `criteria.md`，或在 gap register 登记 |
| R3-P2-3 | M-8 | 在 `docs/production-gaps.md` 登记端口硬编码 / `kill -9` / 浏览器依赖三条 | Major | register 三行可追溯到本计划 |
| R3-P2-4 | M-9 | 规定 E2E 结果写入 `report.md` 的路径 + 失败产出 `artifacts/`（截图、console 日志、Call-ID dump） | Major | `ci.yml` 的 `e2e-trace` artifact 能拿到有效内容 |
| R3-P2-5 | §2.3 / M-5 | `_reset_gen` 失败快速暴露（区分不可达与超时）；删除 conftest 死副本 | Major | 手动 kill generator 时得到明确错误信息，而不是 20s 后一句 gauge 断言失败 |
| R3-P3-1 | N-2/N-3 | 临时目录与日志改用 `TemporaryDirectory`，4 进程日志统一落盘 | Minor | 会话结束后无 `/tmp` 残留 |
| R3-P3-2 | N-4/N-5 | 提给 maintainer：文档语言政策 + `docs/testing/` 加入导航 | Minor | `AGENT.md` 与 `docs/README.md` 一致 |

> 原头部 6 项的处理：P0-3（`import pytest` 缺失）**属实且应立即动手**；P0-2 需按 R3-P0-2 改写；R2-P0-1 需按 R3-P1-4 升级为裁决项；R2-P1-1 并入 R3-P0-1；R2-P2-3、R2-P2-4 保留并按 §7 第 3 条的核实结论直接执行。

---

## 6. 修正后的 REQ / ACC 映射表

依据：`docs/requirements/functional-and-nonfunctional.md` L26（REQ-F-012）、L56–64；`docs/acceptance/criteria.md` L131–139。标 "—" 表示仓库中没有对应条目，不应硬凑 ID。

| # | 测试 | REQ | ACC |
|---|---|---|---|
| 1 | `test_page_loads_without_js_errors` | REQ-F-050 | ACC-P13-006 |
| 2 | `test_all_nav_buttons_present` | REQ-F-012 | ACC-P13-008 |
| 3 | `test_status_bar_renders` | —（`AGENT.md` §4.4 console standard） | — |
| 4 | `test_both_websockets_connect` | REQ-F-042 + REQ-F-044 | ACC-P12-005 + ACC-P12-007 |
| 5 | `test_initial_dashboard_controls_state` | REQ-F-049 | ACC-P13-005 ✔ |
| 6 | `test_call_trace_view_renders` | REQ-F-012 | ACC-P13-008 |
| 7 | `test_rules_view_renders_and_has_content` | REQ-F-012 | ACC-P13-008 |
| 8 | `test_screening_view_renders` | REQ-F-012 | ACC-P13-008 |
| 9 | `test_statistics_view_renders` | REQ-F-012 | ACC-P13-008 |
| 10 | `test_about_view_renders` | REQ-F-012 | ACC-P13-008 |
| 11 | `test_nav_stays_visible_after_each_view` | REQ-F-012 | ACC-P13-008 |
| 12 | `test_round_trip_rules_to_dashboard` | REQ-F-012 | ACC-P13-008 |
| 13 | `test_all_views_then_back_to_dashboard` | REQ-F-012 | ACC-P13-008 |
| 14 | `test_start_button_hits_rest_endpoint` | REQ-F-049 | ACC-P13-005 ✔ |
| 15 | `test_active_calls_rise_after_start` | REQ-F-049 | ACC-P13-005 ✔ |
| 16 | `test_stop_button_drains_active_to_zero` | REQ-F-049 | ACC-P13-005 ✔ |
| 17 | `test_console_gauge_rises_then_falls_with_generator` | REQ-F-047 + REQ-F-049 | ACC-P13-003 + ACC-P13-005 |
| 18 | `test_line_chart_accumulates_points` | REQ-F-045 | ACC-P13-001 |
| 19 | `test_pie_chart_has_nonzero_segments` | REQ-F-046 | ACC-P13-002 |
| 20 | `test_topology_svg_links_change_on_active` | REQ-F-048 | ACC-P13-004 ✔ |
| 21 | `test_trace_panel_accumulates_call_records` | REQ-F-042 | ACC-P12-005 |
| 22 | `test_trace_filter_narrows_list` | REQ-F-042 | ACC-P12-005 |
| 23 | `test_healthz` | —（基础设施） | — ✔ |
| 24 | `test_metrics` | —（基础设施） | — |
| 25 | `test_rules` | —（Rules 视图数据源，同 #7） | — |
| 26 | `test_traces_list_has_calls_key` | REQ-F-042 | ACC-P12-005 |
| 27 | `test_generator_runs_survives_navigation` | REQ-F-049 | ACC-P13-005 ✔ |
| 28 | `test_stop_after_view_hops_resets` | REQ-F-049 | ACC-P13-005 ✔ |

（✔ = 原表已正确）

---

## 7. 已核实为真的陈述（无需修改）

为避免 reviewer 重复劳动，以下条目我逐一验证过：

1. **测试数量 28 / 6 类**：T1=5、T2=8、T3=4、T4=5、T5=4、T6=2 → 28，与实际文件一致；`make e2e` 现状只收 9 个（5+2+2），另外 3 个文件都有 `pytestmark`，唯独本文件没有。**属实。**
2. **P0-3 `import pytest` 缺失**：文件顶部只有 `json` / `time` / `urllib.request`，而 L436 使用 `pytest.skip` → 走 `total_before == 0` 分支会抛 `NameError`（不是 skip）。**属实，且是最应当马上动手的一行。**
3. **conftest `_reset_gen` 为死代码**：全仓检索仅命中其自身定义。**属实**（建议直接删，见 M-5）。
4. **`/tmp/e2e-as.log` 句柄不关闭**：`conftest.py` L134。**属实。**
5. **行号引用全部核对通过**：`pyproject.toml` L81（`--strict-markers`）、`Makefile` L65、`conftest.py` L26/L79/L134/L177–189、`test_console_dashboard.py` L22–38/L76–84/L308、`tools/call_load_generator.py` L105/L240/L252/L729–737、`snapshot()` L245–255 含 `"running"`（印证 §六 B2 的真实路径判断）。
6. **§一 三个历史 bug 的根因与代码现状吻合**：`onPoolStatus` 的 `s = d.attributes || d`（`src/console/main.py` L360）；WS 推送确为 `{"attributes": {...}}` 包裹（`call_load_generator.py` L785–790）；`sv()` 对 `#vw-dashboard` 的 `style.display` 开关（L470–473）。
7. **§4.3 topology `intensity` 公式逐字符一致**（`src/console/main.py` L340–342），含 `instantActive = Math.max(activeCalls, counters.active)` 与 `Math.min(8, 1 + instantActive*0.6 + Math.min(3, totalTraffic*0.03))`。
8. **§3.4 #18 阈值推导的前提成立**：折线图确由 `setInterval(..., 500)` 每 500ms 推点（`src/console/main.py` L519–520），6s ≈ 12 点是合理上界；`ROLL_WINDOW = 60`（L233）在 6s 内不会触发裁剪。
9. **§六 B2 的判断成立**：`snapshot()`（真实路径）有 `"running"`（L248），库模式 `_default_getter()`（L729–737）**没有** `running` 字段 —— "未完全修复"的结论正确，补 `"running": False` 的建议也合理。
10. **`phase3-plan.md` 引用准确**：Stage 4 E2E 原文确为 `(5) slide to 5, (6) verify chart drops`（L625–627），§6 风险表第 4 行确为 "Console control panel slider doesn't actually change pool size" / Impact **High**（L709）。
11. **`--strict-markers` 静默跳过机制属实**：本文件不 `import playwright`，缺 marker 时是被 deselect（无报错）而非收集失败 —— 这正是它长期没被发现的原因。

---

## 8. reviewer 建议的处理顺序

1. 先落 **P0-3**（一行 `import pytest`）+ **M-4**（去掉 `requests`、加 `gen_config` 恢复语义）—— 都在同一个测试文件里，一次改完；
2. 再落 **R3-P0-1 / R3-P0-2 / R3-P0-3**（B-1、B-2、B-3）—— 这三项决定本计划在 CI 里能不能活；
3. 把 **M-1（9.5 / 10.4）提给 maintainer** 裁决 —— 不在本文作者权限内，但必须先有结论才能改 ADR 与 HLD；
4. 最后做 **M-2 映射表重写 + M-3 补测试 + M-8 gap 登记**，完成即可申请重审。


