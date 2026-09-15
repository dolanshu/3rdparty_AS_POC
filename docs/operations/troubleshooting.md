# Troubleshooting

Symptom → cause → action. Every entry names the error code you would see in the log.

## Startup

| Symptom | Cause | Action |
| --- | --- | --- |
| `AS-CFG-001 required configuration value is missing` | `SBC_PEER_ADDRESS` empty or unset | Set it in the environment or `.env`; see `.env.example` |
| `AS-CFG-003 signalling port cannot be bound` | Another process holds `SIP_LISTEN_PORT` | `ss -lunp \| grep 5060`; stop the other process or change the port |
| `AS-CFG-004 trunk peer configuration is not usable` | `ALLOWED_PEERS` is empty | List at least one address |
| `AS-RULE-001 routing rules file cannot be read` | `RULES_FILE` points at a missing path | Check the path; run `uv run python tools/show_rules.py` |
| `AS-RULE-002 ... not valid YAML` | Syntax error after an edit | Validate the file; `git diff config/routing_rules.yaml` |
| `AS-RULE-003 ... violate the schema` | Unknown field, duplicate `rule_id`, or a rule referencing an undefined next hop | Read the validation message; the next hop names must exist in `next_hops` |
| Process starts and exits immediately | `--self-check-only` was passed | Expected: the flag runs the self-check and exits `0` |

## sippy and the stack

| Symptom | Cause | Action |
| --- | --- | --- |
| `Timer.go() from wrong thread, expect Bad Stuff to happen` | `ED2.loop()` is not running on the thread that created the timers | Run `ED2.loop()` on the main thread, as `tools/sippy_probe.py` does |
| `AttributeError: 'NoneType' object has no attribute 'write'` | `_sip_logger` is `None` in the global config | Always set `global_config['_sip_logger']`, for example `SipLogger('as')` |
| No response at all on the trunk | Wrong peer address, or the source is not in `ALLOWED_PEERS` | Check `SBC_PEER_*` and `ALLOWED_PEERS`; capture with `./tools/capture.sh` |
| `OSError: [Errno 98] Address already in use` on start-up | A previous `SipTransactionManager` was not shut down, so the UDP port is still bound | Call `SipTransactionManager.shutdown()` on teardown; in tests the `trunk_pair` fixture does it |
| Outbound messages carry the `Via` or `Contact` of the other application | `SipConf` is a process-wide singleton and both sippy applications share one interpreter | Set `ua.lContact` and `ua.local_ua` and pin `SipConf` around the message generation; see `docs/architecture/lld.md` section 5 |
| A header leaves the AS as `P-charging-vector` instead of `P-Charging-Vector` | sippy renders unknown headers with `SipGenericHF.getCanName()`, which only capitalises the first letter | Expected sippy behaviour; the value is unchanged. Known headers such as `P-Asserted-Identity` keep their canonical spelling |
| The `ACK` is on the wire but missing from the Call-ID trace | The transaction layer sends the `ACK`; it never raises a call control event | Expected; see `docs/architecture/lld.md` section 3.1 and the message samples |
| `uv sync` hangs or is very slow | The default index (`pypi.org`) is slow from this network | Use a mirror for the local run: `UV_DEFAULT_INDEX=https://<mirror>/pypi/simple uv sync` |

## Routing

| Symptom | Cause | Action |
| --- | --- | --- |
| A number is answered `404` and `AS-ROUTE-001` | No enabled rule matches | `uv run python tools/show_rules.py --evaluate <number>`; add a rule or enable the catch-all rule `R-DEFAULT-99` |
| A number is answered `603` and `AS-ROUTE-002` | A `reject` rule matched (premium-rate blocklist) | Intended; change the rule if the number must be routable |
| The translated number is wrong | `strip_prefix` / `prepend` of the matched rule | Inspect the rule and the decision with `tools/show_rules.py` |
| A rule edit has no effect | The file was not changed on disk, or the reload failed | Check the modification time; a failed reload keeps the previous rule set and logs `AS-RULE-00x` |
| `AS-ROUTE-003 no next hop is available` | A rule references a next hop that is not in the catalogue | Add the next hop to `next_hops` or fix the reference |

## Trunk peers

| Symptom | Cause | Action |
| --- | --- | --- |
| `AS-PEER-001 source address is not an allowed trunk peer` | Source not in `ALLOWED_PEERS` (containers: the AS sees the container address, not `127.0.0.1`) | Add the peer address; in compose this is `s-sbc-mock` resolved on the `trunk` network |
| `AS-PEER-003 request ... could not be parsed` | Malformed Request-URI, or a URI without a user part | Capture and inspect the message |
| `AS-PEER-002 next hop peer did not answer` | The next hop is down or a firewall drops UDP | Check the peer; check the pcap |

## Tooling

| Symptom | Cause | Action |
| --- | --- | --- |
| `ruff` or `mypy` fails after a dependency update | A new linter version has new rules | Fix the findings; do not silence them without a decision |
| `pytest` cannot import `as_app` | `PYTHONPATH` does not contain `src` | Use `uv run pytest` (the path is set in `pyproject.toml`) or `make test` |
| `make: command not found` for a target | Typo, or running make from another directory | Run from the repository root; `make help` lists the targets |
| `tcpdump is not installed` | Capture tool missing | Install tcpdump, or use the `docker run` alternative printed by `tools/capture.sh` |
