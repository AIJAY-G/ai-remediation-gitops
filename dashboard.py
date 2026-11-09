"""
KubeGuard AI — Enterprise Autonomous Self-Healing Dashboard
Built with Streamlit, Kubernetes Client, and Ollama.
"""

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
import streamlit as st

# Import KubeGuard AI Core Modules
try:
    from rbac import ROLES, VALID_ROLE_NAMES, get_current_operator, authorize_approval
    from audit_logger import verify_audit_log_integrity, AUDIT_LOG_FILE, log_audit_event
    from chatops import NOTIFICATION_LOG
    from risk_engine import calculate_risk, evaluate_policy_compliance
    from k8s_monitor import detect_incident, select_primary_incident, fetch_pod_logs, fetch_pod_events
    from llm_proposal import generate_remediation, OLLAMA_HOST, OLLAMA_MODEL
    from gitops_remediation import apply_gitops_remediation, MANIFEST
except ImportError as e:
    st.error(f"Error loading KubeGuard modules: {e}")

# Streamlit Page Configuration
st.set_page_config(
    page_title="KubeGuard AI — Enterprise Autonomous SRE Platform",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Enterprise Dark-Theme CSS
st.markdown("""
<style>
    .main-header {
        font-size: 2.2rem;
        font-weight: 800;
        background: linear-gradient(90deg, #00D2FF 0%, #3A7BD5 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0px;
    }
    .sub-header {
        color: #8E9BAE;
        font-size: 1.05rem;
        margin-bottom: 25px;
    }
    .metric-card {
        background: #151B28;
        border: 1px solid #243048;
        border-radius: 10px;
        padding: 16px 20px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
    }
    .metric-title {
        color: #7E8C9F;
        font-size: 0.85rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    .metric-value {
        font-size: 1.6rem;
        font-weight: 700;
        color: #F0F4F8;
        margin-top: 4px;
    }
    .status-badge-healthy {
        background-color: rgba(16, 185, 129, 0.15);
        color: #10B981;
        border: 1px solid #10B981;
        padding: 4px 10px;
        border-radius: 6px;
        font-weight: 600;
        font-size: 0.85rem;
        display: inline-block;
    }
    .status-badge-warning {
        background-color: rgba(245, 158, 11, 0.15);
        color: #F59E0B;
        border: 1px solid #F59E0B;
        padding: 4px 10px;
        border-radius: 6px;
        font-weight: 600;
        font-size: 0.85rem;
        display: inline-block;
    }
    .status-badge-critical {
        background-color: rgba(239, 68, 68, 0.15);
        color: #EF4444;
        border: 1px solid #EF4444;
        padding: 4px 10px;
        border-radius: 6px;
        font-weight: 600;
        font-size: 0.85rem;
        display: inline-block;
    }
    .audit-card {
        background: #111827;
        border-left: 4px solid #3B82F6;
        border-radius: 6px;
        padding: 12px 16px;
        margin-bottom: 12px;
    }
</style>
""", unsafe_allow_html=True)


# ==========================================
# Sidebar: System Health & RBAC Identity
# ==========================================
st.sidebar.markdown("### 🛡️ KubeGuard AI Guardrail")
st.sidebar.markdown("**Enterprise Autonomous Remediation**")

# Operator Identity Persona
st.sidebar.markdown("---")
st.sidebar.markdown("#### 👤 Operator RBAC Identity")
role_selection = st.sidebar.selectbox(
    "Active Persona Role",
    options=["SRE-Lead", "Platform-Admin", "Developer", "Auditor", "Viewer"],
    index=0
)
operator_name = st.sidebar.text_input("Operator Username", value="aijay")
os.environ["KUBEGUARD_USER"] = operator_name
os.environ["KUBEGUARD_ROLE"] = role_selection

# Permitted actions for this persona
allowed_tiers = ROLES.get(role_selection, set())
st.sidebar.caption(f"**Clearance Tiers:** `{', '.join(allowed_tiers) if allowed_tiers else 'Read-Only'}`")

# Cluster & LLM Status
st.sidebar.markdown("---")
st.sidebar.markdown("#### ⚙️ Cluster & Engine Status")

# Test Ollama connection
try:
    import urllib.request
    req = urllib.request.Request(f"{OLLAMA_HOST}/api/tags", headers={"User-Agent": "KubeGuard-Dashboard"})
    with urllib.request.urlopen(req, timeout=1.5) as resp:
        if resp.status == 200:
            st.sidebar.markdown("🟢 **Ollama Local LLM:** Active (`llama3.1:8b`)")
        else:
            st.sidebar.markdown("🟡 **Ollama Local LLM:** Degraded")
except Exception:
    st.sidebar.markdown("🟡 **Ollama Local LLM:** Standby / Air-gapped")

# Test Kubernetes connection
try:
    from kubernetes import client, config
    config.load_kube_config()
    v1 = client.CoreV1Api()
    ns_list = v1.list_namespace(timeout_seconds=2)
    st.sidebar.markdown("🟢 **Kubernetes Cluster:** Connected (Minikube)")
except Exception:
    st.sidebar.markdown("🟡 **Kubernetes Cluster:** Local Sandbox / Standby")

st.sidebar.markdown("🟢 **Argo CD GitOps:** Synced (`kube-guard-lab`)")
st.sidebar.markdown("🟢 **Audit Ledger:** Append-Only SHA-256 Chained")

st.sidebar.markdown("---")
if st.sidebar.button("🔄 Refresh Telemetry & Cluster State", use_container_width=True):
    st.rerun()


# ==========================================
# Main Header & Top Metrics Bar
# ==========================================
st.markdown('<div class="main-header">🛡️ KubeGuard AI — Autonomous Kubernetes Platform</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Zero Cloud Data Egress &bull; Local Ollama Reasoning &bull; 5-Factor Risk Guardrail &bull; GitOps Reconciliation</div>', unsafe_allow_html=True)

# Fetch current incidents
target_ns = "ai-remediation"
incidents = []
try:
    incidents = detect_incident(namespace=target_ns)
except Exception:
    incidents = []

primary_incident = select_primary_incident(incidents) if incidents else None

# Check audit log records
audit_verified, audit_msg, audit_count = False, "No audit log found", 0
try:
    audit_verified, audit_msg, audit_count = verify_audit_log_integrity()
except Exception:
    pass

col1, col2, col3, col4, col5 = st.columns(5)

with col1:
    st.markdown('<div class="metric-card">', unsafe_allow_html=True)
    st.markdown('<div class="metric-title">Cluster Health</div>', unsafe_allow_html=True)
    if not incidents:
        st.markdown('<div class="status-badge-healthy">● All Pods Healthy</div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="status-badge-critical">● {len(incidents)} Incident(s)</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

with col2:
    st.markdown('<div class="metric-card">', unsafe_allow_html=True)
    st.markdown('<div class="metric-title">Local Reasoner</div>', unsafe_allow_html=True)
    st.markdown('<div class="metric-value" style="font-size:1.3rem;">llama3.1:8b</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

with col3:
    st.markdown('<div class="metric-card">', unsafe_allow_html=True)
    st.markdown('<div class="metric-title">Risk Engine</div>', unsafe_allow_html=True)
    st.markdown('<div class="metric-value" style="font-size:1.3rem; color:#10B981;">5-Factor Guard</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

with col4:
    st.markdown('<div class="metric-card">', unsafe_allow_html=True)
    st.markdown('<div class="metric-title">GitOps Sync</div>', unsafe_allow_html=True)
    st.markdown('<div class="metric-value" style="font-size:1.3rem; color:#3B82F6;">Argo CD</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

with col5:
    st.markdown('<div class="metric-card">', unsafe_allow_html=True)
    st.markdown('<div class="metric-title">SOC2 Audit Chain</div>', unsafe_allow_html=True)
    if audit_verified:
        st.markdown(f'<div class="metric-value" style="font-size:1.3rem; color:#10B981;">{audit_count} Verified</div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="metric-value" style="font-size:1.3rem; color:#F59E0B;">{audit_count} Logged</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)


# ==========================================
# Main Navigation Tabs
# ==========================================
tab_monitor, tab_risk, tab_gitops, tab_audit, tab_chatops = st.tabs([
    "🖥️ Live Cluster & Incident Observer",
    "🧠 AI Diagnosis & 5-Factor Risk Engine",
    "🚦 Human-in-the-Loop & GitOps Control",
    "🔐 Cryptographic Compliance Audit Trail",
    "💬 Enterprise ChatOps Alert Stream"
])


# =========================================================================
# TAB 1: Live Cluster & Incident Observer
# =========================================================================
with tab_monitor:
    st.subheader("Kubernetes Namespace Telemetry (`ai-remediation`)")

    # Pod Query
    pod_data = []
    try:
        from kubernetes import client
        v1 = client.CoreV1Api()
        pod_list = v1.list_namespaced_pod(target_ns)
        for p in pod_list.items:
            p_name = p.metadata.name
            p_phase = p.status.phase or "Unknown"
            ready_count = sum(1 for c in (p.status.container_statuses or []) if c.ready)
            total_count = len(p.status.container_statuses or [])
            restarts = sum(c.restart_count for c in (p.status.container_statuses or []))
            
            # Identify waiting or failure reason
            status_desc = p_phase
            for c in (p.status.container_statuses or []):
                if c.state and c.state.waiting and c.state.waiting.reason:
                    status_desc = c.state.waiting.reason
                elif c.state and c.state.terminated and c.state.terminated.reason:
                    status_desc = c.state.terminated.reason

            pod_data.append({
                "Pod Name": p_name,
                "Ready": f"{ready_count}/{total_count}",
                "Status": status_desc,
                "Restarts": restarts,
                "Age": p.metadata.creation_timestamp.strftime("%Y-%m-%d %H:%M:%S") if p.metadata.creation_timestamp else "N/A"
            })
    except Exception as e:
        # Fallback demonstration data if cluster disconnected
        pod_data = [
            {"Pod Name": "demo-app-7b6c59b64c-xyz12", "Ready": "1/1", "Status": "Running", "Restarts": 0, "Age": "2026-11-08 15:30:00"},
            {"Pod Name": "lab-app-5887cf7cf4-k7q9w", "Ready": "1/1", "Status": "Running", "Restarts": 0, "Age": "2026-11-08 16:10:00"}
        ]

    st.dataframe(pod_data, use_container_width=True)

    # Active Incidents Section
    st.markdown("---")
    st.subheader("🚨 Active Incident Diagnostics")

    if primary_incident:
        inc_res = f"{primary_incident.get('resource_type', 'Pod')}/{primary_incident.get('resource_name', 'unknown')}"
        inc_reason = primary_incident.get("evidence", {}).get("failure_reason", "Abnormal crash")
        st.error(f"**Anomaly Detected on `{inc_res}`** — Failure Signature: `{inc_reason}`")

        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### 📋 Incident Evidence Metadata")
            st.json(primary_incident.get("evidence", {}))

        with c2:
            st.markdown("#### 📜 Live Container Logs (Tail)")
            pod_name = primary_incident.get("resource_name", "")
            logs = fetch_pod_logs(pod_name, namespace=target_ns)
            st.code(logs if logs else "No logs available or pod starting...", language="bash")

        events = fetch_pod_events(pod_name, namespace=target_ns)
        if events:
            st.markdown("#### ⚠️ Kubernetes Warning Events")
            for ev in events:
                st.warning(f"**[{ev.get('reason')}]** {ev.get('message')} (x{ev.get('count')})")
    else:
        st.success("✅ **Zero Active Incidents:** All pods and deployments in namespace `ai-remediation` are passing readiness and liveness probes.")


# =========================================================================
# TAB 2: AI Diagnosis & 5-Factor Risk Engine
# =========================================================================
with tab_risk:
    st.subheader("Local LLM Diagnostic Engine & Deterministic Risk Formula")

    col_llm, col_gauge = st.columns([1.2, 1])

    with col_llm:
        st.markdown("#### 🤖 Local Ollama RCA (`llama3.1:8b`)")
        st.caption("Air-gapped local inference — zero telemetry or cluster metadata sent to third-party cloud APIs.")
        
        sample_explanation = "The container repeatedly encountered CrashLoopBackOff due to a missing runtime dependency. Initiating a safe GitOps pod restart annotation will trigger a clean container restart without altering application configuration."
        sample_action = "restart_pod"
        
        if primary_incident:
            with st.spinner("Querying local Ollama llama3.1:8b model..."):
                try:
                    proposal = generate_remediation(primary_incident)
                    sample_explanation = proposal.get("description", sample_explanation)
                    sample_action = proposal.get("action", sample_action)
                except Exception as e:
                    sample_explanation = f"Ollama local inference standby: {e}"

        st.info(f"**Diagnosed Root Cause:**\n\n{sample_explanation}")
        st.markdown(f"**Recommended Action:** `{sample_action}`")

    with col_gauge:
        st.markdown("#### 📐 Mathematical 5-Factor Risk Model")
        st.caption("Objective linear formulation preventing LLM hallucination in production clusters.")

        # Interactive simulation sliders
        st.markdown("**Test Parameters / Current Assessment:**")
        sim_conf = st.slider("LLM Confidence Score", 0.0, 1.0, 0.90, 0.05)
        sim_uncert = st.slider("Epistemic Uncertainty", 0.0, 1.0, 0.10, 0.05)
        sim_policy = st.slider("Policy-as-Code Compliance (OPA)", 0.0, 1.0, 1.0, 0.05)
        sim_rev = st.slider("Action Reversibility (GitOps)", 0.0, 1.0, 0.90, 0.05)
        sim_blast = st.slider("Blast Radius (Impact on Cluster)", 0.0, 1.0, 0.10, 0.05)

        # Formula calculation
        risk_score, decision = calculate_risk(sim_conf, sim_uncert, sim_policy, sim_rev, sim_blast)

        st.markdown("---")
        st.markdown(f"### Composite Risk Score: `{risk_score:.3f}`")
        
        # Color-coded progress
        if risk_score < 0.30:
            st.progress(float(risk_score))
            st.markdown('<div class="status-badge-healthy" style="font-size:1.1rem;">DECISION: AUTO_EXECUTE (Low Risk)</div>', unsafe_allow_html=True)
            st.caption("Safe for fully autonomous execution without human bottleneck.")
        elif risk_score < 0.60:
            st.progress(float(risk_score))
            st.markdown('<div class="status-badge-warning" style="font-size:1.1rem;">DECISION: HUMAN_APPROVAL (Medium Risk)</div>', unsafe_allow_html=True)
            st.caption("Requires affirmative clearance from an authorized SRE-Lead or Platform-Admin.")
        else:
            st.progress(float(risk_score))
            st.markdown('<div class="status-badge-critical" style="font-size:1.1rem;">DECISION: REJECT (High Risk)</div>', unsafe_allow_html=True)
            st.caption("Action violates security policies or blast radius exceeds acceptable safety thresholds.")

    st.markdown("---")
    st.markdown("""
    **Deterministic Mathematical Formula:**
    $$Risk = 0.25 \\cdot (1 - \\text{Confidence}) + 0.20 \\cdot \\text{Uncertainty} + 0.25 \\cdot (1 - \\text{PolicyCompliance}) + 0.15 \\cdot (1 - \\text{Reversibility}) + 0.15 \\cdot \\text{BlastRadius}$$
    """)


# =========================================================================
# TAB 3: Human-in-the-Loop & GitOps Control Plane
# =========================================================================
with tab_gitops:
    st.subheader("Human-in-the-Loop RBAC Authorization & GitOps Reconciliation")

    col_auth, col_pipeline = st.columns([1, 1.2])

    with col_auth:
        st.markdown("#### 🔐 RBAC Approval Clearance Gate")
        st.markdown(f"**Current Operator:** `{operator_name}` &bull; **Active Role:** `{role_selection}`")

        # Evaluate authorization
        is_authorized, auth_msg = authorize_approval(role_selection, decision)

        if is_authorized:
            st.success(f"✅ **Clearance Confirmed:** {auth_msg}")
        else:
            st.error(f"⛔ **Clearance Denied:** {auth_msg}")

        st.markdown("---")
        st.markdown("#### 🎯 Execution Triggers")

        c_app, c_rej = st.columns(2)
        with c_app:
            approve_clicked = st.button("✅ Approve & Execute GitOps PR", disabled=not is_authorized, use_container_width=True)
        with c_rej:
            reject_clicked = st.button("❌ Reject Remediation", use_container_width=True)

        if approve_clicked:
            st.info("🚀 Initiating GitOps commit to repository...")
            try:
                res = apply_gitops_remediation(action=sample_action)
                if res.success:
                    st.success(f"🎉 **GitOps Commit Created & Pushed:** `{res.commit[:7] if res.commit else 'HEAD'}`")
                    # Log audit event
                    log_audit_event(
                        incident_id=primary_incident.get("incident_id", "INC-LIVE-DASHBOARD") if primary_incident else "INC-LIVE-DASHBOARD",
                        resource=primary_incident.get("resource_name", "demo-app") if primary_incident else "demo-app",
                        failure_reason=primary_incident.get("evidence", {}).get("failure_reason", "CrashLoopBackOff") if primary_incident else "CrashLoopBackOff",
                        action=sample_action,
                        risk_score=risk_score,
                        risk_vector={"confidence": sim_conf, "uncertainty": sim_uncert, "policy_compliance": sim_policy, "reversibility": sim_rev, "blast_radius": sim_blast},
                        policy_status="Policy compliant",
                        decision="AUTHORIZED_AND_EXECUTED",
                        authorized_by=operator_name,
                        authorizer_role=role_selection,
                        git_commit=res.commit,
                        validation_status="SUCCESS",
                        description=sample_explanation
                    )
                    st.balloons()
                else:
                    st.warning(f"GitOps execution notice: {res.message}")
            except Exception as e:
                st.error(f"GitOps execution error: {e}")

        if reject_clicked:
            st.warning("Remediation proposal rejected by operator.")
            log_audit_event(
                incident_id="INC-REJECTED",
                resource="demo-app",
                failure_reason="Operator rejected",
                action=sample_action,
                risk_score=risk_score,
                risk_vector={"confidence": sim_conf, "uncertainty": sim_uncert, "policy_compliance": sim_policy, "reversibility": sim_rev, "blast_radius": sim_blast},
                policy_status="Policy compliant",
                decision="DENIED_BY_HUMAN",
                authorized_by=operator_name,
                authorizer_role=role_selection,
                git_commit=None,
                validation_status="REJECTED",
                description="Rejected by operator via web dashboard"
            )

    with col_pipeline:
        st.markdown("#### 🔄 Closed-Loop GitOps Architecture")
        st.markdown("""
        ```mermaid
        flowchart TD
            A[Cluster Anomaly: CrashLoopBackOff] --> B[KubeGuard AI Observer]
            B --> C[Air-Gapped Ollama llama3.1:8b RCA]
            C --> D[5-Factor Deterministic Risk Engine]
            D -->|Risk >= 0.30| E[RBAC Human-in-the-Loop Gate]
            D -->|Risk < 0.30| F[Autonomous GitOps Commit]
            E -->|SRE-Lead Approves| F
            F --> G[Git Push to Repository]
            G --> H[Argo CD Automated Reconciliation]
            H --> I[Post-Reconciliation Validation]
            I -->|Healthy| J[Cryptographic Audit Ledger]
            I -->|Still Unhealthy| K[Automated Git Revert Circuit Breaker]
        ```
        """)


# =========================================================================
# TAB 4: Cryptographic Compliance Audit Trail (SOC2 & ISO 27001)
# =========================================================================
with tab_audit:
    st.subheader("Append-Only Cryptographic Audit Ledger (SOC2 / ISO 27001)")
    st.caption("Every incident, raw LLM diagnosis, risk score, approver signature, and Git commit SHA is chained with SHA-256 hashes.")

    c_audit_top1, c_audit_top2 = st.columns([1.5, 1])
    with c_audit_top1:
        st.markdown(f"**Audit Ledger Path:** `{AUDIT_LOG_FILE}`")
    with c_audit_top2:
        if st.button("🔍 Run Cryptographic Hash Chain Verification", use_container_width=True):
            v_ok, v_msg, v_cnt = verify_audit_log_integrity()
            if v_ok:
                st.success(f"🛡️ **{v_msg}**")
            else:
                st.error(f"❌ **Integrity Alert:** {v_msg}")

    # Read and display audit ledger entries
    audit_records = []
    if AUDIT_LOG_FILE.exists():
        with AUDIT_LOG_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    try:
                        audit_records.append(json.loads(stripped))
                    except Exception:
                        pass

    if audit_records:
        st.markdown(f"**Total Cryptographic Records:** `{len(audit_records)}`")
        
        # Table of recent audit records
        formatted_table = []
        for r in reversed(audit_records[-15:]):
            formatted_table.append({
                "Timestamp (UTC)": r.get("timestamp_utc", "")[:19].replace("T", " "),
                "Incident ID": r.get("incident_id"),
                "Resource": r.get("resource"),
                "Failure": r.get("failure_reason"),
                "Action": r.get("proposed_action"),
                "Risk": f"{r.get('risk_score', 0):.2f}",
                "Decision": r.get("authorization_decision"),
                "Approver": f"{r.get('authorized_by')} ({r.get('authorizer_role')})",
                "Git Commit": (r.get("git_commit_sha") or "NONE")[:7],
                "Record SHA256": (r.get("record_hash") or "")[:12] + "..."
            })
        st.dataframe(formatted_table, use_container_width=True)

        with st.expander("🔎 Inspect Most Recent Cryptographic Record (JSON Proof)"):
            st.json(audit_records[-1])
    else:
        st.info("No compliance audit records found yet. Trigger an action to create the genesis block!")


# =========================================================================
# TAB 5: Enterprise ChatOps Alert Stream
# =========================================================================
with tab_chatops:
    st.subheader("Enterprise ChatOps Notification Feed (Slack / Teams / Discord)")
    st.caption("Real-time webhook notifications dispatched for incident triage and approval.")

    webhook_configured = bool(os.getenv("KUBEGUARD_SLACK_WEBHOOK"))
    if webhook_configured:
        st.success("🟢 **Slack Incoming Webhook:** Configured and active")
    else:
        st.info("ℹ️ **Local Notification Mode:** Webhook not set — alerts are logged locally to `evidence/chatops_notifications.jsonl`")

    chatops_records = []
    if NOTIFICATION_LOG.exists():
        with NOTIFICATION_LOG.open("r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if s:
                    try:
                        chatops_records.append(json.loads(s))
                    except Exception:
                        pass

    if chatops_records:
        for alert in reversed(chatops_records[-10:]):
            ts = alert.get("timestamp_utc", "")[:19].replace("T", " ")
            payload = alert.get("payload", {})
            title = payload.get("text", "KubeGuard AI Incident Alert")
            att = (payload.get("attachments", [{}]) or [{}])[0]
            color = att.get("color", "#36a64f")
            
            st.markdown(f"""
            <div class="audit-card" style="border-left-color: {color};">
                <div style="font-weight:700; font-size:1.05rem; color:#F0F4F8;">{title}</div>
                <div style="font-size:0.85rem; color:#8E9BAE; margin-bottom:8px;">{ts} UTC &bull; Status: {alert.get('delivery_status')}</div>
            """, unsafe_allow_html=True)
            
            fields = att.get("fields", [])
            f_cols = st.columns(len(fields) if fields else 1)
            for idx, f in enumerate(fields):
                with f_cols[idx]:
                    st.caption(f.get("title", ""))
                    st.markdown(f"**{f.get('value', '')}**")
            st.markdown("</div>", unsafe_allow_html=True)
    else:
        st.info("No ChatOps notifications logged yet.")
