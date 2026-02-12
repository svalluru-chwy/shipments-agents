# Shipment Action Prioritizer - Data Dictionary

## Priority Scoring

### Customer Value Scoring (30% weight)
| Customer Class | Score |
|----------------|-------|
| Platinum | 100 |
| Gold | 80 |
| Silver | 60 |
| Standard | 40 |

### Urgency Scoring (25% weight)
| Timeframe | Score |
|-----------|-------|
| < 24 hours | 100 |
| 24-48 hours | 75 |
| 48-72 hours | 50 |
| 72+ hours | 25 |

### Issue Severity Scoring (25% weight)
| Issue Type | Score |
|------------|-------|
| Critical item (Rx/medication) delay | 100 |
| Multiple item delay (3+) | 85 |
| Active exception (lost/damaged) | 90 |
| Single item delay > 5 days | 70 |
| Delay affecting autoship | 60 |
| Standard delay 3-5 days | 40 |

### ROI Scoring (20% weight)
| ROI Ratio | Score |
|-----------|-------|
| > 10x | 100 |
| 5-10x | 80 |
| 2-5x | 60 |
| 1-2x | 40 |
| < 1x | 20 |

## Action Types

| Action | Typical Cost | Use Case |
|--------|--------------|----------|
| `proactive_outreach` | $5 | Inform before customer contacts |
| `refund_shipping` | $9-15 | Shipping cost reimbursement |
| `expedite` | $25-50 | Upgrade to faster shipping |
| `reship` | $15-40 | Send replacement |
| `compensation` | $10-25 | Credit or discount |
| `full_refund` | Variable | Complete order refund |

## Success Metrics

- **Resolution Rate**: % of actions that resolved the issue
- **Repeat Contact Rate**: Customer contacts within 7 days
- **CSAT Impact**: Change in customer satisfaction
- **Retention Impact**: Churn prevented
