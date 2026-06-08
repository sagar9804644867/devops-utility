# DevOps Engineer's Utility (Streamlit)

A single-pane operations console that mirrors what a DevOps engineer does day to day,
modelled on real DevOps dashboards / internal developer portals. Built to be presented
as **the utility** — it ships fully populated with deterministic demo data, and every
module performs real *analysis* (not just display): it flags anomalies, finds root-cause
hints, and prints a recommended next action.

## Modules
| Module | What it does (the DevOps engineer's job) |
|---|---|
| 🎛️ Overview | Mission control — DORA metrics (deploy frequency, lead time, change-failure rate, MTTR), per-service health, activity feed |
| 🔁 CI/CD | Pipeline runs, success rate, slowest + most-failure-prone stage, duration analysis |
| 📈 Monitoring | Golden signals (latency/error/throughput/CPU) with automatic μ+2σ anomaly detection |
| 🧾 Logs | Searchable/filterable log stream, level breakdown, top recurring error patterns |
| 🏗️ Infrastructure | Host/container/cloud inventory, utilisation, IaC drift, cost |
| 🚨 Incidents | Open/resolved incidents, severity, MTTR, on-call ownership |
| 🛡️ Security | Vulnerability scan results by severity, exposed secrets, compliance posture, risk score |
| 🚀 Deployments | Release history, strategy (rolling/canary/blue-green), rollbacks |

## Run
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Wiring it to your application's real data
The app uses deterministic demo data so it demos out of the box. Each data generator
in `app.py` is tagged:

```python
# >> WIRE REAL SOURCE HERE: ...
```

Replace the body of each `gen_*()` function with a call to your real source and return
a DataFrame with the same columns:

- `gen_metrics`   → Prometheus / Datadog / CloudWatch query
- `gen_pipelines` → GitHub Actions / GitLab CI / Jenkins API
- `gen_logs`      → ELK / Loki / CloudWatch Logs
- `gen_infra`     → cloud SDK (boto3 / azure-sdk) or Kubernetes API
- `gen_incidents` → PagerDuty / Opsgenie / Statuspage
- `gen_security`  → Trivy / Snyk / SonarQube report ingest
- `gen_deploys`   → Argo CD / Spinnaker / release API

The analysis logic and charts adapt automatically to whatever the generators return.

## Deploy
- **Streamlit Community Cloud:** push to GitHub → deploy via share.streamlit.io.
- **Container/internal host:** `streamlit run app.py --server.port 8501`.

No data leaves the user's session.
