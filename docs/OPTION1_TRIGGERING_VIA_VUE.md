# Option 1: Triggering Worker Scaling via Vue.js

## Overview

There are **two paths** for triggering via Vue:

| Path | How it works | Trigger From Vue |
|------|-------------|-----------------|
| **1A: Manual** | Vue saves config → Ops runs CLI | Just config save |
| **1B: Hybrid (Recommended)** | Vue saves config → Vue calls scale endpoint → Backend auto-scales | One-click scale |

---

## Path 1A: Config-Only + Manual CLI

This is what I described in the evaluation. Here's the flow:

```
Vue UI (WorkerScaling.vue)
       ↓ [Save Configuration] button clicked
       ├→ PUT /api/configuration/workers { desired_worker_count: 3 }
       │
       ├→ Backend (core.py) validates & saves to MongoDB
       │
       └→ Vue displays: "Configuration saved!"
            + Shows manual command to run:
            "docker-compose up -d --scale datapull_worker=3"

Ops Terminal
       ↓ Manually runs command shown in UI
       ├→ docker-compose up -d --scale datapull_worker=3
       │
       └→ Containers restart
```

**Pros**: Safe, idempotent, ops has full control
**Cons**: Requires manual CLI step

---

## Path 1B: Hybrid Approach (Better UX)

Add a **one-click button** that saves config **AND** triggers scaling in one action.

```
Vue UI (WorkerScaling.vue)
       ↓ [Save & Apply] button clicked
       ├→ PUT /api/configuration/workers { desired_worker_count: 3 }
       │
       ├→ POST /api/workers/apply-scaling { desired_worker_count: 3 }
       │    ↓
       │    └→ Backend executes: docker-compose scale datapull_worker=3
       │
       └→ Vue displays: "Applied! Scaling to 3 workers..."
            + Shows logs as containers scale
```

---

## Implementation: Path 1B (Recommended)

### Step 1: Backend Endpoint (Add to core.py)

```python
import subprocess
import threading

@app.route('/api/workers/apply-scaling', methods=['POST'])
@token_required
def apply_worker_scaling():
    """Apply worker scaling by executing docker-compose scale.
    
    This is ASYNC - returns immediately, logs sent via callback.
    Actual scaling happens in background.
    """
    if not request.is_json:
        return jsonify({'message': 'Request must be JSON.'}), 400
    
    data = request.json or {}
    desired_count = data.get('desired_worker_count')
    
    if not desired_count:
        return jsonify({'message': 'Missing desired_worker_count'}), 400
    
    try:
        desired_count = int(desired_count)
        if desired_count < 1 or desired_count > 100:
            return jsonify({'message': 'Count must be 1-100'}), 400
    except ValueError:
        return jsonify({'message': 'desired_worker_count must be an integer'}), 400
    
    # First, update config in MongoDB
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client['byoint_core_config']
        basicconfigs_col = db['basicconfigs']
        
        core_doc = basicconfigs_col.find_one({'module': 'core'})
        if not core_doc:
            mongo_client.close()
            return jsonify({'message': 'Config not found'}), 404
        
        worker_config = core_doc.get('worker_config', {})
        worker_config['desired_worker_count'] = desired_count
        
        basicconfigs_col.update_one(
            {'_id': core_doc['_id']},
            {'$set': {'worker_config': worker_config}}
        )
        mongo_client.close()
    except Exception as e:
        return jsonify({'message': f'Failed to save config: {e}'}), 500
    
    # Start scaling in background thread (don't block response)
    scaling_job_id = str(uuid4())
    threading.Thread(
        target=_execute_worker_scaling,
        args=(desired_count, scaling_job_id),
        daemon=True
    ).start()
    
    return jsonify({
        'message': f'Scaling to {desired_count} workers...',
        'job_id': scaling_job_id,
        'status': 'in_progress',
    }), 202  # 202 Accepted (async operation)


def _execute_worker_scaling(desired_count, job_id):
    """Execute docker-compose scale in background.
    
    In a real setup, you'd:
    - Log to MongoDB
    - Send WebSocket updates to UI
    - Handle failures gracefully
    """
    try:
        compose_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
        print(f"[{job_id}] Starting: Scale to {desired_count} workers")
        
        # Execute docker-compose scale
        cmd = [
            'docker-compose',
            'up', '-d',
            '--scale', f'datapull_worker={desired_count}',
        ]
        
        result = subprocess.run(
            cmd,
            cwd=compose_dir,
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout
        )
        
        if result.returncode == 0:
            print(f"[{job_id}] Success: Scaled to {desired_count} workers")
            # TODO: Send success notification to UI via WebSocket
        else:
            print(f"[{job_id}] Error: {result.stderr}")
            # TODO: Send error notification to UI
            
    except subprocess.TimeoutExpired:
        print(f"[{job_id}] Timeout: Scale operation exceeded 5 minutes")
    except Exception as e:
        print(f"[{job_id}] Exception: {e}")


@app.route('/api/workers/scaling-status', methods=['GET'])
@token_required
def get_scaling_status():
    """Get current scaling operation status.
    
    In future, this could return detailed logs from async scaling.
    For now, just returns current worker count + config.
    """
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client['byoint_core_config']
        basicconfigs_col = db['basicconfigs']
        
        core_doc = basicconfigs_col.find_one({'module': 'core'})
        if not core_doc:
            mongo_client.close()
            return jsonify({'message': 'Config not found'}), 404
        
        worker_config = core_doc.get('worker_config', {})
        current_workers = _get_current_worker_count()
        
        mongo_client.close()
        
        return jsonify({
            'desired_worker_count': worker_config.get('desired_worker_count', 1),
            'current_worker_count': current_workers,
            'is_scaling': current_workers != worker_config.get('desired_worker_count', 1),
        }), 200
    except Exception as e:
        return jsonify({'message': str(e)}), 500
```

---

### Step 2: Updated Vue Component

```vue
<!-- In byoint-web/src/components/WorkerScaling.vue -->

<template>
  <div class="worker-scaling-panel">
    <div class="card">
      <h3>Worker Scaling Configuration</h3>
      
      <!-- Current State -->
      <div class="state-display">
        <div class="metric">
          <label>Current Running Workers:</label>
          <span class="value">{{ runtimeState.current_running_workers }}</span>
          <span v-if="isScaling" class="scaling-indicator">
            (scaling to {{ config.desired_worker_count }}...)
          </span>
        </div>
        <div class="metric">
          <label>Desired Workers:</label>
          <span class="value">{{ config.desired_worker_count }}</span>
        </div>
        <div class="metric">
          <label>Queue Depth:</label>
          <span class="value">{{ runtimeState.queue_depth }} jobs</span>
        </div>
      </div>

      <!-- Configuration Form -->
      <form @submit.prevent="updateConfig" class="config-form">
        
        <!-- Desired Worker Count -->
        <div class="form-group">
          <label for="desired_worker_count">
            Desired Worker Count:
            <span class="current">(min: {{ config.min_workers }}, max: {{ config.max_workers }})</span>
          </label>
          <input
            id="desired_worker_count"
            v-model.number="config.desired_worker_count"
            type="number"
            min="1"
            max="100"
            :disabled="isScaling"
            @change="validateConfig"
          />
          <small>Number of workers to run</small>
        </div>

        <!-- Auto Scaling Toggle -->
        <div class="form-group checkbox">
          <label>
            <input
              v-model="config.auto_scaling_enabled"
              type="checkbox"
              :disabled="isScaling"
            />
            Enable Auto-Scaling (Future)
          </label>
          <small>Coming soon: Automatically scale based on queue depth</small>
        </div>

        <!-- Submit Buttons -->
        <div class="form-actions">
          <button
            type="button"
            @click="saveAndApplyScaling"
            :disabled="loading || isScaling"
            class="btn-primary btn-large"
          >
            <span v-if="loading">{{ loadingText }}</span>
            <span v-else>
              💾 Save & Apply Scaling
            </span>
          </button>

          <button
            type="submit"
            :disabled="loading || isScaling"
            class="btn-secondary"
          >
            {{ loading ? 'Saving...' : 'Save Config Only' }}
          </button>

          <button
            type="button"
            @click="refreshStatus"
            :disabled="loading"
            class="btn-tertiary"
          >
            🔄 Refresh
          </button>
        </div>

        <!-- Messages -->
        <div v-if="message" :class="['message', messageType]">
          {{ message }}
        </div>

        <!-- Scaling Progress -->
        <div v-if="isScaling" class="scaling-progress">
          <div class="progress-bar">
            <div class="progress-fill"></div>
          </div>
          <p>Scaling in progress... ({{ scalingElapsedSeconds }}s)</p>
        </div>
      </form>

      <!-- Help Section -->
      <div class="info-section">
        <h4>How to Scale Workers</h4>
        <div class="two-column">
          <div class="method">
            <h5>Method A: One-Click (Easiest)</h5>
            <ol>
              <li>Enter desired worker count above</li>
              <li>Click <strong>"Save & Apply Scaling"</strong></li>
              <li>Wait for confirmation (auto-scales in background)</li>
            </ol>
            <p class="note">✅ Recommended for most users</p>
          </div>

          <div class="method">
            <h5>Method B: Manual CLI</h5>
            <ol>
              <li>Update worker count above</li>
              <li>Click <strong>"Save Config Only"</strong></li>
              <li>Run in terminal:</li>
              <code>docker-compose up -d --scale datapull_worker={{ config.desired_worker_count }}</code>
            </ol>
            <p class="note">⚠️ For ops with CLI access</p>
          </div>
        </div>
      </div>

      <!-- Status Table -->
      <div class="status-table">
        <h4>Scaling Status</h4>
        <table>
          <tr>
            <td>Current Workers:</td>
            <td class="value">{{ runtimeState.current_running_workers }}</td>
          </tr>
          <tr>
            <td>Desired Workers:</td>
            <td class="value">{{ config.desired_worker_count }}</td>
          </tr>
          <tr>
            <td>Queue Depth:</td>
            <td class="value">{{ runtimeState.queue_depth }} jobs</td>
          </tr>
          <tr>
            <td>Scaling In Progress:</td>
            <td class="value" :class="{ active: isScaling }">
              {{ isScaling ? 'YES' : 'NO' }}
            </td>
          </tr>
          <tr>
            <td>Last Update:</td>
            <td class="value">{{ lastUpdateTime }}</td>
          </tr>
        </table>
      </div>
    </div>
  </div>
</template>

<script>
import api from '@/api'

export default {
  name: 'WorkerScaling',
  data() {
    return {
      config: {
        desired_worker_count: 1,
        auto_scaling_enabled: false,
        min_workers: 1,
        max_workers: 10,
      },
      runtimeState: {
        current_running_workers: 0,
        queue_depth: 0,
        scheduler_is_leader: false,
      },
      loading: false,
      message: '',
      messageType: '',
      isScaling: false,
      scalingElapsedSeconds: 0,
      scalingInterval: null,
      lastUpdateTime: new Date().toLocaleTimeString(),
      loadingText: 'Scaling...',
    }
  },
  mounted() {
    this.refreshStatus()
    // Auto-refresh every 5 seconds
    setInterval(() => this.refreshStatus(), 5000)
  },
  beforeUnmount() {
    if (this.scalingInterval) clearInterval(this.scalingInterval)
  },
  methods: {
    async refreshStatus() {
      try {
        const response = await api.get('/api/configuration/workers')
        this.config = { ...this.config, ...response.data.worker_config }
        const newRuntimeState = response.data.runtime_state
        this.runtimeState = newRuntimeState
        
        // Check if still scaling
        this.isScaling = 
          newRuntimeState.current_running_workers !== this.config.desired_worker_count
        
        this.lastUpdateTime = new Date().toLocaleTimeString()
        this.message = ''
      } catch (error) {
        this.message = error.response?.data?.message || 'Failed to load config'
        this.messageType = 'error'
      }
    },

    validateConfig() {
      if (this.config.desired_worker_count < this.config.min_workers) {
        this.config.desired_worker_count = this.config.min_workers
      }
      if (this.config.desired_worker_count > this.config.max_workers) {
        this.config.desired_worker_count = this.config.max_workers
      }
    },

    async updateConfig() {
      this.loading = true
      this.message = ''
      try {
        const response = await api.put('/api/configuration/workers', this.config)
        this.config = { ...this.config, ...response.data.worker_config }
        this.message = response.data.message
        this.messageType = 'success'
      } catch (error) {
        this.message = error.response?.data?.message || 'Failed to update config'
        this.messageType = 'error'
      } finally {
        this.loading = false
      }
    },

    async saveAndApplyScaling() {
      this.loading = true
      this.message = ''
      this.loadingText = 'Saving & applying...'

      try {
        // Step 1: Save config
        await api.put('/api/configuration/workers', this.config)

        // Step 2: Trigger scaling
        const response = await api.post('/api/workers/apply-scaling', {
          desired_worker_count: this.config.desired_worker_count
        })

        this.message = response.data.message || 'Scaling started...'
        this.messageType = 'info'
        this.isScaling = true

        // Step 3: Monitor scaling progress
        this.monitorScalingProgress()
      } catch (error) {
        this.message = error.response?.data?.message || 'Failed to apply scaling'
        this.messageType = 'error'
        this.isScaling = false
      } finally {
        this.loading = false
      }
    },

    monitorScalingProgress() {
      this.scalingElapsedSeconds = 0
      
      // Update every 2 seconds during scaling
      this.scalingInterval = setInterval(() => {
        this.scalingElapsedSeconds += 2
        this.refreshStatus()
        this.loadingText = `Scaling (${this.scalingElapsedSeconds}s)...`

        // Stop if scaling complete or timeout (5 min)
        if (!this.isScaling || this.scalingElapsedSeconds > 300) {
          clearInterval(this.scalingInterval)
          if (this.scalingElapsedSeconds > 300) {
            this.message = 'Scaling timeout (5+ minutes). Check logs.'
            this.messageType = 'warning'
          } else {
            this.message = '✅ Scaling complete!'
            this.messageType = 'success'
          }
          this.isScaling = false
        }
      }, 2000)
    },
  },
}
</script>

<style scoped>
.worker-scaling-panel {
  padding: 20px;
  max-width: 1200px;
  margin: 0 auto;
}

.card {
  border: 1px solid #ddd;
  border-radius: 8px;
  padding: 25px;
  background: #fff;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

h3 {
  margin: 0 0 25px 0;
  color: #222;
  font-size: 24px;
}

h4 {
  margin-top: 20px;
  color: #333;
  font-size: 16px;
}

h5 {
  margin: 10px 0 5px 0;
  color: #444;
  font-size: 14px;
}

.state-display {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 15px;
  margin-bottom: 30px;
  padding: 15px;
  background: #f8f9fa;
  border-radius: 6px;
}

.metric {
  display: flex;
  flex-direction: column;
}

.metric label {
  font-size: 11px;
  color: #666;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 6px;
  font-weight: 600;
}

.metric .value {
  font-size: 22px;
  font-weight: bold;
  color: #222;
}

.metric .scaling-indicator {
  font-size: 12px;
  color: #ff8c00;
  font-weight: 500;
  margin-top: 4px;
}

.config-form {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.form-group {
  display: flex;
  flex-direction: column;
}

.form-group label {
  margin-bottom: 8px;
  font-weight: 500;
  color: #333;
  font-size: 14px;
}

.form-group label .current {
  font-size: 12px;
  font-weight: normal;
  color: #666;
  margin-left: 6px;
}

.form-group input[type="number"],
.form-group input[type="text"] {
  padding: 10px 12px;
  border: 1px solid #ddd;
  border-radius: 4px;
  font-size: 14px;
  transition: border-color 0.2s;
}

.form-group input:focus {
  outline: none;
  border-color: #007bff;
  box-shadow: 0 0 0 3px rgba(0, 123, 255, 0.1);
}

.form-group input:disabled {
  background: #f5f5f5;
  color: #999;
  cursor: not-allowed;
}

.form-group small {
  margin-top: 5px;
  color: #666;
  font-size: 12px;
}

.form-group.checkbox {
  flex-direction: row;
  align-items: center;
}

.form-group.checkbox input {
  margin-right: 8px;
  width: 18px;
  height: 18px;
  cursor: pointer;
}

.form-actions {
  display: flex;
  gap: 10px;
  margin-top: 25px;
  flex-wrap: wrap;
}

button {
  padding: 10px 20px;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 500;
  transition: all 0.2s;
}

.btn-primary {
  background: #007bff;
  color: white;
}

.btn-primary:hover:not(:disabled) {
  background: #0056b3;
  box-shadow: 0 2px 5px rgba(0, 86, 179, 0.3);
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-large {
  padding: 12px 30px;
  font-size: 15px;
  font-weight: 600;
}

.btn-secondary {
  background: #6c757d;
  color: white;
}

.btn-secondary:hover:not(:disabled) {
  background: #545b62;
}

.btn-secondary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-tertiary {
  background: #e9ecef;
  color: #333;
  border: 1px solid #ddd;
}

.btn-tertiary:hover:not(:disabled) {
  background: #e2e6ea;
}

.message {
  padding: 12px 15px;
  border-radius: 4px;
  margin-top: 15px;
  font-size: 14px;
}

.message.success {
  background: #d4edda;
  color: #155724;
  border: 1px solid #c3e6cb;
}

.message.error {
  background: #f8d7da;
  color: #721c24;
  border: 1px solid #f5c6cb;
}

.message.info {
  background: #d1ecf1;
  color: #0c5460;
  border: 1px solid #bee5eb;
}

.message.warning {
  background: #fff3cd;
  color: #856404;
  border: 1px solid #ffeeba;
}

.scaling-progress {
  margin-top: 20px;
  padding: 15px;
  background: #e7f3ff;
  border-radius: 4px;
}

.progress-bar {
  height: 6px;
  background: #ddd;
  border-radius: 3px;
  overflow: hidden;
  margin-bottom: 10px;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #007bff, #0056b3);
  animation: progress-animation 1.5s ease-in-out infinite;
}

@keyframes progress-animation {
  0% { width: 0%; }
  50% { width: 100%; }
  100% { width: 0%; }
}

.scaling-progress p {
  margin: 0;
  color: #004085;
  font-size: 13px;
  font-weight: 500;
}

.info-section {
  margin-top: 30px;
  padding: 20px;
  background: #f8f9fa;
  border-radius: 6px;
  border-left: 4px solid #007bff;
}

.two-column {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
  margin-top: 15px;
}

.method {
  padding: 15px;
  background: white;
  border-radius: 4px;
  border: 1px solid #ddd;
}

.method ol {
  margin: 10px 0;
  padding-left: 20px;
}

.method li {
  margin-bottom: 6px;
  color: #333;
  font-size: 13px;
}

.method code {
  display: block;
  background: #f5f5f5;
  padding: 8px 10px;
  border-radius: 3px;
  font-family: 'Courier New', monospace;
  font-size: 12px;
  overflow-x: auto;
  margin: 8px 0;
  border: 1px solid #ddd;
}

.method .note {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid #eee;
  font-size: 12px;
  color: #666;
}

.status-table {
  margin-top: 30px;
}

table {
  width: 100%;
  border-collapse: collapse;
}

table tr {
  border-bottom: 1px solid #eee;
}

table td {
  padding: 12px;
  font-size: 14px;
}

table tr:last-child td {
  border-bottom: none;
}

table td:first-child {
  font-weight: 500;
  color: #666;
  width: 50%;
}

table td.value {
  color: #222;
  font-weight: 500;
}

table td.value.active {
  color: #28a745;
}

@media (max-width: 768px) {
  .state-display,
  .two-column {
    grid-template-columns: 1fr;
  }

  .form-actions {
    flex-direction: column;
  }

  button {
    width: 100%;
  }

  .btn-large {
    width: 100%;
  }
}
</style>
```

---

## How It Works: Step-by-Step

### When User Clicks "Save & Apply Scaling":

```
Frontend (Vue)
    ↓
    1️⃣ saveAndApplyScaling() called
    ├─→ PUT /api/configuration/workers { desired_worker_count: 5 }
    │   └─→ Backend saves to MongoDB
    │
    ├─→ POST /api/workers/apply-scaling { desired_worker_count: 5 }
    │   └─→ Backend returns 202 Accepted
    │       (scaling starts in background thread)
    │
    2️⃣ monitorScalingProgress() starts
    ├─→ Every 2 seconds: GET /api/configuration/workers
    │   └─→ Checks current_worker_count vs desired_count
    │
    3️⃣ Show progress UI
    ├─→ Display "Scaling (15s)..." animation
    ├─→ Show progress bar with animation
    │
    4️⃣ scaling complete
    └─→ current_worker_count == desired_worker_count
        └─→ Stop monitoring, show success message
```

---

## What Happens in Background

```python
# Backend (core.py) during _execute_worker_scaling()

1. Docker-compose scale command is executed:
   docker-compose up -d --scale datapull_worker=5

2. Docker pulls latest images (if needed)

3. Starts/stops containers to match count:
   - If 3 running → wants 5: starts 2 more containers
   - If 10 running → wants 5: stops 5 containers

4. Each new container:
   - Runs queue_worker.py
   - Connects to Redis
   - Starts dequeuing jobs
   - Registers heartbeat metrics

5. Result logged to console:
   [UUID] Success: Scaled to 5 workers
```

---

## Key Features

### ✅ **One-Click Scaling**
```javascript
// User clicks "Save & Apply Scaling"
// Everything happens automatically:
// 1. Config saved to MongoDB ✓
// 2. Docker-compose scaling triggered ✓
// 3. Progress shown in UI ✓
// 4. Completion detected automatically ✓
```

### ✅ **Real-Time Progress**
```
┌──────────────────────────────┐
│ Current Workers: 3           │
│ Desired Workers: 5           │
│ (scaling to 5...)            │
│                              │
│ ████░░░░░░░░░░░░░░░░░░░░░░░ │
│ Scaling (8s)...              │
└──────────────────────────────┘
```

### ✅ **Safe & Idempotent**
```javascript
// Can click "Save & Apply" multiple times
// Each click:
// - Reads current state from Redis
// - Executes docker-compose scale N
// - If N workers already running → no change
// - If N < current → gracefully stops workers
// - If N > current → starts new workers
```

### ✅ **Auto-Refresh**
```javascript
// Every 5 seconds, Vue checks:
// - Current running workers
// - Queue depth
// - Last update timestamp

// If scaling detected:
// - Switch to 2-second refresh
// - Show progress animation
// - Update elapsed time counter
```

---

## Error Handling

```javascript
// Timeout (>5 minutes):
showMessage("Scaling timeout. Check server logs.", 'warning')

// Docker error:
catch (error) {
  showMessage(error.response.data.message, 'error')
  // Examples:
  // - "Docker not running"
  // - "Invalid scale count"
  // - "Insufficient disk space"
}

// Connection error:
catch (error) {
  showMessage("Failed to connect to API", 'error')
}
```

---

## Two-Button Approach

**"Save & Apply"** (one-click):
- `disabled` during scaling
- Shows loading spinner
- Auto-monitors progress
- Best for most users

**"Save Config Only"** (manual):
- For operators with CLI access
- Just saves config, doesn't scale
- User manually runs docker-compose command

---

## Summary

✅ **Frontend triggers scaling in one click**
✅ **Backend executes docker-compose scale asynchronously**
✅ **Vue monitors progress and updates UI in real-time**
✅ **Safe**: Idempotent docker-compose commands
✅ **Error-proof**: Timeout + error handling included

This is **Path 1B (Hybrid Approach)** — best UX while keeping it simple.

