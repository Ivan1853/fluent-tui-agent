# TUI interaction rules

Author: Manuel Sun

## Input semantics

| Input | Meaning and constraints |
|---|---|
| Enter (a zero-length input line) | At a menu: list available entries in the tested v221. At a parameter prompt: may accept the displayed default, terminate a selection list, or advance; establish semantics from that specific prompt. |
| `,` | A TUI default-response token in some grammars; not a universal Enter replacement. At another reader or prompt it may be an invalid token or Scheme read macro. |
| `""` | Two quote characters representing an empty string where a string reader is used. It is not an empty line and not a generic selection terminator. |
| `()` | Scheme empty list or a TUI list value in specific readers. `[()]` only displays a default; do not mechanically type it. |
| `yes` / `no` | Boolean responses only where accepted. `[yes]` means the shown default is yes, not necessarily the user's desired choice. |
| `ok` / `cancel` | v221 may ask `OK to discard? [cancel]`. This is not the same prompt grammar as yes/no. A destructive affirmative response needs the original goal's authorization. |
| `q` | Verified menu/help exit in the tested v221. It is not a universal command cancellation token and may be read as a zone or variable in a sub-prompt. |

Use JSON plans for empty strings in PowerShell 5.1, whose native argument marshalling may drop empty arguments. PowerShell 7 can use `send "" --kind menu_control`; the JSON plan is portable across both.

## Observation boundaries

The transport reads bytes continuously with an incremental decoder; a prompt may have no newline or span chunks. A quiet interval is required after a candidate prompt. All output from the current exchange is inspected for errors, not just the tail. ANSI escapes are retained in raw logs and removed for parsing.

Only a prompt at the end of newly observed output establishes input readiness. If `Error:` follows a previously printed zone prompt and no new prompt appears, the state is unverified. Timeout is never success or permission to repeat. First read/wait; if still unverified, preserve the session and report the ambiguity. PIPE on Windows cannot promise reliable Ctrl-C; ConPTY provides an interrupt input, whose effect still must be observed.

## Menus and help (v221 observed)

From ROOT: `/report/system` enters its menu. An empty line then printed `gpgpu-stats`, `sys-stats`, `proc-stats`, `time-stats`; `q` returned to ROOT. Trailing-slash path alone did not list entries. `?` entered `[help-mode]>`; send `q` in that observed mode to return to command mode. Prompt strings may contain repeated slashes such as `//report/system>`; parse them as menus, not as an error.

Menu entries can depend on whether a case/mesh is loaded and which models are enabled. A missing entry is not automatically a spelling error. The built-in typo recovery only changes a terminal token with a unique close match observed in the same parent menu. It returns to a verified root before retrying. Unknown parent paths or ambiguous matches stop.

## Patch

The user-specified simulated flow is:

```text
/solve/patch
cell zone id/name(1) [()]       → fluid_nozzle
cell zone id/name(2) [()]       → a verified end-of-list response
Variable>                     → pressure
Use Custom Field Function for patching? [yes] → no
Value ... [...]               → 486540
```

Do not assume that this omits every other prompt. A real case may additionally ask for registers or offer another variable set. If `expect_prompt` mismatches, stop and amend the next input using the observed context. Preserve the original command and successful responses; do not replay `/solve/patch` inside an active patch prompt.

`Unable to parse: [compound-procedure]`, `Error: undefined read macro`, `Error Object: ()` jointly support Scheme/TUI argument interaction as a candidate. They do not establish whether the zone name, default terminator, variable, or value is wrong. A repair must say which token is being changed, why the real prompt supports that change, and what next output will confirm it.
