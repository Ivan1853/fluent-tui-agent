"""MOCK ONLY: a deliberately small line-oriented solver fixture. Author: Manuel Sun."""
import os, sys, time
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
state = 'root'
def emit(t): sys.stdout.write(t); sys.stdout.flush()
def prompt():
    return {'root': '> ', 'menu': '/report/system> ', 'zone1': 'cell zone id/name(1) [()] ',
            'zone2': 'cell zone id/name(2) [()] ', 'variable': 'Variable> ',
            'bool': 'Use Custom Field Function for patching? [yes] ',
            'value': 'Value (constant or expression) (real) [0] '}[state]
def main():
    global state
    emit('Welcome to ANSYS Fluent 2022 R1 — MOCK ONLY\n')
    emit('>'); time.sleep(.03); emit(' ')
    for line in sys.stdin:
        cmd = line.rstrip('\r\n')
        if cmd == '/exit yes': break
        if cmd == '/crash': os._exit(17)
        if cmd == '/report/system/sys-stats': state='root'; emit('\nHostname CPU System Mem\n')
        elif cmd == '/report/system': state='menu'; emit('\nsys-stats proc-stats\n')
        elif cmd in ('', 'q') and state in ('root','menu'):
            state='root' if cmd=='q' else state; emit('\nsys-stats proc-stats\n')
        elif cmd.startswith('/report/system/sys-stat'): emit('invalid command [sys-stat]\n')
        elif cmd.startswith('/__codex_invalid_'): emit('invalid command [__codex_invalid_path__]\n')
        elif cmd == '/solve/patch': state='zone1'
        elif state in ('zone1','zone2'):
            if cmd=='()': emit('Unable to parse: [compound-procedure]\nError: undefined read macro\nError Object: ()\n')
            elif state=='zone1' and cmd=='fluid_nozzle': state='zone2'
            elif state=='zone2' and cmd=='': state='variable'
            else: emit('Error: invalid zone not found\nError Object: '+cmd+'\n')
        elif state=='variable':
            if cmd=='pressure': state='bool'
            else: emit('Error: invalid variable\n')
        elif state=='bool':
            if cmd=='no': state='value'
            else: emit('Error: yes or no expected\n')
        elif state=='value':
            if cmd=='486540': state='root'; emit('Done.\n')
            else: emit('Error: invalid comma/default input\n')
        elif cmd.startswith('/file/write-case-data '):
            p=Path(cmd.split(' ',1)[1].strip('"')); p.write_text('MOCK CASE'); p.with_name(p.name.replace('.cas.h5','.dat.h5')).write_text('MOCK DATA');emit('Done.\n');state='root'
        elif cmd.startswith('/file/read-case-data '): emit('Reading MOCK checkpoint\nDone.\n');state='root'
        elif cmd == '/slow':
            emit('Running\n');time.sleep(.7);emit('Done.\n');state='root'
        else: emit('invalid command ['+cmd+']\n')
        emit(prompt())

if __name__ == '__main__':
    main()
