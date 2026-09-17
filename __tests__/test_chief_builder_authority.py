"""The model never runs in the job that holds repository-write credentials."""
from pathlib import Path
import subprocess
import sys
import yaml

ROOT=Path(__file__).resolve().parents[1]

def test_model_job_cannot_write_or_mint_an_app_token():
    workflow=yaml.safe_load((ROOT/'.github/workflows/claude.yml').read_text())
    assert workflow['permissions']=={}
    builder=workflow['jobs']['claude']
    assert builder['permissions']=={'contents':'read','issues':'read','pull-requests':'read'}
    assert "github.event.sender.login == 'parkerron1971-hash'" in builder['if']
    step=next(s for s in builder['steps'] if s.get('uses','').startswith('anthropics/'))
    assert step['with']['github_token']=='${{ github.token }}'
    assert 'claude_code_oauth_token' in step['with']
    publisher=workflow['jobs']['proposal']
    assert publisher['needs']=='claude'
    assert not any('anthropics/' in s.get('uses','') or 'secrets.' in str(s) for s in publisher['steps'])
    scripts='\n'.join(s.get('run','') for s in publisher['steps'])
    assert 'gh pr create --draft' in scripts and 'gh pr merge' not in scripts
    assert 'npm ' not in scripts and 'pytest' not in scripts
    assert 'core.hooksPath=/dev/null' in scripts
    assert 'HEAD:refs/heads/$branch' in scripts

def test_publisher_refuses_workflow_changes_without_evaluating_file_names():
    workflow=yaml.safe_load((ROOT/'.github/workflows/claude.yml').read_text())
    script=workflow['jobs']['proposal']['steps'][-1]['run']
    line=next(l for l in script.splitlines() if 'python -I -c' in l)
    code=line.split("python -I -c '",1)[1][:-1]
    for paths,blocked in [(b'src/app.tsx\0',False),(b'.github/workflows/ci.yml\0',True),
                          (b'.gitattributes\0',True),(b'$(touch stolen)\0',False)]:
        result=subprocess.run([sys.executable,'-I','-c',code],input=paths,capture_output=True)
        assert (result.returncode!=0)==blocked

def test_ci_has_read_only_credentials():
    workflow=yaml.safe_load((ROOT/'.github/workflows/ci.yml').read_text())
    assert workflow['permissions']=={'contents':'read'}
