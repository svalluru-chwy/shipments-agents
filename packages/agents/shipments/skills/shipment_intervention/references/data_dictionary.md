# Shipment Intervention - Data Dictionary

## Customer Value Tiers

| Tier | LTV Range | Churn Cost | Intervention Budget |
|------|-----------|------------|---------------------|
| Platinum | $1000+ | $800+ | Up to $100 |
| Gold | $500-999 | $400-800 | Up to $75 |
| Silver | $200-499 | $160-400 | Up to $50 |
| Standard | < $200 | < $160 | Up to $25 |

## Intervention Types

| Intervention | Typical Cost | Use When | Expected Impact |
|--------------|--------------|----------|-----------------|
| Expedite | $15-50 | High value + significant delay | Prevents 2+ day delay |
| Refund Shipping | $5-15 | Any delay, goodwill gesture | Customer satisfaction |
| Proactive Notify | $0-5 | All delays, transparency | Reduces contact rate |
| Hold/Investigate | $0 | Suspected issue, need info | Prevents wrong action |
| Reship | $20-100+ | Lost/damaged/critical | Immediate resolution |

## ROI Calculation

```
Expected Value Saved = P(Churn | No Action) × LTV × Retention Rate
Intervention Cost = Direct Cost + Operational Cost
ROI = (Expected Value Saved - Intervention Cost) / Intervention Cost
```

### Churn Probability Factors

| Factor | Base Churn Increase |
|--------|---------------------|
| First delay ever | +2% |
| Repeat delay | +5% per occurrence |
| 3+ day delay | +8% |
| No proactive communication | +3% |
| Pet food/medication | +10% |
| Customer already contacted | +15% |

## Approval Requirements

| Cost Threshold | Approval Needed |
|----------------|-----------------|
| $0-25 | None (auto-approve) |
| $25-50 | Team lead |
| $50-100 | Manager |
| $100+ | Director |

## Customer Communication Guidelines

### DO
- Acknowledge proactively before customer notices
- Take ownership ("we" not "the carrier")
- Offer concrete solution and timeline
- Thank them for their patience

### DO NOT
- Blame external parties
- Make promises you can't keep
- Quote exact internal costs
- Overpromise on delivery times
