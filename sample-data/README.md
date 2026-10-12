# Sample data

Everything in this folder is **synthetic**. None of it comes from a real cloud account.

| File | Purpose |
| --- | --- |
| `synthetic_billing_90d.csv` | 90 days of generated multi-service billing data (AWS + GCP, USD) with two deliberately injected anomalies. |
| `invalid_billing_example.csv` | A deliberately broken file that shows the import validation errors (bad date, thousands separator, missing service, bad currency, wrong column count). |

## Injected anomalies

The generator (`backend/app/services/ingestion/sample_data.py`) injects:

1. **Data-transfer spike** 11 days before the end date. NAT Gateway processed bytes jump about 8× on untagged networking resources. The cost increase is driven by usage.
2. **GPU spike** 4 and 3 days before the end date. A new `p4d.24xlarge` EC2 instance appears in `us-west-2` for the `ml-experiments` project and costs about $786 and $590 per day.

## Regenerating

The committed CSV ends on a fixed date. To generate one that ends yesterday:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m scripts.generate_sample_data
```

In the dashboard, **Imports → Load sample data** generates the same dataset ending yesterday and marks it as sample data.
