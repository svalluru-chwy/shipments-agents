# Shipments Agency Platform

Standalone shipment analysis platform powered by AI agents. Processes customer shipment data through signal detection, root cause analysis, and delay prediction using a phased skill architecture.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   FastAPI Gateway                    │
│  /pipeline/run  /skills/{name}/run  /skills/phase/  │
└──────────────┬──────────────────────┬───────────────┘
               │                      │
       ┌───────▼────────┐    ┌───────▼────────┐
       │ ShipmentSignals │    │ ShipmentDecoder │
       │     Agent       │───▶│     Agent       │
       │ (Check Gate +   │    │ (Phase 2 LLM    │
       │  Phase 1 Skills)│    │  Skills)         │
       └───────┬─────────┘    └───────┬──────────┘
               │                      │
       ┌───────▼──────────────────────▼──────────┐
       │              S3 Storage                  │
       │  Raw data (Snowflake) + Agent outputs    │
       └──────────────────────────────────────────┘
```

**Pipeline**: `ShipmentSignalsAgent` (LLM check gate + 12 Phase 1 skills) → `ShipmentDecoderAgent` (2 Phase 2 skills)

## Skills (17 total)

### Phase 1 — Deterministic (11 skills, run in parallel)

| Skill | What it does |
|---|---|
| `shipment_health_check` | Customer CTD vs ZIP benchmark, health status |
| `delivery_performance` | CTD patterns, delayed shipment identification |
| `carrier_analysis` | Per-carrier performance (CTD, delay rate, exceptions) |
| `exception_analysis` | Carrier exceptions, lost shipments |
| `geographic_patterns` | ZIP/FC routing patterns |
| `timing_patterns` | Day-of-week CTD patterns |
| `package_analysis` | Weight distribution, heavy package rates |
| `routing_efficiency` | FC-to-ZIP arc distance vs optimal |
| `order_behavior` | Autoship rate, order frequency, categories |
| `contact_correlation` | Contact rate, WISMO rate vs shipment volume |
| `current_order` | Active/in-transit orders, at-risk detection |

### Phase 1 — LLM (1 skill)

| Skill | What it does |
|---|---|
| `shipment_signal_generator` | LLM-generated signals from shipment data |

### Phase 2 — LLM (2 skills, depend on Phase 1 results)

| Skill | What it does |
|---|---|
| `shipment_delay_predictor` | Predicts delays for active shipments |
| `shipment_signal_decoder` | Decodes signals with root cause analysis |

### Phase 3-4 — Available but not in pipeline

| Skill | What it does |
|---|---|
| `shipment_intervention` | Determines if intervention is needed |
| `shipment_action_prioritizer` | Prioritizes recommended actions |
| `shipment_consolidator` | Consolidates all skill outputs |

## Setup

### Prerequisites

- Python 3.10+
- AWS SSO access (for S3)
- OpenAI API key

### Install

```bash
# Clone
git clone https://github.com/svalluru-chwy/shipments-agents.git
cd shipments-agents

# Install dependencies
pip install -e .

# For Snowflake data extraction (optional)
pip install -e ".[snowflake]"

# For development
pip install -e ".[dev]"
```

### Configure

```bash
# Copy environment template
cp .env.example .env

# Edit .env and set:
#   OPENAI_API_KEY=sk-...
#   AWS_PROFILE=your-sso-profile

# Ensure AWS SSO is authenticated
aws sso login --profile your-sso-profile
```

## Usage

### 1. Run pipeline via CLI (standalone)

```bash
# Run for a single customer (default: 6180005)
python3 run_pipeline_test.py

# Results saved to output_local/<customer_id>_<timestamp>/
```

Output files:
- `shipment_signals_structured.json` — Full Phase 1 skill results
- `shipment_signals_signals_markdown.md` — Human-readable Phase 1 report
- `shipment_signals_check_gate.json` — LLM check gate decision
- `shipment_decoder_structured.json` — Full Phase 2 skill results
- `shipment_decoder_decoded_markdown.md` — Human-readable Phase 2 report
- `pipeline_summary.json` — Pipeline run metadata

### 2. Run pipeline via FastAPI

```bash
# Start the gateway
python3 -m uvicorn packages.gateway.main:app --host 0.0.0.0 --port 8001

# Run full pipeline for a customer
curl -X POST http://localhost:8001/pipeline/run \
  -H "Content-Type: application/json" \
  -d '{"customer_id": "6180005"}'

# Run for multiple customers
curl -X POST http://localhost:8001/pipeline/batch \
  -H "Content-Type: application/json" \
  -d '{"customer_ids": ["6180005", "1234567"]}'
```

### 3. Run individual skills via API

```bash
# List all available skills
curl http://localhost:8001/skills

# Run a single skill
curl -X POST http://localhost:8001/skills/shipment_health_check/run \
  -H "Content-Type: application/json" \
  -d '{"customer_id": "6180005"}'

# Run all skills in a phase
curl -X POST http://localhost:8001/skills/phase/1/run \
  -H "Content-Type: application/json" \
  -d '{"customer_id": "6180005"}'

# Get skill documentation
curl http://localhost:8001/skills/delivery_performance
```

### 4. Health check

```bash
curl http://localhost:8001/health
# {"status": "ok", "service": "shipments-gateway"}
```

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/health` | Gateway health check |
| POST | `/pipeline/run` | Run full pipeline for one customer |
| POST | `/pipeline/batch` | Run pipeline for multiple customers |
| GET | `/skills` | List all skills with metadata |
| GET | `/skills/{name}` | Get SKILL.md documentation |
| POST | `/skills/{name}/run` | Run a single skill |
| POST | `/skills/phase/{n}/run` | Run all skills in phase N |
| GET | `/agents` | List registered agents |
| POST | `/agents/{name}/run` | Run a specific agent |

## Delay Detection

Delays are detected using **CTD (Click-to-Deliver) threshold logic**:

- **Threshold** = customer's mean CTD + 1 standard deviation
- A shipment is **delayed** if its CTD exceeds this threshold
- For records missing `CLICK_TO_DELIVER_DAYS`, an **estimated CTD** is computed from `SHIPMENT_ESTIMATED_DELIVERY_DATE - ORDER_PLACED_DTTM`
- CTD is broken down into **CTR** (Click-to-Release) + **RTS** (Release-to-Ship) + **STD** (Ship-to-Deliver) to identify where delays originate

## Data Flow

1. **Raw data** is extracted from Snowflake via 7 SQL queries and stored in S3
2. **ShipmentSignalsAgent** loads data from S3, runs the LLM check gate, then executes all 12 Phase 1 skills in parallel
3. Phase 1 results are passed to **ShipmentDecoderAgent** which runs 2 Phase 2 LLM skills
4. All outputs are saved to S3 and returned via the API

## Project Structure

```
shipments-agents/
├── packages/
│   ├── agents/
│   │   ├── base/                    # BaseAgent, AgentInterface
│   │   └── shipments/
│   │       ├── signals/agent.py     # ShipmentSignalsAgent (Phase 1)
│   │       ├── decoder/agent.py     # ShipmentDecoderAgent (Phase 2)
│   │       └── skills/              # 17 shipment skills
│   │           ├── loader.py        # Skill metadata/executor loader
│   │           ├── runner.py        # Phased parallel execution
│   │           ├── CONTEXT.md       # Shared workflow context
│   │           └── <skill_name>/    # Each skill directory
│   │               ├── execute.py   # Skill implementation
│   │               ├── SKILL.md     # Skill instructions
│   │               └── references/  # Data dictionary
│   ├── gateway/
│   │   ├── main.py                  # FastAPI app
│   │   ├── orchestrator/pipeline.py # Pipeline orchestrator
│   │   ├── registry/                # Agent registry
│   │   └── routes/                  # API route handlers
│   ├── shared/
│   │   ├── config/settings.py       # Pydantic settings
│   │   ├── models/agent_models.py   # Request/response models
│   │   ├── s3/client.py             # S3 operations
│   │   └── logging/logger.py        # Logging
│   └── data_extraction/             # Snowflake query runner
├── run_pipeline_test.py             # Standalone pipeline test
├── pyproject.toml                   # Dependencies and config
├── .env.example                     # Environment template
├── Dockerfile                       # Container build
└── docs/channel_log.txt             # Implementation log
```

## Performance

Typical pipeline run for one customer: **2-4 minutes**

| Component | Time |
|---|---|
| S3 data loading | ~2-3s |
| Phase 1 deterministic skills (11) | ~1s (parallel) |
| Phase 1 LLM skill (signal generator) | ~60-90s |
| Check gate LLM | ~30-60s |
| Phase 2 LLM skills (2) | ~25-100s |
| S3 output saving | ~1-2s |

Variance is driven by OpenAI API latency. Deterministic skills are negligible.
