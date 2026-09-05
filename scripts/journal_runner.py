"""Isolated journal transactions, transcripts and completion evidence. Author: Manuel Sun."""
from __future__ import annotations
import json, re, time, uuid
from pathlib import Path
try:
    from .fluent_process import FluentProcess, build_argv
    from .fluent_parser import parse_output, clean
    from .fluent_error_analyzer import analyze
    from .fluent_common import TaskLog, now
except ImportError:
    from fluent_process import FluentProcess, build_argv
    from fluent_parser import parse_output, clean
    from fluent_error_analyzer import analyze
    from fluent_common import TaskLog, now

class JournalRunner:
    def __init__(self, config, log=None):
        self.config = config
        self.log = log or TaskLog(config['logs_root'], 'journal')

    def run(self, journal, *, text=None, timeout=None, initial_case_data=None, save_case_data=False, verify_output_regex=None, allow_warning_regex=None):
        # Every run uses an exclusive new directory. Input is preserved byte-for-byte in source.jou.
        n = 1
        while True:
            run = self.log.path / f'run_{n:04d}'
            try: run.mkdir(exist_ok=False); break
            except FileExistsError: n += 1
        if text is None:
            source = Path(journal).resolve()
            payload = source.read_bytes()
            body = payload.decode(self.config.get('journal_encoding', 'utf-8-sig'))
        else: body, payload = text, text.encode('utf-8')
        (run / 'source.jou').write_bytes(payload)
        marker = 'CODEX_JOURNAL_COMPLETE_' + uuid.uuid4().hex
        transcript = run / 'transcript.trn'
        checkpoint = run / 'checkpoint.cas.h5'
        prefix = [f'/file/start-transcript "{transcript.as_posix()}"']
        if initial_case_data:
            initial = Path(initial_case_data).resolve()
            if not initial.is_file(): raise FileNotFoundError(initial)
            prefix.append(f'/file/read-case-data "{initial.as_posix()}"')
        suffix = []
        if save_case_data: suffix.append(f'/file/write-case-data "{checkpoint.as_posix()}"')
        suffix.extend([f'(display "{marker}")', '(newline)', '/file/stop-transcript', '/exit yes'])
        command_file = run / 'command.jou'
        command_file.write_text('; Author: Manuel Sun\n' + '\n'.join(prefix) + '\n' + body + '\n' + '\n'.join(suffix) + '\n', encoding=self.config.get('journal_encoding', 'utf-8'), newline='\n')
        # Run in requested working_directory so relative paths in original journals retain their meaning.
        def mirror(name, chunk):
            with self.log.lock, (self.log.path / f'{name}.log').open('a', encoding='utf-8') as f: f.write(chunk)
        p = FluentProcess(self.config, run, on_output=mirror)
        output, timed_out = '', False
        result = None
        try:
            p._launch('pipe', command_file)
            self.log.event('journal-launch', {'pid': p.pid, 'argv': build_argv(self.config, command_file), 'run': str(run)})
            deadline = time.monotonic() + float(timeout or self.config.get('journal_timeout', 300))
            while p.is_alive() and time.monotonic() < deadline:
                output += p.read_available(); time.sleep(.05)
            timed_out = p.is_alive()
            if timed_out:
                # Batch transaction owns a fresh process; persist failure, then terminate only its tree.
                p.close(force=True)
            for thread in p.threads: thread.join(timeout=2)
            output += p.read_available()
            trn = transcript.read_text(encoding=self.config.get('encoding', 'utf-8'), errors='replace') if transcript.exists() else ''
            # The stdout and transcript may duplicate events. Both originals remain available.
            evidence = output + '\n--- transcript ---\n' + trn
            obs = parse_output(evidence, timed_out=timed_out, process_alive=not timed_out)
            emitted = bool(re.search(r'^\s*' + re.escape(marker) + r'\s*$', clean(output), re.M) or
                           re.search(r'^\s*' + re.escape(marker) + r'\s*$', clean(trn), re.M))
            runtime_version = bool(re.search(r'Fluent (?:2022 R1|22\.1)', output + trn))
            files_ok = not save_case_data or all(x.is_file() and x.stat().st_size for x in [checkpoint, run / 'checkpoint.dat.h5'])
            warnings = [e['text'] for e in obs.events if 'WARNING' in e['types']]
            warnings_ok = all(re.search(allow_warning_regex or r'(?!)', w) for w in warnings)
            postcondition_ok = not verify_output_regex or bool(re.search(verify_output_regex, evidence))
            code = p.process.poll()
            success = bool(runtime_version and emitted and not obs.error_lines and not timed_out and code == 0 and files_ok and warnings_ok and postcondition_ok)
            result = {'success': success, 'timestamp': now(), 'run_dir': str(run), 'exit_code': code,
                      'timed_out': timed_out, 'runtime_v221': runtime_version, 'completion_marker_observed': emitted,
                      'warnings': warnings, 'warnings_accepted': warnings_ok, 'postcondition_verified': postcondition_ok,
                      'stdout': str(run / 'stdout.log'), 'stderr': str(run / 'stderr.log'),
                      'transcript': str(transcript) if transcript.exists() else None, 'observation': obs.to_dict(),
                      'checkpoint': str(checkpoint) if save_case_data and files_ok and success else None}
            if not success:
                result['diagnosis'] = analyze(body, None, parse_output(evidence, timed_out=timed_out, process_alive=code == 0 and not timed_out))
                self.log.append('errors.jsonl', result['diagnosis'])
        except Exception as e:
            result = {'success': False, 'run_dir': str(run), 'error': str(e), 'error_type': 'PROCESS_ERROR'}
            if p.is_alive(): p.close(force=True)
        finally:
            if p.process and not p.is_alive(): p.close()
            if result is not None:
                (run / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
                self.log.append('commands.jsonl', {'timestamp': now(), 'step': 'journal', 'command': body,
                                'state_before': 'NEW_PROCESS', 'output': output, 'state_after': 'EXITED', 'success': result['success']})
                self.log.report(result)
        return result

    def execute_plan(self, plan):
        """Each successful transaction commits a checkpoint; resume skips prior successful steps.

        Conditional prompt workflows require interactive mode. Journal inputs must have been
        recorded/verified for v221. Failed transactions are never blindly re-run.
        """
        try:
            from .fluent_session import check_scope, infer_risk
        except ImportError:
            from fluent_session import check_scope, infer_risk
        if not plan.get('journal_checkpoint_each_step'):
            raise ValueError('Journal plans require journal_checkpoint_each_step=true to preserve state between fresh processes; group expensive operations deliberately')
        resume = self.log.path / 'journal_progress.json'
        progress = json.loads(resume.read_text()) if resume.exists() else {'plan_id': plan.get('id'), 'completed': [], 'checkpoint': plan.get('initial_case_data'), 'last_successful_step': None}
        if progress['plan_id'] != plan.get('id'): raise ValueError('Resume plan id mismatch')
        for step in plan['steps']:
            if step['id'] in progress['completed']: continue
            if step.get('inputs'): raise ValueError('Conditional inputs need interactive mode; use a verified journal transaction for this step')
            if not step.get('journal_verified_v221'): raise ValueError('Journal step requires journal_verified_v221=true, grounded in a recorded/observed v221 sequence')
            body = Path(step['journal']).read_text(encoding='utf-8-sig') if step.get('journal') else step['command']
            check_scope(step, body, solution_valid=bool(progress['checkpoint']))
            destructive_lines = [line for line in body.splitlines() if line.strip() and not line.lstrip().startswith(';') and infer_risk(line, bool(progress['checkpoint'])) == 'DESTRUCTIVE']
            for line in destructive_lines: check_scope(step, line, solution_valid=bool(progress['checkpoint']))
            histories = progress.setdefault('attempts', {})
            history = histories.setdefault(step['id'], [])
            max_attempts = 1 + min(int(step.get('max_auto_retries', self.config.get('max_auto_retries', 3))), int(self.config.get('max_auto_retries', 3)))
            if len(history) >= max_attempts:
                report = {'status': 'needs_decision', **progress, 'reason': 'Journal retry budget exhausted; checkpoint and logs retained'}
                self.log.report(report); return report
            if history and body == history[-1]['body']:
                report = {'status': 'needs_decision', **progress, 'reason': 'Unchanged failed journal will not be repeated. Supply an evidence-based single-line repair.'}
                self.log.report(report); return report
            result = self.run(None, text=body, initial_case_data=progress['checkpoint'], save_case_data=True, timeout=step.get('timeout'), verify_output_regex=step.get('verify_output_regex'), allow_warning_regex=step.get('allow_warning_regex'))
            history.append({'body': body, 'run_dir': result['run_dir'], 'success': result['success']})
            resume.write_text(json.dumps(progress, indent=2), encoding='utf-8')
            while not result['success'] and not destructive_lines and step.get('retry') and step.get('transaction_replay_safe') and len(history) < max_attempts:
                diagnosis = result.get('diagnosis', {})
                if not diagnosis.get('safe_to_retry'): break
                candidate = None
                for repair in step.get('repairs', []):
                    if repair.get('error_type') != diagnosis.get('error_type') or not repair.get('hypothesis') or not repair.get('reason'): continue
                    if not re.search(repair.get('when_output', r'(?!)'), result.get('observation', {}).get('output', '')): continue
                    lines = body.splitlines(); index = int(repair.get('line_number', 0)) - 1
                    if not 0 <= index < len(lines) or lines[index] != repair.get('expected_line'): continue
                    replacement = repair.get('replacement', '')
                    if '\n' in replacement or '\r' in replacement: continue
                    lines[index] = replacement; amended = '\n'.join(lines)
                    if any(x['body'] == amended for x in history): continue
                    check_scope(step, replacement, solution_valid=bool(progress['checkpoint']), retry=True)
                    candidate = repair, amended; break
                if not candidate: break
                repair, amended = candidate
                fixed = self.run(None, text=amended, initial_case_data=progress['checkpoint'], save_case_data=True, timeout=step.get('timeout'), verify_output_regex=step.get('verify_output_regex'), allow_warning_regex=step.get('allow_warning_regex'))
                self.log.append('corrections.jsonl', {'timestamp': now(), 'step': step['id'], 'original_command': body, 'error': diagnosis,
                    'hypothesis': repair['hypothesis'], 'modified_command': amended, 'reason': repair['reason'], 'result': fixed})
                body, result = amended, fixed
                history.append({'body': body, 'run_dir': result['run_dir'], 'success': result['success']})
                resume.write_text(json.dumps(progress, indent=2), encoding='utf-8')
            if not result['success']:
                report = {'status': 'needs_decision', **progress, 'failed_step': step['id'], 'result': result,
                          'reason': 'Inspect result and repair only this journal transaction. Resume from the last successful checkpoint.'}
                self.log.report(report); return report
            progress['checkpoint'] = result['checkpoint']; progress['completed'].append(step['id']); progress['last_successful_step'] = step['id']
            resume.write_text(json.dumps(progress, indent=2), encoding='utf-8')
        report = {'status': 'completed', **progress}; self.log.report(report); return report
