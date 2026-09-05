"""Configuration and append-only task evidence. Author: Manuel Sun."""
import datetime, json, re, threading, uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / 'config' / 'fluent_config.json'

def now(): return datetime.datetime.now().astimezone().isoformat(timespec='milliseconds')
def load_config(path=DEFAULT_CONFIG):
    p = Path(path).resolve()
    c = json.loads(p.read_text(encoding='utf-8-sig')) if p.exists() else {}
    for key in ('working_directory', 'logs_root', 'session_file'):
        if c.get(key): c[key] = str((p.parent / c[key]).resolve())
    c.setdefault('logs_root', str(ROOT / 'logs'))
    c.setdefault('session_file', str(p.with_suffix('.session.json')))
    c['_config_path'] = str(p)
    return c

class TaskLog:
    def __init__(self, root, name='task', existing=False):
        self.path = Path(root) if existing else Path(root) / (datetime.datetime.now().strftime('%Y%m%d_%H%M%S_') + re.sub(r'[^\w-]', '_', name) + '_' + uuid.uuid4().hex[:6])
        self.path.mkdir(parents=True, exist_ok=existing)
        self.lock = threading.RLock()
        for f in ('session.log', 'commands.jsonl', 'stdout.log', 'stderr.log', 'errors.jsonl', 'corrections.jsonl'):
            (self.path / f).touch(exist_ok=True)
        self.event('task-open', {'author': 'Manuel Sun'})

    def event(self, kind, data):
        self.append('session.log', {'timestamp': now(), 'event': kind, 'data': data})

    def append(self, filename, data):
        with self.lock, (self.path / filename).open('a', encoding='utf-8') as f:
            f.write(json.dumps(data, ensure_ascii=False) + '\n')

    def report(self, report):
        with self.lock:
            (self.path / 'final_report.md').write_text('# Fluent task report\n\nAuthor: Manuel Sun\n\n```json\n' + json.dumps(report, ensure_ascii=False, indent=2) + '\n```\n', encoding='utf-8')
            (self.path / 'progress.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
