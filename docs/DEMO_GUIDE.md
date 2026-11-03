# KubeGuard AI — Comprehensive Demonstration & Evaluation Guide

**Project Title:** Risk-Adaptive Authorization of LLM-Generated Kubernetes Remediation with GitOps-Based Execution  
**Academic Degree:** M.Tech in Cloud Computing  
**Git Branch:** `phase2-ollama-integration`  
**Target Review:** Final Year Capstone Project Defense  

---

## 1. System Architecture Overview

KubeGuard AI provides an intelligent authorization and safety layer between Large Language Models (LLMs) and production Kubernetes infrastructure. It enforces a strict **Zero-Unsupervised-Mutation Safeguard** by calculating a 5-factor risk score for every proposed remediation and requiring explicit human operator approval before changes are committed to a GitOps repository.

```text
[Kubernetes Cluster / Prometheus]
           │
           ▼
[Incident Detection: k8s_monitor.py] ──> Structured Incident Evidence
           │
           ▼
[Ollama LLM: llm_proposal.py] ────────> Llama 3.1 8B Proposal (restart_pod)
           │
           ▼
[Risk Engine: risk_engine.py] ─────────> R = 0.25(1-C) + 0.20(U) + 0.25(1-P) + 0.15(1-R) + 0.15(B)
           │
           ▼
[Authorization Gate: main.py] ─────────> AUTO_EXECUTE downgraded to HUMAN_APPROVAL
           │
     ┌─────┴──────────────┐
  [Approved]           [Denied / REJECT]
     │                    │
     ▼                    ▼
[GitOps Manifest Commit]  [Execution Blocked]
     │
     ▼
[Remote Git Push & Refspec Check: gitops_remediation.py]
     │
     ▼
[Argo CD Reconciliation: validator.py]
     │
     ▼
[Cluster Health Verification]
```

---

## 2. Environment Startup & Verification

Before presenting or demonstrating, verify that the prerequisite local services are running.

### Step 2.1: Verify Ollama Service and Model

In a PowerShell terminal:
```powershell
# Check Ollama server status and available models
ollama list
```
**Expected Output:**
```text
NAME            ID              SIZE      MODIFIED
llama3.1:8b     46e0c10c039e    4.9 GB    ...
```

If Ollama is stopped, start it with:
```powershell
ollama serve
```

### Step 2.2: Verify Minikube & Kubernetes Cluster

```powershell
# Verify node status
kubectl get nodes

# Verify active namespaces
kubectl get namespaces
```
**Expected Output:**
```text
NAME             STATUS   ROLES           AGE   VERSION
minikube         Ready    control-plane   34d   v1.37.0
```
Namespaces must include: `ai-remediation`, `argocd`, `monitoring`, and `kube-guard-lab`.

### Step 2.3: Verify Argo CD & Workload Health

```powershell
# Check Argo CD Applications
kubectl get applications -n argocd

# Check demo workloads
kubectl get deployment,pods -n ai-remediation -l app=demo-app
kubectl get deployment,pods -n kube-guard-lab -l app=lab-app
```
**Expected Output:**
```text
NAME             SYNC STATUS   HEALTH STATUS
ai-remediation   Synced        Healthy
kube-guard-lab   Synced        Healthy
```

### Step 2.4: Verify Prometheus & Monitoring Stack

```powershell
kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus
kubectl get svc -n monitoring monitoring-kube-prometheus-prometheus
```
**Expected Output:** Prometheus pod is in `Running` state (2/2 Ready).

If port-forwarding is needed for local metrics access:
```powershell
kubectl port-forward -n monitoring svc/monitoring-kube-prometheus-prometheus 9090:9090
```

---

## 3. Step-by-Step Demonstration Procedures

### Demo 1: Real Local LLM Remediation Proposal Generation

Demonstrates that KubeGuard AI connects to a live, local Ollama LLM (`llama3.1:8b`) to generate a structured, schema-validated remediation proposal with self-reported risk parameters.

**Command:**
```powershell
python llm_proposal.py
```
**Expected Output:**
```text
Ollama LLM Remediation Proposal
--------------------------------
incident: pod_failure
action: restart_pod
description: Restart the failed pod to recover from the failure.
confidence: 0.8
uncertainty: 0.2
policy_compliance: 0.9
reversibility: 0.7
blast_radius: 0.1
```
**Key Evaluation Points:**
- Execution runs 100% locally on device with zero external API dependencies or cloud API costs.
- Output strictly conforms to the JSON schema; non-numeric, NaN, boolean, or out-of-bounds values are rejected.
- Only safe, allowlisted actions (`restart_pod`) are accepted.

---

### Demo 2: Five-Factor Risk Assessment & Threshold Enforcement

Demonstrates the mathematical determinism of the risk calculation formula:
$$\text{Risk} = 0.25 \times (1 - C) + 0.20 \times U + 0.25 \times (1 - P) + 0.15 \times (1 - R) + 0.15 \times B$$

**Command:**
```powershell
python risk_engine.py
```
**Expected Output (when no active failure):**
```text
No incident detected
```

To demonstrate multi-scenario threshold evaluation across all 3 decision boundaries:
```powershell
python -c "
from risk_engine import calculate_risk

scenarios = [
    ('Low Risk Pod Restart', (0.90, 0.10, 1.00, 0.90, 0.10)),
    ('Medium Risk Config Tweak', (0.70, 0.40, 0.80, 0.60, 0.50)),
    ('High Risk Destructive Action', (0.40, 0.80, 0.40, 0.20, 0.90))
]

print(f'{\"Scenario\":<30} {\"Risk\":<10} {\"Decision\":<15}')
print('-' * 55)
for name, v in scenarios:
    r, d = calculate_risk(*v)
    print(f'{name:<30} {r:<10.3f} {d:<15}')
"
```
**Expected Output:**
```text
Scenario                       Risk       Decision       
-------------------------------------------------------
Low Risk Pod Restart           0.075      AUTO_EXECUTE   
Medium Risk Config Tweak       0.340      HUMAN_APPROVAL 
High Risk Destructive Action   0.715      REJECT         
```

---

### Demo 3: Prometheus Telemetry Integration

Demonstrates safe, non-blocking telemetry querying using `prometheus_client.py`.

**Command:**
```powershell
python prometheus_client.py
```
**Expected Output:**
```text
Checking Prometheus at http://localhost:9090...
Prometheus healthy: True
Observed restarts for nginx in ai-remediation: 2
Observed deployment metrics for demo-app: {'available_replicas': 1, 'desired_replicas': 1}
```

---

### Demo 4: Kubernetes Incident Detection

Demonstrates read-only Kubernetes cluster state inspection for pod failures (CrashLoopBackOff, ImagePullBackOff, OOMKilled, excessive restarts, and deployment replica shortfalls).

**Command:**
```powershell
python k8s_monitor.py
```
**Expected Output (under clean cluster conditions):**
```text
No incident detected.
```

---

### Demo 5: End-to-End Orchestration & Mandatory Human Approval

Demonstrates the complete pipeline executed by `main.py`.

**Command:**
```powershell
python main.py
```

#### Scenario A: Clean Cluster (No Incident)
```text
=== AI Kubernetes Remediation Authorization ===

No incident detected.
```

#### Scenario B: Incident Present (Simulated / Live)
```text
=== AI Kubernetes Remediation Authorization ===

Detected 1 incident(s)

Primary Incident
----------------
Type: pod_failure
Severity: medium
Resource: Pod/demo-app-...
Failure Reason: CrashLoopBackOff

LLM Remediation Proposal
------------------------
Action: restart_pod
Description: Restart the failed pod to recover from the failure.

Risk Assessment
----------------
Risk Score: 0.08
Risk Engine Decision: AUTO_EXECUTE

Authorization Safeguard
-----------------------
LLM-generated risk scores require human verification.
Effective Decision: HUMAN_APPROVAL
Approve this GitOps remediation? (yes/no): 
```

- Entering `no` prints:  
  `Human approval denied. No remediation executed.` (Terminates immediately with zero cluster changes).
- Entering `yes` initiates GitOps commit generation, remote push verification, and Argo CD sync polling.

---

### Demo 6: Real Isolated Live End-to-End Remediation (`kube-guard-lab`)

Demonstrates complete, safe, un-mocked live self-healing in an isolated sandbox namespace without touching production workloads (`ai-remediation/demo-app`).

#### Step 6.1: Verify Isolated Workload & Argo CD Application Health
```powershell
kubectl get application kube-guard-lab -n argocd
kubectl get pods,deployment,svc -n kube-guard-lab
```
*Expected Output:* `kube-guard-lab` is `Synced` and `Healthy`, `pod/lab-app-...` is `1/1 Running`.

#### Step 6.2: Introduce Controlled Failure in Lab Workload Only
```powershell
# Apply failure patch to lab deployment:
kubectl patch deployment lab-app -n kube-guard-lab --patch-file failure-patch-lab.yaml
```
Verify the crash:
```powershell
kubectl get pods -n kube-guard-lab
```
*Expected Output:* `lab-app-...` enters `CrashLoopBackOff` (`0/1 Ready`).

#### Step 6.3: Run Live Remediation Workflow
```powershell
python main.py --namespace kube-guard-lab --deployment lab-app --manifest gitops-lab/lab-app.yaml --app kube-guard-lab
```
- Incident Detection identifies `pod_failure` on `Pod/lab-app-...` (`CrashLoopBackOff`) with live Prometheus telemetry correlation.
- Local Ollama `llama3.1:8b` generates structured proposal `restart_pod`.
- Risk engine calculates risk score (e.g., $0.17$).
- Authorization safeguard requires human approval:
  ```text
  Approve this GitOps remediation? (yes/no): yes
  ```
- Upon typing `yes`:
  - `gitops-lab/lab-app.yaml` is updated with a unique restart annotation and restored container command.
  - Manifest is dry-run validated with `kubectl apply --dry-run=client`.
  - Changes are committed and pushed to `phase2-ollama-integration`.
  - Remote push ancestry is confirmed on `origin/phase2-ollama-integration`.
  - Argo CD synchronizes the exact commit revision.
  - Validator confirms:
    ```text
    Validation: SUCCESS
    GitOps and Kubernetes remediation completed successfully.
    Verified synchronized commit: <commit-sha>
    ```

#### Step 6.4: Optional Teardown & Cleanup of Lab Resources
When the demonstration is complete:
```powershell
# Remove the isolated Argo CD application:
kubectl delete application kube-guard-lab -n argocd

# Delete the isolated namespace (does NOT affect ai-remediation, argocd, or monitoring):
kubectl delete namespace kube-guard-lab
```

---

## 4. Automated Test Suite Verification

Demonstrates the QA and code reliability of the prototype.

**Command:**
```powershell
python -m unittest discover -s tests -v
```
**Expected Result:**
```text
Ran 110 tests in 1.4s

OK
```
**Test Coverage Breakdown:**
- `test_k8s_monitor.py`: Pod failures, OOMKilled, CrashLoopBackOff, replica deficits, API errors.
- `test_prometheus_client.py`: Instant queries, vector parsing, timeouts, missing metrics, server errors.
- `test_llm_proposal.py`: Schema validation, score validation (NaN, inf, bool, strings), allowlist, Ollama API mocks.
- `test_risk_engine.py`: Formula calculation, threshold boundary conditions, type checks.
- `test_incident_selection.py`: Primary incident prioritization heuristics.
- `test_gitops_remediation.py`: Multi-workload support, custom manifests, branch safety, staged diff validation, explicit refspec push verification, ancestry checks.
- `test_validator.py`: Argo CD sync/health checks, commit SHA matching, targetRevision alignment, replica readiness.
- `test_main_workflow.py`: End-to-end orchestration, multi-namespace parameters, auto-execute downgrade, human approval, fail-closed handling.
- `test_executor.py`: Legacy direct executor safeguards.

---

## 5. Fallback Procedures (If Live Services are Offline)

| Service Offline | Impact | Fallback Procedure |
|---|---|---|
| **Ollama Offline** | LLM proposal raises `ProposalError` | `main.py` catches `ProposalError`, reports `Remediation proposal rejected: Ollama connection failed`, and safely terminates with zero cluster mutation. Run automated tests in `test_llm_proposal.py` which mock all Ollama interactions. |
| **Prometheus Offline** | Telemetry unavailable | `prometheus_client.py` returns `None`; `k8s_monitor.py` continues functioning seamlessly using direct Kubernetes API status checks. |
| **Minikube Stopped** | Cluster unreachable | `k8s_monitor.py` and `validator.py` catch connection errors, log a clean diagnostic, and exit cleanly without crashing. Execute test suite with mocked Kubernetes client responses. |
| **Git Remote Unreachable** | Remote push fails | `gitops_remediation.py` catches `CalledProcessError`, returns `RemediationResult(success=False, unpushed_commit=...)`, and aborts before calling validation. |
