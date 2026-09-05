# API, plans and backend architecture

Author: Manuel Sun

Python 3.10+ standard library. Windows ConPTY requires Windows 10 1809+ or Windows 11. No PyFluent, no external API key, no third-party runtime packages required.

```text
Codex / PowerShell CLI
  → local authenticated JSON broker (127.0.0.1, one operation at a time)
    → FluentSession: prompt guard / plans / evidence / bounded correction
      → FluentProcess: PIPE; automatically ConPTY on fresh-session failure
        → Fluent v221 stdin + stdout/stderr
      ← parser + analyzer ← fresh output + prompt

JournalRunner → new command.jou → fluent 3ddp -g -t1 -i command.jou
             ← stdout/stderr + transcript + completion marker + exit status
```

`FluentProcess` exposes `start`, `send`, `read_until_prompt`, `read_available`, `is_alive`, `interrupt`, `close`. Low-level `send` only writes one line; `FluentSession.exchange` adds prompt/risk guards and logging. Direct library users should normally use `FluentSession`.

`start` holds a persistent broker in a hidden process. Connection metadata is stored beside config as `fluent_config.session.json`, with a random bearer token; never publish that file. RPC uses JSON (not pickle) over localhost and ignores HTTP proxies. CLI processes may exit while Fluent remains open. `status` is available during long operations; live file tails provide output during them. Mutating concurrent requests are rejected. This is a local single-user tool, not a remotely exposed multi-user service.

## Plan schema

```json
{
  "id": "unique-task-id",
  "client_timeout": 3600,
  "steps": [{
    "id": "initialize",
    "command": "/solve/initialize/initialize-flow",
    "risk": "LOW_RISK",
    "expect": "prompt",
    "retry": true,
    "max_auto_retries": 3,
    "timeout": 60
  }]
}
```

`id` is important for resume: the same plan id skips completed steps and completed inputs. The current broker owns resume state; `progress.json` is a diagnostic snapshot, not proof that a restarted Solver retains old state. After a broker/process restart restore a verified checkpoint and explicitly rebuild the remaining plan. Do not reuse stale progress as live Fluent state.

Step fields:

| Field | Meaning |
|---|---|
| `command`, `kind` | One TUI line, prompt response, Scheme expression, or menu control. |
| `inputs` | Ordered objects with `command`, `kind`, `expect_prompt`; each is sent only after observing its matching prompt. |
| `expect` | `prompt` means final ROOT/MENU; another string is a regex matched against the real final prompt. |
| `verify_output_regex` | Required evidence in the last input's output. |
| `verify` | Read-only `{command, output_regex, risk_evidence?}` observations for physical postconditions. |
| `risk`, `risk_evidence` | Scope classification; evidence is required to classify an unknown command as read-only. Known destructive actions cannot be downgraded. |
| `in_user_goal` | State changes are already part of the actual user request. This is not a new approval mechanism. |
| `allow_destructive` | Explicit original-goal authorization for an initial destructive action; never permits destructive automatic retry. |
| `checkpoint_before` | A checkpoint name; uses a unique directory and verifies case/data files. |
| `allow_warning_regex` | Explicitly reviewed warning pattern; otherwise plan execution stops for warning review. |
| `repairs` | Evidence-matched hypotheses; defaults to no guessed repair. |

Example corrective input (only after the specific error and current prompt actually appear):

```json
{
  "error_type": "SCHEME_PARSE_ERROR",
  "when_output": "undefined read macro",
  "when_prompt": "cell zone id/name\\(2\\)",
  "command": "",
  "kind": "response",
  "expect_prompt": "cell zone id/name\\(2\\)",
  "hypothesis": "This verified zone-list prompt requires blank Enter to finish; () reached the wrong reader.",
  "reason": "Change only the end-of-selection input, based on the recorded current-case interaction."
}
```

This is a conditional example, not a universal fix. If the error occurs after a prompt and the fresh output has no terminal prompt, the driver will not blindly execute it. Repairs cannot downgrade risk, choose a previously failed identical input, or exceed the initial attempt plus three retries. Unknown/ambiguous errors remain for Codex diagnosis.

After a partial step stops, preserve its completed inputs. Append the newly observed next prompt response to that step or add a matching repair; resume with the same plan id. Do not replay the complete original command. Re-running a failed unchanged plan does not reset the input's retry history.

## Journal transactions

Existing journals run with their byte-preserved `source.jou` plus a generated wrapper `command.jou`. The working directory is the configured directory, or the unique run directory if unset; set it when the original journal contains relative paths. Wrapper exit closes only the fresh batch process. Review original exit/write/delete/Scheme commands before passing `--reviewed`.

Each run creates `run_0001`, `run_0002`, … with stdout/stderr and `result.json`; transcript is included when created. Completion is a freshly generated marker emitted by `(display "...")` plus `(newline)`, not the echoed source line. A zero return code or marker alone is insufficient. The runtime must identify as v221 and the full evidence must contain no recognized errors.

Journal mode cannot inspect arbitrary unknown prompts before a static journal consumes its next line. Prefer Interactive for dynamic patch/error recovery. For multi-step fallback, use `execute-plan --backend journal` with:

```json
{
  "id": "journal-cfd",
  "journal_checkpoint_each_step": true,
  "initial_case_data": "C:/CFD/start.cas.h5",
  "steps": [{
    "id": "recorded-patch",
    "journal": "C:/CFD/verified-v221-patch.jou",
    "journal_verified_v221": true,
    "risk": "LOW_RISK"
  }]
}
```

Each successful step saves a unique case/data checkpoint, then the next fresh process reads it. On failure, prior completed steps are not repeated. `--resume-log PATH` resumes the saved `journal_progress.json` from the last successful checkpoint after Codex has repaired the failed transaction. This intentionally trades I/O for state continuity; group steps deliberately to avoid excessive large data writes. A no-mesh journal query should use `run-journal` rather than a checkpoint-based CFD plan.

Journal failure is not permission to relaunch the complete user task. The failed transaction's external file writes may not be reversible by case rollback; review those side effects before any retry.

Optional automatic transaction repair requires `retry:true`, `transaction_replay_safe:true` (the reviewed transaction has no irreversible external effects), and a specific `repairs` item: `error_type`, `when_output`, 1-based `line_number`, exact `expected_line`, `replacement`, `hypothesis`, `reason`. Only that line is replaced; each attempt starts from the last successful checkpoint. Known destructive source lines prohibit automatic replay. Attempt history is saved across `--resume-log`; an unchanged failed body is not resubmitted, and the default total limit is four executions including the initial attempt. `verify_output_regex` and explicitly reviewed `allow_warning_regex` also apply to journal transactions.

## Result interpretation

- `Observation.success`: a fresh prompt, no detected error, process alive, no timeout. It can mean “waiting for the next argument”.
- Plan `completed`: all exchanges, final prompt and configured verification conditions passed. Codex remains responsible for meaningful physical conditions.
- `needs_decision`: no automatic continuation; Interactive retains its process, input progress, errors and correction records.
- Journal `success`: execution evidence and exit criteria passed; target CFD values still need configured read-only reports or artifact checks.
- `solution_valid` in status is a conservative preservation flag once initialization/data may exist. It is not a CFD accuracy or convergence certificate.

## Operational limits

Normal tests use an empty/synthetic case and one CPU. Multi-rank MPI, production UDFs, GUI actions, distributed clusters and large transient cases need task-specific verification. PIPE cannot reliably deliver Windows console Ctrl-C when started with CREATE_NO_WINDOW; `interrupt` reports that limitation. ConPTY's Ctrl-C is sent as console input, then the resulting state must be read. A timeout does not automatically kill a useful Interactive session. `stop --force` only terminates the recorded Fluent process tree; no global image-name termination is used.
