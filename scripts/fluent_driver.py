"""Unified local CLI and persistent JSON/HTTP broker. Author: Manuel Sun."""
from __future__ import annotations
import argparse, hmac, json, os, secrets, subprocess, sys, threading, time, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
try:
    from .fluent_common import DEFAULT_CONFIG, load_config, TaskLog
    from .fluent_discovery import discover, save_discovery, validate_executable
    from .fluent_process import FluentProcess
    from .fluent_session import FluentSession
    from .journal_runner import JournalRunner
except ImportError:
    from fluent_common import DEFAULT_CONFIG, load_config, TaskLog
    from fluent_discovery import discover, save_discovery, validate_executable
    from fluent_process import FluentProcess
    from fluent_session import FluentSession
    from journal_runner import JournalRunner

def emit(value): print(json.dumps(value, ensure_ascii=False, indent=2), flush=True)

def ensure_executable(config):
    if not config.get('executable') or not validate_executable(config['executable'])['valid_v221']:
        found = discover(config)
        if not found['selected']: raise FileNotFoundError(json.dumps(found, ensure_ascii=False))
        save_discovery(config['_config_path'], found)
        config['executable'] = found['selected']['executable']
    return config

def rpc(config, action, payload=None, timeout=30):
    meta = json.loads(Path(config['session_file']).read_text(encoding='utf-8'))
    url = f'http://127.0.0.1:{int(meta["port"])}/{action}'
    request = urllib.request.Request(url, data=json.dumps(payload or {}).encode('utf-8'), headers={'Authorization': 'Bearer ' + meta['token'], 'Content-Type': 'application/json'})
    # Local broker must never go through corporate HTTP proxies.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response: result = json.load(response)
    if not result.get('ok'): raise RuntimeError(result.get('error', result))
    return result['result']

def serve(config):
    log = TaskLog(config['logs_root'], config.get('task_name', 'interactive'))
    process = FluentProcess(config, log.path)
    session = FluentSession(process, log, config)
    lock = threading.Lock()
    startup = {'initializing': True}
    token = secrets.token_hex(32)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            if not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + token):
                self.send_error(403); return
            acquired = False
            try:
                size = int(self.headers.get('Content-Length', 0))
                if size > 8 * 1024 * 1024: raise ValueError('Request too large')
                body = json.loads(self.rfile.read(size))
                action = self.path.strip('/')
                if action == 'status':
                    result = {**session.status(), **startup}
                    result['available'] = bool(process.available and process.is_alive())
                else:
                    acquired = lock.acquire(blocking=False)
                    if not acquired or startup['initializing']: raise RuntimeError('Session is busy; inspect status and live log files')
                    if action == 'send': result = session.exchange(body['command'], kind=body.get('kind', 'tui'), item=body, step=body.get('step', 'manual'))
                    elif action == 'observe': result = session.observe(body.get('wait', False), body.get('timeout'))
                    elif action == 'execute-plan': result = session.execute_plan(body)
                    elif action == 'checkpoint': result = session.checkpoint(body.get('name', 'checkpoint'))
                    elif action == 'rollback': result = session.rollback(body['name'], authorized=body.get('authorized', False))
                    elif action == 'interrupt':
                        result = process.interrupt(); log.event('interrupt', result)
                    elif action == 'stop':
                        if session.modified and not body.get('discard') and not body.get('force'):
                            raise ValueError('Unsaved state may exist. Save a checkpoint or use stop --discard when closing without saving is authorized')
                        log.event('stop-request', body)
                        result = process.close(force=body.get('force', False))
                        log.report(session.summary('closed' if result['closed'] else 'needs_decision', result))
                        if result['closed']: threading.Thread(target=self.server.shutdown, daemon=True).start()
                    else: raise ValueError('Unknown action')
                response = {'ok': True, 'result': result}
            except Exception as e:
                log.event('broker-error', {'error': str(e), 'type': type(e).__name__})
                response = {'ok': False, 'error': str(e), 'type': type(e).__name__}
            finally:
                if acquired: lock.release()
            payload = json.dumps(response, ensure_ascii=False).encode('utf-8')
            try:
                self.send_response(200); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(payload))); self.end_headers(); self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError): pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    session_file = Path(config['session_file']); session_file.parent.mkdir(parents=True, exist_ok=True)
    meta = {'pid': os.getpid(), 'port': server.server_port, 'token': token, 'log_dir': str(log.path), 'config': config['_config_path']}
    # Exclusive local metadata; no external listeners, arbitrary evaluation or pickle RPC.
    with os.fdopen(os.open(session_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'w', encoding='utf-8') as f: json.dump(meta, f)
    def initialize():
        with lock:
            try:
                startup.update(process.start())
                log.event('backend-verification', startup)
                for attempt in startup.get('attempts', []):
                    for key in ('startup', 'probe'):
                        if key in attempt:
                            log.append('commands.jsonl', {'timestamp': __import__('datetime').datetime.now().isoformat(), 'step': key,
                                'command': attempt.get('probe_command') if key == 'probe' else '<launch>', 'state_before': 'UNKNOWN',
                                'output': attempt[key]['output'], 'state_after': attempt[key]['state'], 'success': attempt[key]['success']})
                log.report(session.summary('ready' if process.available else 'interactive_unavailable', startup))
            except Exception as e: startup.update({'available': False, 'error': str(e), 'fallback': 'journal'})
            finally: startup['initializing'] = False
    threading.Thread(target=initialize, daemon=True).start()
    try: server.serve_forever(poll_interval=.2)
    finally:
        server.server_close()
        # Normal shutdown occurs only after a verified stop. Never auto-discard on retry exhaustion.
        if session_file.exists() and json.loads(session_file.read_text())['token'] == token: session_file.unlink()

def start(config):
    file = Path(config['session_file'])
    if file.exists():
        try: return rpc(config, 'status')
        except Exception as e: raise RuntimeError(f'Session metadata exists but broker is unreachable: {file}. Check its PID/logs before using clear-session. {e}')
    lockfile = file.with_suffix(file.suffix + '.start-lock')
    lockfile.parent.mkdir(parents=True, exist_ok=True)
    try: fd = os.open(lockfile, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError: raise RuntimeError(f'Startup lock exists: {lockfile}; inspect prior starter before clearing')
    os.close(fd)
    try:
        logpath = Path(config['logs_root']); logpath.mkdir(parents=True, exist_ok=True)
        broker_log = logpath / ('broker_' + secrets.token_hex(5) + '.log')
        with broker_log.open('w', encoding='utf-8') as f:
            child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--config', config['_config_path'], '_serve'],
                    stdin=subprocess.DEVNULL, stdout=f, stderr=f, cwd=str(Path(__file__).resolve().parents[1]),
                    creationflags=(subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == 'nt' else 0,
                    start_new_session=os.name != 'nt')
        deadline = time.monotonic() + config.get('startup_timeout', 120) * 2 + 90
        while time.monotonic() < deadline:
            if child.poll() is not None: raise RuntimeError(f'Broker exited {child.returncode}; see {broker_log}')
            if file.exists():
                try:
                    status = rpc(config, 'status', timeout=3)
                    if not status['initializing']: return status
                except (OSError, ValueError): pass
            time.sleep(.3)
        return {'available': False, 'initializing': True, 'reason': 'Startup still running; use status', 'broker_pid': child.pid, 'broker_log': str(broker_log)}
    finally: lockfile.unlink(missing_ok=True)

def main(argv=None):
    parser = argparse.ArgumentParser(description='Fluent 2022 R1 TUI feedback agent (no PyFluent)')
    parser.add_argument('--config', default=str(DEFAULT_CONFIG))
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('discover').add_argument('--save', action='store_true')
    for action in ('start', 'status', '_serve', 'interrupt'): sub.add_parser(action)
    p = sub.add_parser('send'); p.add_argument('command'); p.add_argument('--kind', choices=['tui', 'response', 'scheme', 'menu_control'], default='tui'); p.add_argument('--expect-prompt'); p.add_argument('--in-goal', action='store_true'); p.add_argument('--allow-destructive', action='store_true'); p.add_argument('--risk', choices=['READ_ONLY', 'LOW_RISK', 'STATE_CHANGING', 'DESTRUCTIVE']); p.add_argument('--risk-evidence'); p.add_argument('--timeout', type=float)
    p = sub.add_parser('observe'); p.add_argument('--wait', action='store_true'); p.add_argument('--timeout', type=float, default=30)
    p = sub.add_parser('stop'); p.add_argument('--force', action='store_true'); p.add_argument('--discard', action='store_true')
    p = sub.add_parser('execute-plan'); p.add_argument('plan'); p.add_argument('--backend', choices=['interactive', 'journal'], default='interactive'); p.add_argument('--resume-log')
    p = sub.add_parser('run-journal'); p.add_argument('journal'); p.add_argument('--timeout', type=float); p.add_argument('--reviewed', action='store_true', help='Journal side effects have been reviewed against the user goal')
    p = sub.add_parser('checkpoint'); p.add_argument('name')
    p = sub.add_parser('rollback'); p.add_argument('name'); p.add_argument('--authorized', action='store_true')
    p = sub.add_parser('diagnose'); p.add_argument('output_file'); p.add_argument('--command', default=''); p.add_argument('--before')
    p = sub.add_parser('clear-session'); p.add_argument('--confirmed-stopped', action='store_true')
    args = parser.parse_args(argv); config = load_config(args.config)
    try:
        if args.action == 'discover':
            result = discover(config)
            if args.save: save_discovery(args.config, result)
        elif args.action in ('start', '_serve'):
            ensure_executable(config)
            if args.action == '_serve': serve(config); return 0
            result = start(config)
        elif args.action == 'diagnose':
            try:
                from .fluent_error_analyzer import analyze
                from .fluent_parser import parse_output
            except ImportError:
                from fluent_error_analyzer import analyze
                from fluent_parser import parse_output
            result = analyze(args.command, args.before, parse_output(Path(args.output_file).read_text(encoding='utf-8-sig', errors='replace')))
        elif args.action == 'run-journal':
            if not args.reviewed: raise ValueError('Inspect the journal for writes, deletes, model changes and exit commands; use --reviewed when already authorized by the user goal')
            result = JournalRunner(ensure_executable(config)).run(args.journal, timeout=args.timeout)
        elif args.action == 'execute-plan':
            plan = json.loads(Path(args.plan).read_text(encoding='utf-8-sig'))
            if args.backend == 'journal':
                log = TaskLog(args.resume_log, existing=True) if args.resume_log else None
                result = JournalRunner(ensure_executable(config), log).execute_plan(plan)
            else: result = rpc(config, 'execute-plan', plan, timeout=float(plan.get('client_timeout', 86400)))
        elif args.action == 'clear-session':
            if not args.confirmed_stopped: raise ValueError('Inspect recorded broker and Fluent PIDs before clearing dead session metadata')
            try: rpc(config, 'status'); raise ValueError('Broker still alive; use stop')
            except (OSError, FileNotFoundError): pass
            Path(config['session_file']).unlink(missing_ok=True)
            Path(config['session_file'] + '.start-lock').unlink(missing_ok=True)
            result = {'cleared': True}
        else:
            body = {k: v for k, v in vars(args).items() if v is not None and k not in ('action', 'config')}
            body['in_user_goal'] = body.pop('in_goal', False)
            result = rpc(config, args.action, body, timeout=max(45, float(body.get('timeout', 30)) + 15))
        emit(result)
        return 2 if (result.get('success') is False or result.get('status') == 'needs_decision' or result.get('available') is False) else 0
    except Exception as e:
        emit({'success': False, 'error': str(e), 'type': type(e).__name__}); return 2

if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    raise SystemExit(main())
