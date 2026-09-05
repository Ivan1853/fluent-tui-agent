"""Feedback loop, authorization scope, bounded repair and checkpoints. Author: Manuel Sun."""
from __future__ import annotations
import difflib, json, re, uuid
from pathlib import Path
try:
    from .fluent_common import now
    from .fluent_parser import parse_output
    from .fluent_error_analyzer import analyze
except ImportError:
    from fluent_common import now
    from fluent_parser import parse_output
    from fluent_error_analyzer import analyze

RANK = {'READ_ONLY': 0, 'LOW_RISK': 1, 'STATE_CHANGING': 2, 'DESTRUCTIVE': 3}
MENU_STATES = ('ROOT', 'MENU')

def infer_risk(command, solution_valid=False):
    c = command.strip().lower()
    if c.startswith('(') and re.search(r'\b(?:system|delete-file|remove-file|exit|quit)\b', c): return 'DESTRUCTIVE'
    if re.match(r'^/(?:exit|file/(?:write|delete|remove))', c): return 'DESTRUCTIVE'
    if '/initialize/' in c: return 'DESTRUCTIVE' if solution_valid else 'LOW_RISK'
    if c.startswith('/solve/patch') or c.startswith('/solve/monitors/'): return 'LOW_RISK'
    if c == '/' or re.fullmatch(r'/[\w/-]*/\??', c): return 'READ_ONLY'
    if re.match(r'^/(?:report/system/(?:sys-stats|proc-stats)|mesh/check|mesh/size-info)(?:\s|$)', c): return 'READ_ONLY'
    if c.startswith('/__codex_invalid_'): return 'READ_ONLY'
    if re.fullmatch(r'\(display "[A-Za-z0-9_: .\\n-]+"\)', command.strip()): return 'READ_ONLY'
    return 'STATE_CHANGING'

def check_scope(item, command, *, solution_valid=False, retry=False, inherited=None):
    inferred = inherited or infer_risk(command, solution_valid)
    declared = item.get('risk', inferred)
    if declared not in RANK: raise ValueError('Unknown risk class')
    if inferred == 'DESTRUCTIVE':
        if retry or not item.get('allow_destructive'): raise PermissionError('Destructive command/prompt response cannot be an automatic repair probe')
        return 'DESTRUCTIVE'
    # A read-only declaration for an unknown command must include a concrete audit reason.
    if RANK[declared] < RANK[inferred] and not item.get('risk_evidence'):
        raise ValueError(f'Cannot lower inferred risk {inferred} without risk_evidence from actual menu/help or a reviewed journal')
    risk = declared if item.get('risk_evidence') else inferred
    if risk == 'STATE_CHANGING' and not item.get('in_user_goal'):
        raise PermissionError('State change requires in_user_goal=true, grounded in the existing user request')
    if risk == 'DESTRUCTIVE' and (retry or not item.get('allow_destructive')):
        raise PermissionError('Destructive actions are never automatic repair probes; initial execution needs explicit goal authorization')
    return risk

class FluentSession:
    def __init__(self, process, log, config):
        self.process, self.log, self.config = process, log, config
        self.last_successful_step = None; self.completed = {}; self.plan_id = None
        self.solution_valid = False; self.modified = False; self.active_risk = None
        self.last_result = None; self.checkpoints = {}; self.busy = False
        self.pending_output = ''
        self._recoveries = {}; self._last_failure_key = None

    def status(self):
        return {'alive': self.process.is_alive(), 'available': self.process.available,
                'transport': self.process.transport, 'pid': self.process.pid, 'state': self.process.state,
                'prompt': self.process.prompt, 'busy': self.busy, 'last_successful_step': self.last_successful_step,
                'plan_id': self.plan_id, 'completed_steps': list(self.completed),
                'solution_valid': self.solution_valid, 'modified': self.modified,
                'log_dir': str(self.log.path), 'last_result': self.last_result}

    def observe(self, wait=False, timeout=None):
        # read_until_prompt after a timeout continues the same command, never sends again.
        if wait:
            obs = self.process.read_until_prompt(timeout)
        else:
            self.pending_output += self.process.read_available()
            obs = parse_output(self.pending_output, process_alive=self.process.is_alive())
            if obs.prompt:
                self.process.prompt, self.process.state = obs.prompt, obs.state
        if obs.output: self.log.event('observe', obs.to_dict())
        return obs.to_dict()

    def exchange(self, command, *, kind='tui', item=None, step='manual', retry=False):
        item = item or {}
        # Drain unsolicited late output BEFORE deciding what Fluent currently expects.
        late = self.process.read_available()
        if late:
            self.pending_output += late
            obs = parse_output(self.pending_output, process_alive=self.process.is_alive())
            self.process.prompt, self.process.state = obs.prompt, obs.state
            self.log.event('unsolicited-output', obs.to_dict())
        before, state = self.process.prompt, self.process.state
        if not before: raise RuntimeError('No observed input prompt; use observe --wait before sending')
        if kind == 'tui':
            if state not in MENU_STATES: raise ValueError(f'Fluent awaits {state}: send a response, not a TUI command')
            if not command.startswith('/'): raise ValueError('TUI commands must use an absolute path')
        elif kind == 'menu_control':
            if command not in ('', 'q', '?') or not (state in MENU_STATES or ('[help-mode]' in (before or '') and command == 'q')):
                raise ValueError('menu_control allows Enter/list, q/back, ?/help at an observed menu; only q exits observed help-mode')
        elif kind == 'response':
            if state in MENU_STATES or state in ('UNKNOWN', 'ERROR', 'SOLVING'): raise ValueError('No active argument prompt')
            if command.startswith('/'): raise ValueError('An absolute TUI path is not a prompt response')
            if not item.get('expect_prompt') or not re.search(item['expect_prompt'], before):
                raise ValueError('A response needs expect_prompt matching the current real prompt')
        elif kind == 'scheme':
            if state not in (*MENU_STATES, 'SCHEME'): raise ValueError('Scheme expressions are not parameter responses')
            if not command.lstrip().startswith('('): raise ValueError('Expected a Scheme expression')
        else: raise ValueError('kind must be tui, response or scheme')
        inherited = 'READ_ONLY' if kind == 'menu_control' else self.active_risk if kind == 'response' else None
        destructive_prompt = kind == 'response' and re.search(r'(?i)discard|overwrite|delete|without saving', before or '') and command.strip().lower() in ('yes', 'y', 'ok')
        if destructive_prompt: inherited = 'DESTRUCTIVE'
        risk = check_scope(item, command, solution_valid=self.solution_valid, retry=retry, inherited=inherited)
        self.pending_output = ''
        self.process.send(command)
        obs = self.process.read_until_prompt(item.get('timeout'))
        self.pending_output = obs.output if not obs.prompt else ''
        self.active_risk = risk if obs.state not in MENU_STATES else None
        if RANK[risk] >= 1: self.modified = True
        if '/initialize/' in command and obs.success and obs.state in MENU_STATES: self.solution_valid = True
        if re.match(r'^/file/read-(?:case-data|data)', command) and obs.success: self.solution_valid = True
        record = {'timestamp': now(), 'step': step, 'command': command, 'kind': kind, 'risk': risk,
                  'prompt_before': before, 'state_before': state, 'output': obs.output,
                  'state_after': obs.state, 'prompt_after': obs.prompt, 'success': obs.success,
                  'observation': obs.to_dict()}
        self.log.append('commands.jsonl', record)
        if not obs.success:
            record['diagnosis'] = analyze(command, before, obs)
            self.log.append('errors.jsonl', {'timestamp': now(), 'step': step, **record['diagnosis']})
        self.last_result = record
        self.log.report(self.summary('observed', record))
        return record

    def summary(self, status, result=None):
        return {'status': status, 'timestamp': now(), 'last_successful_step': self.last_successful_step,
                'plan_id': self.plan_id, 'completed_steps': list(self.completed), 'session_retained': self.process.is_alive(),
                'state': self.process.state, 'prompt': self.process.prompt, 'log_dir': str(self.log.path), 'result': result}

    def _path_repair(self, command, item):
        # Only repair ONE terminal token, using names returned by the SAME parent menu.
        if self.process.state not in MENU_STATES or not re.fullmatch(r'/[\w/-]+', command): return None
        parent, token = command.rsplit('/', 1)
        if self.process.state == 'MENU':
            back = self.exchange('q', kind='menu_control', step='repair-return-root')
            if not back['success'] or self.process.state != 'ROOT': return None
        if parent:
            entered = self.exchange(parent, step='repair-enter-menu', item={'risk': 'READ_ONLY', 'risk_evidence': 'Enter the failed command parent solely to inspect its actual menu'})
            if not entered['success'] or self.process.state != 'MENU': return None
        listing = self.exchange('', kind='menu_control', step='repair-inspect-menu')
        if not listing['success'] or listing['state_after'] not in MENU_STATES: return None
        names = set()
        for line in listing['output'].splitlines():
            for word in line.split():
                if re.fullmatch(r'[a-z][a-z0-9-]*/?', word): names.add(word.rstrip('/'))
        matches = difflib.get_close_matches(token, sorted(names), n=2, cutoff=.7)
        if self.process.state == 'MENU':
            back = self.exchange('q', kind='menu_control', step='repair-return-root')
            if not back['success'] or self.process.state != 'ROOT': return None
        if not matches: return None
        if len(matches) == 2 and abs(difflib.SequenceMatcher(None, token, matches[0]).ratio() - difflib.SequenceMatcher(None, token, matches[1]).ratio()) < .12: return None
        replacement = (parent or '') + '/' + matches[0]
        return {'command': replacement, 'kind': 'tui', 'hypothesis': f'Terminal token {token!r} is a typo of the uniquely similar option {matches[0]!r} in the observed parent menu.',
                'reason': 'Changed one path component using actual Fluent menu output.', 'evidence': listing['output']}

    def _repair_candidate(self, step, result, tried):
        d = result.get('diagnosis') or analyze(result['command'], result['prompt_before'], parse_output(result['output']))
        if not d['safe_to_retry']: return None
        # Codex may supply evidence-matched candidates. These are hypotheses, not known successes.
        for candidate in step.get('repairs', []):
            if candidate.get('error_type') != d['error_type']: continue
            if not candidate.get('hypothesis') or not candidate.get('reason'): continue
            if not re.search(candidate.get('when_output', r'(?!)'), result['output']): continue
            if not re.search(candidate.get('when_prompt', r'(?!)'), self.process.prompt or ''): continue
            if candidate.get('command') in tried: continue
            return candidate
        if d['error_type'] == 'TUI_PATH_ERROR': return self._path_repair(result['command'], step)
        return None

    def _execute_input(self, entry, step, label):
        combined = {**step, **entry}
        command, kind = entry['command'], entry.get('kind', 'tui')
        history = getattr(self, '_attempt_history', {})
        self._attempt_history = history
        key = (self.plan_id, label)
        past = history.setdefault(key, [])
        if past:
            result = past[-1]
        else:
            result = self.exchange(command, kind=kind, item=combined, step=label)
            past.append(result)
        retries = min(int(step.get('max_auto_retries', self.config.get('max_auto_retries', 3))), int(self.config.get('max_auto_retries', 3)))
        if retries < 0: raise ValueError('max_auto_retries cannot be negative')
        tried = {x['command'] for x in past}
        for attempt in range(max(0, retries - (len(past) - 1)) if step.get('retry', False) else 0):
            if result['success']: break
            candidate = self._repair_candidate(combined, result, tried)
            if not candidate or candidate['command'] in tried: break
            candidate_item = {**combined, **{k: candidate[k] for k in ('expect_prompt',) if k in candidate}}
            fixed = self.exchange(candidate['command'], kind=candidate.get('kind', kind), item=candidate_item, step=label, retry=True)
            self.log.append('corrections.jsonl', {'timestamp': now(), 'step': label, 'attempt': attempt + 2,
                            'original_command': result['command'], 'error': result.get('diagnosis'),
                            'hypothesis': candidate['hypothesis'], 'modified_command': candidate['command'],
                            'reason': candidate['reason'], 'evidence': candidate.get('evidence'), 'result': fixed})
            tried.add(candidate['command']); result = fixed; past.append(fixed)
        return result

    def execute_plan(self, plan):
        if not isinstance(plan.get('steps'), list) or not plan['steps']: raise ValueError('steps must be a nonempty list')
        ids = [s['id'] for s in plan['steps']]
        if len(set(ids)) != len(ids): raise ValueError('step ids must be unique')
        pid = plan.get('id') or uuid.uuid4().hex
        plans = getattr(self, '_plans', {})
        self._plans = plans
        old_plan = plans.get(pid)
        revision = None
        if old_plan is not None and old_plan != plan:
            revision = {'timestamp': now(), 'type': 'plan_revision', 'step': self.last_successful_step,
                        'original_command': json.dumps(old_plan, ensure_ascii=False),
                        'error': self.last_result, 'hypothesis': plan.get('revision_hypothesis', plan.get('notes', 'Not supplied; inspect recorded plan difference')),
                        'modified_command': json.dumps(plan, ensure_ascii=False),
                        'reason': 'Codex revised the remaining plan after observing the current session.'}
        plans[pid] = json.loads(json.dumps(plan))
        plan_dir = self.log.path / 'plans'; plan_dir.mkdir(exist_ok=True)
        (plan_dir / (uuid.uuid4().hex + '.json')).write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
        if self.plan_id != pid:
            self.plan_id, self.completed, self.last_successful_step = pid, {}, None
        self.busy = True
        try:
            for step in plan['steps']:
                sid = step['id']
                if sid in self.completed: continue
                checkpointed = getattr(self, '_checkpointed_steps', set())
                self._checkpointed_steps = checkpointed
                if step.get('checkpoint_before') and (pid, sid) not in checkpointed:
                    self.checkpoint(step['checkpoint_before']); checkpointed.add((pid, sid))
                entries = step.get('inputs') or [{'command': step['command'], 'kind': step.get('kind', 'tui')}]
                # Remember completed inputs for resuming the FAILED step inside its sub-prompt.
                done = getattr(self, '_input_progress', {})
                self._input_progress = done
                key = (pid, sid)
                result = None
                for i, entry in enumerate(entries):
                    if i < done.get(key, 0):
                        result = self._attempt_history[(pid, f'{sid}:{i}')][-1]
                        continue
                    if entry.get('expect_prompt') and not re.search(entry['expect_prompt'], self.process.prompt or ''):
                        raise ValueError(f'{sid}[{i}] prompt mismatch: {self.process.prompt!r}')
                    result = self._execute_input(entry, step, f'{sid}:{i}')
                    if not result['success']:
                        report = self.summary('needs_decision', result); self.log.report(report); return report
                    done[key] = i + 1
                    warnings = [e['text'] for e in result['observation']['events'] if 'WARNING' in e['types']]
                    if warnings and not all(re.search(step.get('allow_warning_regex', r'(?!)'), w) for w in warnings): break
                warnings = [e['text'] for i in range(done.get(key, 0))
                            for e in self._attempt_history[(pid, f'{sid}:{i}')][-1]['observation']['events'] if 'WARNING' in e['types']]
                if warnings and not all(re.search(step.get('allow_warning_regex', r'(?!)'), w) for w in warnings):
                    report = self.summary('needs_decision', {'reason': 'Review real warnings before accepting this step; do not resend the command.', 'warnings': warnings, 'last_exchange': result})
                    self.log.report(report); return report
                expected = step.get('expect', 'prompt')
                passed = self.process.state in MENU_STATES if expected == 'prompt' else bool(re.search(expected, self.process.prompt or ''))
                if step.get('verify_output_regex'):
                    passed = passed and bool(re.search(step['verify_output_regex'], result['output']))
                if not passed:
                    report = self.summary('needs_decision', {'reason': 'Step postcondition unverified; supply the pending prompt response or a read-only verification.', 'step': sid, 'last_exchange': result})
                    self.log.report(report); return report
                for verify in step.get('verify', []):
                    if verify.get('risk', 'READ_ONLY') != 'READ_ONLY': raise ValueError('Verification must be read-only')
                    vr = self.exchange(verify['command'], item={**verify, 'risk': 'READ_ONLY'}, step=f'{sid}:verify')
                    if not vr['success'] or not re.search(verify['output_regex'], vr['output']):
                        report = self.summary('needs_decision', {'reason': 'CFD postcondition not proven', 'verification': vr})
                        self.log.report(report); return report
                self.completed[sid] = {'timestamp': now(), 'result': result}
                self.last_successful_step = sid
                self.log.report(self.summary('running'))
            report = self.summary('completed'); self.log.report(report); return report
        except Exception as e:
            report = self.summary('needs_decision', {'exception': type(e).__name__, 'reason': str(e)})
            self.log.event('plan-stopped', report); self.log.report(report); return report
        finally:
            self.busy = False
            if revision:
                revision['result'] = self.summary('plan_revision_observed', self.last_result)
                self.log.append('corrections.jsonl', revision)

    def checkpoint(self, name='checkpoint'):
        if self.process.state not in MENU_STATES: raise ValueError('Checkpoint requires a menu prompt')
        if not re.fullmatch(r'[A-Za-z0-9_-]+', name): raise ValueError('Checkpoint name must be a simple identifier')
        directory = self.log.path / 'checkpoints' / (name + '_' + uuid.uuid4().hex[:8])
        directory.mkdir(parents=True, exist_ok=False)
        path = directory / 'state.cas.h5'
        # New private path only. No overwrite prompt is answered automatically.
        cmd = f'/file/write-case-data "{path.as_posix()}"'
        result = self.exchange(cmd, item={'risk': 'DESTRUCTIVE', 'allow_destructive': True}, step=f'checkpoint:{name}')
        data = directory / 'state.dat.h5'
        if not result['success'] or self.process.state not in MENU_STATES or not all(p.is_file() and p.stat().st_size for p in (path, data)):
            raise RuntimeError('Checkpoint write not verified by Fluent output and nonempty case/data files')
        record = {'name': name, 'case': str(path), 'data': str(data), 'timestamp': now(), 'last_successful_step': self.last_successful_step,
                  'solution_valid': self.solution_valid, 'completed': dict(self.completed), 'plan_id': self.plan_id}
        (directory / 'checkpoint.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
        self.checkpoints[name] = record; self.modified = False
        self.log.event('checkpoint', record); return record

    def rollback(self, name, *, authorized=False):
        if not authorized: raise PermissionError('Rollback replaces the current Fluent state; requires a specific recovery decision')
        cp = self.checkpoints[name]
        for key in ('case', 'data'):
            if not Path(cp[key]).is_file(): raise FileNotFoundError(cp[key])
        result = self.exchange(f'/file/read-case-data "{Path(cp["case"]).as_posix()}"',
                               item={'in_user_goal': True}, step=f'rollback:{name}')
        if result['success'] and re.fullmatch(r'OK to discard\? \[cancel\]', self.process.prompt or '', re.I):
            result = self.exchange('ok', kind='response', item={'expect_prompt': r'^OK to discard\? \[cancel\]$', 'in_user_goal': True, 'allow_destructive': True}, step=f'rollback:{name}:discard-current')
        if not result['success'] or result['state_after'] not in MENU_STATES: raise RuntimeError('Rollback was not confirmed')
        self.plan_id, self.completed, self.last_successful_step = cp['plan_id'], cp['completed'], cp['last_successful_step']
        self.solution_valid = cp['solution_valid']; self._input_progress = {}
        self._attempt_history = {}; self.modified = False
        self.log.event('rollback', {'checkpoint': cp, 'result': result}); return result
