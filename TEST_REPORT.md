# Validation report

Author: Manuel Sun

Test date: 2026-09-05, Windows, Python 3.11.9, installed Fluent 2022 R1. This is **verified with real Fluent within the scope below**, not a mock-only delivery.

## Installation and packaging

- Detected executable: a local `v221/fluent/ntbin/win64/fluent.exe` installation (machine-specific prefix omitted).
- Environment evidence: AWP_ROOT221 and ANSYS221_DIR. File version: 22.1.0; runtime banner: ANSYS Fluent 2022 R1, Build Id 10213.
- `SKILL.md` has required name/description frontmatter; bundled skill-creator validator passed with Python UTF-8 mode. All script modules import; CLI help/discovery/start/status/send/execute-plan/run-journal/stop exercised.
- Default Windows code page caused the external validator's first read to fail; `python -X utf8 .../quick_validate.py` passed. Skill files are UTF-8; no source contents were changed to hide the encoding issue.
- **23 unit/behavioral tests passed.** The reproducible command is shown below.
- Final delivered integration script returned **PASSED** for startup/root/query, safe invalid path, automatic recovery and journal/transcript. The public repository includes the integration script; raw machine logs are retained privately.
- The executable `patch_example.jou` was also run in a real fresh v221 transaction from the test checkpoint; the resulting report was required to contain **486540 Pa**. The measured result and scope are summarized below; private transcript paths are excluded.

## Requested test coverage

| Test | Evidence/result |
|---|---|
| Executable discovery | Real v221 detected and persisted; unit coverage of config/env and rejecting a different version. |
| Fluent startup | Real `3ddp -g -t1`, runtime banner and ROOT observed. |
| Root prompt detection | Real root prompts, plus fragmented/non-newline parsing through live pipes. |
| Simple query | Real `/report/system/sys-stats`, CPU/memory output and ROOT. |
| Multi-prompt command | Real patch and volume report, one response per observed prompt. Requested six-stage/CFF variant covered by mock Solver. |
| Journal execution | Real `-i` execution, exit 0 plus independently emitted unique marker. |
| Transcript parsing | Real transcript and full stdout/stderr captured; historical error + final prompt covered by tests. |
| Invalid TUI path | Real invalid-path response, TUI_PATH_ERROR, actual menu-derived typo repair. |
| Invalid zone | Real invalid symbolic zone produced `Invalid cell zone` and unbound-variable error, no new final prompt. Driver stopped and retained session; no claim that it recovered that stalled reader. Normal reprompt branch covered by mock. |
| Malformed `()` | Requested compound-procedure/read-macro/Error Object sequence detected and corrected in mock. An explicit `()` zone-list terminator was also accepted in the real fixture; it is not universally invalid. |
| Comma/default input | Mock Value prompt rejects comma; candidate supplies only the explicit target numeric value. No global equivalence rule. |
| Scheme parse error | Requested exact strings tested; complete context and Error Object retained. Real unbound-variable output also preserved. |
| Process crash | Controlled mock subprocess exits with code 17; PROCESS_ERROR returned. Real Fluent was not deliberately crashed. |
| Max retry | Initial attempt + 3 distinct retries, then stop with process retained; same-plan resume cannot reset budget. |
| Checkpoint recovery | Real nonempty `.cas.h5/.dat.h5`, patch report 486540 Pa, rollback read of case/data, report 0 Pa. |

## Real recovery and CFD observations

`/report/system/sys-stat` failed. The driver read `/report/system` + empty-line menu output, selected its actual unique `sys-stats` entry, returned to root and retried only the failed command. Prior successful steps were skipped; the corrected query produced real CPU/memory output.

The user-supplied patch sequence expected a CFF yes/no prompt. The actual simple v221 case returned Value directly after pressure. The driver blocked the unmatched `no`; the remaining plan was corrected and resumed in place.

The first closed-wall cube returned 0 Pa despite patch input completion. Therefore that attempt was **not accepted as the requested pressure-field result**. Changing only the zone-list terminator did not change the outcome and that hypothesis was rejected. A separate pressure-outlet fixture then verified the actual 486540 Pa field. This distinguishes input acceptance from physical success and does not authorize changing user physics to make a test pass.

After rollback of the open fixture, Fluent's actual volume-weighted Static Pressure report returned 0 Pa. The temporary test sessions were then closed. Original cases/results were not used or overwritten.

## Backend status and remaining limits

| Component | Status |
|---|---|
| Interactive via PIPE | **VERIFIED WITH REAL FLUENT** on this workstation. |
| Journal + Transcript | **VERIFIED WITH REAL FLUENT** on this workstation. |
| Native Windows ConPTY alternative | Implemented and attempted; **UNAVAILABLE on this setup** because no Fluent text/prompt was received. Never marked available. |
| Windows PIPE Ctrl-C | No reliable console-control channel under CREATE_NO_WINDOW; reports unsupported, does not pretend to interrupt. Observe/wait, or deliberately terminate only the owned process tree. |
| Arbitrary CFD physics / long iterations / GUI / multi-rank MPI | Not validated by this small test. Settings are configurable, but require actual task-specific observation. |
| General automatic repair | Bounded deterministic typo repair plus Codex-supplied evidence-matched hypotheses; no claim that all Fluent errors are automatically repairable. |
| Journal replay | Transactions need reviewed side effects and explicit checkpoint policy. Dynamic unknown prompts require Interactive. |

Raw evidence is retained in the original local delivery. This public repository contains a summarized test report, reproducible tests, and synthetic mesh fixtures; it deliberately excludes machine-specific configuration, session credentials, host information, and raw transcripts. This report records the author's local run, not an independent certification or a guarantee for another installation.

```powershell
python -m unittest discover -s tests -p test_agent.py -v
python tests/integration_fluent.py --config config/fluent_config.json
```

No real Fluent tests run in hosted CI: a compatible local installation and license are required. A missing installation must be reported as **NOT VERIFIED WITH REAL FLUENT**.
