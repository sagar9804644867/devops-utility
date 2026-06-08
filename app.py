"""
DevOps Engineer's Utility  —  v2  (generic, connect-your-app edition)
======================================================================
Users configure their real application's data sources in ⚙️ Connect and
every module switches from demo data to live data automatically.

Supported integrations
  CI/CD        → GitHub Actions REST API
  Monitoring   → Prometheus HTTP API  (configurable PromQL queries)
  Logs         → Grafana Loki HTTP API
  Incidents    → PagerDuty REST API
  Infrastructure → Kubernetes API server
  Deployments  → Argo CD REST API
  Security     → Upload Trivy / Snyk JSON report

Credentials live only in st.session_state — nothing is persisted server-side.
"""

import json
import time
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

# ─────────────────────────────────────────────────────────────────────────────
# Page config & constants
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="DevOps Utility", page_icon="🛠️", layout="wide")

SERVICES = ["payments-api","auth-service","web-frontend",
            "order-service","notification-svc","inventory-svc"]
ACCENT, TEAL, RED, AMBER, GREEN, GREY = (
    "#ff7a3d","#3ad6c8","#ff5d5d","#ffb648","#4ade80","#8593a6")
SEED = 42

DEFAULT_CFG: dict = {
    "app_name": "",
    "ssl_verify": True,
    "github":     {"enabled": False, "token": "", "owner": "", "repo": ""},
    "prometheus": {"enabled": False, "url": "http://localhost:9090",
                   "latency_query": 'histogram_quantile(0.95,sum(rate(http_request_duration_seconds_bucket[5m]))by(le,job))',
                   "error_query":   'sum(rate(http_requests_total{status=~"5.."}[5m]))by(job)/sum(rate(http_requests_total[5m]))by(job)*100',
                   "rps_query":     'sum(rate(http_requests_total[5m]))by(job)',
                   "cpu_query":     '100-(avg by(instance)(rate(node_cpu_seconds_total{mode="idle"}[5m]))*100)'},
    "loki":       {"enabled": False, "url": "http://localhost:3100",
                   "query": '{app="myapp"}', "limit": 500},
    "pagerduty":  {"enabled": False, "token": ""},
    "kubernetes": {"enabled": False, "url": "https://localhost:6443",
                   "token": "", "namespace": "default"},
    "argocd":     {"enabled": False, "url": "https://localhost:8080", "token": ""},
    "security":   {"enabled": False, "upload": None},
}

def cfg() -> dict:
    return st.session_state.get("config", DEFAULT_CFG)

def is_live(key: str) -> bool:
    return cfg().get(key, {}).get("enabled", False)

# ─────────────────────────────────────────────────────────────────────────────
# Styling helpers
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600;700&family=IBM+Plex+Sans:wght@400;500;600&display=swap');
html,body,[class*="css"]{font-family:'IBM Plex Sans',sans-serif;}
h1,h2,h3,h4{font-family:'IBM Plex Mono',monospace!important;letter-spacing:-.01em;}
.pill{display:inline-block;font-family:'IBM Plex Mono',monospace;font-size:11px;
      padding:3px 10px;border-radius:99px;margin-right:4px;}
.analysis{border-left:3px solid #ff7a3d;background:rgba(255,122,61,.08);
           border-radius:8px;padding:14px 16px;margin:6px 0 4px;}
.analysis b{color:#ff7a3d;font-family:'IBM Plex Mono',monospace;}
div[data-testid="stMetricValue"]{font-family:'IBM Plex Mono',monospace;}
</style>
""", unsafe_allow_html=True)

def pill(text, color):
    return (f"<span class='pill' style='color:{color};border:1px solid {color}55;"
            f"background:{color}14'>{text}</span>")

def analysis_box(html):
    st.markdown(f"<div class='analysis'>🔍 <b>ANALYSIS</b> &nbsp; {html}</div>",
                unsafe_allow_html=True)

def source_badge(live: bool, source: str = ""):
    label = f"🟢 Live · {source}" if live else "🟡 Demo data"
    color = TEAL if live else AMBER
    st.markdown(pill(label, color), unsafe_allow_html=True)
    st.markdown("")

def plotly_dark(fig, height=300):
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="IBM Plex Sans", color="#c8d2de", size=11),
        margin=dict(l=10,r=10,t=30,b=10), height=height,
        xaxis=dict(gridcolor="rgba(255,255,255,.07)"),
        yaxis=dict(gridcolor="rgba(255,255,255,.07)"),
        legend=dict(orientation="h", y=-0.2),
    )
    return fig

# ─────────────────────────────────────────────────────────────────────────────
# Demo data generators (always available as fallback)
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data
def _demo_metrics():
    rng = np.random.default_rng(SEED)
    end = datetime.now().replace(minute=0,second=0,microsecond=0)
    hours = [end - timedelta(hours=h) for h in range(47,-1,-1)]
    rows = []
    for svc in SERVICES:
        bl, be, br = rng.uniform(40,120), rng.uniform(0.2,1.2), rng.uniform(80,400)
        for i,ts in enumerate(hours):
            d = 1 + 0.4*np.sin((i%24)/24*2*np.pi)
            lat = bl*d + rng.normal(0,6)
            err = max(0, be + rng.normal(0,.25))
            rps = br*d + rng.normal(0,15)
            cpu = min(98, 35*d + rng.normal(0,6))
            mem = min(96, 50 + rng.normal(0,5))
            if svc == "payments-api" and 30 <= i <= 36:
                lat *= 3.4; err += 6.5; cpu = min(99, cpu+35)
            rows.append(dict(ts=ts, service=svc,
                             latency_p95=round(lat,1), error_rate=round(err,2),
                             rps=round(max(0,rps),0), cpu=round(cpu,1), mem=round(mem,1)))
    return pd.DataFrame(rows)

@st.cache_data
def _demo_pipelines():
    rng = np.random.default_rng(SEED+1)
    stages = ["build","unit-test","integration-test","security-scan","deploy"]
    rows = []
    for n in range(40):
        svc = rng.choice(SERVICES)
        branch = rng.choice(["main","feature/checkout","fix/auth-token","release/2.4"])
        ts = datetime.now() - timedelta(hours=int(rng.integers(1,120)))
        fail = rng.random() < 0.22
        fail_stage = rng.choice(stages) if fail else None
        dur = {}; reached = True
        for s in stages:
            if not reached: dur[s]=None; continue
            dur[s] = round(rng.uniform(20,240),0)
            if s == fail_stage: reached = False
        rows.append(dict(run_id=1200+n, service=svc, branch=branch, ts=ts,
                         status="failed" if fail else "success", failed_stage=fail_stage,
                         duration_s=int(sum(v for v in dur.values() if v)),
                         **{f"d_{s}": dur[s] for s in stages}))
    return pd.DataFrame(rows).sort_values("ts",ascending=False).reset_index(drop=True), stages

@st.cache_data
def _demo_logs():
    rng = np.random.default_rng(SEED+2)
    templates = [("INFO","Request handled in {ms}ms"),("INFO","Health check OK"),
                 ("INFO","Cache hit for key user:{id}"),("WARN","Slow query took {ms}ms"),
                 ("WARN","Retry {n}/3 for upstream call"),
                 ("ERROR","Upstream timeout calling payments gateway"),
                 ("ERROR","NullPointerException in OrderHandler"),
                 ("ERROR","Connection pool exhausted"),
                 ("ERROR","5xx returned from auth-service")]
    weights = [22,18,16,10,8,9,7,5,5]
    rows = []
    for _ in range(400):
        svc = rng.choice(SERVICES)
        ts = datetime.now() - timedelta(minutes=int(rng.integers(1,720)))
        lvl, msg = templates[rng.choice(len(templates), p=np.array(weights)/sum(weights))]
        msg = msg.format(ms=int(rng.integers(20,4000)), id=int(rng.integers(1,9999)),
                         n=int(rng.integers(1,3)))
        rows.append(dict(ts=ts, service=svc, level=lvl, message=msg))
    return pd.DataFrame(rows).sort_values("ts",ascending=False).reset_index(drop=True)

@st.cache_data
def _demo_infra():
    rng = np.random.default_rng(SEED+3)
    rows = []
    for i in range(14):
        kind = rng.choice(["EC2","Pod","RDS","Lambda","LB"])
        rows.append(dict(resource=f"{kind.lower()}-{1000+i}", kind=kind,
                         env=rng.choice(ENVS:=["dev","staging","prod"]),
                         region=rng.choice(["ap-south-1","us-east-1","eu-west-1"]),
                         cpu=round(rng.uniform(8,92),1), mem=round(rng.uniform(20,95),1),
                         status="running" if rng.random()>0.08 else "degraded",
                         iac_drift=rng.random()<0.18,
                         monthly_cost=round(rng.uniform(12,480),2)))
    return pd.DataFrame(rows)

@st.cache_data
def _demo_incidents():
    rng = np.random.default_rng(SEED+4)
    titles = ["Payments latency spike","Auth 5xx errors","Disk pressure on node",
              "Cert expiry warning","Queue backlog growing","Deploy rollback triggered"]
    rows = []
    for i,t in enumerate(titles):
        opened = datetime.now() - timedelta(hours=int(rng.integers(2,200)))
        resolved = rng.random() > 0.34
        rows.append(dict(id=f"INC-{200+i}", title=t,
                         severity=rng.choice(["SEV1","SEV2","SEV3"]),
                         service=rng.choice(SERVICES), opened=opened,
                         status="resolved" if resolved else "open",
                         mttr_min=int(rng.integers(15,240)) if resolved else None,
                         oncall=rng.choice(["A. Rao","S. Iyer","M. Khan","P. Das"])))
    return pd.DataFrame(rows)

@st.cache_data
def _demo_security():
    rng = np.random.default_rng(SEED+5)
    rows = [dict(service=s, critical=int(rng.integers(0,3)), high=int(rng.integers(0,6)),
                 medium=int(rng.integers(2,14)), low=int(rng.integers(5,25)),
                 secrets=int(rng.integers(0,2)),
                 last_scan=datetime.now()-timedelta(hours=int(rng.integers(1,72))))
            for s in SERVICES]
    checks = {"Branch protection":True,"Signed commits":False,"SBOM generated":True,
              "Secrets in vault":True,"Image scanning in CI":True,"Policy-as-code":False}
    return pd.DataFrame(rows), checks

@st.cache_data
def _demo_deploys():
    rng = np.random.default_rng(SEED+6)
    rows = [dict(release=f"v2.{rng.integers(0,9)}.{rng.integers(0,9)}",
                 service=rng.choice(SERVICES), env=rng.choice(["dev","staging","prod"]),
                 strategy=rng.choice(["rolling","canary","blue-green"]),
                 ts=datetime.now()-timedelta(hours=int(rng.integers(1,240))),
                 status="success" if rng.random()>0.18 else "rolled-back",
                 duration_min=int(rng.integers(2,25))) for _ in range(16)]
    return pd.DataFrame(rows).sort_values("ts",ascending=False).reset_index(drop=True)

# ─────────────────────────────────────────────────────────────────────────────
# Live API fetchers  (real HTTP calls — each returns a DataFrame or raises)
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=300, show_spinner=False)
def _live_github_pipelines(token, owner, repo, verify):
    headers = {"Authorization": f"Bearer {token}",
               "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    r = requests.get(f"https://api.github.com/repos/{owner}/{repo}/actions/runs",
                     headers=headers, params={"per_page": 50}, verify=verify, timeout=10)
    r.raise_for_status()
    runs = r.json().get("workflow_runs", [])
    stages = ["build","unit-test","integration-test","security-scan","deploy"]
    rows = []
    for run in runs:
        started = run.get("run_started_at") or run.get("created_at")
        updated = run.get("updated_at")
        try:
            dur = int((datetime.fromisoformat(updated.replace("Z","+00:00")) -
                       datetime.fromisoformat(started.replace("Z","+00:00"))).total_seconds())
        except Exception:
            dur = 0
        conclusion = run.get("conclusion") or run.get("status")
        status = "success" if conclusion == "success" else ("failed" if conclusion in ("failure","timed_out","cancelled") else "running")
        rows.append(dict(
            run_id=run["id"], service=run.get("name","workflow"),
            branch=run.get("head_branch",""), ts=pd.to_datetime(started, utc=True).tz_localize(None),
            status=status, failed_stage=None if status!="failed" else "deploy",
            duration_s=dur,
            **{f"d_{s}": dur//len(stages) for s in stages}
        ))
    df = pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["run_id","service","branch","ts","status","failed_stage","duration_s"]+[f"d_{s}" for s in stages])
    return df.sort_values("ts",ascending=False).reset_index(drop=True), stages

@st.cache_data(ttl=120, show_spinner=False)
def _live_prometheus(url, lat_q, err_q, rps_q, cpu_q, verify):
    end_ts = time.time(); start_ts = end_ts - 48*3600
    params_base = {"start": start_ts, "end": end_ts, "step": "3600"}
    rows = []
    def query(q):
        r = requests.get(f"{url.rstrip('/')}/api/v1/query_range",
                         params={"query": q, **params_base}, verify=verify, timeout=15)
        r.raise_for_status()
        return r.json()["data"]["result"]
    lat_results = query(lat_q)
    err_results = query(err_q)
    rps_results = query(rps_q)
    cpu_results = query(cpu_q)
    def ts_to_dt(t): return datetime.fromtimestamp(float(t))
    # Build from latency as primary series
    for series in lat_results:
        svc = series["metric"].get("job") or series["metric"].get("service") or "app"
        err_map = {}; rps_map = {}; cpu_map = {}
        for es in err_results:
            if es["metric"].get("job","") == svc:
                for t,v in es["values"]: err_map[t] = float(v)
        for rs in rps_results:
            if rs["metric"].get("job","") == svc:
                for t,v in rs["values"]: rps_map[t] = float(v)
        for cs in cpu_results:
            for t,v in cs["values"]: cpu_map[t] = float(v)
        for t, v in series["values"]:
            rows.append(dict(ts=ts_to_dt(t), service=svc,
                             latency_p95=round(float(v)*1000,1),
                             error_rate=round(err_map.get(t,0.5),2),
                             rps=round(rps_map.get(t,100),0),
                             cpu=round(cpu_map.get(t,40),1),
                             mem=50.0))
    return pd.DataFrame(rows) if rows else None

@st.cache_data(ttl=60, show_spinner=False)
def _live_loki(url, query, limit, verify):
    end_ns = int(time.time()*1e9); start_ns = end_ns - 24*3600*int(1e9)
    r = requests.get(f"{url.rstrip('/')}/loki/api/v1/query_range",
                     params={"query":query,"start":start_ns,"end":end_ns,"limit":limit},
                     verify=verify, timeout=15)
    r.raise_for_status()
    rows = []
    for stream in r.json()["data"]["result"]:
        svc = stream["stream"].get("app") or stream["stream"].get("container","app")
        for ts_ns, line in stream["values"]:
            lvl = ("ERROR" if "error" in line.lower() or "exception" in line.lower()
                   else "WARN" if "warn" in line.lower() else "INFO")
            rows.append(dict(ts=datetime.fromtimestamp(int(ts_ns)/1e9),
                             service=svc, level=lvl, message=line[:200]))
    df = pd.DataFrame(rows) if rows else None
    return df.sort_values("ts",ascending=False).reset_index(drop=True) if df is not None else None

@st.cache_data(ttl=120, show_spinner=False)
def _live_pagerduty(token, verify):
    headers = {"Authorization":f"Token token={token}",
               "Accept":"application/vnd.pagerduty+json;version=2"}
    r = requests.get("https://api.pagerduty.com/incidents",
                     headers=headers, params={"limit":50,"sort_by":"created_at:desc"},
                     verify=verify, timeout=10)
    r.raise_for_status()
    rows = []
    for inc in r.json().get("incidents",[]):
        created = pd.to_datetime(inc["created_at"]).tz_localize(None) if isinstance(inc["created_at"],str) else pd.to_datetime(inc["created_at"]).tz_localize(None)
        resolved = inc.get("resolved_at")
        mttr = None
        if resolved:
            mttr = int((pd.to_datetime(resolved) - pd.to_datetime(inc["created_at"])).total_seconds()/60)
        svc = inc.get("service",{}).get("summary","unknown")
        oncall = (inc.get("assignments",[{}])[0].get("assignee",{}).get("summary","—") if inc.get("assignments") else "—")
        urg = inc.get("urgency","low")
        sev = "SEV1" if urg=="high" else "SEV2"
        rows.append(dict(id=inc["incident_number"], title=inc["title"], severity=sev,
                         service=svc, opened=created,
                         status="resolved" if inc["status"]=="resolved" else "open",
                         mttr_min=mttr, oncall=oncall))
    return pd.DataFrame(rows) if rows else None

@st.cache_data(ttl=60, show_spinner=False)
def _live_kubernetes(url, token, namespace, verify):
    headers = {"Authorization":f"Bearer {token}"}
    rows = []
    # nodes
    r = requests.get(f"{url}/api/v1/nodes", headers=headers, verify=verify, timeout=10)
    r.raise_for_status()
    for node in r.json().get("items",[]):
        name = node["metadata"]["name"]
        ready = any(c["type"]=="Ready" and c["status"]=="True"
                    for c in node["status"].get("conditions",[]))
        cap = node["status"].get("capacity",{})
        rows.append(dict(resource=name, kind="Node",
                         env="prod", region=node["metadata"].get("labels",{}).get("topology.kubernetes.io/region","—"),
                         cpu=0.0, mem=0.0,
                         status="running" if ready else "degraded",
                         iac_drift=False, monthly_cost=0.0))
    # pods
    r2 = requests.get(f"{url}/api/v1/namespaces/{namespace}/pods",
                      headers=headers, verify=verify, timeout=10)
    r2.raise_for_status()
    for pod in r2.json().get("items",[]):
        phase = pod["status"].get("phase","Unknown")
        rows.append(dict(resource=pod["metadata"]["name"], kind="Pod",
                         env=namespace, region="—",
                         cpu=0.0, mem=0.0,
                         status="running" if phase=="Running" else "degraded",
                         iac_drift=False, monthly_cost=0.0))
    return pd.DataFrame(rows) if rows else None

@st.cache_data(ttl=120, show_spinner=False)
def _live_argocd(url, token, verify):
    headers = {"Authorization":f"Bearer {token}"}
    r = requests.get(f"{url.rstrip('/')}/api/v1/applications",
                     headers=headers, verify=verify, timeout=10)
    r.raise_for_status()
    rows = []
    for app in r.json().get("items",[]):
        sync = app["status"].get("sync",{}).get("status","Unknown")
        health = app["status"].get("health",{}).get("status","Unknown")
        op = app["status"].get("operationState",{})
        started = op.get("startedAt","")
        finished = op.get("finishedAt","")
        dur = 0
        try:
            dur = int((datetime.fromisoformat(finished.replace("Z","+00:00")) -
                       datetime.fromisoformat(started.replace("Z","+00:00"))).total_seconds()/60)
        except Exception: pass
        rows.append(dict(
            release=app["status"].get("sync",{}).get("revision","—")[:8],
            service=app["metadata"]["name"],
            env=app["spec"].get("destination",{}).get("namespace","—"),
            strategy="GitOps",
            ts=pd.to_datetime(started, utc=True).tz_localize(None) if started else datetime.now(),
            status="success" if sync=="Synced" and health=="Healthy" else "rolled-back",
            duration_min=dur
        ))
    return pd.DataFrame(rows).sort_values("ts",ascending=False).reset_index(drop=True) if rows else None

def _parse_trivy_json(raw: bytes):
    """Parse Trivy or Snyk JSON report → DataFrame with severity counts per target."""
    data = json.loads(raw)
    rows = []
    # Trivy format
    if "Results" in data:
        for result in data["Results"]:
            target = result.get("Target","unknown")
            vulns = result.get("Vulnerabilities") or []
            counts = {"critical":0,"high":0,"medium":0,"low":0,"secrets":0}
            for v in vulns:
                s = v.get("Severity","LOW").lower()
                if s in counts: counts[s] += 1
            rows.append(dict(service=target, **counts,
                             last_scan=datetime.now()))
    # Snyk format
    elif "vulnerabilities" in data:
        vulns = data["vulnerabilities"]
        counts = {"critical":0,"high":0,"medium":0,"low":0,"secrets":0}
        for v in vulns:
            s = v.get("severity","low").lower()
            if s in counts: counts[s] += 1
        rows.append(dict(service=data.get("projectName","project"), **counts,
                         last_scan=datetime.now()))
    checks = {"Branch protection":False,"Signed commits":False,"SBOM generated":True,
              "Secrets in vault":False,"Image scanning in CI":True,"Policy-as-code":False}
    return pd.DataFrame(rows) if rows else None, checks

# ─────────────────────────────────────────────────────────────────────────────
# Smart getters — check config, return (data, is_live, source_name)
# ─────────────────────────────────────────────────────────────────────────────
def get_pipelines():
    c = cfg(); gh = c.get("github",{})
    if gh.get("enabled") and gh.get("token") and gh.get("owner") and gh.get("repo"):
        try:
            df, stages = _live_github_pipelines(gh["token"],gh["owner"],gh["repo"],c["ssl_verify"])
            return df, stages, True, f"GitHub · {gh['owner']}/{gh['repo']}"
        except Exception as e:
            st.warning(f"GitHub API error: {e} — falling back to demo data.")
    df, stages = _demo_pipelines()
    return df, stages, False, ""

def get_metrics():
    c = cfg(); p = c.get("prometheus",{})
    if p.get("enabled") and p.get("url"):
        try:
            df = _live_prometheus(p["url"],p["latency_query"],p["error_query"],
                                  p["rps_query"],p["cpu_query"],c["ssl_verify"])
            if df is not None and len(df):
                return df, True, "Prometheus"
        except Exception as e:
            st.warning(f"Prometheus error: {e} — falling back to demo data.")
    return _demo_metrics(), False, ""

def get_logs():
    c = cfg(); lk = c.get("loki",{})
    if lk.get("enabled") and lk.get("url"):
        try:
            df = _live_loki(lk["url"],lk["query"],lk.get("limit",500),c["ssl_verify"])
            if df is not None and len(df):
                return df, True, "Loki"
        except Exception as e:
            st.warning(f"Loki error: {e} — falling back to demo data.")
    return _demo_logs(), False, ""

def get_incidents():
    c = cfg(); pd_cfg = c.get("pagerduty",{})
    if pd_cfg.get("enabled") and pd_cfg.get("token"):
        try:
            df = _live_pagerduty(pd_cfg["token"],c["ssl_verify"])
            if df is not None and len(df):
                return df, True, "PagerDuty"
        except Exception as e:
            st.warning(f"PagerDuty error: {e} — falling back to demo data.")
    return _demo_incidents(), False, ""

def get_infra():
    c = cfg(); k = c.get("kubernetes",{})
    if k.get("enabled") and k.get("url") and k.get("token"):
        try:
            df = _live_kubernetes(k["url"],k["token"],k.get("namespace","default"),c["ssl_verify"])
            if df is not None and len(df):
                return df, True, "Kubernetes"
        except Exception as e:
            st.warning(f"Kubernetes API error: {e} — falling back to demo data.")
    return _demo_infra(), False, ""

def get_deploys():
    c = cfg(); ac = c.get("argocd",{})
    if ac.get("enabled") and ac.get("url") and ac.get("token"):
        try:
            df = _live_argocd(ac["url"],ac["token"],c["ssl_verify"])
            if df is not None and len(df):
                return df, True, "Argo CD"
        except Exception as e:
            st.warning(f"Argo CD error: {e} — falling back to demo data.")
    return _demo_deploys(), False, ""

def get_security():
    c = cfg(); s = c.get("security",{})
    if s.get("enabled") and s.get("upload"):
        try:
            df, checks = _parse_trivy_json(s["upload"])
            if df is not None and len(df):
                return df, checks, True, "Trivy/Snyk report"
        except Exception as e:
            st.warning(f"Security report parse error: {e} — falling back to demo data.")
    df, checks = _demo_security()
    return df, checks, False, ""

# ─────────────────────────────────────────────────────────────────────────────
# ⚙️  Connect page
# ─────────────────────────────────────────────────────────────────────────────
def m_connect():
    st.subheader("⚙️ Connect your application")
    st.markdown(
        "Enter your application's real data sources below. Credentials are stored "
        "**only in this browser session** — nothing is persisted server-side. "
        "Each module automatically switches from demo data to live data once connected.")

    current = st.session_state.get("config", DEFAULT_CFG.copy())

    # Show current connection status
    integrations = {"CI/CD":"github","Monitoring":"prometheus","Logs":"loki",
                    "Incidents":"pagerduty","Infrastructure":"kubernetes",
                    "Deployments":"argocd","Security":"security"}
    status_cols = st.columns(len(integrations))
    for col,(label,key) in zip(status_cols,integrations.items()):
        live = current.get(key,{}).get("enabled",False)
        col.markdown(pill(f"{'🟢' if live else '⚫'} {label}", TEAL if live else GREY),
                     unsafe_allow_html=True)
    st.markdown("---")

    with st.form("connect_form"):
        app_name = st.text_input("Application / project name",
                                 value=current.get("app_name",""),
                                 placeholder="e.g. my-ecommerce-app")
        ssl_verify = st.checkbox("Enable SSL certificate verification",
                                 value=current.get("ssl_verify",True),
                                 help="Uncheck if your org uses a corporate CA cert that causes SSL errors")
        st.markdown("---")

        # ── GitHub Actions ─────────────────────────────────────────────────
        with st.expander("🔁  CI/CD  —  GitHub Actions", expanded=False):
            gh = current.get("github",{})
            gh_en = st.checkbox("Enable GitHub Actions", value=gh.get("enabled",False), key="gh_en")
            c1,c2,c3 = st.columns(3)
            gh_owner = c1.text_input("Owner / org", value=gh.get("owner",""), placeholder="my-org", key="gh_owner")
            gh_repo  = c2.text_input("Repository", value=gh.get("repo",""), placeholder="my-repo", key="gh_repo")
            gh_token = c3.text_input("Personal access token", value=gh.get("token",""),
                                     type="password", placeholder="ghp_...", key="gh_token")
            st.caption("Token needs the **repo** and **actions:read** scopes.")

        # ── Prometheus ─────────────────────────────────────────────────────
        with st.expander("📈  Monitoring  —  Prometheus", expanded=False):
            pr = current.get("prometheus",{})
            pr_en  = st.checkbox("Enable Prometheus", value=pr.get("enabled",False), key="pr_en")
            pr_url = st.text_input("Prometheus base URL", value=pr.get("url","http://localhost:9090"),
                                   placeholder="http://prometheus:9090", key="pr_url")
            with st.expander("PromQL queries (click to customise)", expanded=False):
                pr_lat = st.text_area("Latency p95 query", value=pr.get("latency_query",DEFAULT_CFG["prometheus"]["latency_query"]), height=70, key="pr_lat")
                pr_err = st.text_area("Error rate query",  value=pr.get("error_query",DEFAULT_CFG["prometheus"]["error_query"]),   height=70, key="pr_err")
                pr_rps = st.text_area("Throughput query",  value=pr.get("rps_query",DEFAULT_CFG["prometheus"]["rps_query"]),       height=70, key="pr_rps")
                pr_cpu = st.text_area("CPU usage query",   value=pr.get("cpu_query",DEFAULT_CFG["prometheus"]["cpu_query"]),       height=70, key="pr_cpu")

        # ── Loki ───────────────────────────────────────────────────────────
        with st.expander("🧾  Logs  —  Grafana Loki", expanded=False):
            lk = current.get("loki",{})
            lk_en    = st.checkbox("Enable Loki", value=lk.get("enabled",False), key="lk_en")
            lk_url   = st.text_input("Loki base URL", value=lk.get("url","http://localhost:3100"),
                                     placeholder="http://loki:3100", key="lk_url")
            lk_query = st.text_input("LogQL query",   value=lk.get("query",'{app="myapp"}'),
                                     placeholder='{namespace="prod"}', key="lk_query")
            lk_limit = st.number_input("Max log lines", value=int(lk.get("limit",500)), min_value=50, max_value=5000, step=50, key="lk_limit")

        # ── PagerDuty ──────────────────────────────────────────────────────
        with st.expander("🚨  Incidents  —  PagerDuty", expanded=False):
            pd_cfg = current.get("pagerduty",{})
            pd_en    = st.checkbox("Enable PagerDuty", value=pd_cfg.get("enabled",False), key="pd_en")
            pd_token = st.text_input("API token", value=pd_cfg.get("token",""),
                                     type="password", placeholder="y_NbAkKc66ryYTWUXYEu", key="pd_token")
            st.caption("Create a v2 REST API key in PagerDuty → Integrations → API Access Keys.")

        # ── Kubernetes ─────────────────────────────────────────────────────
        with st.expander("🏗️  Infrastructure  —  Kubernetes API", expanded=False):
            k8 = current.get("kubernetes",{})
            k8_en  = st.checkbox("Enable Kubernetes", value=k8.get("enabled",False), key="k8_en")
            c1,c2  = st.columns(2)
            k8_url = c1.text_input("API server URL",value=k8.get("url","https://localhost:6443"),key="k8_url")
            k8_ns  = c2.text_input("Namespace",     value=k8.get("namespace","default"),          key="k8_ns")
            k8_tok = st.text_input("Bearer token", value=k8.get("token",""), type="password",
                                   placeholder="eyJhbGci...", key="k8_tok")
            st.caption("Run `kubectl -n <ns> create token <serviceaccount>` to generate a token.")

        # ── Argo CD ────────────────────────────────────────────────────────
        with st.expander("🚀  Deployments  —  Argo CD", expanded=False):
            ac = current.get("argocd",{})
            ac_en  = st.checkbox("Enable Argo CD", value=ac.get("enabled",False), key="ac_en")
            c1,c2  = st.columns(2)
            ac_url = c1.text_input("Argo CD URL",  value=ac.get("url","https://localhost:8080"), key="ac_url")
            ac_tok = c2.text_input("Auth token",   value=ac.get("token",""), type="password",
                                   placeholder="JWT from argocd account generate-token", key="ac_tok")

        # ── Security upload ────────────────────────────────────────────────
        with st.expander("🛡️  Security  —  Upload Trivy / Snyk JSON report", expanded=False):
            sec_en   = st.checkbox("Enable security report", value=current.get("security",{}).get("enabled",False), key="sec_en")
            sec_file = st.file_uploader("Upload Trivy or Snyk JSON output",
                                        type=["json"], key="sec_file")
            st.caption("Generate with: `trivy image --format json --output report.json <image>` "
                       "or `snyk test --json > report.json`")

        saved = st.form_submit_button("💾  Save configuration", type="primary", use_container_width=True)

    if saved:
        new_cfg = {
            "app_name": app_name,
            "ssl_verify": ssl_verify,
            "github":     {"enabled":st.session_state.gh_en,  "token":st.session_state.gh_token,
                           "owner":st.session_state.gh_owner,  "repo":st.session_state.gh_repo},
            "prometheus": {"enabled":st.session_state.pr_en,  "url":st.session_state.pr_url,
                           "latency_query":st.session_state.pr_lat, "error_query":st.session_state.pr_err,
                           "rps_query":st.session_state.pr_rps,     "cpu_query":st.session_state.pr_cpu},
            "loki":       {"enabled":st.session_state.lk_en,  "url":st.session_state.lk_url,
                           "query":st.session_state.lk_query,  "limit":st.session_state.lk_limit},
            "pagerduty":  {"enabled":st.session_state.pd_en,  "token":st.session_state.pd_token},
            "kubernetes": {"enabled":st.session_state.k8_en,  "url":st.session_state.k8_url,
                           "token":st.session_state.k8_tok,    "namespace":st.session_state.k8_ns},
            "argocd":     {"enabled":st.session_state.ac_en,  "url":st.session_state.ac_url,
                           "token":st.session_state.ac_tok},
            "security":   {"enabled":st.session_state.sec_en,
                           "upload": st.session_state.sec_file.read() if st.session_state.sec_file else current.get("security",{}).get("upload")},
        }
        st.session_state["config"] = new_cfg
        live_count = sum(1 for k in ["github","prometheus","loki","pagerduty","kubernetes","argocd","security"] if new_cfg[k]["enabled"])
        st.success(f"✅ Configuration saved. {live_count} integration(s) enabled — navigate to any module to see live data.")
        _live_github_pipelines.clear(); _live_prometheus.clear()
        _live_loki.clear(); _live_pagerduty.clear()
        _live_kubernetes.clear(); _live_argocd.clear()

# ─────────────────────────────────────────────────────────────────────────────
# Operational modules
# ─────────────────────────────────────────────────────────────────────────────
def m_overview():
    st.subheader("Mission control")
    m, m_live, m_src = get_metrics()
    inc, i_live, i_src = get_incidents()
    dep, d_live, d_src = get_deploys()
    pipe, _, p_live, p_src = get_pipelines()

    deploys_24h = (dep["ts"] > datetime.now()-timedelta(hours=24)).sum()
    cfr = round((dep["status"]=="rolled-back").mean()*100,1)
    mttr = int(inc["mttr_min"].dropna().mean()) if inc["mttr_min"].notna().any() else 0
    lead = int(pipe["duration_s"].mean()/60)

    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Deploys / 24h", deploys_24h)
    c2.metric("Lead time", f"{lead} min")
    c3.metric("Change failure rate", f"{cfr}%")
    c4.metric("MTTR", f"{mttr} min")

    app_label = cfg().get("app_name","") or "your application"
    st.markdown(f"##### Service health · {app_label}")
    latest = m.sort_values("ts").groupby("service").tail(1)
    cols = st.columns(min(len(latest),6))
    for col,(_,r) in zip(cols, latest.iterrows()):
        bad = r.error_rate > 3 or r.latency_p95 > 250
        col.markdown(
            f"**{r.service}**<br>{pill('● DOWN' if bad else '● OK', RED if bad else GREEN)}"
            f"<br><span style='font-family:IBM Plex Mono,monospace;font-size:11px;color:{GREY}'>"
            f"p95 {r.latency_p95:.0f}ms · err {r.error_rate:.1f}%</span>",
            unsafe_allow_html=True)

    open_inc = inc[inc.status=="open"]
    worst = latest.sort_values("error_rate",ascending=False).iloc[0]
    msg = (f"<b>{len(open_inc)} open incident(s)</b>. Highest error rate: "
           f"<b>{worst.service}</b> at {worst.error_rate:.1f}% (p95 {worst.latency_p95:.0f}ms). ")
    msg += ("⚠️ Breaches 3% SLO threshold." if worst.error_rate>3 else "All within SLO thresholds.")
    analysis_box(msg)
    st.dataframe(dep.head(6)[["ts","service","release","env","status"]]
                 .assign(ts=dep.head(6)["ts"].dt.strftime("%b %d %H:%M")),
                 use_container_width=True, hide_index=True)

def m_cicd():
    st.subheader("CI/CD pipelines")
    pipe, stages, live, src = get_pipelines()
    source_badge(live, src)
    success = round((pipe.status=="success").mean()*100,1)
    avg_dur = int(pipe.duration_s.mean()) if len(pipe) else 0
    c1,c2,c3 = st.columns(3)
    c1.metric("Pipeline success rate", f"{success}%")
    c2.metric("Avg duration", f"{avg_dur}s")
    c3.metric("Total runs", len(pipe))
    failed = pipe[pipe.failed_stage.notna()]
    top_stage = failed.failed_stage.value_counts().idxmax() if len(failed) else "—"
    top_n = failed.failed_stage.value_counts().max() if len(failed) else 0
    stage_avg = {s: pipe[f"d_{s}"].mean() for s in stages if f"d_{s}" in pipe.columns}
    if stage_avg:
        slowest = max(stage_avg, key=lambda k: stage_avg[k] or 0)
        fig = go.Figure(go.Bar(x=list(stage_avg.keys()),
                               y=[round(v or 0,0) for v in stage_avg.values()],
                               marker_color=ACCENT))
        fig.update_layout(title="Avg stage duration (s)")
        st.plotly_chart(plotly_dark(fig), use_container_width=True)
        analysis_box(f"<b>{top_stage}</b> is the most failure-prone stage ({top_n} failures); "
                     f"<b>{slowest}</b> is the slowest ({stage_avg[slowest]:.0f}s avg). "
                     f"Cache/parallelise <b>{slowest}</b> and quarantine flaky tests in <b>{top_stage}</b>.")
    show = pipe.head(15).copy()
    if "ts" in show.columns: show["ts"] = show["ts"].dt.strftime("%b %d %H:%M")
    cols = [c for c in ["run_id","service","branch","ts","status","failed_stage","duration_s"] if c in show.columns]
    st.dataframe(show[cols], use_container_width=True, hide_index=True)

def m_monitoring():
    st.subheader("Monitoring & observability")
    m, live, src = get_metrics()
    source_badge(live, src)
    svcs = list(m["service"].unique())
    svc = st.selectbox("Service", svcs)
    d = m[m.service==svc].sort_values("ts")
    signal = st.radio("Signal", ["latency_p95","error_rate","rps","cpu"], horizontal=True,
                      format_func=lambda s: {"latency_p95":"Latency p95 (ms)",
                                             "error_rate":"Error rate (%)","rps":"Throughput (rps)","cpu":"CPU (%)"}[s])
    series = d[signal].values
    mu,sd = series.mean(), series.std()
    threshold = mu + 2*sd
    anomalies = d[d[signal]>threshold]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=d.ts, y=series, mode="lines", line=dict(color=TEAL,width=2), name=signal))
    fig.add_hline(y=threshold, line_dash="dash", line_color=AMBER, annotation_text="μ+2σ threshold")
    if len(anomalies):
        fig.add_trace(go.Scatter(x=anomalies.ts, y=anomalies[signal], mode="markers",
                                 marker=dict(color=RED,size=9), name="anomaly"))
    st.plotly_chart(plotly_dark(fig,340), use_container_width=True)
    if len(anomalies):
        win = f"{anomalies.ts.min():%b %d %H:%M} → {anomalies.ts.max():%b %d %H:%M}"
        analysis_box(f"<b>{len(anomalies)} anomalous point(s)</b> on <b>{svc}</b> during <b>{win}</b>, "
                     f"peaking at <b>{anomalies[signal].max():.1f}</b> (baseline μ={mu:.1f}). "
                     f"Correlate with a deploy/incident in that window — consider rollback if linked.")
    else:
        analysis_box(f"No anomalies on <b>{svc}/{signal}</b>. Service is healthy (μ={mu:.1f}, σ={sd:.1f}).")

def m_logs():
    st.subheader("Log analysis")
    logs, live, src = get_logs()
    source_badge(live, src)
    c1,c2,c3 = st.columns([1,1,2])
    svc = c1.selectbox("Service", ["all"]+list(logs.service.unique()))
    lvl = c2.selectbox("Level", ["all","INFO","WARN","ERROR"])
    q   = c3.text_input("Search message","")
    f = logs.copy()
    if svc!="all": f=f[f.service==svc]
    if lvl!="all": f=f[f.level==lvl]
    if q: f=f[f.message.str.contains(q,case=False,na=False)]
    counts = logs.level.value_counts()
    k1,k2,k3 = st.columns(3)
    k1.metric("ERROR", int(counts.get("ERROR",0)))
    k2.metric("WARN",  int(counts.get("WARN",0)))
    k3.metric("INFO",  int(counts.get("INFO",0)))
    errors = logs[logs.level=="ERROR"]
    if len(errors):
        top = errors.message.value_counts().head(3)
        chips = " ".join(pill(f"{c}× {m[:34]}", RED) for m,c in top.items())
        analysis_box(f"<b>{len(errors)} errors</b>; top patterns:<br>{chips}<br>"
                     f"<b>{errors.service.value_counts().idxmax()}</b> is the noisiest service. "
                     f"Create an alert rule and runbook entry for the top pattern.")
    _lmap = {"ERROR": RED, "WARN": AMBER, "INFO": GREY}
    def color_level(v): return f"color:{_lmap.get(v, GREY)}"
    show = f.head(60).copy()
    if "ts" in show.columns: show["ts"] = show["ts"].dt.strftime("%b %d %H:%M")
    st.dataframe(show.style.map(color_level,subset=["level"]),
                 use_container_width=True, hide_index=True, height=320)

def m_infra():
    st.subheader("Infrastructure inventory")
    infra, live, src = get_infra()
    source_badge(live, src)
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Resources", len(infra))
    c2.metric("Degraded",  int((infra.status=="degraded").sum()))
    c3.metric("IaC drift",  int(infra.iac_drift.sum()))
    c4.metric("Monthly cost", f"${infra.monthly_cost.sum():,.0f}")
    hot = infra[infra.cpu>80]; drift = infra[infra.iac_drift]
    msg = ""
    if len(hot):   msg += f"<b>{len(hot)}</b> resource(s) over 80% CPU ({', '.join(hot.resource)}) — scale up. "
    if len(drift): msg += f"<b>{len(drift)}</b> IaC drift(s) detected — run plan/apply to reconcile."
    analysis_box(msg or "All resources healthy and in sync with IaC.")
    def hi(row): return ["background-color:rgba(255,93,93,.14)"
                         if (row.cpu>80 or row.status=="degraded" or row.iac_drift) else "" for _ in row]
    st.dataframe(infra.style.apply(hi,axis=1), use_container_width=True, hide_index=True, height=320)

def m_incidents():
    st.subheader("Incident management")
    inc, live, src = get_incidents()
    source_badge(live, src)
    open_n = int((inc.status=="open").sum())
    mttr = int(inc.mttr_min.dropna().mean()) if inc.mttr_min.notna().any() else 0
    c1,c2,c3 = st.columns(3)
    c1.metric("Open incidents", open_n)
    c2.metric("MTTR", f"{mttr} min")
    c3.metric("SEV1 total", int((inc.severity=="SEV1").sum()))
    openi = inc[inc.status=="open"]
    if len(openi):
        worst = openi.sort_values("severity").iloc[0]
        analysis_box(f"<b>{open_n} open</b>; worst: <b>{worst.severity}</b> — '{worst.title}' "
                     f"on <b>{worst.service}</b> (on-call: {worst.oncall}). Schedule blameless postmortem.")
    else:
        analysis_box("No open incidents. Verify postmortem action items from recent SEVs are closed.")
    show = inc.copy()
    if "opened" in show.columns: show["opened"] = show["opened"].dt.strftime("%b %d %H:%M")
    st.dataframe(show[["id","title","severity","service","status","mttr_min","oncall","opened"]],
                 use_container_width=True, hide_index=True)

def m_security():
    st.subheader("Security & compliance (DevSecOps)")
    sec, checks, live, src = get_security()
    source_badge(live, src)
    tot = sec[["critical","high","medium","low"]].sum()
    risk = int(tot.critical*10 + tot.high*4 + tot.medium)
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Critical", int(tot.critical))
    c2.metric("High",     int(tot.high))
    c3.metric("Secrets",  int(sec.secrets.sum()))
    c4.metric("Risk score", risk)
    fig = go.Figure()
    for sev,col_ in [("critical",RED),("high",AMBER),("medium","#6fd3ff"),("low",GREY)]:
        fig.add_trace(go.Bar(name=sev, x=sec.service, y=sec[sev], marker_color=col_))
    fig.update_layout(barmode="stack", title="Vulnerabilities by service")
    st.plotly_chart(plotly_dark(fig), use_container_width=True)
    failing = [k for k,v in checks.items() if not v]
    worst_svc = sec.set_index("service")[["critical","high"]].sum(axis=1).idxmax()
    analysis_box(f"<b>{int(tot.critical)} critical + {int(tot.high)} high</b> findings; "
                 f"<b>{worst_svc}</b> carries the most. Failing controls: "
                 f"{', '.join(failing) or 'none'}. Fix criticals first, then close compliance gaps.")
    st.markdown("##### Compliance posture")
    cols = st.columns(3)
    for i,(k,v) in enumerate(checks.items()):
        cols[i%3].markdown(pill(f"{'✓' if v else '✗'} {k}", GREEN if v else RED), unsafe_allow_html=True)

def m_deploys():
    st.subheader("Deployments")
    dep, live, src = get_deploys()
    source_badge(live, src)
    ok = round((dep.status=="success").mean()*100,1)
    c1,c2,c3 = st.columns(3)
    c1.metric("Success rate", f"{ok}%")
    c2.metric("Rollbacks",    int((dep.status=="rolled-back").sum()))
    c3.metric("Avg deploy time", f"{int(dep.duration_min.mean())} min")
    rb = dep[dep.status=="rolled-back"]
    if len(rb):
        by_strat = rb.strategy.value_counts().idxmax()
        analysis_box(f"<b>{len(rb)} rollback(s)</b>, most under the <b>{by_strat}</b> strategy. "
                     f"Shift risky services to <b>canary</b> with automated health gates.")
    else:
        analysis_box("No rollbacks — release health is strong. Keep batch sizes small.")
    show = dep.head(15).copy()
    if "ts" in show.columns: show["ts"] = show["ts"].dt.strftime("%b %d %H:%M")
    cols = [c for c in ["release","service","env","strategy","ts","status","duration_min"] if c in show.columns]
    st.dataframe(show[cols], use_container_width=True, hide_index=True)
    st.button("⟲ Trigger rollback of latest release", help="Hook to your CD rollback API here")

# ─────────────────────────────────────────────────────────────────────────────
# Sidebar navigation
# ─────────────────────────────────────────────────────────────────────────────
MODULES = {
    "⚙️  Connect":       m_connect,
    "🎛️  Overview":      m_overview,
    "🔁  CI/CD":         m_cicd,
    "📈  Monitoring":    m_monitoring,
    "🧾  Logs":          m_logs,
    "🏗️  Infrastructure":m_infra,
    "🚨  Incidents":     m_incidents,
    "🛡️  Security":      m_security,
    "🚀  Deployments":   m_deploys,
}

with st.sidebar:
    st.markdown("## 🛠️ DevOps Utility")
    app_nm = cfg().get("app_name","")
    st.caption(f"Connected app: **{app_nm}**" if app_nm else "No app connected yet — start at ⚙️ Connect")
    choice = st.radio("", list(MODULES.keys()), label_visibility="collapsed")
    live_count = sum(1 for k in ["github","prometheus","loki","pagerduty","kubernetes","argocd","security"]
                     if cfg().get(k,{}).get("enabled",False))
    if live_count:
        st.markdown(pill(f"🟢 {live_count} live source(s)", TEAL), unsafe_allow_html=True)
    else:
        st.markdown(pill("🟡 Demo data only", AMBER), unsafe_allow_html=True)

st.markdown("<div style='font-family:IBM Plex Mono,monospace;color:#3ad6c8;"
            "letter-spacing:.24em;font-size:11px;text-transform:uppercase'>"
            "DevOps Engineer · Operations Utility</div>", unsafe_allow_html=True)
MODULES[choice]()
