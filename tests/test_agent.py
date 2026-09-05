"""Behavioral tests using real pipes to a MOCK solver. Author: Manuel Sun."""
import importlib, json, os, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
from fluent_parser import parse_output
from fluent_error_analyzer import analyze, ERROR_TYPES
from fluent_discovery import discover, validate_executable
from fluent_process import FluentProcess, build_argv
from fluent_session import FluentSession
from fluent_common import TaskLog
from journal_runner import JournalRunner

class ParserTests(unittest.TestCase):
    def test_full_context_and_scheme(self):
        t='Unable to parse: [compound-procedure]\nError: undefined read macro\nError Object: ()\n\n> '
        o=parse_output(t); self.assertFalse(o.success);self.assertEqual(o.state,'ROOT')
        d=analyze('()', 'cell zone id/name(2) [()]',o)
        self.assertEqual(d['error_type'],'SCHEME_PARSE_ERROR');self.assertEqual(d['error_objects'],['()']);self.assertEqual(d['context'],t)
    def test_states(self):
        for text,state in [('> ','ROOT'),('/solve> ','MENU'),('Variable>','COMMAND_ARGUMENT'),('cell zone id/name(1) [()]','ZONE_PROMPT'),('Use Custom Field Function for patching? [yes]','YES_NO_PROMPT'),('Value (constant or expression) (real) [0]','VALUE_PROMPT'),('scheme>','SCHEME')]:
            self.assertEqual(parse_output(text).state,state,text)
    def test_not_old_prompt_or_done(self):
        self.assertIsNone(parse_output('> \nRunning iterations\n').prompt)
        self.assertFalse(parse_output('Done.\n').success)
        self.assertFalse(parse_output('Error: bad\nDone.\n> ').success)
    def test_warning_iteration_convergence(self):
        o=parse_output('Warning: reversed flow\nAMG cycle\n  12 1e-5 2e-6\nsolution converged\n> ')
        types={k for e in o.events for k in e['types']}
        self.assertTrue({'WARNING','ITERATION','CONVERGENCE','PROMPT'} <= types);self.assertTrue(o.success)
    def test_crash_and_numerics(self):
        self.assertEqual(analyze('/solve/iterate 10','>',parse_output('floating point exception',process_alive=True))['error_type'],'SOLVER_ERROR')
        self.assertEqual(analyze('x','>',parse_output('',process_alive=False))['error_type'],'PROCESS_ERROR')
    def test_error_taxonomy(self):
        cases={'TUI_PATH_ERROR':'invalid command [foo]','MISSING_ARGUMENT':'Error: missing argument','EXTRA_ARGUMENT':'Error: too many arguments','INVALID_ARGUMENT':'Error: invalid argument','ZONE_ERROR':'Error: invalid zone not found','VARIABLE_ERROR':'Error: invalid variable','YES_NO_ERROR':'Error: yes or no expected','DEFAULT_VALUE_ERROR':'Error: invalid comma/default input','FILE_PATH_ERROR':'Error: no such file','MODEL_NOT_ENABLED':'Error: model is not enabled','STATE_DEPENDENCY_ERROR':'Error: no mesh','UNKNOWN_ERROR':'Error: mystery'}
        for kind,text in cases.items():self.assertEqual(analyze('x','>',parse_output(text+'\n>'))['error_type'],kind)
        self.assertEqual(analyze('/solve/patch','Variable>',parse_output('invalid command\nVariable>'))['error_type'],'MENU_STATE_ERROR')
        self.assertEqual(analyze('9999','cell zone id/name(1) [()]',parse_output('Invalid cell zone.\ncell zone id/name(1) [()]'))['error_type'],'ZONE_ERROR')
    def test_imports(self):
        for p in SCRIPTS.glob('*.py'): importlib.import_module(p.stem)
        for name in ('fake_fluent', 'integration_fluent'):
            spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(name+'.py'))
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class DiscoveryTests(unittest.TestCase):
    def test_config_env_multiple_versions(self):
        with tempfile.TemporaryDirectory() as d:
            def exe(v):
                p=Path(d)/v/'fluent/ntbin/win64/fluent.exe';p.parent.mkdir(parents=True);p.write_bytes(b'fixture');(p.parents[2]/'fluent22.1.0').mkdir();return p
            new, old = exe('v242'),exe('v221')
            r=discover({'executable':str(new)},environ={'AWP_ROOT221':str(old.parents[3])},common_roots=[])
            self.assertEqual(r['selected']['executable'],str(old));self.assertFalse(validate_executable(new)['valid_v221'])
    def test_missing(self):self.assertEqual(discover({},environ={},common_roots=[])['status'],'NOT_FOUND')
    def test_args(self):
        a=build_argv({'executable':'fluent.exe','dimension':'2d','precision':'single','parallel':True,'processors':2,'gui':True},'a b.jou')
        self.assertEqual(a[:3],['fluent.exe','2d','-t2']);self.assertEqual(a[-2],'-i')

class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.log=TaskLog(self.tmp.name,'mock')
        self.c={'executable':'MOCK','encoding':'utf-8','transport':'pipe','startup_timeout':3,'command_timeout':2,'prompt_settle_seconds':.06,'max_auto_retries':3}
        self.argv=patch('fluent_process.build_argv',return_value=[sys.executable,str(Path(__file__).with_name('fake_fluent.py'))]);self.argv.start()
        self.p=FluentProcess(self.c,self.log.path);self.assertTrue(self.p.start()['available'])
        self.s=FluentSession(self.p,self.log,self.c)
    def tearDown(self):
        if self.p.is_alive():
            self.p.send('/exit yes');self.p.process.wait(timeout=3)
        self.p.close()
        for thread in self.p.threads:thread.join(timeout=1)
        self.argv.stop();self.tmp.cleanup()
    def test_start_query_and_path_recovery(self):
        plan={'id':'path','steps':[{'id':'good','command':'/report/system/sys-stats'}, {'id':'typo','command':'/report/system/sys-stat','risk':'READ_ONLY','risk_evidence':'Known read-only system report; terminal typo under test','retry':True}]}
        r=self.s.execute_plan(plan);self.assertEqual(r['status'],'completed');self.assertEqual(self.s.last_successful_step,'typo')
        corrections=[json.loads(x) for x in (self.log.path/'corrections.jsonl').read_text().splitlines()]
        self.assertEqual(len(corrections),1);self.assertNotEqual(corrections[0]['original_command'],corrections[0]['modified_command'])
    def test_patch_multistep_and_scheme_recovery(self):
        inputs=[{'command':'/solve/patch'}, {'command':'fluid_nozzle','kind':'response','expect_prompt':r'cell zone.*\(1\)'},
                {'command':'()','kind':'response','expect_prompt':r'cell zone.*\(2\)','repairs':[{'error_type':'SCHEME_PARSE_ERROR','when_output':'undefined read macro','when_prompt':r'cell zone.*\(2\)','command':'','kind':'response','hypothesis':'The fixture confirmed blank Enter terminates this zone list; () reached its reader.','reason':'Change only the failed list terminator.'}]},
                {'command':'pressure','kind':'response','expect_prompt':'Variable>'},{'command':'no','kind':'response','expect_prompt':'Custom Field'}, {'command':'486540','kind':'response','expect_prompt':'Value'}]
        r=self.s.execute_plan({'id':'patch','steps':[{'id':'patch','risk':'LOW_RISK','retry':True,'inputs':inputs}]})
        self.assertEqual(r['status'],'completed')
        commands=[json.loads(x)['command'] for x in (self.log.path/'commands.jsonl').read_text().splitlines()]
        self.assertEqual(commands.count('()'),1);self.assertEqual(commands.count('/solve/patch'),1)
    def test_invalid_zone_and_guard(self):
        self.s.exchange('/solve/patch')
        with self.assertRaises(ValueError):self.s.exchange('/report/system/sys-stats')
        r=self.s.exchange('missing',kind='response',item={'expect_prompt':'cell zone','risk':'LOW_RISK'})
        self.assertEqual(r['diagnosis']['error_type'],'ZONE_ERROR')
    def test_max_retry_and_resume(self):
        repairs=[{'error_type':'TUI_PATH_ERROR','when_output':'invalid command','when_prompt':'>','command':'/__codex_invalid_'+str(i),'hypothesis':f'Candidate {i}','reason':'Mock retry limit test'} for i in range(8)]
        plan={'id':'max','steps':[{'id':'fail','command':'/__codex_invalid_original','retry':True,'repairs':repairs}]}
        self.assertEqual(self.s.execute_plan(plan)['status'],'needs_decision');self.assertTrue(self.p.is_alive())
        count=len((self.log.path/'commands.jsonl').read_text().splitlines())
        self.assertEqual(count,4);self.s.execute_plan(plan);self.assertEqual(len((self.log.path/'commands.jsonl').read_text().splitlines()),count)
    def test_timeout_no_assumed_success(self):
        r=self.s.exchange('/slow',item={'risk':'READ_ONLY','risk_evidence':'mock delayed query','timeout':.15})
        self.assertFalse(r['success']);self.assertEqual(r['diagnosis']['error_type'],'PROCESS_ERROR')
        with self.assertRaises(RuntimeError):self.s.exchange('/report/system/sys-stats')
        self.assertEqual(self.s.observe(wait=True,timeout=2)['state'],'ROOT')
    def test_process_crash(self):
        r=self.s.exchange('/crash',item={'in_user_goal':True});self.assertEqual(r['diagnosis']['error_type'],'PROCESS_ERROR')
    def test_checkpoint_rollback(self):
        cp=self.s.checkpoint('one');self.assertTrue(Path(cp['data']).exists())
        with self.assertRaises(PermissionError):self.s.rollback('one')
        self.assertTrue(self.s.rollback('one',authorized=True)['success'])
    def test_destructive_not_repair(self):
        self.s.solution_valid=True
        with self.assertRaises(PermissionError):self.s.exchange('/solve/initialize/initialize-flow',item={'retry':True})
        with self.assertRaises(PermissionError):self.s.exchange('/file/write-case-data "bad.cas.h5"',item={'risk':'READ_ONLY','risk_evidence':'must not bypass destructive check'},retry=True)
    def test_comma_default_recovery(self):
        inputs=[{'command':'/solve/patch'},{'command':'fluid_nozzle','kind':'response','expect_prompt':'cell zone.*1'},
                {'command':'','kind':'response','expect_prompt':'cell zone.*2'},{'command':'pressure','kind':'response','expect_prompt':'Variable>'},
                {'command':'no','kind':'response','expect_prompt':'Custom Field'},
                {'command':',','kind':'response','expect_prompt':'Value','repairs':[{'error_type':'DEFAULT_VALUE_ERROR','when_output':'invalid comma','when_prompt':'Value','kind':'response','command':'486540','hypothesis':'The user requested a numeric value, while comma was rejected.','reason':'Supply only the explicit goal value at its observed prompt.'}]}]
        r=self.s.execute_plan({'id':'comma','steps':[{'id':'patch','risk':'LOW_RISK','inputs':inputs,'retry':True}]})
        self.assertEqual(r['status'],'completed')
    def test_failed_postcondition_resume_does_not_repeat(self):
        plan={'id':'postcondition','steps':[{'id':'query','command':'/report/system/sys-stats','verify_output_regex':'not present'}]}
        self.assertEqual(self.s.execute_plan(plan)['status'],'needs_decision')
        self.assertEqual(self.s.execute_plan(plan)['status'],'needs_decision')
        self.assertEqual(len((self.log.path/'commands.jsonl').read_text().splitlines()),1)
    def test_transcript_errors_before_final_prompt(self):
        t='> /bad\ninvalid command [bad]\n> /report/system/sys-stats\nCPU\n> '
        o=parse_output(t);self.assertFalse(o.success);self.assertEqual(len(o.error_lines),1)

class JournalPlanTests(unittest.TestCase):
    def test_failed_transaction_only_is_repaired(self):
        with tempfile.TemporaryDirectory() as d:
            runner=JournalRunner({'logs_root':d,'max_auto_retries':3})
            plan={'id':'batch','journal_checkpoint_each_step':True,'steps':[{'id':'query','command':'/report/system/sys-stat','journal_verified_v221':True,
                'risk':'READ_ONLY','risk_evidence':'Read-only system report typo fixture','retry':True,'transaction_replay_safe':True,
                'repairs':[{'error_type':'TUI_PATH_ERROR','when_output':'invalid command','line_number':1,'expected_line':'/report/system/sys-stat','replacement':'/report/system/sys-stats','hypothesis':'Observed terminal token typo','reason':'Only one token differs from the menu entry'}]}]}
            failed={'success':False,'run_dir':'MOCK-run1','diagnosis':{'error_type':'TUI_PATH_ERROR','safe_to_retry':True},'observation':{'output':'invalid command [sys-stat]'}}
            passed={'success':True,'run_dir':'MOCK-run2','checkpoint':'MOCK-state.cas.h5'}
            with patch.object(runner,'run',side_effect=[failed,passed]) as run:
                self.assertEqual(runner.execute_plan(plan)['status'],'completed')
                self.assertEqual(run.call_count,2)
                self.assertEqual(run.call_args_list[1].kwargs['text'],'/report/system/sys-stats')
                runner.execute_plan(plan);self.assertEqual(run.call_count,2)
    def test_unchanged_failed_batch_not_repeated(self):
        with tempfile.TemporaryDirectory() as d:
            runner=JournalRunner({'logs_root':d})
            plan={'id':'batch','journal_checkpoint_each_step':True,'steps':[{'id':'bad','command':'/__codex_invalid_path__','journal_verified_v221':True}]}
            with patch.object(runner,'run',return_value={'success':False,'run_dir':'MOCK'}) as run:
                self.assertEqual(runner.execute_plan(plan)['status'],'needs_decision')
                self.assertEqual(runner.execute_plan(plan)['status'],'needs_decision');self.assertEqual(run.call_count,1)

if __name__=='__main__':unittest.main(verbosity=2)
