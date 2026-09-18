import sys
sys.path.insert(0, "src")
from sparrow.config import load_catalog

for p in load_catalog():
    print(f"{p.id} key_env={p.key_env} keyless={p.keyless}")
