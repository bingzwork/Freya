import hashlib 
import os 
import subprocess 
import threading 
from app.core.logger import logger 
from app.verification.runner import VerificationResult, VerificationStatus

_active = {}
_lock = threading.Lock() 
def fingerprint(runner, command): 
    digest = hashlib.sha256('\\0'.join(command).encode('utf-8')) 
    for path in sorted(runner.workspace.rglob('*.py')): 
        if '__pycache__' in path.parts: continue 
        try: digest.update(str(path.relative_to(runner.workspace)).encode('utf-8')); digest.update(path.read_bytes()) 
        except OSError: continue 
    return digest.hexdigest() 
def terminate(runner, process): 
    if process.poll() is not None: return 
    try: 
        if os.name == 'nt': subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True, text=True) 
        else: process.kill() 
    except (OSError, subprocess.SubprocessError): 
        try: process.kill() 
        except OSError: pass 
def process(runner, command): 
    proc = subprocess.Popen(command, cwd=runner.workspace, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) 
    try: 
        out, err = proc.communicate(timeout=runner.timeout_seconds) 
        return VerificationResult(proc.returncode == 0, command, out or '', err or '', proc.returncode, status=VerificationStatus.VERIFIED if proc.returncode == 0 else VerificationStatus.FAILED)
    except subprocess.TimeoutExpired as error: 
        runner._terminate_process(proc) 
        out = getattr(error, 'output', '') or ''; err = getattr(error, 'stderr', '') or '' 
        logger.warning('[Verification] Timed out; process terminated and lock released') 
        return VerificationResult(False, command, out, err or f'Verification timed out after {runner.timeout_seconds} seconds.', -1, status=VerificationStatus.UNKNOWN)
def run(runner, command): 
    key = fingerprint(runner, command) 
    with _lock: 
        entry = _active.get(key); owner = entry is None 
        if owner: entry = {'event': threading.Event(), 'result': None, 'waiters': 0}; _active[key] = entry 
        entry['waiters'] = entry['waiters'] + 1  
    if owner: 
        try: 
            result = process(runner, command) 
            with _lock: entry['result'] = result; entry['event'].set() 
            return result 
        finally: 
            with _lock: entry['waiters'] = entry['waiters'] - 1; _active.pop(key, None) if entry['waiters'] == 0 else None 
    entry['event'].wait(timeout=runner.timeout_seconds + 2) 
    with _lock: result = entry['result']; entry['waiters'] = entry['waiters'] - 1; _active.pop(key, None) if entry['waiters'] == 0 else None 
    return result or VerificationResult(False, command, '', 'Verification waiter timed out.', -1, status=VerificationStatus.UNKNOWN)

