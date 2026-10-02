"""Run three deliberately broken controller copies; each alarm must fail.

Only temporary source/fixture copies are mutated. No working tree, production
service, supplier or paid model is changed/contacted. Exit nonzero if an alarm
does not detect its intended regression. Run from the backend repo root.
"""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
MUTANTS = [
    ('mask', 'mask=masks, mask_color=NAVY', 'mask=[], mask_color=NAVY',
     'test_mask_alarm_real_password_pixels'),
    ('scrub', "out = out.replace(value, '[redacted]')", 'out = out',
     'test_login_fill_is_internal_and_all_text_surfaces_scrubbed'),
    ('post_action_host', 'not host_allowed(page.url, self.hosts, self.deny_hosts)', 'False',
     'test_post_action_host_check_alarm'),
]


def main():
    source = (ROOT / 'browser_controller.py').read_text(encoding='utf-8')
    for name, before, after, test in MUTANTS:
        assert source.count(before) == 1, f'{name}: mutation anchor changed'
        with tempfile.TemporaryDirectory(prefix='chief-alarm-') as directory:
            dest = Path(directory)
            (dest / 'browser_controller.py').write_text(source.replace(before, after), encoding='utf-8')
            for file in ('browser_hand.py', 'secret_vault.py'):
                shutil.copy2(ROOT / file, dest / file)
            shutil.copy2(ROOT / '__tests__' / 'test_browser_controller.py', dest / 'test_browser_controller.py')
            shutil.copytree(ROOT / '__tests__' / 'fixtures', dest / 'fixtures')
            result = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider',
                                     'test_browser_controller.py::' + test],
                                    cwd=dest, capture_output=True, text=True,
                                    env={**os.environ, 'PYTHONPATH': str(dest)}, timeout=90)
            if result.returncode != 1 or '1 failed' not in result.stdout or 'ERROR' in result.stdout:
                print(f'FAIL: {name} did not trigger its expected assertion')
                print(result.stdout[-3000:], result.stderr[-1000:])
                return 1
            print(f'PASS: {name} sabotage was detected')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
