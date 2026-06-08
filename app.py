"""
DevOps Engineer's Utility  —  Streamlit console
================================================
A single-pane utility that mirrors what a DevOps engineer does day to day, modelled
on real DevOps dashboards / internal developer portals. Modules:

    Overview     - mission control: DORA metrics, service health, activity feed
    CI/CD        - pipeline runs, success rate, slowest/most-failing stage, flaky tests
    Monitoring   - golden signals + automatic anomaly analysis & recommendations
    Logs         - searchable log stream, level breakdown, top error patterns, spikes
    Infrastructure - host/container/cloud inventory, utilisation, IaC drift
    Incidents    - open/resolved incidents, severity, MTTR, on-call
    Security     - vulnerability scan results, compliance posture, risk score
    Deployments  - release history, environments, strategy, rollback

Every module does ANALYSIS, not just display: it computes findings and prints a
"what to do next" recommendation, which is the part a DevOps engineer cares about.

DATA: ships with deterministic demo data so it presents fully populated out of the
box. Each generator is marked  # >> WIRE REAL SOURCE HERE  so you can swap in your
application's real feeds (CI API, Prometheus/Datadog, log backend, cloud SDK, etc.).

Run:     pip install -r requirements.txt && streamlit run app.py
"""

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ======================================================================================
# Config & constants
# ======================================================================================
st.set_page_config(page_title="DevOps Utility", page_icon="🛠️", layout="wide")

SERVICES = ["payments-api", "auth-service", "web-frontend",
            "order-service", "notification-svc", "inventory-svc"]
ENVS = ["dev", "staging", "prod"]
ACCENT = "#ff7a3d"
TEAL = "#3ad6c8"
RED = "#ff5d5d"
AMBER = "#ffb648"
GREEN = "#4ade80"
GREY = "#8593a6"
SEED = 42

st.markdown(
    """
    <style>
      @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600;700&family=IBM+Plex+Sans:wght@400;500;600&display=swap');
      html, body, [class*="css"] { font-family:'IBM Plex Sans',sans-serif; }
      h1,h2,h3,h4 { font-family:'IBM Plex Mono',monospace !important; letter-spacing:-.01em; }
      .pill { display:inline-block; font-family:'IBM Plex Mono',monospace; font-size:11px;
              padding:3px 10px; border-radius:99px; margin-right:4px; }
      .analysis { border-left:3px solid #ff7a3d; background:rgba(255,122,61,.08);
                  border-radius:8px; padding:14px 16px; margin:6px 0 4px; }
      .analysis b { color:#ff7a3d; font-family:'IBM Plex Mono',monospace; }
      div[data-testid="stMetricValue"] { font-family:'IBM Plex Mono',monospace; }
    </style>
    """,
    unsafe_allow_html=True,
)


def status_pill(text, color):
    return (f"<span class='pill' style='color:{color};border:1px solid {color}55;"
            f"background:{color}14'>{text}</span>")


def analysis_box(html):
    st.markdown(f"<div class='analysis'>🔍 <b>ANALYSIS</b> &nbsp; {html}</div>",
                unsafe_allow_html=True)


def plotly_dark(fig, height=300):
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="IBM Plex Sans", color="#c8d2de", size=11),
        margin=dict(l=10, r=10, t=30, b=10), height=height,
        xaxis=dict(gridcolor="rgba(255,255,255,.07)"),
        yaxis=dict(gridcolor="rgba(255,255,255,.07)"),
        legend=dict(orientation="h", y=-0.2),
    )
    return fig


# ======================================================================================
# Data layer  (deterministic demo data — replace each generator with a real feed)
# ======================================================================================
@st.cache_data
def gen_metrics():
    """# >> WIRE REAL SOURCE HERE: Prometheus / Datadog / CloudWatch query."""
    rng = np.random.default_rng(SEED)
    end = datetime.now().replace(minute=0, second=0, microsecond=0)
    hours = [end - timedelta(hours=h) for h in range(47, -1, -1)]
    rows = []
    for svc in SERVICES:
        base_lat = rng.uniform(40, 120)
        base_err = rng.uniform(0.2, 1.2)
        base_rps = rng.uniform(80, 400)
        for i, ts in enumerate(hours):
            diurnal = 1 + 0.4 * np.sin((i % 24) / 24 * 2 * np.pi)
            lat = base_lat * diurnal + rng.normal(0, 6)
            err = max(0, base_err + rng.normal(0, 0.25))
            rps = base_rps * diurnal + rng.normal(0, 15)
            cpu = min(98, 35 * diurnal + rng.normal(0, 6))
            mem = min(96, 50 + rng.normal(0, 5))
            # inject an incident window on payments-api
            if svc == "payments-api" and 30 <= i <= 36:
                lat *= 3.4
                err += 6.5
                cpu = min(99, cpu + 35)
            rows.append(dict(ts=ts, service=svc, latency_p95=round(lat, 1),
                             error_rate=round(err, 2), rps=round(max(0, rps), 0),
                             cpu=round(cpu, 1), mem=round(mem, 1)))
    return pd.DataFrame(rows)


@st.cache_data
def gen_pipelines():
    """# >> WIRE REAL SOURCE HERE: GitHub Actions / GitLab CI / Jenkins API."""
    rng = np.random.default_rng(SEED + 1)
    stages = ["build", "unit-test", "integration-test", "security-scan", "deploy"]
    rows = []
    for n in range(40):
        svc = rng.choice(SERVICES)
        branch = rng.choice(["main", "feature/checkout", "fix/auth-token", "release/2.4"])
        ts = datetime.now() - timedelta(hours=int(rng.integers(1, 120)))
        # decide a failing stage sometimes
        fail = rng.random() < 0.22
        fail_stage = rng.choice(stages) if fail else None
        dur = {}
        status = "success"
        reached = True
        for sstage in stages:
            if not reached:
                dur[sstage] = None
                continue
            d = round(rng.uniform(20, 240), 0)
            dur[sstage] = d
            if sstage == fail_stage:
                status = "failed"
                reached = False
        rows.append(dict(run_id=1200 + n, service=svc, branch=branch, ts=ts,
                         status=status, failed_stage=fail_stage,
                         duration_s=int(sum(v for v in dur.values() if v)),
                         **{f"d_{s}": dur[s] for s in stages}))
    df = pd.DataFrame(rows).sort_values("ts", ascending=False).reset_index(drop=True)
    return df, stages


@st.cache_data
def gen_logs():
    """# >> WIRE REAL SOURCE HERE: ELK / Loki / CloudWatch Logs query."""
    rng = np.random.default_rng(SEED + 2)
    templates = [
        ("INFO", "Request handled in {ms}ms"),
        ("INFO", "Health check OK"),
        ("INFO", "Cache hit for key user:{id}"),
        ("WARN", "Slow query took {ms}ms"),
        ("WARN", "Retry {n}/3 for upstream call"),
        ("ERROR", "Upstream timeout calling payments gateway"),
        ("ERROR", "NullPointerException in OrderHandler"),
        ("ERROR", "Connection pool exhausted"),
        ("ERROR", "5xx returned from auth-service"),
    ]
    rows = []
    for _ in range(400):
        svc = rng.choice(SERVICES)
        ts = datetime.now() - timedelta(minutes=int(rng.integers(1, 720)))
        weights = [22, 18, 16, 10, 8, 9, 7, 5, 5]
        lvl, msg = templates[rng.choice(len(templates), p=np.array(weights) / sum(weights))]
        msg = msg.format(ms=int(rng.integers(20, 4000)), id=int(rng.integers(1, 9999)),
                         n=int(rng.integers(1, 3)))
        rows.append(dict(ts=ts, service=svc, level=lvl, message=msg))
    return pd.DataFrame(rows).sort_values("ts", ascending=False).reset_index(drop=True)


@st.cache_data
def gen_infra():
    """# >> WIRE REAL SOURCE HERE: cloud SDK (boto3/azure-sdk) / k8s API."""
    rng = np.random.default_rng(SEED + 3)
    kinds = ["EC2", "Pod", "RDS", "Lambda", "LB"]
    rows = []
    for i in range(14):
        kind = rng.choice(kinds)
        cpu = round(rng.uniform(8, 92), 1)
        mem = round(rng.uniform(20, 95), 1)
        drift = rng.random() < 0.18
        status = "running" if rng.random() > 0.08 else "degraded"
        rows.append(dict(resource=f"{kind.lower()}-{1000+i}", kind=kind,
                         env=rng.choice(ENVS), region=rng.choice(["ap-south-1", "us-east-1", "eu-west-1"]),
                         cpu=cpu, mem=mem, status=status, iac_drift=drift,
                         monthly_cost=round(rng.uniform(12, 480), 2)))
    return pd.DataFrame(rows)


@st.cache_data
def gen_incidents():
    """# >> WIRE REAL SOURCE HERE: PagerDuty / Opsgenie / Statuspage API."""
    rng = np.random.default_rng(SEED + 4)
    titles = ["Payments latency spike", "Auth 5xx errors", "Disk pressure on node",
              "Cert expiry warning", "Queue backlog growing", "Deploy rollback triggered"]
    sev = ["SEV1", "SEV2", "SEV3"]
    rows = []
    for i, t in enumerate(titles):
        opened = datetime.now() - timedelta(hours=int(rng.integers(2, 200)))
        resolved = rng.random() > 0.34
        ttr = int(rng.integers(15, 240)) if resolved else None
        rows.append(dict(id=f"INC-{200+i}", title=t, severity=rng.choice(sev),
                         service=rng.choice(SERVICES), opened=opened,
                         status="resolved" if resolved else "open",
                         mttr_min=ttr, oncall=rng.choice(["A. Rao", "S. Iyer", "M. Khan", "P. Das"])))
    return pd.DataFrame(rows)


@st.cache_data
def gen_security():
    """# >> WIRE REAL SOURCE HERE: Trivy / Snyk / SonarQube report ingest."""
    rng = np.random.default_rng(SEED + 5)
    rows = []
    for svc in SERVICES:
        rows.append(dict(service=svc,
                         critical=int(rng.integers(0, 3)),
                         high=int(rng.integers(0, 6)),
                         medium=int(rng.integers(2, 14)),
                         low=int(rng.integers(5, 25)),
                         secrets=int(rng.integers(0, 2)),
                         last_scan=datetime.now() - timedelta(hours=int(rng.integers(1, 72)))))
    checks = {"Branch protection": True, "Signed commits": False, "SBOM generated": True,
              "Secrets in vault": True, "Image scanning in CI": True, "Policy-as-code": False}
    return pd.DataFrame(rows), checks


@st.cache_data
def gen_deploys():
    """# >> WIRE REAL SOURCE HERE: Argo CD / Spinnaker / release API."""
    rng = np.random.default_rng(SEED + 6)
    rows = []
    for i in range(16):
        ok = rng.random() > 0.18
        rows.append(dict(release=f"v2.{rng.integers(0,9)}.{rng.integers(0,9)}",
                         service=rng.choice(SERVICES), env=rng.choice(ENVS),
                         strategy=rng.choice(["rolling", "canary", "blue-green"]),
                         ts=datetime.now() - timedelta(hours=int(rng.integers(1, 240))),
                         status="success" if ok else "rolled-back",
                         duration_min=int(rng.integers(2, 25))))
    return pd.DataFrame(rows).sort_values("ts", ascending=False).reset_index(drop=True)


# ======================================================================================
# Modules
# ======================================================================================
def m_overview():
    st.subheader("Mission control")
    m = gen_metrics()
    inc = gen_incidents()
    dep = gen_deploys()
    pipe, _ = gen_pipelines()

    # DORA-style headline metrics
    deploys_24h = (dep["ts"] > datetime.now() - timedelta(hours=24)).sum()
    cfr = round((dep["status"] == "rolled-back").mean() * 100, 1)
    mttr = int(inc["mttr_min"].dropna().mean()) if inc["mttr_min"].notna().any() else 0
    lead = int(pipe["duration_s"].mean() / 60)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Deploys / 24h", deploys_24h, help="Deployment frequency (DORA)")
    c2.metric("Lead time", f"{lead} min", help="Avg pipeline duration ~ lead time for change (DORA)")
    c3.metric("Change failure rate", f"{cfr}%", help="Rolled-back deploys / total (DORA)")
    c4.metric("MTTR", f"{mttr} min", help="Mean time to resolve incidents (DORA)")

    st.markdown("##### Service health")
    latest = m.sort_values("ts").groupby("service").tail(1)
    cols = st.columns(len(SERVICES))
    for col, (_, r) in zip(cols, latest.iterrows()):
        bad = r.error_rate > 3 or r.latency_p95 > 250
        col.markdown(
            f"**{r.service}**<br>{status_pill('● DOWN' if bad else '● OK', RED if bad else GREEN)}"
            f"<br><span style='font-family:IBM Plex Mono,monospace;font-size:11px;color:{GREY}'>"
            f"p95 {r.latency_p95:.0f}ms · err {r.error_rate:.1f}%</span>",
            unsafe_allow_html=True)

    open_inc = inc[inc.status == "open"]
    worst = latest.sort_values("error_rate", ascending=False).iloc[0]
    msg = (f"<b>{len(open_inc)} open incident(s)</b>. "
           f"Highest error rate is <b>{worst.service}</b> at {worst.error_rate:.1f}% "
           f"(p95 {worst.latency_p95:.0f}ms). ")
    if worst.error_rate > 3:
        msg += "This breaches the 3% threshold — investigate before it escalates to SEV."
    else:
        msg += "All services within SLO thresholds."
    analysis_box(msg)

    st.markdown("##### Recent activity")
    feed = dep.head(6)[["ts", "service", "release", "env", "status"]].copy()
    feed["ts"] = feed["ts"].dt.strftime("%b %d %H:%M")
    st.dataframe(feed, use_container_width=True, hide_index=True)


def m_cicd():
    st.subheader("CI/CD pipelines")
    pipe, stages = gen_pipelines()
    success = round((pipe.status == "success").mean() * 100, 1)
    avg_dur = int(pipe.duration_s.mean())
    c1, c2, c3 = st.columns(3)
    c1.metric("Pipeline success rate", f"{success}%")
    c2.metric("Avg duration", f"{avg_dur}s")
    c3.metric("Runs (last 5 days)", len(pipe))

    # stage failure analysis
    failed = pipe[pipe.failed_stage.notna()]
    if len(failed):
        top_stage = failed.failed_stage.value_counts().idxmax()
        top_n = failed.failed_stage.value_counts().max()
    else:
        top_stage, top_n = "none", 0
    stage_avg = {s: pipe[f"d_{s}"].mean() for s in stages}
    slowest = max(stage_avg, key=stage_avg.get)

    fig = go.Figure(go.Bar(x=list(stage_avg.keys()),
                           y=[round(v, 0) for v in stage_avg.values()],
                           marker_color=ACCENT))
    fig.update_layout(title="Avg stage duration (s)")
    st.plotly_chart(plotly_dark(fig), use_container_width=True)

    analysis_box(
        f"<b>{top_stage}</b> is the most failure-prone stage ({top_n} failures), and "
        f"<b>{slowest}</b> is the slowest on average ({stage_avg[slowest]:.0f}s). "
        f"Recommend caching/parallelising <b>{slowest}</b> and adding a flaky-test quarantine "
        f"on <b>{top_stage}</b> to lift the {success}% success rate.")

    show = pipe.head(15).copy()
    show["ts"] = show["ts"].dt.strftime("%b %d %H:%M")
    st.dataframe(show[["run_id", "service", "branch", "ts", "status", "failed_stage", "duration_s"]],
                 use_container_width=True, hide_index=True)


def m_monitoring():
    st.subheader("Monitoring & observability")
    m = gen_metrics()
    svc = st.selectbox("Service", SERVICES, index=SERVICES.index("payments-api"))
    d = m[m.service == svc].sort_values("ts")
    signal = st.radio("Signal", ["latency_p95", "error_rate", "rps", "cpu"],
                      horizontal=True, format_func=lambda s:
                      {"latency_p95": "Latency p95 (ms)", "error_rate": "Error rate (%)",
                       "rps": "Throughput (rps)", "cpu": "CPU (%)"}[s])

    series = d[signal].values
    mu, sd = series.mean(), series.std()
    threshold = mu + 2 * sd
    anomalies = d[d[signal] > threshold]

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=d.ts, y=series, mode="lines", line=dict(color=TEAL, width=2), name=signal))
    fig.add_hline(y=threshold, line_dash="dash", line_color=AMBER,
                  annotation_text="anomaly threshold (μ+2σ)")
    if len(anomalies):
        fig.add_trace(go.Scatter(x=anomalies.ts, y=anomalies[signal], mode="markers",
                                 marker=dict(color=RED, size=9), name="anomaly"))
    st.plotly_chart(plotly_dark(fig, 340), use_container_width=True)

    if len(anomalies):
        win = f"{anomalies.ts.min():%b %d %H:%M} → {anomalies.ts.max():%b %d %H:%M}"
        peak = anomalies[signal].max()
        analysis_box(
            f"Detected <b>{len(anomalies)} anomalous point(s)</b> on <b>{svc}</b> "
            f"between <b>{win}</b>, peaking at <b>{peak:.1f}</b> vs baseline μ={mu:.1f}. "
            f"This window correlates with a likely deploy/incident — pull logs for that range "
            f"and consider a rollback if it aligns with a release.")
    else:
        analysis_box(f"No anomalies on <b>{svc}/{signal}</b> in the last 48h "
                     f"(baseline μ={mu:.1f}, σ={sd:.1f}). Service is healthy.")


def m_logs():
    st.subheader("Log analysis")
    logs = gen_logs()
    c1, c2, c3 = st.columns([1, 1, 2])
    svc = c1.selectbox("Service", ["all"] + SERVICES)
    lvl = c2.selectbox("Level", ["all", "INFO", "WARN", "ERROR"])
    q = c3.text_input("Search message", "")
    f = logs.copy()
    if svc != "all":
        f = f[f.service == svc]
    if lvl != "all":
        f = f[f.level == lvl]
    if q:
        f = f[f.message.str.contains(q, case=False, na=False)]

    counts = logs.level.value_counts()
    k1, k2, k3 = st.columns(3)
    k1.metric("ERROR", int(counts.get("ERROR", 0)))
    k2.metric("WARN", int(counts.get("WARN", 0)))
    k3.metric("INFO", int(counts.get("INFO", 0)))

    errors = logs[logs.level == "ERROR"]
    if len(errors):
        top = errors.message.value_counts().head(3)
        top_html = " ".join(status_pill(f"{c}× {m[:34]}", RED) for m, c in top.items())
        worst_svc = errors.service.value_counts().idxmax()
        analysis_box(
            f"<b>{len(errors)} errors</b> across the window; <b>{worst_svc}</b> is the noisiest. "
            f"Top recurring errors:<br>{top_html}<br>"
            f"Recommend creating an alert rule on the top pattern and a runbook entry for it.")

    show = f.head(60).copy()
    show["ts"] = show["ts"].dt.strftime("%b %d %H:%M")

    def color_level(v):
        c = {"ERROR": RED, "WARN": AMBER, "INFO": GREY}.get(v, GREY)
        return f"color:{c}"
    st.dataframe(show.style.map(color_level, subset=["level"]),
                 use_container_width=True, hide_index=True, height=320)


def m_infra():
    st.subheader("Infrastructure inventory")
    infra = gen_infra()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Resources", len(infra))
    c2.metric("Degraded", int((infra.status == "degraded").sum()))
    c3.metric("IaC drift", int(infra.iac_drift.sum()))
    c4.metric("Monthly cost", f"${infra.monthly_cost.sum():,.0f}")

    hot = infra[infra.cpu > 80]
    drift = infra[infra.iac_drift]
    msg = ""
    if len(hot):
        msg += f"<b>{len(hot)} resource(s)</b> over 80% CPU ({', '.join(hot.resource)}) — consider scaling. "
    if len(drift):
        msg += (f"<b>{len(drift)} resource(s)</b> have drifted from IaC ({', '.join(drift.resource)}) — "
                f"run a plan/apply to reconcile before the next deploy.")
    if not msg:
        msg = "All resources healthy and in sync with IaC."
    analysis_box(msg)

    def hi(row):
        return ["background-color: rgba(255,93,93,.14)" if (row.cpu > 80 or row.status == "degraded"
                or row.iac_drift) else "" for _ in row]
    st.dataframe(infra.style.apply(hi, axis=1), use_container_width=True, hide_index=True, height=320)


def m_incidents():
    st.subheader("Incident management")
    inc = gen_incidents()
    open_n = int((inc.status == "open").sum())
    mttr = int(inc.mttr_min.dropna().mean()) if inc.mttr_min.notna().any() else 0
    sev1 = int((inc.severity == "SEV1").sum())
    c1, c2, c3 = st.columns(3)
    c1.metric("Open incidents", open_n)
    c2.metric("MTTR", f"{mttr} min")
    c3.metric("SEV1 (total)", sev1)

    openi = inc[inc.status == "open"]
    if len(openi):
        worst = openi.sort_values("severity").iloc[0]
        analysis_box(
            f"<b>{open_n} open incident(s)</b>; highest severity is <b>{worst.severity}</b> — "
            f"'{worst.title}' on <b>{worst.service}</b> (on-call: {worst.oncall}). "
            f"Prioritise this; ensure a blameless postmortem is scheduled once resolved.")
    else:
        analysis_box("No open incidents. Confirm postmortem action items from recent SEVs are closed.")

    show = inc.copy()
    show["opened"] = show["opened"].dt.strftime("%b %d %H:%M")
    st.dataframe(show[["id", "title", "severity", "service", "status", "mttr_min", "oncall", "opened"]],
                 use_container_width=True, hide_index=True)


def m_security():
    st.subheader("Security & compliance (DevSecOps)")
    sec, checks = gen_security()
    tot = sec[["critical", "high", "medium", "low"]].sum()
    risk = int(tot.critical * 10 + tot.high * 4 + tot.medium * 1)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Critical", int(tot.critical))
    c2.metric("High", int(tot.high))
    c3.metric("Exposed secrets", int(sec.secrets.sum()))
    c4.metric("Risk score", risk)

    fig = go.Figure()
    for sev, col in [("critical", RED), ("high", AMBER), ("medium", "#6fd3ff"), ("low", GREY)]:
        fig.add_trace(go.Bar(name=sev, x=sec.service, y=sec[sev], marker_color=col))
    fig.update_layout(barmode="stack", title="Vulnerabilities by service")
    st.plotly_chart(plotly_dark(fig), use_container_width=True)

    failing = [k for k, v in checks.items() if not v]
    worst_svc = sec.set_index("service")[["critical", "high"]].sum(axis=1).idxmax()
    analysis_box(
        f"<b>{int(tot.critical)} critical</b> + <b>{int(tot.high)} high</b> findings; "
        f"<b>{worst_svc}</b> carries the most. Failing controls: "
        f"{', '.join(failing) if failing else 'none'}. "
        f"Fix criticals first, then close {('/'.join(failing)) or 'remaining gaps'} to harden the pipeline.")

    st.markdown("##### Compliance posture")
    cols = st.columns(3)
    for i, (k, v) in enumerate(checks.items()):
        cols[i % 3].markdown(status_pill(f"{'✓' if v else '✗'} {k}", GREEN if v else RED),
                             unsafe_allow_html=True)


def m_deploys():
    st.subheader("Deployments")
    dep = gen_deploys()
    ok = round((dep.status == "success").mean() * 100, 1)
    c1, c2, c3 = st.columns(3)
    c1.metric("Deploy success rate", f"{ok}%")
    c2.metric("Rollbacks", int((dep.status == "rolled-back").sum()))
    c3.metric("Avg deploy time", f"{int(dep.duration_min.mean())} min")

    rb = dep[dep.status == "rolled-back"]
    if len(rb):
        by_strat = rb.strategy.value_counts().idxmax()
        analysis_box(
            f"<b>{len(rb)} rollback(s)</b> recorded, most under the <b>{by_strat}</b> strategy. "
            f"Consider shifting risky services to <b>canary</b> with automated health gates so bad "
            f"releases are caught before full rollout.")
    else:
        analysis_box("No rollbacks — release health is strong. Keep batch sizes small to maintain it.")

    show = dep.head(15).copy()
    show["ts"] = show["ts"].dt.strftime("%b %d %H:%M")
    st.dataframe(show[["release", "service", "env", "strategy", "ts", "status", "duration_min"]],
                 use_container_width=True, hide_index=True)
    st.button("⟲ Simulate rollback of latest release", help="Hook to your CD tool's rollback API")


# ======================================================================================
# Navigation
# ======================================================================================
MODULES = {
    "🎛️  Overview": m_overview,
    "🔁  CI/CD": m_cicd,
    "📈  Monitoring": m_monitoring,
    "🧾  Logs": m_logs,
    "🏗️  Infrastructure": m_infra,
    "🚨  Incidents": m_incidents,
    "🛡️  Security": m_security,
    "🚀  Deployments": m_deploys,
}

with st.sidebar:
    st.markdown("## 🛠️ DevOps Utility")
    st.caption("Single-pane console for day-to-day DevOps operations.")
    choice = st.radio("Modules", list(MODULES.keys()), label_visibility="collapsed")
    st.markdown("---")
    st.caption("Demo data is deterministic. Each generator in the code is marked "
               "`# >> WIRE REAL SOURCE HERE` to connect your application's real feeds "
               "(CI API, Prometheus/Datadog, log backend, cloud SDK).")

st.markdown("<div style='font-family:IBM Plex Mono,monospace;color:#3ad6c8;"
            "letter-spacing:.24em;font-size:11px;text-transform:uppercase'>"
            "DevOps Engineer · Operations Utility</div>", unsafe_allow_html=True)
MODULES[choice]()
