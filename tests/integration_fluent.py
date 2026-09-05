"""Non-destructive REAL Fluent/CLI integration, never silently mock. Author: Manuel Sun."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from fluent_common import load_config, TaskLog
from fluent_discovery import discover
from fluent_driver import start, rpc
from journal_runner import JournalRunner

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--config',default=str(ROOT/'config/fluent_config.json'));a=ap.parse_args()
    config=load_config(a.config); discovery=discover(config)
    log=TaskLog(config['logs_root'],'real_integration')
    report={'author':'Manuel Sun','discovery':discovery,'tests':{},'log_dir':str(log.path)}
    if not discovery['selected']:
        report['status']='NOT VERIFIED WITH REAL FLUENT';log.report(report);print(json.dumps(report,indent=2));return 3
    config['executable']=discovery['selected']['executable']
    config['working_directory']=str(log.path/'solver-work')
    config['session_file']=str(log.path/'test.session.json')
    config['logs_root']=str(log.path)
    cp=log.path/'test_config.json';config['_config_path']=str(cp)
    cp.write_text(json.dumps({k:v for k,v in config.items() if not k.startswith('_')},indent=2),encoding='utf-8')
    session_config=load_config(cp)
    try:
        s=start(session_config)
        report['tests']['startup_root_query']={'passed':s.get('available') is True,'transport':s.get('transport'),'attempts':s.get('attempts')}
        if not s.get('available'): raise RuntimeError('Real interactive startup failed; inspect attempt logs')
        result=rpc(session_config,'send',{'command':'/__codex_invalid_path__'})
        report['tests']['real_invalid_path']={'passed':not result['success'] and result.get('diagnosis',{}).get('error_type')=='TUI_PATH_ERROR','result':result}
        plan=json.loads((ROOT/'examples/recovery_plan.json').read_text())
        result=rpc(session_config,'execute-plan',plan)
        report['tests']['automatic_recovery']={'passed':result['status']=='completed','result':result}
        journal=JournalRunner(session_config).run(ROOT/'examples/safe_query.jou')
        report['tests']['journal_transcript']={'passed':journal['success'] and bool(journal['transcript']),'run_dir':journal['run_dir']}
        report['status']='PASSED' if all(t['passed'] for t in report['tests'].values()) else 'FAILED'
    except Exception as e:
        report['status']='FAILED';report['error']=str(e)
    finally:
        try:report['stop']=rpc(session_config,'stop',{'discard':True})
        except Exception as e:report['stop_error']=str(e)
        log.report(report)
    print(json.dumps({'status':report['status'],'log_dir':str(log.path),'tests':{k:v['passed'] for k,v in report['tests'].items()}},indent=2))
    return 0 if report['status']=='PASSED' else 2

if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8',errors='replace')
    raise SystemExit(main())
