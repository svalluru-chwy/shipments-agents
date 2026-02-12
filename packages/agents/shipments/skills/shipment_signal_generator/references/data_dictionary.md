# Shipment Signal Generator - Data Dictionary

## Shipment Record Fields

| Field | Description | Example |
|-------|-------------|---------|
| ORDER_ID | Unique order identifier | ORD_12345678 |
| SHIPMENT_TRACKING_NUMBER | Carrier tracking number | TRK987654321 |
| CUSTOMER_ID | Customer identifier | 7880372 |
| WAREHOUSE_CARRIER | Shipping carrier | FedEx, UPS, USPS |
| FFMCENTER_NAME | Fulfillment center name | PA_FC, TX_FC |
| ORDER_PLACED_DTTM | Order placement timestamp | 2026-01-01T10:30:00 |
| RELEASE_DTTM | Order release timestamp | 2026-01-01T12:00:00 |
| ACTUAL_SHIP_DATE | Shipment ship date | 2026-01-01T14:00:00 |
| BULK_TRACK_DELIVERY_DTTM | Delivery timestamp | 2026-01-03T16:00:00 |
| POSTCODE | Delivery ZIP code | 12345 |
| BULK_TRACK_LB_PACKAGE_WEIGHT | Package weight (lbs) | 15.5 |
| SHIPMENT_QUANTITY | Units in shipment | 3 |

## Delivery Time Metrics

| Metric | Formula | Interpretation |
|--------|---------|----------------|
| CTD | Delivery Date - Order Date | Total customer wait time |
| CTR | Release Date - Order Date | Internal processing time |
| RTS | Ship Date - Release Date | Fulfillment to carrier handoff |
| STD | Delivery Date - Ship Date | Carrier transit time |

### CTD Breakdown
```
CTD = CTR + RTS + STD

Example:
- Order placed: Jan 1
- Released: Jan 1 (CTR = 0 days)
- Shipped: Jan 2 (RTS = 1 day)
- Delivered: Jan 4 (STD = 2 days)
- Total CTD = 3 days
```

## Signal Severity Levels

| Severity | CTD vs Threshold | Action Required |
|----------|-----------------|----------------|
| Low | CTD ≤ avg | No action needed |
| Medium | avg < CTD ≤ threshold | Monitor |
| High | CTD > threshold | Proactive notification |
| Critical | CTD > 2× threshold | Immediate intervention |

## Delay Exception Codes

| Code | Description | Typical Impact |
|------|-------------|----------------|
| WEATHER_DELAY | Weather-related delay | 1-3 days |
| MECHANICAL_DELAY | Vehicle/equipment issue | 1-2 days |
| VOLUME_DELAY | High volume surge | 1-2 days |
| ADDRESS_ISSUE | Delivery address problem | 1-3 days |
| CUSTOMER_REQUEST | Customer-initiated hold | Variable |

## Product Categories for Priority

| Category | Examples | Delay Urgency |
|----------|----------|---------------|
| Rx (Prescription) | Medications, prescription food | CRITICAL |
| Required Food | Pet food, essential nutrition | HIGH |
| Flea & Tick | Preventive medications | HIGH |
| Treats & Supplements | Treats, vitamins | MEDIUM |
| Toys & Accessories | Toys, beds, bowls | LOW |

## Carrier Performance Benchmarks

| Carrier | Target On-Time Rate | Typical Transit Days |
|---------|--------------------|--------------------|
| FedEx Ground | 95% | 2-5 days |
| FedEx Home | 97% | 1-3 days |
| UPS Ground | 94% | 2-5 days |
| USPS Priority | 92% | 2-4 days |

## Signal Categories Reference

| Category | Signal Types |
|----------|--------------|
| Delivery Performance | Excessive Delay, Geographic Inefficiency, Performance Degradation |
| Tracking Visibility | Missing Tracking, Tracking Gap, Exception Status |
| Package Integrity | Weight Anomaly, Damage Risk, Fragile Handling |
| Carrier Logistics | Carrier Performance, Route Efficiency, Capacity Constraint |
| Customer Pattern | Rush Order, Stockpiling, Recovery Attempt |
