# fluent-tui-agent

Author: Manuel Sun

[简体中文](README.md) | English

A Codex Agent Skill that executes, observes, diagnoses, and corrects **ANSYS Fluent 2022 R1 (v221) TUI** operations on Windows. It controls the installed Fluent executable directly and uses no PyFluent dependency.

**Actual Fluent output is the authority.** Model knowledge produces candidate commands; a prompt, `Done.`, or exit code alone does not prove a CFD result is correct.

## Capabilities

- Discover and validate a v221 installation from configuration, environment, installation trees, and custom search roots.
- Maintain a live Solver session across CLI calls using a local authenticated broker and stdin/stdout transport.
- Attempt native Windows ConPTY when PIPE probing fails; mark a transport available only after a real version/prompt/query test.
- Run existing journals through `-i`, capture stdout/stderr and transcript, and require an independently emitted completion marker.
- Distinguish root/menu/argument/zone/value/yes-no/Scheme/solving/error states and respond to the actual current prompt.
- Classify errors, preserve complete local context, and retry only the failed step with an explicit evidence-based hypothesis. Default: at most three automatic retries.
- Save audit logs and checkpoints; require observed result checks for state changes such as patching.

Built-in repairs are deliberately bounded: a unique terminal-path typo may be corrected using the actual parent menu; other hypotheses are supplied by Codex and matched against observed evidence. This is not a universal autonomous CFD solver.

## Requirements and installation

Windows 10 1809+ or Windows 11, Python 3.10+, and a licensed local Fluent 2022 R1 installation. The Python implementation uses only the standard library.

```powershell
git clone https://github.com/Ivan1853/fluent-tui-agent.git
# Run from the clone's parent directory. Choose your client's actual skill location.
$skillSource = Join-Path (Get-Location) 'fluent-tui-agent'
$skillTarget = Join-Path $env:USERPROFILE '.codex\skills\fluent-tui-agent'
if (Test-Path -LiteralPath $skillTarget) { throw 'Inspect the existing installation before updating.' }
Copy-Item -LiteralPath $skillSource -Destination $skillTarget -Recurse
Set-Location -LiteralPath $skillTarget
Copy-Item config\fluent_config.example.json config\fluent_config.json
python scripts\fluent_driver.py discover --save
python scripts\fluent_driver.py start
python scripts\fluent_driver.py status
```

Current Codex documentation also describes `.agents/skills`; use the directory recognized by your client and avoid duplicate installations. This project's creation workstation recognized `.codex/skills`. See [official skills documentation](https://learn.chatgpt.com/docs/build-skills).

If discovery fails, set `executable` or `search_roots` in the local config. Configuration supports dimension, precision, GUI, processors, working directory, transport, encoding, and timeouts. The default is `3ddp -g -t1`; it is configurable, not a compatibility claim for every mode.

## Three examples

```powershell
# 1. A real read-only query; inspect the returned output and prompt.
python scripts\fluent_driver.py send '/report/system/sys-stats'

# 2. Multi-step query plan with an intentionally misspelled terminal command.
python scripts\fluent_driver.py execute-plan examples\recovery_plan.json

# 3. Run a reviewed journal in a fresh process.
python scripts\fluent_driver.py run-journal 'C:\CFD\job.jou' --reviewed --timeout 600
```

Or ask Codex: `$fluent-tui-agent Run the recovery example on Fluent 2022 R1 and show the observed error, menu evidence, correction, and verified result.`

Journal review must cover paths, prerequisite model state, overwrites, and exit commands. Dynamic unknown prompts need Interactive mode. PowerShell 5.1 may discard empty native arguments; use JSON plan inputs with `"command":""` when sending Enter.

## Observe and stop

```powershell
python scripts\fluent_driver.py observe --wait --timeout 30
$fluentStatus = python scripts\fluent_driver.py status | ConvertFrom-Json
Get-Content -LiteralPath (Join-Path $fluentStatus.log_dir 'stdout.log') -Tail 40 -Wait
# In another terminal:
Get-Content -LiteralPath (Join-Path $fluentStatus.log_dir 'errors.jsonl') -Tail 5
Get-Content -LiteralPath (Join-Path $fluentStatus.log_dir 'corrections.jsonl') -Tail 5
python scripts\fluent_driver.py stop
```

For a deliberately discarded test session, use `stop --discard`. For a confirmed hung session, `stop --force` targets the owned process tree. Do not kill all Fluent processes by image name. PIPE does not provide reliable Ctrl-C under the tested no-window launch mode. See the [full operational guide](README.md) for checkpoints, rollback, and stale-session cleanup.

## Validation and limits

On 2026-09-05, 23 unit/behavioral tests passed. Real local Fluent v221 tests verified PIPE startup/root/query, invalid-path diagnosis and bounded recovery, Journal + Transcript, and a small pressure patch/checkpoint rollback. The open fixture reported 486540 Pa after patching and 0 Pa after rollback.

**ConPTY did not pass the real probe on that workstation.** GUI, multi-rank MPI, long iterations, and production CFD physics were not validated. The requested compound-procedure/read-macro sequence was tested with the mock Solver; a real invalid-zone stall was preserved and reported, not falsely declared recovered.

```powershell
python -m unittest discover -s tests -p test_agent.py -v
python tests\integration_fluent.py --config config\fluent_config.json
```

Read the [test report](TEST_REPORT.md), [architecture](docs/ARCHITECTURE.md), [plan API](references/api_and_plans.md), and [related projects](docs/RELATED_PROJECTS.md). Local configuration, session credentials, raw transcripts, and production case/data are excluded from the public repository. Fluent and licenses are not distributed.

This is an independent community tool, not an Ansys or OpenAI product.
