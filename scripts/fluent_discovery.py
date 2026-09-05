"""Ordered Windows v221 discovery with version evidence. Author: Manuel Sun."""
from __future__ import annotations
import json, os, re, shutil, ctypes
from pathlib import Path

def file_version(path):
    if os.name != 'nt': return None
    try:
        from ctypes import wintypes as w
        lib = ctypes.WinDLL('version', use_last_error=True)
        lib.GetFileVersionInfoSizeW.argtypes = [w.LPCWSTR, ctypes.POINTER(w.DWORD)]
        lib.GetFileVersionInfoW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p]
        lib.VerQueryValueW.argtypes = [ctypes.c_void_p, w.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(w.UINT)]
        size = lib.GetFileVersionInfoSizeW(str(path), None)
        if not size: return None
        buf = ctypes.create_string_buffer(size)
        if not lib.GetFileVersionInfoW(str(path), 0, size, buf): return None
        ptr, length = ctypes.c_void_p(), w.UINT()
        if not lib.VerQueryValueW(buf, '\\', ctypes.byref(ptr), ctypes.byref(length)): return None
        values = ctypes.cast(ptr, ctypes.POINTER(w.DWORD))
        hi, lo = values[2], values[3]
        return f'{hi >> 16}.{hi & 65535}.{lo >> 16}.{lo & 65535}'
    except (OSError, ValueError): return None

def validate_executable(path):
    p = Path(os.path.expandvars(str(path))).expanduser().resolve()
    version = file_version(p) if p.is_file() else None
    v221 = any(x.lower() == 'v221' for x in p.parts)
    sibling = any((a / 'fluent22.1.0').is_dir() for a in list(p.parents)[:4])
    valid = p.is_file() and p.name.lower() == 'fluent.exe' and (version.startswith('22.1.') if version else (v221 and sibling))
    return {'executable': str(p), 'exists': p.is_file(), 'file_version': version,
            'v221_directory': v221, 'fluent22_1_payload': sibling, 'valid_v221': bool(valid),
            'verification': 'file_version' if version else 'directory_and_payload' if v221 and sibling else 'unverified'}

def discover(config=None, *, environ=None, common_roots=None):
    c, env = config or {}, os.environ if environ is None else environ
    candidates, roots, seen = [], [], set()
    def add(path, source):
        key = str(path).lower()
        if key in seen: return
        seen.add(key)
        d = validate_executable(path); d['source'] = source; candidates.append(d)
    def root(path, source):
        p = Path(os.path.expandvars(str(path)))
        if p.is_file(): add(p, source); return
        roots.append((p, source))
        for suffix in ('fluent/ntbin/win64/fluent.exe', 'ntbin/win64/fluent.exe', 'fluent.exe'):
            if (p / suffix).is_file(): add(p / suffix, source)
        for child in sorted(p.glob('v*/fluent/ntbin/win64/fluent.exe')) if p.is_dir() else []: add(child, source)
    if c.get('executable'): add(c['executable'], 'config.executable')
    for p in c.get('installation_roots', []): root(p, 'config.installation_roots')
    keys = sorted((k for k in env if re.match(r'(?i)AWP_ROOT|ANSYS.*DIR|FLUENT_ROOT|FLUENT_EXECUTABLE', k)), key=lambda k: ('221' not in k, k))
    for k in keys:
        root(env[k], f'env.{k}')
        if re.match(r'(?i)ANSYS221_DIR', k): root(Path(env[k]).parent, f'env.{k}.parent')
    if common_roots is None:
        common_roots = [f'{d}:/Program Files/ANSYS Inc' for d in 'CDEFGHIJKLMNOPQRSTUVWXYZ' if Path(f'{d}:/').exists()]
    for p in common_roots: root(p, 'common_path')
    for p in c.get('search_roots', []): root(p, 'config.search_roots')
    found = shutil.which('fluent.exe', path=env.get('PATH', ''))
    if found: add(found, 'PATH')
    # Bounded installation trees, not an unbounded whole-disk scan.
    max_depth = int(c.get('discovery_max_depth', 7))
    for base, source in roots:
        if not base.is_dir(): continue
        for folder, dirs, files in os.walk(base, followlinks=False):
            if len(Path(folder).relative_to(base).parts) >= max_depth: dirs[:] = []
            dirs[:] = [d for d in dirs if d.lower() not in ('node_modules', '.git', 'help', 'doc', 'msvc', 'clang')]
            for f in files:
                if f.lower() == 'fluent.exe': add(Path(folder) / f, source + '.search')
    valid = [x for x in candidates if x['valid_v221']]
    return {'target': 'ANSYS Fluent 2022 R1 (v221)', 'selected': valid[0] if valid else None,
            'candidates': candidates, 'searched_roots': [str(p) for p, _ in roots],
            'status': 'FOUND_V221' if valid else 'NOT_FOUND', 'author': 'Manuel Sun'}

def save_discovery(config_path, result):
    p = Path(config_path)
    c = json.loads(p.read_text(encoding='utf-8-sig')) if p.exists() else {}
    if result['selected']: c['executable'] = result['selected']['executable']
    c['discovery'] = result
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(c, ensure_ascii=False, indent=2), encoding='utf-8')
    return c
