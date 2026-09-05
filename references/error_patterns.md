# Evidence-based error classification

Author: Manuel Sun

Every diagnosis returns `error_type`, `confidence`, `evidence`, `likely_cause`, `recommended_action`, `safe_to_retry`, plus the command, before/after prompts, full context, error lines and Error Objects. Confidence is a rule score, not a calibrated statistical probability.

| Type | Typical evidence | Next action |
|---|---|---|
| TUI_PATH_ERROR | invalid/unknown command | Inspect actual same-parent menu; correct one unique terminal token. |
| MENU_STATE_ERROR | Full path injected at an argument prompt | Finish the pending input; do not enter a second command. |
| MISSING_ARGUMENT | missing/too few arguments, unfinished sub-prompt | Supply only the required response. |
| EXTRA_ARGUMENT | too many/extra arguments | Remove the evidenced surplus token. |
| INVALID_ARGUMENT | invalid argument, unable to parse | Inspect type and reader semantics. |
| ZONE_ERROR | invalid cell zone, unknown/not found zone | Use case-specific observed names/IDs. An unquoted nonexistent symbol may also generate a Scheme unbound-variable error. |
| VARIABLE_ERROR | invalid/unknown variable | Inspect actual choices and enabled models. |
| YES_NO_ERROR | yes/no expected | Use explicit goal-derived yes/no. |
| DEFAULT_VALUE_ERROR | invalid comma/default | Distinguish blank Enter, comma, `""`, `()`. |
| SCHEME_PARSE_ERROR | compound-procedure, undefined read macro | Candidate Scheme/TUI argument interaction; inspect surrounding prompts. |
| FILE_PATH_ERROR | no such file, file/path not found | Verify local existence, access, forward-slash quoted path. |
| MODEL_NOT_ENABLED | model/equation disabled | Enable only if required by original user goal. |
| STATE_DEPENDENCY_ERROR | no mesh/case, not initialized | Establish actual prerequisites. |
| SOLVER_ERROR | FPE, divergence, AMG failure | Stop and inspect numerical/physical causes; no blind retry. |
| PROCESS_ERROR | exited process, launch failure, timeout | Distinguish crash, license/transport failure and a busy solve. |
| UNKNOWN_ERROR | other error | Preserve state, gather a minimal additional observation. |

`Warning: reversed flow` is a warning, not proof of failure. Ordinary AMG mentions or iteration rows are not errors by themselves. A returned prompt does not erase earlier error lines. A marker or `Done.` following an error also does not erase the failure. Numerical failure requires physical diagnosis; never treat it as a command typo.

Process timeouts take precedence for automatic safety: a parser may identify Scheme/zone evidence, while the final diagnosis becomes PROCESS_ERROR because no new prompt was returned. The raw context and error lines remain available for Codex's more specific explanation.
