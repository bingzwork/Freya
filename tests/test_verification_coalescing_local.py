import sys 
import time 
import threading 
from unittest.mock import patch 
from app.verification.runner import VerificationRunner 
def test_identical_runs_share_process(tmp_path): 
    runner = VerificationRunner(tmp_path, timeout_seconds=2) 
    calls = [] 
    process = type('P', (), {'returncode': 0, 'poll': lambda self: 0, 'communicate': lambda self, timeout=None: (time.sleep(0.05) or ('ok', ''))})() 
    def fake_popen(*args, **kwargs): calls.append(1); return process 
    results = [] 
    with patch('app.verification.coalescing.subprocess.Popen', side_effect=fake_popen): 
        threads = [threading.Thread(target=lambda: results.append(runner.run([sys.executable, '-m', 'pytest', '-q']))) for _ in range(2)] 
        [thread.start() for thread in threads]; [thread.join() for thread in threads] 
    assert len(calls) == 1 and len(results) == 2 and all(result.success for result in results) 
def test_fingerprint_changes_with_source(tmp_path): 
    runner = VerificationRunner(tmp_path) 
    source = tmp_path / 'module.py'; source.write_text('x=1') 
    first = runner._fingerprint([sys.executable, '-m', 'pytest', '-q']); source.write_text('x=2') 
    assert first != runner._fingerprint([sys.executable, '-m', 'pytest', '-q'])
