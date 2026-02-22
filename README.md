# Shipments Agency Platform

**Production-ready AI agent platform for automated shipment analysis, signal detection, and delay prediction.**

The Shipments Agency Platform processes customer shipment data through a multi-phase pipeline of specialized AI agents and deterministic skills. It provides comprehensive analysis of delivery performance, carrier efficiency, delay patterns, and customer risk assessment to enable proactive intervention.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Features](#features)
- [Skills Catalog](#skills-catalog)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
  - [CLI Pipeline](#1-cli-pipeline-standalone)
  - [FastAPI Gateway](#2-fastapi-gateway)
  - [Docker Deployment](#3-docker-deployment)
  - [API Examples](#4-api-examples)
- [API Reference](#api-reference)
- [Data Pipeline](#data-pipeline)
- [Output Format](#output-format)
- [Project Structure](#project-structure)
- [Performance](#performance)
- [Development](#development)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)

---

## Overview

### What It Does

The platform analyzes customer shipment history to:

1. **Detect anomalies** in delivery performance using statistical thresholds and pattern recognition
2. **Generate signals** for delayed, at-risk, or problematic shipments
3. **Predict delays** for active/in-transit orders using historical carrier and route performance
4. **Assess customer risk** by correlating delivery patterns, carrier reliability, and customer behavior
5. **Provide root cause analysis** for identified issues (carrier performance, routing, geographic patterns)

### Key Capabilities

- **18 specialized skills** across 4 execution phases
- **Deterministic + LLM hybrid approach** for accuracy and interpretability
- **RESTful API** for integration with downstream systems
- **Individual skill execution** for debugging and development
- **S3-backed data pipeline** with Snowflake data extraction
- **Production-ready Docker deployment** with health checks and monitoring

---

## Architecture

### Agent Pipeline

```
┌─────────────────────────────────────────────────────────────┐
│                      FastAPI Gateway                         │
│  /pipeline/run  /skills/{name}/run  /skills/phase/{n}/run   │
└────────────┬────────────────────────────────┬───────────────┘
             │                                │
             │                                │
     ┌───────▼──────────┐            ┌───────▼──────────┐
     │ ShipmentSignals  │            │ ShipmentDecoder  │
     │     Agent        │───────────▶│     Agent        │
     │                  │  Results   │                  │
     │ • Check Gate LLM │            │ • Phase 2 Skills │
     │ • Phase 1 Skills │            │ • Phase 3 Skills │
     │   (12 skills)    │            │   (3 skills)     │
     └───────┬──────────┘            └───────┬──────────┘
             │                                │
             │                                │
     ┌───────▼────────────────────────────────▼───────────┐
     │                 S3 Storage                          │
     │  • Raw shipment data (from Snowflake)              │
     │  • Intermediate results (Phase 1 outputs)          │
     │  • Final analysis (Phase 2+3 outputs)              │
     └────────────────────────────────────────────────────┘
```

### Execution Flow

1. **Data Loading**: Agent loads customer shipment data from S3 (7 pre-extracted Snowflake queries)
2. **Check Gate**: LLM analyzes shipment health and determines if detailed analysis is needed
3. **Phase 1**: 12 skills run in parallel (deterministic metrics + signal generation)
4. **Phase 2**: 2 LLM skills decode signals and predict delays for active shipments
5. **Phase 3**: 1 deterministic skill computes cross-skill customer risk profile
6. **Output**: Structured JSON + human-readable markdown reports saved to S3

### Technology Stack

- **Runtime**: Python 3.10+
- **Web Framework**: FastAPI with Uvicorn
- **AI/LLM**: OpenAI GPT-4.1 / GPT-5-nano (configurable)
- **Data Storage**: AWS S3 (with optional Snowflake extraction)
- **Data Processing**: Pandas, NumPy
- **Containerization**: Docker multi-stage builds
- **Testing**: Pytest with async support

---

## Features

### ✅ Production-Ready

- **Health checks** and liveness probes for orchestration
- **Error handling** with graceful degradation and fallbacks
- **Logging** with structured output for observability
- **Configuration management** via environment variables and YAML
- **Docker support** with optimized multi-stage builds
- **Non-root container** execution for security

### 🔍 Comprehensive Analysis

- **Statistical delay detection** using CTD (Click-to-Deliver) thresholds
- **Carrier performance benchmarking** with delay rates and exception tracking
- **Geographic pattern analysis** (fulfillment center, ZIP code, zones)
- **Temporal pattern detection** (day-of-week, weekend effects, trends)
- **Customer behavior profiling** (autoship rate, order frequency, contact patterns)
- **Active order monitoring** with at-risk flagging

### 🚀 Flexible Deployment

- **Standalone CLI** for batch processing and testing
- **REST API** for real-time queries and integrations
- **Skill-level execution** for debugging and development
- **Batch processing** for multiple customers in parallel
- **Docker deployment** for cloud-native environments

### 📊 Rich Output

- **Structured JSON** for programmatic consumption
- **Markdown reports** for human readability
- **Signal tracking** with severity levels and intervention flags
- **Metadata tracking** (timestamps, versions, execution times)

---

## Skills Catalog

### Phase 1 — Deterministic Analysis (11 skills)

These skills run in parallel and produce deterministic, reproducible results from shipment data.

| Skill | Description | Key Metrics |
|-------|-------------|-------------|
| **`shipment_health_check`** | Overall health assessment comparing customer CTD to ZIP benchmark | Health status (HEALTHY/ATTENTION/AT_RISK), CTD percentile, on-time rate |
| **`delivery_performance`** | Detailed CTD analysis with trend detection | Delayed shipment count, CTD breakdown (CTR/RTS/STD), trend direction |
| **`carrier_analysis`** | Per-carrier performance breakdown | Carrier utilization %, delay rates, exceptions by carrier |
| **`exception_analysis`** | Carrier exception categorization and lost shipment detection | Exception types, rates, lost shipment tracking |
| **`geographic_patterns`** | ZIP code, fulfillment center, and zone analysis | Primary FC, ZIP-level performance, zone distribution |
| **`timing_patterns`** | Day-of-week and temporal pattern detection | Best/worst delivery days, weekend vs weekday CTD |
| **`package_analysis`** | Package weight, dimensions, and heavy package tracking | Weight distribution, heavy package rate (>30 lbs) |
| **`routing_efficiency`** | FC-to-ZIP routing efficiency vs optimal paths | Actual vs optimal miles, efficiency %, excess distance |
| **`order_behavior`** | Autoship vs one-time order patterns, frequency | Autoship rate, orders/month, product categories |
| **`contact_correlation`** | Customer contact patterns correlated with shipments | Contact rate, WISMO rate, contact timing |
| **`current_order`** | Active/in-transit order identification with risk flagging | Active order count, at-risk shipments, expected delivery dates |

### Phase 1 — LLM Analysis (1 skill)

| Skill | Description | Output |
|-------|-------------|--------|
| **`shipment_signal_generator`** | Anomaly-based signal generation with recency awareness | Signals with severity (HIGH/MEDIUM/LOW), intervention flags, order IDs |

### Phase 2 — LLM Interpretation (2 skills)

These skills depend on Phase 1 results and use LLM for complex reasoning.

| Skill | Description | Output |
|-------|-------------|--------|
| **`shipment_delay_predictor`** | Predicts delays for active shipments using carrier/route history | Delay likelihood, contributing factors, route performance |
| **`shipment_signal_decoder`** | Root cause analysis for generated signals | Decoded signals with routing analysis, carrier patterns, recommendations |

### Phase 3 — Risk Assessment (1 skill)

| Skill | Description | Output |
|-------|-------------|--------|
| **`customer_risk_profile`** | Deterministic cross-skill risk assessment | 4-dimensional risk profile (temporal, pattern, forward, relationship) |

### Phase 4 — Not Used in Production Pipeline

These skills exist in the codebase but are not wired into the production pipeline:

- **`shipment_intervention`** — Intervention determination (replaced by `customer_risk_profile`)
- **`shipment_action_prioritizer`** — Action prioritization
- **`shipment_consolidator`** — Executive summary consolidation

---

## Prerequisites

### Required

- **Python 3.10 or higher**
- **OpenAI API key** (for LLM-based skills)
- **AWS credentials** with S3 access (via IAM role or SSO)

### Optional

- **Snowflake account** (for data extraction; not needed if data is pre-loaded to S3)
- **Docker** (for containerized deployment)

---

## Installation

### 1. Clone Repository

```bash
git clone https://github.com/your-org/shipments-agents.git
cd shipments-agents
```

### 2. Install Dependencies

#### Core Installation

```bash
pip install -e .
```

#### With Snowflake Support

```bash
pip install -e ".[snowflake]"
```

#### Development Installation

```bash
pip install -e ".[dev]"
```

#### Install All Optional Dependencies

```bash
pip install -e ".[all]"
```

### 3. Verify Installation

```bash
python -c "from packages.agents.shipments.signals import ShipmentSignalsAgent; print('✓ Installation successful')"
```

---

## Configuration

### 1. Environment Variables

Copy the example environment file and configure:

```bash
cp .env.example .env
```

Edit `.env` and set required values:

```bash
# === Required ===
OPENAI_API_KEY=sk-proj-...your-key-here

# AWS Configuration (choose one approach)
# Option 1: AWS SSO (recommended)
AWS_PROFILE=PowerUserAccess-977247693856
AWS_REGION=us-east-1

# Option 2: Explicit credentials
# AWS_ACCESS_KEY_ID=AKIA...
# AWS_SECRET_ACCESS_KEY=...
# AWS_REGION=us-east-1

# === Optional: Snowflake (for data extraction) ===
# SNOWFLAKE_ACCOUNT=chewy.us-east-1
# SNOWFLAKE_USER=user@chewy.com
# SNOWFLAKE_WAREHOUSE=SC_FORECAST_WH
# SNOWFLAKE_DATABASE=EDLDB
# SNOWFLAKE_SCHEMA=sc_user_tools_analytics_sandbox
# SNOWFLAKE_ROLE=SC_USER_TOOLS_ANALYTICS_DEVELOPER

# === Optional: Gateway ===
# GATEWAY_HOST=0.0.0.0
# GATEWAY_PORT=8000
```

### 2. AWS Authentication

#### Using AWS SSO (Recommended)

```bash
aws sso login --profile PowerUserAccess-977247693856
```

#### Using IAM Credentials

Set `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` in `.env`

### 3. Configuration File

The `config.yaml` file contains additional settings. Environment variables take precedence.

**Key Configuration Sections:**

- **`s3`**: S3 bucket and path configuration
- **`openai`**: Default model, timeout, reasoning effort
- **`agents`**: Per-agent model overrides and settings
- **`skills`**: Skill execution parameters
- **`gateway`**: API server host, port, CORS settings
- **`snowflake`**: Data extraction connection settings

---

## Usage

### 1. CLI Pipeline (Standalone)

Run the pipeline for a single customer from the command line:

```bash
python run_pipeline_test.py
```

**Default behavior:**
- Runs for customer ID `6180005`
- Loads data from S3
- Executes full pipeline (Signals → Decoder agents)
- Saves outputs to `output_local/<customer_id>_<timestamp>/`

**Output files:**

```
output_local/6180005_20260222_143025/
├── pipeline_summary.json                        # Execution metadata
├── shipment_signals_structured.json             # Phase 1 results (JSON)
├── shipment_signals_signals_markdown.md         # Phase 1 report (markdown)
├── shipment_signals_check_gate.json             # LLM check gate decision
├── shipment_decoder_structured.json             # Phase 2+3 results (JSON)
└── shipment_decoder_decoded_markdown.md         # Phase 2+3 report (markdown)
```

**Customize customer ID:**

Edit `run_pipeline_test.py` and change:

```python
customer_id = "6180005"  # Change to your customer ID
```

---

### 2. FastAPI Gateway

Start the API server for real-time queries:

```bash
# Start the gateway
uvicorn packages.gateway.main:app --host 0.0.0.0 --port 8001

# Or use the installed command
shipments-gateway
```

**Server will start on:** `http://localhost:8001`

**API documentation:** `http://localhost:8001/docs` (Swagger UI)

---

### 3. Docker Deployment

#### Build Image

```bash
docker build -t shipments-agents:latest .
```

#### Run Container

```bash
docker run -d \
  --name shipments-agents \
  -p 8001:8000 \
  -e OPENAI_API_KEY=sk-proj-... \
  -e AWS_ACCESS_KEY_ID=AKIA... \
  -e AWS_SECRET_ACCESS_KEY=... \
  -e AWS_REGION=us-east-1 \
  shipments-agents:latest
```

#### Health Check

```bash
curl http://localhost:8001/health
```

Expected response:

```json
{
  "status": "ok",
  "service": "shipments-gateway"
}
```

---

### 4. API Examples

#### Run Full Pipeline

```bash
curl -X POST http://localhost:8001/pipeline/run \
  -H "Content-Type: application/json" \
  -d '{"customer_id": "6180005"}'
```

#### Batch Processing

```bash
curl -X POST http://localhost:8001/pipeline/batch \
  -H "Content-Type: application/json" \
  -d '{
    "customer_ids": ["6180005", "1234567", "7654321"]
  }'
```

#### Run Individual Skill

```bash
curl -X POST http://localhost:8001/skills/shipment_health_check/run \
  -H "Content-Type: application/json" \
  -d '{"customer_id": "6180005"}'
```

#### Run All Skills in a Phase

```bash
# Run all Phase 1 skills (12 skills in parallel)
curl -X POST http://localhost:8001/skills/phase/1/run \
  -H "Content-Type: application/json" \
  -d '{"customer_id": "6180005"}'

# Run all Phase 2 skills (2 skills)
curl -X POST http://localhost:8001/skills/phase/2/run \
  -H "Content-Type: application/json" \
  -d '{"customer_id": "6180005"}'
```

#### List Available Skills

```bash
curl http://localhost:8001/skills
```

#### Get Skill Documentation

```bash
curl http://localhost:8001/skills/delivery_performance
```

Returns the `SKILL.md` documentation for the specified skill.

---

## API Reference

### Endpoints

| Method | Endpoint | Description | Request Body | Response |
|--------|----------|-------------|--------------|----------|
| `GET` | `/health` | Gateway health check | None | `{"status": "ok", "service": "..."}` |
| `GET` | `/agents` | List registered agents | None | List of agent manifests |
| `POST` | `/agents/{name}/run` | Run specific agent | `{"customer_id": "..."}` | Agent execution result |
| `POST` | `/pipeline/run` | Run full pipeline | `{"customer_id": "..."}` | Pipeline results with all agent outputs |
| `POST` | `/pipeline/batch` | Run pipeline for multiple customers | `{"customer_ids": ["...", "..."]}` | Batch execution results |
| `GET` | `/skills` | List all skills with metadata | None | Skill registry with phases and descriptions |
| `GET` | `/skills/{name}` | Get skill documentation | None | SKILL.md content (markdown) |
| `POST` | `/skills/{name}/run` | Run individual skill | `{"customer_id": "..."}` | Skill execution result |
| `POST` | `/skills/phase/{n}/run` | Run all skills in phase N | `{"customer_id": "..."}` | Phase execution results |
| `POST` | `/data/customers` | Query customer data | `{"customer_ids": ["..."]}` | Customer data from S3 |
| `GET` | `/admin/config` | Get current configuration | None | Active configuration (sanitized) |
| `POST` | `/admin/refresh-health` | Refresh agent health checks | None | Updated health status |

### Request Format

All POST endpoints accept JSON with at minimum:

```json
{
  "customer_id": "6180005"
}
```

### Response Format

Successful responses return:

```json
{
  "status": "success",
  "customer_id": "6180005",
  "execution_time_seconds": 123.45,
  "results": {
    "structured_output": { ... },
    "markdown_output": "...",
    "metadata": { ... }
  }
}
```

Error responses return:

```json
{
  "status": "error",
  "error": "Error message",
  "customer_id": "6180005",
  "timestamp": "2026-02-22T14:30:45.123Z"
}
```

---

## Data Pipeline

### Data Flow

1. **Extraction** (optional): 7 SQL queries extract customer data from Snowflake
2. **Storage**: Data is stored in S3 at `s3://{bucket}/{base_path}/{customer_id}/`
3. **Loading**: Agents load data from S3 on-demand
4. **Processing**: Skills process data through 4 phases
5. **Output**: Results saved to S3 and returned via API

### S3 Data Structure

```
s3://dev-use1-worker-sc-fp-data/uta/cat_outputs/{customer_id}/
├── 01_main_shipment_query.parquet              # Primary shipment records
├── 02_customer_contacts_query.parquet          # Customer service contacts
├── 03_customer_zip_performance.parquet         # Customer's ZIP benchmark
├── 04_benchmark_zip_performance.parquet        # All ZIP benchmarks
├── 05_shipment_inspector_query.parquet         # Route/arc distance data
├── 08_customer_information_query.parquet       # Customer profile
├── 15_order_shipment_summary_stats.parquet     # Order summary stats
└── analysis/
    ├── shipment_signals_20260222_143025.json
    ├── shipment_decoder_20260222_143025.json
    └── ...
```

### Snowflake Queries

The platform uses 7 pre-built SQL queries (in `packages/data_extraction/queries/`):

1. **`01_main_shipment_query.sql`** — Primary shipment records with 274 fields
2. **`02_customer_contacts_query.sql`** — Customer service contact history
3. **`03_customer_zip_performance.sql`** — Customer's primary ZIP performance
4. **`04_benchmark_zip_performance.sql`** — ZIP-level benchmarks for comparison
5. **`05_shipment_inspector_query.sql`** — Route analysis with arc distances
6. **`08_customer_information_query.sql`** — Customer profile and metadata
7. **`15_order_shipment_summary_stats.sql`** — Order-level summary statistics

### Data Extraction (Optional)

If you need to extract fresh data from Snowflake:

```bash
# Extract data for a customer
shipments-extract --customer-id 6180005

# Or use the Python module
python -m packages.data_extraction.run_pipeline --customer-id 6180005
```

---

## Output Format

### Structured JSON Output

All skill results follow a standardized format:

```json
{
  "skill_name": "delivery_performance",
  "execution_time_seconds": 0.234,
  "timestamp": "2026-02-22T14:30:45.123Z",
  "customer_id": "6180005",
  "grounded_metrics": {
    "total_shipments": 30,
    "delayed_shipments": 4,
    "avg_ctd": 2.67,
    "delay_rate": 0.133,
    "trend_direction": "DECLINING"
  },
  "qualitative_observations": [
    "4 shipments exceeded the CTD threshold of 4.29 days",
    "Delay rate is 13.3%, concentrated in FedEx FSMS shipments"
  ],
  "flagged_items": [
    {
      "order_id": "5094661531",
      "tracking_number": "494399793244",
      "ctd": 5.0,
      "severity": "HIGH",
      "reason": "Exceeded threshold by 0.71 days"
    }
  ]
}
```

### Markdown Report Output

Human-readable reports are generated for each agent:

```markdown
# Shipment Analysis Report
**Customer:** 6180005  
**Generated:** 2026-02-22 14:30:45 UTC  
**Status:** ATTENTION  

## Check Gate Decision
**Status:** GREEN  
**Severity:** LOW  
...

## Signals Detected (4)
### Signal 1: Excessive Delivery Time - Rx Medication
- **Order:** 5094661531 / 494399793244
- **Severity:** HIGH
- **Intervention Needed:** Yes
- **CTD:** 5.0 days (vs benchmark 4.29)
...
```

---

## Project Structure

```
shipments-agents/
├── packages/                           # Main application code
│   ├── agents/                         # AI agent implementations
│   │   ├── base/                       # Base agent classes and interfaces
│   │   │   ├── agent_interface.py      # Abstract agent interface
│   │   │   └── base_agent.py           # BaseAgent with common functionality
│   │   └── shipments/                  # Shipments domain agents
│   │       ├── signals/                # ShipmentSignalsAgent (Phase 1)
│   │       │   └── agent.py            # Check gate + Phase 1 skills
│   │       ├── decoder/                # ShipmentDecoderAgent (Phase 2+3)
│   │       │   └── agent.py            # Phase 2+3 skills
│   │       ├── actions/                # ShipmentActionsAgent (dormant)
│   │       │   └── agent.py
│   │       └── skills/                 # 18 shipment analysis skills
│   │           ├── CONTEXT.md          # Shared domain context
│   │           ├── loader.py           # Skill metadata loader
│   │           ├── runner.py           # Phased parallel execution
│   │           ├── record_trimmer.py   # Record field reduction utility
│   │           ├── shipment_health_check/
│   │           │   ├── execute.py      # Skill implementation
│   │           │   ├── SKILL.md        # Skill documentation
│   │           │   └── references/
│   │           │       └── data_dictionary.md
│   │           ├── delivery_performance/
│   │           ├── carrier_analysis/
│   │           ├── exception_analysis/
│   │           ├── geographic_patterns/
│   │           ├── timing_patterns/
│   │           ├── package_analysis/
│   │           ├── routing_efficiency/
│   │           ├── order_behavior/
│   │           ├── contact_correlation/
│   │           ├── current_order/
│   │           ├── shipment_signal_generator/
│   │           ├── shipment_delay_predictor/
│   │           ├── shipment_signal_decoder/
│   │           ├── customer_risk_profile/
│   │           ├── shipment_intervention/  # Dormant
│   │           ├── shipment_action_prioritizer/  # Dormant
│   │           └── shipment_consolidator/  # Dormant
│   │
│   ├── gateway/                        # FastAPI web service
│   │   ├── main.py                     # Application entry point
│   │   ├── orchestrator/               # Pipeline orchestration
│   │   │   └── pipeline.py             # Multi-agent pipeline coordinator
│   │   ├── registry/                   # Agent registration
│   │   │   └── agent_registry.py       # Agent registry and health checks
│   │   └── routes/                     # API route handlers
│   │       ├── health.py               # Health check endpoints
│   │       ├── agents.py               # Agent execution endpoints
│   │       ├── pipeline.py             # Pipeline endpoints
│   │       ├── skills.py               # Skill execution endpoints
│   │       ├── data.py                 # Data query endpoints
│   │       └── admin.py                # Admin/config endpoints
│   │
│   ├── shared/                         # Shared utilities
│   │   ├── config/                     # Configuration management
│   │   │   └── settings.py             # Pydantic settings models
│   │   ├── models/                     # Data models
│   │   │   └── agent_models.py         # Request/response models
│   │   ├── s3/                         # S3 operations
│   │   │   └── client.py               # S3 client wrapper
│   │   ├── logging/                    # Logging configuration
│   │   │   └── logger.py               # Logger setup
│   │   ├── exceptions.py               # Custom exceptions
│   │   └── token_tracker.py            # LLM token/cost tracking
│   │
│   └── data_extraction/                # Snowflake data extraction
│       ├── queries/                    # SQL query files (7 queries)
│       │   ├── 01_main_shipment_query.sql
│       │   ├── 02_customer_contacts_query.sql
│       │   ├── 03_customer_zip_performance.sql
│       │   ├── 04_benchmark_zip_performance.sql
│       │   ├── 05_shipment_inspector_query.sql
│       │   ├── 08_customer_information_query.sql
│       │   └── 15_order_shipment_summary_stats.sql
│       ├── runner/                     # Data extraction pipeline
│       │   ├── data_pipeline.py        # Pipeline coordinator
│       │   ├── query_registry.py       # Query management
│       │   └── sql_runner.py           # Snowflake execution
│       └── run_pipeline.py             # CLI entry point
│
├── skills/                             # Agent manifest YAML files
│   ├── shipment_signals.yaml           # ShipmentSignalsAgent manifest
│   ├── shipment_decoder.yaml           # ShipmentDecoderAgent manifest
│   └── shipment_actions.yaml           # ShipmentActionsAgent manifest (dormant)
│
├── tests/                              # Test suite
│   ├── unit/                           # Unit tests
│   └── integration/                    # Integration tests
│
├── docs/                               # Documentation
│   └── channel_log.txt                 # Implementation changelog
│
├── run_pipeline_test.py                # Standalone CLI pipeline runner
├── pyproject.toml                      # Python package configuration
├── config.yaml                         # Application configuration
├── .env.example                        # Environment variable template
├── .gitignore                          # Git ignore rules
├── Dockerfile                          # Multi-stage Docker build
└── README.md                           # This file
```

---

## Performance

### Typical Execution Times

Pipeline execution for a single customer: **2-4 minutes**

| Component | Time (seconds) | Notes |
|-----------|----------------|-------|
| S3 data loading | 2-3 | 7 parquet files (~5-10MB total) |
| Phase 1 deterministic skills (11) | <1 | Parallel execution in ThreadPoolExecutor |
| Check gate LLM | 30-60 | GPT-5-nano inference |
| Phase 1 signal generator LLM | 60-90 | GPT-4.1 with anomaly pre-filtering |
| Phase 2 delay predictor LLM | 10-20 | Only runs if active shipments exist |
| Phase 2 signal decoder LLM | 15-80 | Depends on number of signals (0-30) |
| Phase 3 customer risk profile | <1 | Pure Python, no LLM |
| S3 output saving | 1-2 | JSON + markdown files |
| **Total** | **120-240** | Variance driven by OpenAI API latency |

### Optimization Notes

- **Deterministic skills** complete in <1 second due to parallel execution
- **LLM skills** dominate execution time (90%+ of total runtime)
- **Record trimming** reduces prompt size by ~90%, improving LLM response times
- **Anomaly pre-filtering** in signal generator reduces LLM calls by only processing flagged records
- **Batch processing** can parallelize multiple customers with ThreadPoolExecutor

### Scaling Considerations

- **Horizontal scaling**: Deploy multiple gateway instances behind a load balancer
- **Async processing**: Use background task queues (Celery, AWS SQS) for long-running pipelines
- **Caching**: Cache S3 data loads for repeated queries on the same customer
- **Rate limiting**: Implement rate limiting to prevent OpenAI API throttling

---

## Development

### Setup Development Environment

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Install pre-commit hooks (optional)
pip install pre-commit
pre-commit install
```

### Run Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=packages --cov-report=html

# Run specific test file
pytest tests/unit/test_skills.py

# Run integration tests only
pytest tests/integration/
```

### Code Quality

```bash
# Format code with Black
black packages/ tests/

# Lint with Ruff
ruff check packages/ tests/

# Type check with mypy
mypy packages/
```

### Adding a New Skill

1. **Create skill directory**: `packages/agents/shipments/skills/my_skill/`
2. **Implement `execute.py`**: Define `execute(state, **kwargs)` function
3. **Write `SKILL.md`**: Document skill purpose, inputs, outputs, and logic
4. **Create data dictionary**: `references/data_dictionary.md` with field mappings
5. **Register in `runner.py`**: Add skill name to appropriate phase in `SHIPMENTS_SKILL_PHASES`
6. **Test**: Run skill individually via API or CLI

### Logging

```python
from packages.shared.logging import get_logger

logger = get_logger(__name__)

logger.info("Processing customer", customer_id=customer_id)
logger.warning("Missing field", field="SHIPMENT_STATUS", record_id=record_id)
logger.error("Skill failed", skill="delivery_performance", error=str(e))
```

### Debugging

#### Enable Debug Logging

Set in `.env`:

```bash
LOG_LEVEL=DEBUG
```

#### Run Single Skill

```python
from packages.agents.shipments.skills import run_skill

state = {
    "customer_id": "6180005",
    "shipment_data": {...},  # Load from S3
}

result = run_skill("delivery_performance", state)
print(result)
```

#### Check Agent Health

```bash
curl http://localhost:8001/admin/refresh-health
```

---

## Troubleshooting

### Common Issues

#### 1. OpenAI API Errors

**Symptom:** `openai.error.AuthenticationError` or `openai.error.RateLimitError`

**Solution:**
- Verify `OPENAI_API_KEY` is set correctly in `.env`
- Check API key has sufficient quota and permissions
- Implement exponential backoff for rate limits (already built into BaseAgent)

#### 2. S3 Access Denied

**Symptom:** `botocore.exceptions.ClientError: An error occurred (403) when calling the GetObject operation: Forbidden`

**Solution:**
- Verify AWS credentials are configured (`aws sso login` or set AWS_ACCESS_KEY_ID)
- Check IAM role/user has `s3:GetObject` and `s3:PutObject` permissions for the bucket
- Verify bucket name and region in `config.yaml` match your S3 setup

#### 3. Missing Snowflake Dependencies

**Symptom:** `ModuleNotFoundError: No module named 'snowflake'`

**Solution:**
```bash
pip install -e ".[snowflake]"
```

#### 4. Skill Execution Timeout

**Symptom:** Skill hangs or times out after 10 minutes

**Solution:**
- Increase timeout in `config.yaml`:
  ```yaml
  openai:
    timeout: 900  # 15 minutes
  ```
- Check OpenAI API status: https://status.openai.com

#### 5. Empty or Invalid S3 Data

**Symptom:** `ValueError: No shipment data found for customer`

**Solution:**
- Verify data exists in S3: `aws s3 ls s3://dev-use1-worker-sc-fp-data/uta/cat_outputs/6180005/`
- Extract fresh data: `shipments-extract --customer-id 6180005`
- Check customer ID is valid and has shipment history

### Debug Mode

Enable verbose logging for troubleshooting:

```bash
# In .env
LOG_LEVEL=DEBUG

# Run with debug output
python run_pipeline_test.py 2>&1 | tee debug.log
```

### Health Check Failed

**Symptom:** Docker health check fails or `/health` endpoint returns 500

**Solution:**
- Check logs: `docker logs shipments-agents`
- Verify environment variables are set correctly
- Test individual components: `curl http://localhost:8001/agents`

---

## Contributing

### Guidelines

1. **Follow existing patterns**: Match the style and structure of existing skills/agents
2. **Write tests**: All new features should have unit tests
3. **Document**: Update README and add SKILL.md for new skills
4. **Log appropriately**: Use structured logging with context
5. **Handle errors**: Implement graceful fallbacks and error messages

### Pull Request Process

1. Create feature branch from `main`
2. Implement changes with tests
3. Run code quality checks (`black`, `ruff`, `mypy`)
4. Update documentation (README, channel_log.txt)
5. Submit PR with clear description and test results
6. Address review feedback

---

## Delay Detection Methodology

The platform uses **CTD-based statistical thresholds** for delay detection:

### Click-to-Deliver (CTD)

**CTD** = Days from order placement (`ORDER_PLACED_DTTM`) to delivery (`BULK_TRACK_DELIVERY_DTTM`)

### Threshold Calculation

**Threshold** = `mean(customer_CTDs) + 1 * stddev(customer_CTDs)`

- Computed per customer from delivered shipments
- Typically 3-5 days for most customers
- Accounts for customer-specific patterns (location, product mix)

### Delay Classification

A shipment is **delayed** if: `CTD > Threshold`

### CTD Breakdown

CTD is decomposed into three components:

1. **CTR** (Click-to-Release): Order placement to warehouse release
2. **RTS** (Release-to-Ship): Warehouse release to carrier pickup
3. **STD** (Ship-to-Deliver): Carrier pickup to delivery

This breakdown identifies where delays originate (warehouse vs carrier).

### Estimated CTD

For active/in-transit shipments without delivery dates:

**Estimated CTD** = `(SHIPMENT_ESTIMATED_DELIVERY_DATE - ORDER_PLACED_DTTM) / 86400`

Falls back to `WIZMO_CURRENT_ARRIVAL_DATE` or `LAST_EXPECTED_DELIVERY_DATE` if primary field is null.

---

## License

Copyright © 2026 Chewy, Inc. All rights reserved.

Internal use only. Not for redistribution.

---

## Support

For questions, issues, or feature requests:

- **Email**: [supply-chain-analytics@chewy.com](mailto:supply-chain-analytics@chewy.com)
- **Slack**: `#supply-chain-analytics`
- **GitHub Issues**: [Create an issue](https://github.com/your-org/shipments-agents/issues)

---

## Changelog

See `docs/channel_log.txt` for detailed implementation history and changes.

**Latest Version**: 1.0.0 (2026-02-22)

- ✅ 18 skills across 4 phases
- ✅ 2-agent pipeline (Signals + Decoder)
- ✅ RESTful API with FastAPI
- ✅ Docker deployment support
- ✅ Comprehensive documentation
- ✅ Production-ready error handling and logging
