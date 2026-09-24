# Integration 测试计划

> 状态：已实现 · 更新日期：2026-09-24
> 对应目录：`tests/integration/`（10 个文件，48 tests）
> 标签：`pytest.mark.integration`

---

## 一、定位

Integration 层测试**两个或多个真实模块**的交互，但**不**起独立进程、**不**用浏览器。测试和被测 AS 在同一 Python 进程里跑，fixture bind sockets + drive sippy ED2 loop。

| 层 | 进程 | 浏览器 | 测试数量 | 典型耗时 |
|---|---|---|---|---|
| unit | 无 | 无 | 182 | ~20s |
| **integration** | **1（测试进程内 bind）** | **无** | **48** | **~30s** |
| e2e (call flows) | 1 | 无 | 9 | ~10s |
| e2e (dashboard) | 4 独立进程 | Chromium headless | 28 | ~130s |

---

## 二、Fixtures（继承自 `tests/conftest.py`）

| Fixture | 覆盖测试 | Scope | 说明 |
|---------|----------|-------|------|
| `trunk_pair` | test_translation, test_signalling_path, test_console, test_concurrent_load | per-test | Translation AS + Mock S-SBC on ephemeral UDP |
| `fraud_trunk_pair` | test_fraud_screening_path, test_concurrent_load | per-test | Anti-Fraud AS + Mock S-SBC |
| `fraud_pair_factory` | test_fraud_screening_path | per-test | 工厂，每 test 可 build + stop 多个 pair |
| `chained_pair_factory` | test_chained_topology, test_concurrent_load | per-test | 工厂，build AS-1 + AS-2 + `ims_mock` iFC 编排器 + P-CSCF/UAS 的 chain（AS 之间不直连）|
| `free_udp_port` | test_startup_self_check | per-test | 一个不被占用的 UDP 端口 |
| `screening_file` | 多个 | per-test | `shipped_screening_file` 的可编辑副本 |
| `rule_set` | test_translation | per-test | 加载好的 `RuleSet` 对象（`config/routing_rules.yaml`）|

---

## 三、测试用例清单（48 个 / 10 文件）

### 3.1 test_translation.py（7 tests）—— Routing + Hot Reload + Error 分支

| # | 测试名 | 核心断言 |
|---|--------|----------|
| 1 | `test_next_hop_failover_uses_the_second_hop` | 主 hop 不响应 → AS 自动 failover 到 second hop → S-SBC return 侧收到 INVITE（rewrite 后的端口全绑同一个 mock return UAS，主 hop 手动 bind 到一个无 socket 的端口）|
| 2 | `test_hot_reload_activates_a_new_rule_set_without_restart` | 修改 rules 文件 → AS reload → 新规则生效（called number 被新规则 translate）|
| 3 | `test_hot_reload_keeps_previous_rule_set_on_broken_edit` | reload 后规则文件变成无效 YAML → AS 保持旧规则集 |
| 4 | `test_route_decision_with_no_next_hop_yields_480` | 规则匹配到但 next_hop 列表空 → trunk 收 480 |
| 5 | `test_translation_to_empty_yields_500` | rule 的 translate `to_format=""` → AS 内部 500 条件 |
| 6 | `test_translation_to_empty_is_answered_500_on_the_trunk` | 同上，trunk 侧收到 500 |
| 7 | `test_unresolvable_hop_is_answered_480_on_the_trunk` | next_hop 地址不可达 → trunk 收 480 |

### 3.2 test_signalling_path.py（4 tests）—— SIP Message Pass-Through + Counters

| # | 测试名 | 核心断言 |
|---|--------|----------|
| 1 | `test_headers_and_sdp_pass_through` | INVITE 的 X-Call-Id / User-Agent / Content-Type / SDP body → outbound INVITE 原样携带 |
| 2 | `test_request_from_an_unlisted_source_is_rejected` | `allowed_peers=["127.0.0.2"]` → 来自 127.0.0.1 的 trunk INVITE 被 403 |
| 3 | `test_counters_health_endpoint_and_graceful_shutdown` | Start → 打 3 calls → `GET /healthz` counters 反映这些 call；stop 后 counters 仍保留（持久化）|
| 4 | `test_stopping_the_stack_leaves_no_transaction_timer_armed` | Stop stack → 所有 sippy `Timeout` 已 cancel（用 `Timeout._arm_counter` 断言）|

### 3.3 test_console.py（7 tests）—— Console 静态页面 + AS Internal API

| # | 测试名 | 核心断言 |
|---|--------|----------|
| 1 | `test_console_page_has_only_vendored_static_scripts` | HTML 模板里的 `<script>` src 只有 Chart.js（无第三方加载器）|
| 2 | `test_console_page_has_chartjs_canvases` | `#lineChart`, `#pieChart`, `#gaugeChart`, `#topologyChart` 全部存在 |
| 3 | `test_console_page_contains_operations_ui_elements` | nav buttons / gauges / trace panel / ws status dots |
| 4 | `test_console_page_injects_as_api_url` | HTML 里 `LD_URL` 和 `AS_URL` 被替换成实际值（不是 `__LOAD_API_URL__` 占位符）|
| 5 | `test_console_page_carries_the_screening_and_instance_surfaces` | `.vw-rules`, `.vw-screening`, `.vw-statistics`, `.vw-about`, `.vw-call-trace` 全部存在 |
| 6 | `test_internal_api_serves_health_metrics_rules_and_traces` | `GET /healthz`, `GET /api/v1/metrics`, `GET /api/v1/rules`, `GET /api/v1/traces` 全部返回可序列化 JSON |
| 7 | `test_console_runs_as_separate_process_with_no_external_refs` | console 的 FastAPI app 独立于 AS（不是 import 进来的模块）|

### 3.4 test_concurrent_load.py（7 tests）—— 并发负载 + P12 Events Fanout

| # | 测试名 | 核心断言 |
|---|--------|----------|
| 1 | `test_ten_concurrent_calls_through_translation_as` | 10 calls 并行 → 全部 completed；无 deadlock |
| 2 | `test_ten_concurrent_calls_get_distinct_outbound_call_ids` | 每 call 的 outbound Call-ID 都不同（`outbound_call_id(trunk_call_id)` 生成）|
| 3 | `test_ten_concurrent_calls_emit_p12_events_via_fanout` | internal API fanout **结构**就绪（``broadcast`` / ``publisher`` / ``_loop``）；**不**断言 payload Call-ID（见 §3.8）|
| 4 | `test_ten_concurrent_calls_through_anti_fraud_as` | AS-1 版并发，全部 completed 或被正确 reject |
| 5 | `test_ten_concurrent_calls_through_chained_topology` | iFC 编排的 AS-1 / AS-2 chain 版并发（两次独立 trunk INVITE）|
| 6 | `test_ten_concurrent_calls_in_chained_topology_do_not_cross_contaminate` | AS-1 的 counters 和 AS-2 的 counters 不互相污染 |
| 7 | `test_ten_concurrent_failover_calls_each_try_primary_then_land_on_secondary` | 主 hop 不可达 → 每 call 都 failover 到 secondary |

### 3.5 test_fraud_screening_path.py（13 tests）—— Screening + Window + Reputation

| # | 测试名 | 核心断言 |
|---|--------|----------|
| 1 | `test_a_block_listed_caller_is_answered_608_and_never_reaches_the_core` | caller 在 block list → 608；core 侧无 INVITE |
| 2 | `test_a_caller_that_never_declared_sip_608_is_still_answered_608` | caller 不在 allow **和** 不在 block → 默认 reject 608 |
| 3 | `test_a_reject_from_the_allow_list_is_not_rejected` | caller 在 allow list → relay 到下 hop |
| 4 | `test_an_allowed_call_is_relayed_with_no_added_header` | allowed call 的 INVITE → AS 不插入 screening header |
| 5 | `test_an_invite_without_a_calling_identity_is_allowed` | 无 P-Asserted-Identity header → fail-open relay |
| 6 | `test_a_request_from_an_unlisted_source_is_rejected` | `allowed_peers` 只配了 127.0.0.2，来自 127.0.0.1 的 INVITE → 403 |
| 7 | `test_the_window_and_then_reputation_reject_through_the_real_controller` | 同一 caller 在 60s 内打满 window_threshold → 被 reject；reputation 分数累积 → 超过 reputation_threshold 时也 reject |
| 8 | `test_a_reloaded_file_activates_a_new_block_entry` | reload screening file → 新加的 block entry 生效 |
| 9 | `test_a_reload_reapplies_the_window_and_reputation_parameters` | reload 后 window_threshold / reputation_threshold 变更生效 |
| 10 | `test_a_broken_edit_keeps_the_previous_screening_data` | reload 成无效 YAML → AS 保持旧 screening |
| 11 | `test_stopping_the_process_leaves_no_timer_armed` | stop → 所有 sippy Timeout cancel |
| 12 | `test_the_process_serves_health_and_exits_zero_on_sigterm` | Anti-Fraud AS 的 healthz 端点 + SIGTERM 正确处理 |
| 13 | `test_the_running_process_reloads_the_screening_file_on_its_own_timer` | 文件 watcher timer 触发 reload（10s 周期）|

### 3.6 test_chained_topology.py（3 tests）—— iFC 编排的 AS-1 / AS-2 Chain 验证

| # | 测试名 | 核心断言 |
|---|--------|----------|
| 1 | `test_an_allowed_call_traverses_both_b2bus_and_is_translated` | allowed caller → iFC#1 → AS-1 relay（回到 S-SBC return）→ iFC#2 → AS-2 translate → S-SBC return → P-CSCF → terminating UAS → complete |
| 2 | `test_every_leg_regenerates_its_call_id_and_each_instance_keys_its_trace` | 四条 AS-leg Call-ID 各自重新生成（`X` / `X-b2b_1` / `Z` / `Z-b2b_1`）；AS-1 用它 trunk 上的 Call-ID 记 trace，AS-2 用它 iFC #2 trunk 上的 Call-ID 记 trace；两个 trace 分离 |
| 3 | `test_a_reject_at_as1_short_circuits_before_as2_and_the_core` | blocked caller → AS-1 608；AS-2 和 core 都无消息 |

### 3.7 test_startup_self_check.py（3 tests）—— Process-level Boot / Config Validation

| # | 测试名 | 核心断言 |
|---|--------|----------|
| 1 | `test_self_check_binds_and_releases_the_signalling_port` | settings self_check → bind + 立即 release → 下次 bind 正常 |
| 2 | `test_self_check_accepts_a_reloaded_rule_set` | self_check 加载后的 rule_set 可以 reload 而不崩 |
| 3 | `test_sippy_is_installed_at_the_pinned_version` | sippy 版本和 `pyproject.toml` 里 pin 的一致 |

### 3.8 test_p12_call_events.py（1 test）—— 单通呼叫 P12 Call-ID 对齐

> **定位**：此 bug **不是** load-generator 专属。单通 ``trunk_pair.place_call`` + ``start_internal_api()`` 即可复现/回归。Playwright E2E #43 是浏览器侧附加证据，**主回归在本文件 + unit ``test_p12_call_controller.py``**。

| # | 测试名 | 核心断言 |
|---|--------|----------|
| 1 | `test_single_call_p12_events_share_trunk_call_id` | 单通 completed call → broadcast 捕获 ``call_started`` + ``call_routed`` + ``call_ended``，三者 ``call_id`` 均为 trunk Call-ID（≠ ``"-"``）；无 ``call_started`` 落在 ``call_id='-'`` |

### 3.9 test_call_trace_sequence.py（1 test）—— REST trace 生命周期（P15-A）

| # | 测试名 | 核心断言 |
|---|--------|----------|
| 1 | `test_completed_call_trace_has_invite_and_200_events` | ``trunk_pair`` + ``start_internal_api`` → ``GET /api/v1/traces/{id}`` 含 trunk INVITE、internal decision、next_hop 200 |

### 3.10 test_console_call_trace_flow.py（1 test）—— Console 页面 marker（P15-A）

| # | 测试名 | 核心断言 |
|---|--------|----------|
| 1 | `test_console_page_has_call_trace_flow_markers` | ``CONSOLE_PAGE`` 含 ``#traceFlowSvg``、``#traceDetailModal``、``#traceFlowHeader``；不含 placeholder 文案 |

### 3.11 test_call_trace_messages_api.py（2 tests）—— verbatim SIP REST（P15-B）

| # | 测试名 | 核心断言 |
|---|--------|----------|
| 1 | `test_messages_api_returns_invite_for_completed_call` | ``trunk_pair`` + ``start_internal_api`` → ``GET .../messages`` ≥ 2 条，含 ``INVITE`` 起头的 ``text`` |
| 2 | `test_messages_include_outbound_call_id_field` | 响应 ``outbound_call_id`` = ``outbound_call_id(trunk_call_id)`` |

---

## 四、执行

```bash
# 全部 integration
python3 -m pytest tests/integration/ -v

# 单文件
python3 -m pytest tests/integration/test_translation.py -v
python3 -m pytest tests/integration/test_fraud_screening_path.py -v
# ...
```

预计耗时：**~30 秒**（ephemeral UDP，单进程）。

---

## 五、不覆盖的东西

Integration 层**不**覆盖：
- 单元级纯逻辑（routing_engine 规则匹配算法、CallPool tick loop 等）→ 那是 unit 层
- 浏览器渲染 → 那是 console dashboard E2E
- 4 进程独立进程栈启动 → 那是 console dashboard E2E 的 conftest fixture
