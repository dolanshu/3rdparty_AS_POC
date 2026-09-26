# SIP Call Flows — E2E 测试计划

> 状态：已实现 · 更新日期：2026-09-23
> 对应文件：
> - `tests/e2e/test_call_flows.py`（5 tests）— Translation AS 完整 + 错误分支
> - `tests/e2e/test_fraud_call_flows.py`（2 tests）— Anti-Fraud AS 完整 + reject
> - `tests/e2e/test_chained_call_flows.py`（2 tests）— Chained topology（iFC 编排：AS-1 → S-SBC → S-CSCF → S-SBC → AS-2 → P-CSCF → UAS）
> 总计：**9 测试**

---

## 一、背景与动机

Console dashboard E2E 用的是 Playwright 起 4 个独立进程，覆盖浏览器视角。但项目还有另一层 E2E——**不经过浏览器**，直接驱动 SIP 信令流：

- 一个真实的 Translation AS / Anti-Fraud AS 实例
- 一个真实的 Mock S-SBC（sippy UAC 驱动）
- 在同一进程的 ED2 event dispatcher loop 上跑
- 每个测试打印 Call-ID keyed 的 trace ladder（Ladder diagram 风格），可直接作为 demo 证据

这层 E2E 是 `AGENT.md` Section 11 要求的"可独立演示的 call flows"——不需要起 4 进程，`pytest tests/e2e/test_call_flows.py -v` 就跑完。

---

## 二、测试架构

### 2.1 和 Console Dashboard E2E 的区别

| 项 | Console Dashboard E2E | SIP Call Flows E2E（这里） |
|---|---|---|
| 进程数 | **4 个独立进程**（console AS gen mock）| **1 个进程** |
| 驱动方式 | Playwright Chromium headless | pytest + conftest 里的 fixture + `TrunkPair.run_until()` |
| 端口 | 固定 5061/5060/8080/8765/8081 | **动态分配 ephemeral UDP**（`socket.bind(("127.0.0.1", 0))`）|
| 浏览器 | Chromium | 不涉及 |
| sippy ED2 loop | 每进程独立 loop | 进程级 singleton，fixture 驱动 `TrunkPair.run_until()` |
| 耗时 | ~130s（含进程启动）| ~10s |

### 2.2 Fixture 架构（`tests/conftest.py`）

三个核心 fixture，每个都在同一进程里 bind + drive sippy ED2 loop：

| Fixture | 返回 | 说明 | 覆盖测试文件 |
|---------|------|------|-------------|
| `trunk_pair` | `TrunkPair` | Translation AS + Mock S-SBC（rewrite next-hop ports 到 mock 的 core port）| `test_call_flows.py` |
| `fraud_trunk_pair` | `TrunkPair` | Anti-Fraud AS + Mock S-SBC | `test_fraud_call_flows.py` |
| `chained_pair_factory` | factory → `ChainedPair` | AS-1 (Anti-Fraud) + AS-2 (Translation) + `src/ims_mock` 的 S-CSCF/iFC 编排器 + P-CSCF relay + terminating UAS（**两个 AS 不直连**）| `test_chained_call_flows.py` |

`TrunkPair` 提供三个方法：
- `place_call(scenario)` → Call-ID（用 `CallScenario` 描述一个 SIP 场景）
- `outcome_for(call_id)` → `CallOutcome`（trunk 侧观察到的最终状态 + 收到的 response code）
- `run_until(predicate, timeout=10s)` → bool（驱动 ED2 loop 直到 predicate 成立或超时）

### 2.3 CallScenario（来自 `s_sbc_mock.uac`）

每个测试通过 `CallScenario(name=..., called=..., caller=..., behaviour=..., duration_ms=...)` 描述一个完整的 SIP 场景：

```python
scenario = CallScenario(
    name="complete-call",
    called="+8613800138000",  # 目标号码（会被 AS translate）
    caller="1001",             # 主叫
    behaviour="answer_and_bye", # "answer_and_bye" | "cancel_after_200ok" | "no_answer_608"
    duration_ms=3000,          # 200 OK 后多少毫秒 BYE
)
```

---

## 三、测试用例清单

### 3.1 test_call_flows.py — Translation AS（5 tests）

| # | 测试名 | 核心断言 | ACC / REQ |
|---|--------|----------|-----------|
| 1 | `test_complete_call_invite_to_bye` | INVITE→100→180→200 OK→ACK→BYE 完整走通；SDP pass-through；outcome=completed | ACC-P7-001 / REQ-F-001 |
| 2 | `test_caller_abandonment_sends_cancel` | caller 在 180 Ringing 后发 CANCEL；AS 转发 CANCEL 到 core；outcome=cancelled | ACC-P7-002 / REQ-F-002 |
| 3 | `test_request_uri_carries_the_translated_number` | core 收到的 INVITE Request-URI 是 translate 后的号码（如 `+8613800138000` → `013800138000`） | ACC-P7-003 / REQ-F-005 |
| 4 | `test_unmatched_number_is_answered_with_404` | 目标号码不在任何 routing rule 里 → AS 回 trunk 404（不转发）| ACC-P7-004 / REQ-F-006 |
| 5 | `test_blocked_number_is_answered_with_603` | 目标号码在 blocklist（`+86168xxx`）→ AS 回 trunk 603 | ACC-P7-005 / REQ-F-007 |

### 3.2 test_fraud_call_flows.py — Anti-Fraud AS（2 tests）

| # | 测试名 | 核心断言 | ACC / REQ |
|---|--------|----------|-----------|
| 1 | `test_an_allowed_call_runs_invite_to_bye` | caller 在 allow list 或不在 block list → AS relay → 完整走通 INVITE→BYE | ACC-P8-001 / REQ-F-016, REQ-F-021 |
| 2 | `test_a_rejected_call_ends_with_608_and_no_second_leg` | caller 在 block list → AS 回 trunk 608；**core 侧完全没收到 INVITE**（无 second leg）| ACC-P8-002 / REQ-F-017, REQ-F-019 |

### 3.3 test_chained_call_flows.py — Chained topology（2 tests）

| # | 测试名 | 核心断言 | ACC / REQ |
|---|--------|----------|-----------|
| 1 | `test_the_complete_chained_call_runs_invite_to_bye` | allowed caller → AS-1 allow relay → AS-2 translate → 被叫侧 answer BYE；**四条 AS-leg Call-ID 各不相同**（`X` / `X-b2b_1` / `Z` / `Z-b2b_1`，iFC #2 给 AS-2 一个新的 trunk Call-ID）| ACC-P9-001 / REQ-F-025 |
| 2 | `test_a_rejected_call_ends_with_608_at_as1_and_reaches_nothing_else` | blocked caller → AS-1 回 608；**AS-2 和 core 侧完全没消息**（短路）| ACC-P9-002 / REQ-F-027 |

### 3.4 Chain topology 附加验证（test_chained_call_flows.py 内）

虽然只有 2 个顶层 `def test_`，但每个都在内部验证了额外属性：

- **每实例独立 trace**：AS-1 在 trunk Call-ID 下写 trace，AS-2 在 outbound Call-ID 下写 trace，两个 trace 完全分离（ADR-0008 — 不能共用 process-wide trace recorder）
- **rule match 在 AS-2**：翻译完成的号码在 AS-2 的 routing catalogue 里匹配到 `R-MOB-CM-40`（demo 规则集）
- **translation 正确**：`+8613800138000` → `013800138000`（`+86` 前缀 strip + 加 `0`）

---

## 四、Trace Ladder（demo 输出）

每个测试调用 `render_trace(trace)` 打印一个多行 ladder，直接送到 stdout（capsys 捕获）。典型输出：

```
call-id 7a3f...@127.0.0.1
  2026-09-22T01:00:00.000  inbound  -        INVITE  Complete call
  2026-09-22T01:00:00.001  outbound primary   INVITE  Translated +8613800138000 → 013800138000
  2026-09-22T01:00:00.050  inbound  primary   100     Trying
  2026-09-22T01:00:00.100  inbound  primary   180     Ringing
  2026-09-22T01:00:00.200  inbound  primary   200     OK
  2026-09-22T01:00:00.201  outbound -        ACK     OK
  2026-09-22T01:00:03.200  inbound  primary   BYE     Call duration
  2026-09-22T01:00:03.201  outbound -        200     OK
```

两实例 chain 则输出两个 trace block（AS-1 的 Call-ID 和 AS-2 的 Call-ID 不同）。

---

## 五、关键技术细节

### 5.1 ED2 loop 是进程级 singleton

sippy 的 `ED2.loop()` 只能在主线程跑一次。fixture 的 `TrunkPair.run_until()` 用 `sippy.Time.Timeout.Timeout(poll, POLL_SECONDS=0.02, -1)` 把 poll 函数挂到 ED2 上，然后调 `ED2.loop(timeout=10)`。**绝对不能**让 pytest 的 asyncio 调度器和 ED2 loop 同时跑——ED2 是同步的。

### 5.2 端口 rewrite

demo `config/routing_rules.yaml` 里 next hop 端口是硬编码的（六个 hop 全是 `127.0.0.1:5061`），测试用 ephemeral 端口所以 fixture 在 `tmp_path` 里生成一份 rewrite 后的 rules file，把所有 `port:` 行替换成 mock 的 return（UAS）port。

### 5.3 AS-2 的 trace recorder 必须独立

两个 AS 实例都默认用 process-wide `TraceRecorder()` 和 `MetricsRegistry()`。**chain fixture 必须给每个 stack 传独立实例**，否则 AS-1 和 AS-2 的 trace 会混在一起（无法验证"每实例 Call-ID 独立"）。

### 5.4 不覆盖的东西

这 9 个测试**不**覆盖：
- Generator 驱动的并发负载（那是 `tests/integration/test_concurrent_load.py`）
- Console dashboard 的浏览器渲染（那是 `tests/e2e/test_console_dashboard.py`）
- 进程级启动/重启/self-check（那是 `tests/integration/test_startup_self_check.py`）

---

## 六、执行

```bash
# 全部 9 测试
python3 -m pytest tests/e2e/test_call_flows.py tests/e2e/test_fraud_call_flows.py tests/e2e/test_chained_call_flows.py -v

# 单文件
python3 -m pytest tests/e2e/test_call_flows.py -v
python3 -m pytest tests/e2e/test_fraud_call_flows.py -v
python3 -m pytest tests/e2e/test_chained_call_flows.py -v
```

预计耗时：**~10 秒**（ephemeral ports，无进程启动）。
