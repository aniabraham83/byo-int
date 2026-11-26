# Environmental Variable-Based Worker Scaling for Docker Compose

## Quick Answer

✅ **YES**, but with tradeoffs. Environment variables can drive scaling via several patterns, each with different deployment friction.

---

## Approach 1: `.env` File Substitution

### Concept
Store `WORKER_COUNT=N` in `.env` file. Sidecar/CLI updates `.env`, then triggers `docker-compose up -d`.

```yaml
# docker-compose.yml
services:
  datapull_worker:
    image: byoint-core:latest
    deploy:
      replicas: ${WORKER_COUNT:-1}  # ⚠️ Only works in Swarm mode!
    # OR manually define N services:
```

### ❌ Problem
Docker Compose `replicas:` field **only works in Swarm mode**, not Compose standalone.

### ✅ Workaround: Template Multiple Services

```yaml
# docker-compose.yml
services:
  datapull_worker_1:
    image: byoint-core:latest
    environment:
      - WORKER_ID=1
  
  datapull_worker_2:
    image: byoint-core:latest
    environment:
      - WORKER_ID=2
    profiles: ["${SCALE_TO_2:-}"]  # Only starts if env var set
  
  datapull_worker_3:
    image: byoint-core:latest
    environment:
      - WORKER_ID=3
    profiles: ["${SCALE_TO_3:-}"]
  
  # ... scale up to N
```

Then:
```bash
SCALE_TO_2=true SCALE_TO_3=true docker-compose up -d
```

**Pros:**
- Pure Docker Compose (no custom scripts)
- Env-driven

**Cons:**
- Hard to manage (need 100 service definitions for 100 workers)
- Not compatible with `docker-compose up -d --scale datapull_worker=N`
- Fragile

---

## Approach 2: `.env` + Shell Script Wrapper

### Concept
Store `DESIRED_WORKER_COUNT=5` in `.env`. Script reads it, calls `docker-compose scale`.

```bash
# scale.sh
#!/bin/bash

# Load .env
source .env

# Extract desired count
DESIRED=${DESIRED_WORKER_COUNT:-1}

# Scale
docker-compose up -d --scale datapull_worker=$DESIRED

echo "Scaled to $DESIRED workers"
```

Usage:
```bash
# Change .env
sed -i 's/DESIRED_WORKER_COUNT=.*/DESIRED_WORKER_COUNT=5/' .env

# Run script
./scale.sh
```

**Pros:**
- ✅ Uses env variables
- ✅ Backward compatible with existing compose scaling
- ✅ Simple

**Cons:**
- ❌ Still requires script execution (external automation needed)
- Shell scripts not portable (Windows vs Linux)
- No automatic reconciliation

---

## Approach 3: Env Var + Docker API Direct

### Concept
Instead of `docker-compose`, directly read env var and call Docker API to scale.

```python
# New file: byoint_core/scale_from_env.py

import os
import docker

def scale_from_env():
    """Read DESIRED_WORKER_COUNT from env and scale via Docker API."""
    
    desired = int(os.getenv('DESIRED_WORKER_COUNT', '1'))
    
    client = docker.from_env()
    
    # Get all datapull_worker containers
    containers = client.containers.list(
        filters={'label': ['com.docker.compose.service=datapull_worker']}
    )
    
    current = len([c for c in containers if c.status == 'running'])
    
    if current == desired:
        print(f"Already at {desired} workers")
        return
    
    if desired > current:
        # Create new containers
        delta = desired - current
        image = containers[0].image if containers else 'byoint-core:latest'
        
        for i in range(delta):
            client.containers.run(
                image,
                detach=True,
                name=f"datapull_worker_{current + i + 1}",
                environment={'DATAPULL_WORKER_ID': str(current + i + 1)}
            )
            print(f"Started worker {current + i + 1}")
    
    elif desired < current:
        # Stop excess containers
        delta = current - desired
        to_stop = sorted(containers, key=lambda c: c.attrs['Created'], reverse=True)[:delta]
        for container in to_stop:
            container.stop(timeout=10)
            print(f"Stopped {container.name}")
    
    print(f"Scaled {current} → {desired} workers")

if __name__ == '__main__':
    scale_from_env()
```

**Usage:**
```bash
DESIRED_WORKER_COUNT=5 python byoint_core/scale_from_env.py
```

**Pros:**
- ✅ Driven by env variable
- ✅ Works without docker-compose CLI
- ✅ Can be triggered by environment updates

**Cons:**
- ❌ Requires docker socket (same as sidecar)
- Manual execution (unless scheduled)
- More logic needed (handle network, volumes, etc.)

---

## Approach 4: Hybrid - Sidecar Watching `.env` Changes

### Concept
Sidecar monitors `.env` file for `DESIRED_WORKER_COUNT` changes, auto-triggers scaling.

```python
# byoint_core/env_file_watcher.py

import os
import time
import subprocess
from pathlib import Path

WATCH_FILE = '/app/byoint_core/.env'
POLL_INTERVAL = 5

def watch_env_file():
    """Watch .env file for DESIRED_WORKER_COUNT changes."""
    
    last_mtime = 0
    last_desired = None
    
    while True:
        try:
            # Check if .env changed
            mtime = os.path.getmtime(WATCH_FILE)
            
            if mtime > last_mtime:
                # Read desired count
                with open(WATCH_FILE) as f:
                    content = f.read()
                    for line in content.split('\n'):
                        if line.startswith('DESIRED_WORKER_COUNT='):
                            desired = int(line.split('=')[1])
                            
                            if desired != last_desired:
                                print(f"Scaling: {last_desired} → {desired}")
                                result = subprocess.run(
                                    ['./scale.sh'],
                                    cwd='/app/byoint_core'
                                )
                                
                                if result.returncode == 0:
                                    last_desired = desired
                                    last_mtime = mtime
                
        except Exception as e:
            print(f"Error: {e}")
        
        time.sleep(POLL_INTERVAL)

if __name__ == '__main__':
    watch_env_file()
```

**Usage:**
```bash
# In docker-compose.yml
services:
  env_file_watcher:
    image: byoint-core:latest
    working_dir: /app/byoint_core
    command: python env_file_watcher.py
    volumes:
      - ./.env:/app/byoint_core/.env:ro
      - /var/run/docker.sock:/var/run/docker.sock
    environment:
      - MONGO_HOST=mongodb
    depends_on:
      - datapull_worker
```

**Pros:**
- ✅ Env-variable-driven
- ✅ Automatic reconciliation
- ✅ Edit `.env` file, scaling happens immediately

**Cons:**
- ❌ Another sidecar container
- File watching less reliable than API polling
- Requires docker socket access

---

## Approach 5: Compose Env File + Orchestration Tool

Let Compose variables control services, use external tool to update `.env`:

```yaml
# docker-compose.yml
services:
  datapull_worker:
    image: byoint-core:latest
    environment:
      - WORKER_COUNT=${WORKER_COUNT:-1}

  # API endpoint to update .env and restart services
  scaling_api:
    image: byoint-core:latest
    ports:
      - "5001:5001"
    command: python -m flask run --port=5001
    volumes:
      - ./.env:/app/byoint_core/.env
    environment:
      - COMPOSE_PROJECT_NAME=${COMPOSE_PROJECT_NAME}
```

```python
# New Flask endpoint in core.py
@app.route('/api/scale/env/<int:count>', methods=['POST'])
def scale_from_internal_env(count):
    """Update internal .env and trigger rescale."""
    
    if not 1 <= count <= 100:
        return {'error': 'Invalid count'}, 400
    
    # Update .env
    with open('.env', 'r') as f:
        lines = f.readlines()
    
    with open('.env', 'w') as f:
        found = False
        for line in lines:
            if line.startswith('WORKER_COUNT='):
                f.write(f'WORKER_COUNT={count}\n')
                found = True
            else:
                f.write(line)
        if not found:
            f.write(f'WORKER_COUNT={count}\n')
    
    # Signal orchestration tool to restart services
    # (This is pseudo-code; real implementation needs proper restart mechanism)
    
    return {'message': f'Scaled to {count}'}, 200
```

**Pros:**
- ✅ Env-variable-based
- ✅ API-driven (can call from UI)

**Cons:**
- ❌ Still needs container restart (loses running jobs)
- Service interruption
- Complex to implement correctly

---

## Comparison

| Approach | Env Var Driven | Auto Reconcile | Easy to Implement | Works with Compose | Production Ready |
|----------|--------|-----------|-------------|-----------|---------|
| **1: Profiles** | ✅ | ❌ | ❌ | ✅ | ❌ |
| **2: .env + Shell** | ✅ | ❌ | ✅ | ✅ | ⚠️ (manual) |
| **3: Docker API Direct** | ✅ | ❌ | ✅ | ❌ | ⚠️ (socket) |
| **4: .env File Watcher** | ✅ | ✅ | ⚠️ | ✅ | ⚠️ (fragile) |
| **5: .env + API + Restart** | ✅ | ❌ | ❌ | ✅ | ❌ (downtime) |
| **MongoDB + Sidecar** (Previous) | ⚠️ (config) | ✅ | ⚠️ | ✅ | ✅ |

---

## Recommendation

### For env-variable-only requirement:

**Best Option: #2 (.env + Shell Script Wrapper)**
- Transparent to Compose
- Works with existing `docker-compose scale` command
- Easy to test locally
- Can be triggered by CI/CD or cron jobs

```bash
# Usage
DESIRED_WORKER_COUNT=5 ./scale.sh
```

Or with env file:
```bash
echo "DESIRED_WORKER_COUNT=5" > .env
./scale.sh
```

### For automatic reconciliation (recommended):

**Best Option: MongoDB-based Sidecar** (from earlier evaluation)
- More reliable than file watching
- Cleaner separation of concerns
- Can be triggered from UI + auto-reconciles

---

## Hybrid Approach (Best of Both)

**Use env variables + MongoDB for flexibility:**

```python
# byoint_core/worker_scaler.py

import os
from all_connects import connect_mongodb

def get_desired_worker_count():
    """Read desired count from either env var or MongoDB (env var wins)."""
    
    # Check env first (allows override)
    if 'DESIRED_WORKER_COUNT' in os.environ:
        return int(os.getenv('DESIRED_WORKER_COUNT'))
    
    # Fall back to MongoDB
    mongo_client, _ = connect_mongodb()
    db = mongo_client['byoint_core_config']
    config = db['basicconfigs'].find_one({'module': 'core'})
    
    count = config.get('worker_scaling', {}).get('desired_worker_count', 1)
    mongo_client.close()
    
    return count
```

**Deployment:**
- Sidecar reads `get_desired_worker_count()`
- Can override at runtime: `DESIRED_WORKER_COUNT=5 docker-compose up -d`
- Persists in MongoDB when using UI
- Best flexibility

---

## Summary

| Use Case | Recommended Approach |
|----------|-----|
| "Just use env vars, nothing fancy" | **Approach 2**: `.env` + shell script |
| "Automatic reconciliation + env override" | **Hybrid**: MongoDB sidecar + env var override |
| "Already have MongoDB config UI" | **MongoDB-based sidecar** (from earlier eval) |
| "Kubernetes next, don't optimize Compose" | **Skip all**, just use manual `--scale` |

**My take:** The MongoDB-based sidecar from the previous evaluation handles env variables too (it just checks `DESIRED_WORKER_COUNT` env var as override). That's already the best answer.

But if you want **pure env-variable-only without MongoDB**, use **Approach 2** (`.env` + shell wrapper).

