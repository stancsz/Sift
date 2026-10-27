"""Native CLI validation must accept real fixture sizes and retain failures."""
import pytest
from benchmarks.cli_acceptance import _successful_unittest, native_evidence

@pytest.mark.parametrize('count',[1,2,3,4,49])
@pytest.mark.parametrize('newline',['\n','\r\n'])
def test_positive_native_counts(count,newline):
    output=f'Ran {count} test'+('' if count==1 else 's')+' in 0.004s'+newline+newline+'OK'+newline
    assert _successful_unittest(output)
    events=[{'type':'item.completed','item':{'id':'test','type':'command_execution','command':'python -m unittest -q',
        'aggregated_output':output,'exit_code':0,'status':'completed'}},{'type':'turn.completed'}]
    assert native_evidence('codex',events)['final_passed']
    events[0]['item']['exit_code']=1
    assert not native_evidence('codex',events)['final_passed']

@pytest.mark.parametrize('output',[
    'Ran 0 tests in 0.001s\n\nOK\n','Ran 3 tests in 0.001s\n\nOK (skipped=3)\n',
    'Ran 3 tests in 0.001s\n\nFAILED (failures=1)\n','ERROR\nRan 3 tests\nOK\n',
    'The output was "Ran 3 tests in 0.001s" and "OK"', '"Ran 3 tests in 0.001s\\n\\nOK\\n"'])
def test_non_success_is_not_promoted(output):
    assert not _successful_unittest(output)


def test_escaped_native_windows_executable_is_a_real_baseline():
    command=r'"C:\PowerShell\pwsh.exe" -Command "& \\"C:\\Program Files\\Python\\python.exe\\" -m unittest -q"'
    events=[{'type':'item.completed','item':{'id':'baseline','type':'command_execution','command':command,
        'aggregated_output':'Ran 3 tests\r\nFAILED (failures=1)\r\n','exit_code':1,'status':'failed'}}]
    assert native_evidence('codex',events)['baseline_failed']
    events[0]['item']['command']=command.replace('-q','-q; Write-Output quoted')
    assert not native_evidence('codex',events)['baseline_failed']
