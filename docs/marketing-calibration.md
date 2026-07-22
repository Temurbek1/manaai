# Marketing Agent calibration

Calibration is typed, versioned, reversible, and layered. Effective settings resolve in this order:

1. global configuration defaults;
2. provider defaults;
3. account calibration;
4. objective override;
5. campaign override.

Later layers replace only explicitly supplied fields. Removing an account calibration immediately
reverts the account to the applicable provider/global defaults without changing historical versions.

## Data-derived method

For available normalized ad-level base rows, volume floors use the 25th percentile, efficiency
targets use medians, maximum frequency uses the 75th percentile, and relative interquartile ranges
set bounded change/anomaly sensitivity. Confidence and completeness thresholds are bounded by
observed metric availability. The configuration stores source snapshot ID, calibration timestamp,
row/day counts, unavailable thresholds, and human-readable rationale.

## Live result

The live period had zero normalized base rows. No quantile, variability, confidence, completeness,
baseline length, comparison length, conversion lag, or performance target can be estimated from that
evidence. Configuration version 7 therefore stores `null` for all 15 account overrides and inherits
lower-layer defaults. This is provisional and must be recalibrated after sufficient completed
delivery data exists.

A zero-row calibration must never substitute convenient fallback numbers as if they were
account-derived. The focused regression test enforces this invariant.

## Recalibration checklist

- Use completed account-local days only and preserve currency/attribution identity.
- Require base ad-level rows; breakdown rows cannot inflate sample size.
- Review row count, represented days, completeness, delayed conversion behavior, and outliers.
- Compare candidate thresholds to the prior version before activation.
- Keep notifications disabled during a calibration validation run.
- Roll back by activating/removing the account calibration layer, then rerun analysis.
