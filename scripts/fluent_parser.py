"""Incremental-output classification and Fluent input state. Author: Manuel Sun."""
from __future__ import annotations
import re
from dataclasses import dataclass, asdict

STATES = {'ROOT', 'MENU', 'COMMAND_ARGUMENT', 'YES_NO_PROMPT', 'ZONE_PROMPT',
          'VALUE_PROMPT', 'SCHEME', 'SOLVING', 'ERROR', 'UNKNOWN'}
ANSI = re.compile(r'\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))')
ERROR = re.compile(r'(?i)(^\s*Error(?: Object)?\s*:|Unable to parse|undefined (?:read macro|variable)|'
                   r'\binvalid (?:command|argument|(?:cell |face )?zone|variable|input)|\bunexpected\b|'
                   r'\bno such\b|\bnot found\b|\bdoes not exist\b|'
                   r'\b(?:zone|variable)\b.*\b(?:invalid|unknown)\b|'
                   r'\b(?:scheme|compound-procedure|read macro)\b.*\b(?:error|parse|invalid)\b)')
FATAL = re.compile(r'(?i)(floating[ -]point exception|segmentation (?:fault|violation)|'
                   r'\bfatal\b|MPI_ABORT|solver process.*(?:exited|died)|license.*(?:failed|denied)|'
                   r'license manager error|unable to (?:connect|checkout)|divergence detected.*AMG)')
WARNING = re.compile(r'(?i)(\bwarning\s*:|reversed flow|\bdivergen(?:ce|t)\b|AMG.*(?:stall|diverg))')

def clean(text: str) -> str:
    text = ANSI.sub('', text).replace('\r\n', '\n').replace('\r', '\n')
    # ConPTY can erase echoed characters with backspace.
    while '\b' in text:
        text = re.sub(r'[^\n]?\x08', '', text)
    return text

def prompt_state(line: str) -> str | None:
    s = line.strip()
    if s == '>': return 'ROOT'
    if re.search(r'\[help-mode\]>$', s): return 'COMMAND_ARGUMENT'
    if re.fullmatch(r'(?:/|[a-zA-Z][\w-]*/)[\w/?.-]*>', s): return 'MENU'
    if re.search(r'(?i)^(?:cell |face |register )?zone(?:s| id/name)?', s) and re.search(r'[>\]]$', s): return 'ZONE_PROMPT'
    if re.search(r'(?i)\[(?:yes|no|y/n|yes/no)\]\s*\??$', s): return 'YES_NO_PROMPT'
    if re.search(r'(?i)^(?:use |overwrite|ok to |do you |continue).*\?$', s): return 'YES_NO_PROMPT'
    if re.match(r'(?i)^(?:value|constant|expression|pressure|temperature)\b', s) and re.search(r'[>\]]$', s): return 'VALUE_PROMPT'
    if re.fullmatch(r'(?i)(?:Variable|Field Variable)\s*>', s): return 'COMMAND_ARGUMENT'
    if re.fullmatch(r'(?i)(?:scheme|[0-9]+)\s*[>]', s): return 'SCHEME'
    if re.search(r'\[[^\n]*\]\s*$', s) and not ERROR.search(s): return 'COMMAND_ARGUMENT'
    if re.fullmatch(r'[\w /()-]+>', s): return 'COMMAND_ARGUMENT'
    if s.endswith('?'): return 'COMMAND_ARGUMENT'
    return None

@dataclass
class Observation:
    output: str
    events: list
    prompt: str | None
    state: str
    error_lines: list
    error_objects: list
    timed_out: bool = False
    process_alive: bool = True
    success: bool = False

    def to_dict(self): return asdict(self)

def parse_output(output: str, *, timed_out=False, process_alive=True) -> Observation:
    """Classify EVERY line. A prompt only describes readiness, never CFD correctness."""
    lines = clean(output).split('\n')
    events, errors, objects = [], [], []
    for number, line in enumerate(lines, 1):
        s = line.strip()
        if not s: continue
        kinds = []
        if FATAL.search(s): kinds.append('FATAL')
        if ERROR.search(s): kinds.append('ERROR')
        if WARNING.search(s): kinds.append('WARNING')
        if re.search(r'(?i)\b(?:converged|convergence achieved)\b', s): kinds.append('CONVERGENCE')
        if re.match(r'^\s*\d+\s+[-+\d.eE]+\s+[-+\d.eE]+', line) or re.match(r'(?i)^\s*iter\s+continuity', line): kinds.append('ITERATION')
        if re.search(r'(?i)\bDone\.|\bcompleted\b', s): kinds.append('SUCCESS')
        ps = prompt_state(s)
        if ps:
            kinds.append('PROMPT' if ps in ('ROOT', 'MENU', 'SCHEME') else 'QUESTION')
        if not kinds: kinds.append('UNKNOWN')
        if 'ERROR' in kinds or 'FATAL' in kinds: errors.append(line)
        obj = re.match(r'(?i)\s*Error Object\s*:\s*(.*)', line)
        if obj: objects.append(obj.group(1))
        events.append({'line': number, 'text': line, 'types': kinds})
    # Historical prompts in a transcript must not be mistaken for current readiness.
    tail = next((x.strip() for x in reversed(lines) if x.strip()), '')
    state = prompt_state(tail)
    prompt = tail if state else None
    if not state:
        state = 'ERROR' if errors or not process_alive else ('SOLVING' if any('ITERATION' in e['types'] for e in events) else 'UNKNOWN')
    success = bool(prompt and not errors and not timed_out and process_alive)
    return Observation(output, events, prompt, state, errors, objects, timed_out, process_alive, success)
