"""Lance l'API de descripteurs (5001) ET l'application web (5000) en un seul terminal. Ctrl+C pour arrêter.

Usage de développement uniquement. En production : voir docker-compose.yml (gunicorn)."""
import os
import subprocess
import sys
import time
from pathlib import Path

root = Path(__file__).resolve().parent
env = dict(os.environ, PYTHONPATH=str(root))
procs = [subprocess.Popen([sys.executable, "-m", "api.app"], cwd=root, env=env),
         subprocess.Popen([sys.executable, "-m", "flask", "--app", "wsgi:app", "run",
                           "--host", "127.0.0.1", "--port", "5000"], cwd=root, env=env)]
print("API : http://127.0.0.1:5001   |   Application : http://127.0.0.1:5000")
try:
    while all(p.poll() is None for p in procs):
        time.sleep(1)
except KeyboardInterrupt:
    pass
finally:
    for p in procs:
        p.terminate()
