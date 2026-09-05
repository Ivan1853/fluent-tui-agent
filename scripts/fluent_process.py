"""Persistent Fluent subprocess with fresh-output barriers. Author: Manuel Sun."""
from __future__ import annotations
import codecs, locale, os, queue, signal, subprocess, threading, time
from pathlib import Path
try:
    from .fluent_parser import parse_output
    from .windows_conpty import ConPTY
except ImportError:
    from fluent_parser import parse_output
    from windows_conpty import ConPTY

def build_argv(config, journal=None):
    dimension = config.get('dimension', '3d')
    precision = config.get('precision', 'double')
    if dimension not in ('2d', '3d') or precision not in ('single', 'double'): raise ValueError('Invalid dimension/precision')
    n = int(config.get('processors', 1))
    parallel = config.get('parallel', False)
    if n < 1 or (not parallel and n != 1): raise ValueError('serial requires processors=1; parallel requires processors>=1')
    argv = [str(config['executable']), dimension + ('dp' if precision == 'double' else '')]
    if not config.get('gui', False): argv.append('-g')
    # v221 uses a one-rank solver for the serial configuration on this workstation.
    argv.append(f'-t{n}')
    argv.extend(config.get('extra_args', []))
    if journal: argv.extend(['-i', str(Path(journal).resolve())])
    return argv

class FluentProcess:
    def __init__(self, config, log_dir, on_output=None):
        self.config, self.log_dir = dict(config), Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.cwd = Path(config.get('working_directory') or self.log_dir).resolve()
        self.cwd.mkdir(parents=True, exist_ok=True)
        self.process = None; self.transport = None; self.available = False
        self.queue = queue.Queue(); self.on_output = on_output
        self.prompt = None; self.state = 'UNKNOWN'; self.attempts = []
        self.threads = []

    @property
    def pid(self): return self.process.pid if self.process else None

    def _reader(self, stream, name, transport):
        encoding = 'utf-8' if transport == 'conpty' else self.config.get('encoding', locale.getpreferredencoding(False))
        decoder = codecs.getincrementaldecoder(encoding)(errors='replace')
        try:
            with (self.log_dir / f'{name}.log').open('a', encoding='utf-8', newline='') as f:
                while True:
                    data = stream.read() if transport == 'conpty' else os.read(stream.fileno(), 8192)
                    if not data: break
                    text = decoder.decode(data)
                    if text:
                        f.write(text); f.flush(); self.queue.put((name, text))
                        if self.on_output: self.on_output(name, text)
                tail = decoder.decode(b'', final=True)
                if tail: f.write(tail); f.flush(); self.queue.put((name, tail))
        except (OSError, ValueError) as e:
            self.queue.put(('stderr', f'\nReader closed: {e}\n'))

    def _launch(self, transport, journal=None):
        self.transport = transport
        argv = build_argv(self.config, journal)
        if transport == 'pipe':
            flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            self.process = subprocess.Popen(argv, cwd=self.cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                            stderr=subprocess.PIPE, bufsize=0, creationflags=flags,
                                            start_new_session=os.name != 'nt')
            streams = [(self.process.stdout, 'stdout'), (self.process.stderr, 'stderr')]
        elif transport == 'conpty':
            self.process = ConPTY(argv, self.cwd); streams = [(self.process, 'stdout')]
            (self.log_dir / 'stderr.log').touch(exist_ok=True)
        else: raise ValueError('transport must be auto, pipe or conpty')
        for stream, name in streams:
            thread = threading.Thread(target=self._reader, args=(stream, name, transport), daemon=True)
            thread.start(); self.threads.append(thread)

    def start(self):
        if self.is_alive(): raise RuntimeError('Already started')
        mode = self.config.get('transport', 'auto')
        modes = ['pipe', 'conpty'] if mode == 'auto' and os.name == 'nt' else ['pipe'] if mode == 'auto' else [mode]
        for mode in modes:
            try:
                self._launch(mode)
                startup = self.read_until_prompt(self.config.get('startup_timeout', 120))
                attempt = {'transport': mode, 'startup': startup.to_dict()}
                self.attempts.append(attempt)
                # Validate runtime identity, not just directory/version resource.
                if startup.state != 'ROOT' or not startup.success or not ('Fluent 2022 R1' in startup.output or 'Fluent 22.1' in startup.output):
                    raise RuntimeError('No verified v221 root prompt at startup')
                query = self.config.get('probe_command', '/report/system/sys-stats')
                self.send(query)
                probe = self.read_until_prompt(self.config.get('command_timeout', 30))
                attempt['probe_command'] = query; attempt['probe'] = probe.to_dict()
                # A bare/echoed prompt is insufficient: probe must produce configured evidence.
                import re
                evidence = self.config.get('probe_expect_regex', r'Hostname|CPU|System Mem')
                if not (probe.success and probe.state == 'ROOT' and re.search(evidence, probe.output)):
                    raise RuntimeError('Safe query did not yield expected output and root prompt')
                self.available = True
                return {'available': True, 'transport': mode, 'pid': self.pid, 'attempts': self.attempts}
            except Exception as e:
                self.attempts.append({'transport': mode, 'failure': str(e)})
                # Only a fresh, unused verification session is disposed here.
                if self.is_alive(): self.close(force=True)
                for thread in self.threads: thread.join(timeout=1)
                self.threads.clear(); self.process = None; self.queue = queue.Queue()
        return {'available': False, 'fallback': 'journal', 'attempts': self.attempts}

    def send(self, command):
        if not self.is_alive(): raise RuntimeError('Fluent process is not alive')
        if '\n' in command or '\r' in command: raise ValueError('send accepts exactly one input line')
        encoding = 'utf-8' if self.transport == 'conpty' else self.config.get('encoding', locale.getpreferredencoding(False))
        data = (command + ('\r\n' if self.transport == 'conpty' else '\n')).encode(encoding)
        if self.transport == 'conpty': self.process.write(data)
        else: self.process.stdin.write(data); self.process.stdin.flush()
        self.prompt = None; self.state = 'UNKNOWN'

    def read_available(self):
        chunks = []
        while True:
            try: chunks.append(self.queue.get_nowait()[1])
            except queue.Empty: break
        return ''.join(chunks)

    def read_until_prompt(self, timeout=None):
        deadline = time.monotonic() + float(timeout or self.config.get('command_timeout', 30))
        settle = float(self.config.get('prompt_settle_seconds', .25))
        output, changed = '', time.monotonic()
        while time.monotonic() < deadline:
            data = self.read_available()
            if data: output += data; changed = time.monotonic()
            alive = self.is_alive()
            obs = parse_output(output, process_alive=alive)
            if (obs.prompt and time.monotonic() - changed >= settle) or (not alive and time.monotonic() - changed >= settle):
                self.prompt, self.state = obs.prompt, obs.state
                return obs
            time.sleep(.03)
        obs = parse_output(output, timed_out=True, process_alive=self.is_alive())
        self.prompt, self.state = obs.prompt, obs.state
        return obs

    def is_alive(self): return bool(self.process and self.process.poll() is None)

    def interrupt(self):
        if not self.is_alive(): return {'interrupted': False, 'reason': 'not alive'}
        if self.transport == 'conpty': self.process.write(b'\x03'); return {'interrupted': True, 'verified': False}
        if os.name != 'nt': os.killpg(self.pid, signal.SIGINT); return {'interrupted': True, 'verified': False}
        # CREATE_NO_WINDOW PIPE has no console control event target. Do not fake Ctrl-C via stdin.
        return {'interrupted': False, 'reason': 'Windows PIPE has no reliable Ctrl-C channel; observe/wait, or explicitly stop --force. Use ConPTY when interrupts are required.'}

    def close(self, force=False):
        if not self.process: return {'closed': True}
        if self.is_alive() and not force:
            if self.state not in ('ROOT', 'MENU'): raise RuntimeError('Cannot gracefully exit from a sub-prompt; inspect/complete it or explicitly force stop')
            self.send('/exit yes')
            deadline = time.monotonic() + 15
            while self.is_alive() and time.monotonic() < deadline: time.sleep(.1)
            if self.is_alive(): return {'closed': False, 'reason': 'Exit not confirmed; session retained'}
        if self.is_alive() and force:
            if os.name == 'nt':
                r = subprocess.run(['taskkill', '/PID', str(self.pid), '/T', '/F'], capture_output=True)
                if r.returncode and self.is_alive(): raise OSError(r.stderr.decode(errors='replace'))
            else: os.killpg(self.pid, signal.SIGKILL)
        self.available = False
        if self.transport == 'conpty': self.process.close()
        else:
            for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
                try: stream.close()
                except OSError: pass
        return {'closed': not self.is_alive(), 'forced': force}
