# Recovery examples

Author: Manuel Sun

## Real path typo

User goal: query system statistics. `/report/system/sys-stat` produced `invalid command [sys-stat]`. The agent entered `/report/system`, sent an empty menu-control line, read the actual choices containing `sys-stats`, returned with `q`, and retried `/report/system/sys-stats`. The corrected command returned CPU/memory information and ROOT. The preceding successful step was not rerun. See `examples/recovery_plan.json` and the real logs listed in TEST_REPORT.

## Simulated Scheme/TUI interaction

`tests/test_agent.py` drives a mock Solver over real subprocess pipes. At the second zone prompt it sends `()`. The mock emits the requested compound-procedure/undefined-read-macro/Error Object sequence and reprints the same zone prompt. The analyzer identifies SCHEME_PARSE_ERROR, retains all evidence, and a matching hypothesis replaces only `()` with the specifically verified blank list terminator. It then observes Variable, CFF, Value and final ROOT. The identical failed input is not sent again.

This is a test of the feedback mechanism, not proof that blank Enter fixes every Fluent Scheme error. If real output does not contain a new prompt, the candidate is blocked.

## Real patch prompt difference

The simulated plan expected a CFF prompt, but the tested v221 case directly returned Value after `pressure`. `expect_prompt` rejected the unmatched `no` input before it was sent. Codex removed that unused response from the current plan and resumed only the pending Value input. The previous successful inputs were not replayed. Use `patch_plan_v221_observed.json` only when its prompts match the current case.
