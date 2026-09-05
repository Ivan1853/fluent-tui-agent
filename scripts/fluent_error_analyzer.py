"""Evidence-based diagnoses, never a claim that a repair worked. Author: Manuel Sun."""
from __future__ import annotations
import re
try:
    from .fluent_parser import Observation, prompt_state
except ImportError:
    from fluent_parser import Observation, prompt_state

ERROR_TYPES = ('TUI_PATH_ERROR MENU_STATE_ERROR MISSING_ARGUMENT EXTRA_ARGUMENT INVALID_ARGUMENT '
               'ZONE_ERROR VARIABLE_ERROR YES_NO_ERROR DEFAULT_VALUE_ERROR SCHEME_PARSE_ERROR '
               'FILE_PATH_ERROR MODEL_NOT_ENABLED STATE_DEPENDENCY_ERROR SOLVER_ERROR '
               'PROCESS_ERROR UNKNOWN_ERROR').split()

def analyze(command: str, before: str | None, obs: Observation) -> dict:
    t = '\n'.join(obs.error_lines) or obs.output
    et, confidence, cause, action, safe = 'UNKNOWN_ERROR', .35, 'No sufficiently specific evidence.', 'Inspect the complete local context; request a targeted observation before a repair.', False
    rules = [
        ('SCHEME_PARSE_ERROR', r'compound-procedure|undefined read macro|read macro|scheme.*(?:error|parse)', .93, 'Scheme reader/TUI argument interaction; punctuation may have been read in the wrong prompt.', 'Use prompt_before/prompt_after to locate the missing or misplaced token. Do not resend () or the entire patch line.', True),
        ('FILE_PATH_ERROR', r'(?:file|directory|path).*(?:not found|no such|cannot|unable|does not exist)|no such file', .94, 'File path or access failure.', 'Check the exact local path, permissions, forward slashes and TUI quoting.', True),
        ('ZONE_ERROR', r'zone.*(?:invalid|not found|unknown|does not exist)|invalid.*zone', .94, 'Zone selector is not valid for this case or zone type.', 'List zones with a verified command after reaching a menu, or use valid choices shown in this prompt. Never invent a zone.', True),
        ('VARIABLE_ERROR', r'variable.*(?:invalid|unknown|not found)|invalid.*variable', .9, 'Variable is unavailable or its token is wrong.', 'Inspect actual variable choices and enabled models.', True),
        ('YES_NO_ERROR', r'yes.*no.*(?:expected|required)|invalid.*(?:yes|boolean)', .92, 'Boolean prompt received a non-boolean token.', 'Map the explicit user intent to yes or no at the same prompt.', True),
        ('DEFAULT_VALUE_ERROR', r'invalid.*(?:\bcomma\b|\bdefault\b)|unexpected.*\bcomma\b', .86, 'A default token was used in an incompatible context.', 'Distinguish blank Enter, comma, quoted empty string and list terminator. Use an explicitly verified default response.', True),
        ('EXTRA_ARGUMENT', r'too many arguments|extra argument', .92, 'Extra tokens were consumed by the wrong prompt.', 'Remove only the evidenced surplus token and inspect the remaining prompt.', True),
        ('MISSING_ARGUMENT', r'too few arguments|missing argument|not enough arguments', .92, 'An argument is missing.', 'Supply only the missing response in the current sub-prompt.', True),
        ('MODEL_NOT_ENABLED', r'(?:model|equation).*(?:not enabled|disabled|inactive)', .9, 'The requested model/equation is inactive.', 'Enable it only if the original user goal includes this model change.', False),
        ('STATE_DEPENDENCY_ERROR', r'not initialized|no (?:mesh|case|data)|(?:read|load).*mesh.*first|requires.*(?:mesh|initial)', .88, 'A prerequisite state is absent.', 'Inspect prerequisites and continue only within the authorized plan.', False),
        ('SOLVER_ERROR', r'floating[ -]point|divergen|AMG.*(?:error|fail)|segmentation', .95, 'Numerical instability or solver failure.', 'Stop iterations; inspect mesh, physics and residual history. Do not blindly change physics or reinitialize.', False),
        ('TUI_PATH_ERROR', r'invalid command|unknown command|unrecognized command', .96, 'The command path/token is not available in this menu/version.', 'Inspect the same parent menu and correct one token using a unique observed option.', True),
        ('INVALID_ARGUMENT', r'invalid argument|unexpected|unable to parse|undefined', .8, 'The argument type or grammar does not match the prompt.', 'Inspect prompt semantics and change one supported argument.', True),
    ]
    for typ, pattern, cf, c, a, s in rules:
        if re.search(pattern, t, re.I): et, confidence, cause, action, safe = typ, cf, c, a, s; break
    if not obs.process_alive:
        et, confidence, cause, action, safe = 'PROCESS_ERROR', 1., 'Fluent process exited.', 'Preserve logs; restart only with an explicit checkpoint/recovery decision.', False
    elif obs.timed_out:
        et, confidence, cause, action, safe = 'PROCESS_ERROR', .8, 'No stable input prompt before the timeout; Fluent may still be busy.', 'Read live output/status. Do not resend the command. Interrupt only deliberately.', False
    elif command.startswith('/') and before and prompt_state(before) not in ('ROOT', 'MENU'):
        et, confidence, cause, action, safe = 'MENU_STATE_ERROR', .97, 'A full command was sent while Fluent awaited an argument.', 'Complete the active command using its actual prompt; do not inject a new absolute command.', True
    elif not obs.error_lines and obs.prompt and obs.state not in ('ROOT', 'MENU'):
        et, confidence, cause, action, safe = 'MISSING_ARGUMENT', .9, 'Command remains in an argument prompt.', 'Provide the next planned prompt response; this is not a completed command.', True
    return {'error_type': et, 'confidence': confidence, 'evidence': obs.error_lines or [obs.prompt or 'No fresh prompt'],
            'likely_cause': cause, 'recommended_action': action, 'safe_to_retry': safe,
            'command': command, 'prompt_before': before, 'context': obs.output,
            'error_lines': obs.error_lines, 'error_objects': obs.error_objects, 'prompt_after': obs.prompt,
            'candidate_error_types': ['SCHEME_PARSE_ERROR', 'MENU_STATE_ERROR', 'INVALID_ARGUMENT'] if et == 'SCHEME_PARSE_ERROR' else [et]}
