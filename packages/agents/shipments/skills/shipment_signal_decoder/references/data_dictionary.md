# Shipment Signal Decoder - Data Dictionary

## Root Cause Analysis Levels

| Level | Focus | Examples |
|-------|-------|----------|
| Level 1: Direct | Immediate operational causes | Weather delay, system outage, carrier exception |
| Level 2: Systemic | Broader operational patterns | Single-hub dependency, capacity constraints |
| Level 3: External | Market/environment factors | Seasonal surge, regional weather patterns |

## Business Impact Metrics

### Cost Efficiency Metrics

| Metric | Formula | Benchmark |
|--------|---------|-----------|
| CPP | Cost per Package | $8-12 typical |
| CPO | Cost per Order | $15-25 typical |
| CPU | Cost per Unit | $3-6 typical |
| CPLD | Cost per Pound Delivered | $0.50-1.50 |

### Revenue Risk Metrics

| Metric | Formula | Interpretation |
|--------|---------|----------------|
| LTV at Risk | LTV × Churn Probability | Dollar value at risk |
| Churn Increase | Base Churn + Delay Impact | % increase per delay |
| Retention Cost | Intervention Cost | Cost to prevent churn |

### Churn Probability Factors

| Factor | Base Churn Increase |
|--------|---------------------|
| First delay ever | +2% |
| Repeat delay | +5% per occurrence |
| 3+ day delay | +8% |
| No proactive communication | +3% |
| Pet food/medication | +10% |
| Customer already contacted | +15% |

## Customer Impact Categories

| Category | Indicators | Severity |
|----------|------------|----------|
| Frustration | Multiple contacts, negative sentiment | High |
| Inconvenience | Single delay, resolved | Medium |
| Trust Erosion | Repeat issues, no resolution | Critical |
| Satisfaction | On-time, proactive communication | Positive |

## Pet Care Impact Assessment

| Category | Products | Delay Urgency |
|----------|----------|---------------|
| Rx (Prescription) | Medications, prescription food | CRITICAL - Health risk |
| Required Food | Pet food, essential nutrition | HIGH - Feeding disruption |
| Preventive Care | Flea/tick, vitamins | HIGH - Health prevention |
| Wellness | Supplements, dental | MEDIUM - Can wait briefly |
| Discretionary | Toys, accessories | LOW - Not time-sensitive |

## Evidence Quality Standards

### Strong Evidence
- Specific tracking events with timestamps
- Calculated metrics from data
- Comparative benchmarks
- Multiple corroborating data points

### Weak Evidence
- Single data point
- Inferred rather than stated
- Missing timestamps
- No baseline comparison

## Hypothesis Validation Checklist

| Criterion | Required |
|-----------|----------|
| Specific order/shipment ID | ✓ |
| Date/timestamp evidence | ✓ |
| Quantified metric | ✓ |
| Baseline comparison | ✓ |
| Causal mechanism | ✓ |
| Alternative explanations considered | ✓ |

## Cross-Signal Pattern Types

| Pattern | Description | Intervention |
|---------|-------------|--------------|
| Geographic Cluster | Multiple delays same ZIP | Carrier routing change |
| Temporal Cluster | Multiple delays same period | Seasonal planning |
| Carrier Cluster | Multiple delays same carrier | Carrier performance review |
| Product Cluster | Multiple delays same category | Priority handling |
| FC Cluster | Multiple delays same FC | FC capacity review |
