-- Fixed paths only; no filesystem arguments and no SECURITY DEFINER privileges.
CREATE SCHEMA IF NOT EXISTS criterion_monitor;
REVOKE ALL ON SCHEMA criterion_monitor FROM PUBLIC;
CREATE OR REPLACE FUNCTION criterion_monitor.snapshot() RETURNS jsonb
LANGUAGE plpython3u VOLATILE AS $$
import json
import os
from pathlib import Path
root = Path('/sys/fs/cgroup')
try:
    # A private cgroup namespace is required: never label host counters as DB counters.
    if Path('/proc/self/cgroup').read_text().strip() != '0::/':
        return json.dumps({'status': 'unavailable', 'reason': 'private_cgroup_v2_required'})
    cpu = dict(line.split() for line in (root / 'cpu.stat').read_text().splitlines())
    quota = (root / 'cpu.max').read_text().split()
    memory_limit = (root / 'memory.max').read_text().strip()
    if quota[0] == 'max' and memory_limit == 'max':
        return json.dumps({'status': 'unavailable', 'reason': 'bounded_container_required'})
    return json.dumps({
        'status': 'available', 'cpu_seconds': int(cpu['usage_usec']) / 1e6,
        'memory_bytes': int((root / 'memory.current').read_text()),
        'cpu_limit_cores': None if quota[0] == 'max' else int(quota[0])/int(quota[1]),
        'memory_limit_bytes': None if memory_limit == 'max' else int(memory_limit),
        'identity': str(os.stat(root).st_ino) + ':' + Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
    })
except (OSError, ValueError, KeyError):
    return json.dumps({'status': 'unavailable', 'reason': 'cgroup_counters_unreadable'})
$$;
REVOKE ALL ON FUNCTION criterion_monitor.snapshot() FROM PUBLIC;
