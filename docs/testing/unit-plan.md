# Unit 测试计划

> 状态：已实现 · 更新日期：2026-09-23
> 对应目录：`tests/unit/`（17 个文件，约 182 tests）
> 标签：`pytest.mark.unit`

---

## 一、定位

Unit 层测试**单个模块**的纯逻辑——不 bind socket、不起进程、不依赖 sippy ED2 loop。被测对象直接 import，用 `monkeypatch` 注入 fake 依赖。

| 层 | Socket | 进程 | 浏览器 | 测试数量 |
|---|---|---|---|---|
| **unit** | **否** | **否** | **否** | **~182** |
| integration | 是（fixture bind） | 否（同一进程） | 否 | 44 |
| e2e (call flows) | 是 | 否 | 否 | 9 |
| e2e (dashboard) | 是 | 4 独立进程 | Chromium headless | 28 |

关键约定：**任何 unit test 如果要 `pytest.mark.skipif` 掉"需要 socket"的条件，说明这个测试放错层了——该进 integration**。

---

## 二、模块覆盖一览

按被测代码目录分组：

| 被测模块 | 测试文件 | Tests |
|----------|----------|------:|
| `config/`（项目骨架、版本、CI）| `test_repository_baseline.py` | ~18 |
| `src/as_app/routing/rules.py` + `routing_engine.py` | `test_routing_rules.py`, `test_routing_engine.py` | ~23 |
| `src/as_app/observability/` | `test_observability.py`, `test_errors.py` | ~8 |
| `src/as_app/internal_api.py` | `test_internal_api.py` | ~4 |
| `src/as_app/bootstrap.py` | `test_bootstrap.py` | ~7 |
| `src/as_app/sip_adapter.py` | `test_sip_adapter.py` | ~11 |
| `src/anti_fraud_as/config/` + `error_model.py` | `test_fraud_configuration.py`, `test_fraud_error_model.py` | ~28 |
| `src/anti_fraud_as/caller_state.py` + `screening/` | `test_caller_state.py`, `test_screening_engine.py`, `test_screening_data.py` | ~52 |
| `src/anti_fraud_as/fraud_call_controller.py` | `test_fraud_call_controller.py` | ~4 |
| `tools/call_load_generator.py`（generator 配置 + FastAPI）| `test_call_load_models.py`, `test_call_pool.py`, `test_generator_api.py` | ~28 |

---

## 三、测试用例清单

### 3.1 test_repository_baseline.py（~18 tests）—— 项目骨架完整性

> 不被测 runtime 代码，测 repo 文件结构、版本一致性、CI gate 声明等。

| # | 测试名 | 断言 |
|---|--------|------|
| 1 | `test_meta_file_exists` | `pyproject.toml`, `README.md`, `LICENSE` 全部存在 |
| 2 | `test_top_level_directory_exists` | `src/`, `config/`, `tests/`, `docs/`, `tools/` 存在 |
| 3 | `test_documentation_set_exists` | `docs/architecture/`, `docs/adr/` 各 ADR 文件存在 |
| 4 | `test_no_forbidden_module_names_in_source` | src/ 里没有 `s_server`, `s_controller`, `s_gateway` 这些被 ADR-0001 禁止的模块名 |
| 5 | `test_source_files_carry_licence_header_and_docstring` | 每个 .py 文件开头有 Apache 2.0 header + module docstring |
| 6 | `test_ci_runs_the_gates_in_layers` | CI workflow 里明确分 lint → unit → integration → e2e 层 |
| 7 | `test_compose_defines_the_three_services` | docker-compose 有 s-sbc-mock、translation-as、anti-fraud-as 三个 service |
| 8 | `test_version_file_matches_the_project_version` | `VERSION` 文件和 `pyproject.toml` version 字段一致 |
| 9 | `test_runtime_version_matches_the_version_file` | runtime `as_app` 的 `get_version()` 读 `VERSION` 文件 |
| 10 | `test_runtime_version_is_not_the_unknown_placeholder` | version 不是 "unknown" 或空字符串 |
| 11 | `test_runtime_version_falls_back_to_the_version_file_when_metadata_is_missing` | importlib.metadata 失败时 fallback 到 VERSION 文件 |
| 12 | `test_runtime_version_is_unknown_when_no_version_source_is_available` | 所有源都失败时返回 "unknown" |
| 13 | `test_env_example_declares_every_configuration_knob` | `.env.example` 覆盖了 bootstrap / fraud bootstrap 里的所有 Pydantic settings |
| 14 | `test_as_app_does_not_import_the_anti_fraud_as` | `as_app` 包里没有 `import anti_fraud_as` |
| 15 | `test_make_demo_chained_is_a_documented_first_class_entry_point` | Makefile 里有 `demo-chained` target |
| 16 | `test_chaining_added_no_new_configuration_knob` | chain 用 config-only wiring（AS-1 的 next_hop = AS-2 的 listen address），不新增 env var |
| 17 | `test_the_library_is_consumed_from_the_sibling_checkout` | `anti_fraud_as` 通过 `[tool.uv.sources]` 从 sibling checkout 引用 |
| 18 | `test_the_library_is_not_a_uv_workspace_member` | `anti_fraud_as` 不在 `uv workspace` 声明里 |

### 3.2 test_routing_engine.py（~12 tests）—— 号码翻译算法

> 测 `as_app.routing.engine`：号码格式分类、规则匹配优先级、翻译输出。

| # | 测试名 | 断言 |
|---|--------|------|
| 1 | `test_number_format_classification` | E.164 / national / extension / emergency 正确分类 |
| 2 | `test_translation_strips_and_prepends` | translate 时 strip + 加前缀正确组合 |
| 3 | `test_translation_tolerates_a_missing_prefix` | 号码没有 `+86` 也能正常 translate |
| 4 | `test_mobile_e164_is_translated_to_national` | `+8613800138000` → `013800138000` |
| 5 | `test_international_prefix_is_normalised_to_e164` | `0014155551234` → `+14155551234` |
| 6 | `test_office_extension_is_expanded_to_the_office_range` | 短号 `1234` → 匹配 office range |
| 7 | `test_emergency_short_code_is_not_translated` | `110` / `119` 不被 translate，原样 relay |
| 8 | `test_blocked_premium_rate_number_is_rejected_with_603` | `+86168xxx` → 603 |
| 9 | `test_number_without_matching_rule_yields_404` | 无任何 rule match → 404 |
| 10 | `test_select_rule_prefers_lower_priority` | 同号匹配多条 rule → 选 priority 最低（数字小）的 |
| 11 | `test_select_rule_returns_none_for_unknown_number` | 不在任何 rule 匹配 → None |
| 12 | `test_rule_matching_respects_the_format_filter` | rule 的 `match.format` 只匹配指定格式 |

### 3.3 test_routing_rules.py（~11 tests）—— RuleSet 加载 + Hot Reload

| # | 测试名 | 断言 |
|---|--------|------|
| 1 | `test_shipped_rule_set_loads_and_meets_sample_data_scale` | `config/routing_rules.yaml` 加载成功，规则数 ≥ 3（demo 有 ~15 条）|
| 2 | `test_rules_are_ordered_by_priority` | 加载后 rule list 按 priority 排序 |
| 3 | `test_disabled_rules_are_not_evaluated` | rule `enabled: false` → 跳过 |
| 4 | `test_duplicate_rule_identifier_is_rejected` | YAML 里 rule_id 重复 → 抛 `RuleParseError` |
| 5 | `test_unknown_next_hop_reference_is_rejected` | rule 引用的 next_hop 不在 catalogue → `RouteError` |
| 6 | `test_missing_file_raises_rule_file_unreadable` | 文件不存在 → `RuleFileUnreadable` |
| 7 | `test_invalid_yaml_raises_rule_parse_error` | YAML 语法错误 → `RuleParseError` |
| 8 | `test_next_hops_are_resolved_by_priority` | 同一 rule 多个 next_hop → 按 priority 顺序 |
| 9 | `test_unknown_next_hop_lookup_raises_route_error` | 查不存在的 next_hop → `RouteError` |
| 10 | `test_store_reloads_when_the_file_changes` | 文件 mtime 变 → `RuleStore.reload()` 加载新规则 |
| 11 | `test_store_keeps_previous_rule_set_when_reload_fails` | reload 失败 → 旧规则保留 |

### 3.4 test_observability.py（~4 tests）—— Metrics + Traces

| # | 测试名 | 断言 |
|---|--------|------|
| 1 | `test_counters_are_counted_per_disposition_code_and_rule` | MetricsRegistry counter 按 disposition + rule_id 独立计数 |
| 2 | `test_trace_is_keyed_by_call_id_and_keeps_order` | TraceRecorder 按 Call-ID key，events 保持时间序 |
| 3 | `test_trace_recorder_is_bounded` | TraceRecorder 有容量上限，超过后 FIFO evict 最旧 call |
| 4 | `test_structured_log_line_carries_the_mandatory_fields` | 结构化 log 行有 timestamp, level, module, message, trace_id |

### 3.5 test_errors.py（~4 tests）—— Error Code Enumeration

| # | 测试名 | 断言 |
|---|--------|------|
| 1 | `test_every_code_has_a_unique_identifier_and_status` | 每个 `ErrorCode` 有唯一 code string + SIP status |
| 2 | `test_relevant_sip_statuses_are_present` | 404, 403, 480, 500, 603, 608 都有 |
| 3 | `test_error_exposes_status_phrase_and_log_fields` | `Error` 对象有 status, phrase, log_fields |
| 4 | `test_error_falls_back_to_the_code_message` | Error 无自定义 message → 用 `ErrorCode` 的默认 message |

### 3.6 test_internal_api.py（~4 tests）—— AS Internal API FastAPI routes

| # | 测试名 | 断言 |
|---|--------|------|
| 1 | `test_documented_routes_cover_health_metrics_rules_and_traces` | `GET /healthz`, `GET /api/v1/metrics`, `GET /api/v1/rules`, `GET /api/v1/traces` 全部注册 |
| 2 | `test_health_payload_reports_rule_set_state` | healthz payload 有 `rules_loaded: bool` |
| 3 | `test_metrics_payload_exposes_the_counters` | metrics payload 有 `counters: dict` |
| 4 | `test_rules_payload_is_serialisable_and_read_only` | rules payload 是纯 dict，没有任何 mutable object（比如 `RuleSet` 实例）被直接 JSON 化 |

### 3.7 test_bootstrap.py（~7 tests）—— AS 启动配置 + Self-Check

| # | 测试名 | 断言 |
|---|--------|------|
| 1 | `test_settings_read_the_environment` | `AsSettings` 从 env 变量读取每个 field |
| 2 | `test_invalid_log_level_is_rejected` | `LOG_LEVEL=debug` 正确；`LOG_LEVEL=xxx` → 抛 ValidationError |
| 3 | `test_port_availability_check_detects_a_busy_port` | self_check bind 到已占用端口 → 抛 |
| 4 | `test_self_check_passes_with_a_valid_configuration` | 合法 rules_file + 空闲端口 → self_check 通过 |
| 5 | `test_self_check_fails_when_the_rules_file_is_absent` | rules_file 不存在 → self_check 失败 |
| 6 | `test_self_check_fails_without_a_peer` | `sbc_peer_*` 没配 → self_check 失败 |
| 7 | （更多 bootstrap 测试） | ... |

### 3.8 test_sip_adapter.py（~11 tests）—— SIP URI 解析 + Transaction Timer 管理

| # | 测试名 | 断言 |
|---|--------|------|
| 1 | `test_user_part_is_extracted_from_a_sip_uri` | `sip:1001@127.0.0.1:5060` → user = "1001" |
| 2 | `test_uri_parameters_are_not_part_of_the_number` | `sip:1001@127.0.0.1:5060;transport=tcp` → user = "1001"（不带参数）|
| 3 | `test_missing_user_part_is_rejected` | `sip:@127.0.0.1:5060` → 抛 `InvalidSipUri` |
| 4 | `test_outbound_request_uri_carries_host_port_and_transport` | outbound INVITE Request-URI 格式正确 |
| 5 | `test_ipv6_next_hop_is_bracketed` | IPv6 address → `sip:[::1]:5060` |
| 6 | `test_every_transaction_timer_is_cancelled_before_a_shutdown` | `SipAdapter.shutdown()` → 所有 `sippy.Timeout` cancel |
| 7 | `test_a_second_cancellation_finds_nothing_left_to_do` | `shutdown()` 调两次 → 第二次不崩 |
| 8 | `test_a_timer_that_has_already_fired_is_not_counted` | timer 自然 fire 后 → cancel 不计入 |
| 9 | `test_a_manager_that_was_already_shut_down_is_tolerated` | shutdown 后再调 stop → 幂等 |
| 10 | `test_peer_allowlist_accepts_configured_and_rejects_others` | `allowed_peers=["127.0.0.1"]` → 127.0.0.2 被 reject |
| 11 | `test_outbound_call_id_is_derived_from_and_distinct_from_the_trunk_one` | `outbound_call_id(trunk_call_id)` 总是生成新的，永远不等于 trunk 的 |

### 3.9 test_fraud_configuration.py（~14 tests）—— Anti-Fraud AS Pydantic Settings

| # | 测试名 | 断言 |
|---|--------|------|
| 1 | `test_defaults_are_loopback_and_do_not_collide_with_the_first_as` | 默认端口（fraud_sip_listen_port 等）≠ translation AS 默认端口 |
| 2 | `test_every_knob_is_read_from_the_environment` | 每个 settings field 都可通过 FRAUD_* env 变量注入 |
| 3 | `test_allowed_peers_accept_a_comma_separated_string` | `FRAUD_ALLOWED_PEERS=127.0.0.1,127.0.0.2` → list |
| 4 | `test_the_log_level_is_validated` | 同上 bootstrap |
| 5 | `test_a_port_outside_the_valid_range_is_rejected` | port=0 或 port=65536 → ValidationError |
| 6 | `test_the_self_check_passes_for_a_valid_configuration` | |
| 7 | `test_the_self_check_rejects_a_missing_screening_file` | |
| 8 | `test_the_self_check_rejects_an_invalid_screening_file` | screening file YAML 无效 → |
| 9 | `test_the_self_check_requires_a_next_hop` | fraud_sbc_peer_port 未配 → |
| 10 | `test_the_self_check_requires_at_least_one_allowed_peer` | |
| 11 | `test_the_self_check_fails_fast_when_the_port_is_taken` | |
| 12 | `test_env_example_declares_every_fraud_knob` | `.env.example` 覆盖 FRAUD_* 所有变量 |
| 13 | `test_the_fraud_package_adds_no_third_party_dependency` | fraud package 只依赖 as_app（共享平台库），不引入新第三方 |
| 14 | `test_the_runtime_dependency_pin_is_unchanged` | fraud 引用 as_app 的版本 pin 正确 |

### 3.10 test_fraud_error_model.py（~14 tests）—— Anti-Fraud Error Codes + Metrics + Health

| # | 测试名 | 断言 |
|---|--------|------|
| 1 | `test_sip_phrases_maps_608_to_rejected` | |
| 2 | `test_every_error_code_has_a_reason_phrase` | |
| 3 | `test_the_screening_rejections_are_answered_with_608` | block list / window / reputation → 全部 608 |
| 4 | `test_the_configuration_failures_are_answered_with_500` | screening file 不存在 / invalid → 500 |
| 5 | `test_the_fraud_codes_are_unique_and_prefixed` | 每个 code 唯一，前缀是 AS-FRAUD-* |
| 6 | `test_fraud_codes_live_in_the_shared_error_model` | ErrorCode 共享 as_app.error_codes |
| 7 | `test_the_counter_bucket_records_named_counters` | fraud metrics counters |
| 8 | `test_the_counter_bucket_is_empty_until_it_is_written` | 初始 0 |
| 9 | `test_metrics_payload_exposes_the_counters_next_to_the_errors` | fraud metrics payload |
| 10 | `test_health_reports_the_instance_identity` | healthz payload 有 instance_id |
| 11 | `test_health_reports_the_honest_readiness_key_and_the_compatibility_one` | readiness 字段 |
| 12 | `test_the_internal_api_covers_the_console_surface` | fraud 的 internal API 路由覆盖 console dashboard 需要的 endpoint |
| 13 | `test_the_screening_payload_is_read_only_json` | |
| 14 | `test_the_second_as_serves_the_repository_version` | fraud healthz 里也有 VERSION |

### 3.11 test_caller_state.py（~16 tests）—— CallerStateStore + Reputation Decay

> 测 `anti_fraud_as.caller_state`：窗口计数、reputation 分数、clock 注入、decay 计算。

| # | 测试名 | 断言 |
|---|--------|------|
| 1 | `test_observe_records_the_call_and_returns_plain_signals` | `observe(caller_id, now)` 记录 call，返回当前 window count + reputation |
| 2 | `test_repeated_calls_accumulate_up_to_the_cap` | 同一 caller 多次 observe → count 增长，上限 = window_threshold |
| 3 | `test_calls_older_than_the_window_are_forgotten` | window 是 60s；calls 超过 60s 前的 → 不计 |
| 4 | `test_the_window_boundary_is_exclusive` | 边界时刻 t-window_seconds 不计；t-window_seconds+1ms 计 |
| 5 | `test_calls_inside_the_window_still_count` | window 内的 call 正确累计 |
| 6 | `test_a_callers_window_is_bounded` | 每个 caller 最多保存 N 个 call timestamps |
| 7 | `test_the_store_is_bounded_across_callers` | 全 store 最多保存 M 个 caller，超过 evict LRU |
| 8 | `test_an_unknown_caller_starts_at_the_default_score` | 未见过的 caller → reputation = default |
| 9 | `test_penalise_subtracts_the_configured_penalty` | 惩罚 → reputation -= penalty |
| 10 | `test_reputation_decays_halfway_back_after_one_half_life` | half_life = 24h；过 24h → 回到 default + (旧 - default)/2 |
| 11 | `test_reputation_decays_three_quarters_of_the_way_after_two_half_lives` | 过 48h → 回到 default + (旧 - default)/4 |
| 12 | `test_decay_is_monotonic_towards_the_default` | reputation 只朝 default 移动，不反向 |
| 13 | `test_a_second_penalty_applies_to_the_decayed_score` | 两次 penalty 之间 decay 正确 |
| 14 | `test_reconfigure_changes_the_thresholds_but_keeps_the_history` | 修改 window_threshold → 历史 call timestamps 保留，用新阈值重新计算 |
| 15 | `test_the_store_reads_only_the_injected_clock` | 不读 `time.time()`，只用注入的 `clock.now()` |
| 16 | （更多 caller_state 测试） | |

### 3.12 test_screening_engine.py（~16 tests）—— Screening Decision Logic

> 按 priority 顺序：allow_list > block_list > window > reputation > default allow。

| # | 测试名 | 断言 |
|---|--------|------|
| 1 | `test_a_healthy_caller_is_allowed_with_no_signal_named` | 不在任何 list，没超 window / reputation → allow，无 signal |
| 2 | `test_a_block_listed_caller_is_rejected_with_the_entry_identifier` | block list 里的 caller → reject，error_code + entry_id |
| 3 | `test_an_allow_listed_caller_is_allowed_and_named` | allow list → allow，entry_id 标记 |
| 4 | `test_the_allow_list_wins_over_every_other_signal` | caller 同时在 allow 和 block → **allow 优先**（安全默认：allow 是 explicit 白名单）|
| 5 | `test_the_block_list_wins_over_the_window_and_reputation` | caller 在 block list 里同时 window over → block 优先 |
| 6 | `test_the_window_wins_over_reputation` | caller window over + reputation high → window reject 优先 |
| 7 | `test_calls_at_or_below_the_threshold_are_allowed` | window_count ≤ threshold → allow |
| 8 | `test_calls_above_the_threshold_are_rejected` | window_count > threshold → reject |
| 9 | `test_a_score_below_the_threshold_is_rejected` | reputation_score < reputation_threshold → reject |
| 10 | `test_a_score_at_or_above_the_threshold_is_allowed` | reputation_score ≥ threshold → allow |
| 11 | `test_a_missing_calling_identity_fails_open` | 无 P-Asserted-Identity → fail-open allow（不能因为缺 header 就 reject）|
| 12 | `test_the_decision_carries_the_score_it_decided_on` | 返回的 ScreeningDecision 带 `score` 字段 |
| 13 | `test_every_rejection_reason_is_lower_case_english` | rejection reason 纯小写英文（无用户输入）|
| 14 | `test_only_a_rejection_carries_an_error_code` | allow decision → `error_code=None`；reject → 有 |
| 15 | `test_the_same_inputs_always_produce_the_same_decision` | deterministic（不依赖 clock 注入）|
| 16 | `test_the_engine_reads_no_clock` | 不读 `time.time()`；window/reputation timing 全由 caller_state 注入 |

### 3.13 test_screening_data.py（~19 tests）—— Screening YAML 加载 + 校验 + Reload

| # | 测试名 | 断言 |
|---|--------|------|
| 1 | `test_the_shipped_file_loads` | `config/caller_screening.yaml` 加载成功 |
| 2 | `test_the_shipped_file_carries_no_address` | 默认 screening data 无 IP 地址（用 phone number 识别）|
| 3 | `test_the_policy_is_derived_from_the_document` | `policy: allow_missing` 从 YAML 读 |
| 4 | `test_entries_get_identifiers_derived_from_file_order` | 每条 entry 的 identifier 是 `BLOCK-001`, `ALLOW-003` 这种文件顺序编号 |
| 5 | `test_the_shipped_file_matches_as_an_operator_would_expect` | 有 block_list, allow_list, window_threshold, reputation_threshold 都有值 |
| 6 | `test_an_exact_entry_wins_over_a_prefix_entry` | 同一 caller 出现在 exact 和 prefix 里 → exact 优先生效 |
| 7 | `test_a_missing_file_is_as_fraud_004` | 文件不存在 → 抛 error code AS-FRAUD-004 |
| 8 | `test_invalid_yaml_is_as_fraud_005` | YAML 语法错 → AS-FRAUD-005 |
| 9 | `test_an_entry_with_both_number_and_prefix_is_rejected` | 一条 entry 同时写 `number:` 和 `prefix:` → invalid |
| 10 | `test_an_entry_with_neither_number_nor_prefix_is_rejected` | 既没 number 也没 prefix → invalid |
| 11 | `test_a_duplicate_entry_inside_a_list_is_rejected` | 同一 list 里 number 重复 → invalid |
| 12 | `test_a_value_in_both_lists_is_rejected` | block list 和 allow list 里有相同号码 → invalid |
| 13 | `test_unusable_window_and_reputation_values_are_rejected` | window_threshold ≤ 0 / reputation_threshold ≤ 0 → invalid |
| 14 | `test_an_unknown_field_is_rejected` | YAML 里出现 schema 没定义的字段 → invalid |
| 15 | `test_an_unsupported_version_is_rejected` | `version: 99` → invalid |
| 16 | `test_reload_is_a_no_op_while_the_file_is_unchanged` | mtime 不变 → reload 返回 False（不做无谓操作）|
| 17 | `test_reload_activates_a_changed_file` | mtime 变 → reload 返回 True，新数据生效 |
| 18 | `test_a_broken_edit_keeps_the_previous_document` | reload 成 invalid → 保持旧 document |
| 19 | `test_a_deleted_file_keeps_the_previous_document` | 文件被删 → 保持旧 document |

### 3.14 test_fraud_call_controller.py（~4 tests）—— Fraud-specific Call Controller

| # | 测试名 | 断言 |
|---|--------|------|
| 1 | `test_the_peer_status_key_is_the_address_and_port` | metrics 的 peer status key = f"{host}:{port}" |
| 2 | `test_the_peer_status_key_never_renders_the_internal_hop_name` | 不暴露内部 next_hop 名字 |
| 3 | `test_the_no_answer_label_is_the_serving_hop_address_and_port` | no_answer label = 实际 server 的 host:port |
| 4 | `test_the_no_answer_label_is_a_dash_without_a_serving_hop` | 没有 serving hop → label = "-" |

### 3.15 test_call_load_models.py（~18 tests）—— Generator 配置模型

> `tools/call_load_generator.py` 里的 Pydantic 配置 + CallInstance + DurationModel。

| # | 测试名 | 断言 |
|---|--------|------|
| 1 | `test_call_model_pick_from_enabled_types` | 从 enabled_types 里 pick 一个 call type |
| 2 | `test_call_model_pick_covers_all_types_when_all_enabled` | 全 enabled → pick 结果覆盖 10 种类型 |
| 3 | `test_call_model_rejects_empty_enabled` | enabled_types=[] → ValidationError |
| 4 | `test_call_model_rejects_unknown_types` | enabled_types=["FAKE"] → ValidationError |
| 5 | `test_call_model_all_types_constant` | 10 种类型常量定义正确 |
| 6 | `test_duration_model_weights_sum_to_one` | D1(30%) + D2(50%) + D3(15%) + D4(5%) = 1.0 |
| 7 | `test_duration_model_pick_returns_valid_class` | pick 结果是 D1/D2/D3/D4 之一 |
| 8 | `test_duration_model_midpoints_cover_all_classes` | 每个 duration class 的 midpoint duration 正确 |
| 9 | `test_duration_model_avg_duration_constant` | AVG = 9.5s（加权平均）|
| 10 | `test_pool_config_accepts_valid_values` | concurrency=10, rate=3.0, enabled_types=[T1,...T10] 都 OK |
| 11 | `test_pool_config_rejects_concurrency_too_low` | concurrency=0 → |
| 12 | `test_pool_config_rejects_concurrency_too_high` | concurrency=10000 → |
| 13 | `test_pool_config_rejects_rate_too_low` | rate=0.1 → |
| 14 | `test_pool_config_rejects_rate_too_high` | rate=1000 → |
| 15 | `test_pool_config_rejects_empty_enabled` | |
| 16 | `test_pool_config_rejects_unknown_types` | |
| 17 | `test_call_instance_defaults` | CallInstance 默认 running=false, active_calls=0, started_at=None |
| 18 | `test_call_instance_explicit_ended_at` | CallInstance 可以带 explicit ended_at |

### 3.16 test_call_pool.py（~4 tests）—— Generator CallPool 核心

| # | 测试名 | 断言 |
|---|--------|------|
| 1 | `test_binding_concurrency` | `CallPool(config)._config.target_concurrency = 10` |
| 2 | `test_binding_rate` | rate = 3.0 |
| 3 | `test_binding_at_boundary` | concurrency=1, rate=0.1 边界值接受 |
| 4 | `test_snapshot_fields` | `CallPool.snapshot()` 返回 dict 有 active_calls, running, target_concurrency, call_rate |

### 3.17 test_generator_api.py（~6 tests）—— Generator FastAPI REST API

| # | 测试名 | 断言 |
|---|--------|------|
| 1 | `test_get_status_keys` | `GET /load/status` 返回 dict 有 active_calls, running, target_concurrency, call_rate |
| 2 | `test_put_config_valid` | `PUT /load/config` 用合法 body → 200，config 更新 |
| 3 | `test_put_config_rejects_out_of_range` | `PUT` concurrency=1000 → 422 |
| 4 | `test_put_config_rejects_unknown_call_type` | `PUT` enabled_types=["FAKE"] → 422 |
| 5 | `test_post_start` | `POST /load/start` → pool 启动 |
| 6 | `test_post_stop` | `POST /load/stop` → pool 停止 |

---

## 四、执行

```bash
# 全部 unit
python3 -m pytest tests/unit/ -v

# 单文件
python3 -m pytest tests/unit/test_routing_engine.py -v
python3 -m pytest tests/unit/test_caller_state.py -v
python3 -m pytest tests/unit/test_screening_engine.py -v
# ...
```

预计耗时：**~20 秒**（纯 Python，无 socket）。

---

## 五、Ruff 豁免

`pyproject.toml` 里配置了：
```
"tests/**/*.py" = ["D", "E501", "N801", "N802", "N803", "ANN"]
```
→ 测试文件 D 系列 docstring / E501 行长度 / N 系列命名 / ANN 类型注解被豁免。这是项目约定，不是 unit 层独有的。
