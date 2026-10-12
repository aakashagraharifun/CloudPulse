# Sample data

Everything in this folder is **synthetic**. None of it comes from a real cloud account.

| File | Purpose |
| --- | --- |
| `synthetic_billing_90d.csv` | 90 days of generated billing data in USD with three deliberately injected anomalies. It covers cloud infrastructure (AWS, Google Cloud, Microsoft Azure), AI model APIs billed per token (OpenAI, Anthropic, Google Gemini) and a SaaS tool (Datadog). |
| `invalid_billing_example.csv` | A deliberately broken file that shows the import validation errors (bad date, thousands separator, missing service, bad currency, wrong column count). |

## What is in it

| Category | Provider (`provider`) | Services | Notes |
| --- | --- | --- | --- |
| Cloud | `aws` | EC2, RDS, S3, CloudFront, Lambda, EKS, DynamoDB, VPC (NAT), CloudWatch | Production, staging and an untagged shared-networking slice |
| Cloud | `gcp` | BigQuery, Cloud Storage | Analytics |
| Cloud | `azure` | Virtual Machines, Storage | Reporting workloads |
| AI | `openai` | OpenAI API | `gpt-4o` input/output tokens and `text-embedding-3-small` embeddings |
| AI | `anthropic` | Claude API | `claude-sonnet-4-5` input/output tokens for the `support-assistant` project |
| AI | `google-ai` | Gemini API | `gemini-2.5-flash` ticket classification |
| SaaS | `datadog` | Infrastructure Monitoring | Untagged shared monitoring |

AI line items carry the model in the `model` column, the token direction in `usage_type` (`input_tokens` / `output_tokens`) and the token count in `usage_quantity` with `usage_unit` = `tokens`. Unit prices are illustrative list prices, not quotes.

## Injected anomalies

The generator (`backend/app/services/ingestion/sample_data.py`) injects:

1. **Data-transfer spike** 11 days before the end date. NAT Gateway processed bytes jump about 8× on untagged networking resources. The cost increase is driven by usage.
2. **GPU spike** 4 and 3 days before the end date. A new `p4d.24xlarge` EC2 instance appears in `us-west-2` for the `ml-experiments` project and costs about $786 and $590 per day.
3. **LLM token spike** 6 days before the end date. `claude-sonnet-4-5` output tokens for the `support-assistant` project jump about 10× (usage-driven, roughly +$29 that day). It is a large percentage but a small amount, so it raises a low-severity `Claude API` incident and does not move total spend past the thresholds.

With the default detection settings the sample produces five incidents: the NAT spike (total and `Amazon Virtual Private Cloud`), the GPU spike (total and `Amazon Elastic Compute Cloud`) and the token spike (`Claude API`).

## Regenerating

The committed CSV ends on a fixed date. To generate one that ends yesterday:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m scripts.generate_sample_data
```

In the dashboard, **Imports → Load sample data** generates the same dataset ending yesterday and marks it as sample data.
