# NS-G1 direct-measurement decision

**Registered protocol:** [OSF 5sc3v](https://osf.io/5sc3v/)  
**Aggregate GFW/BTS relevance:** FAIL  
**Annual container-call check:** FAIL  
**Full NS-G1:** NOT PASSED (component failure)

## Aggregate queue relevance

The primary series is mean daily `<2`-knot GFW cargo presence within 0–300 nautical miles over the trailing
seven dates ending at each of 113 BTS observations. GFW cargo is broader than
container ships and the result is aggregate operational relevance, not individual waiting validation.

- positive association: **PASS**
- timing within one observation: **FAIL**
- stronger than movement control: **PASS**

| Association | Estimate | 95% moving-block bootstrap CI |
| --- | ---: | ---: |
| Low-speed Pearson | 0.906 | [0.876, 0.953] |
| Low-speed Spearman | 0.903 | [0.775, 0.943] |
| Movement-control Pearson | 0.295 | — |
| Movement-control Spearman | 0.423 | — |

Best GFW shifts are 7 BTS observations (Pearson) and
4 (Spearman). Both correlation families were required to
pass each registered association clause; this is the conservative implementation of wording that did not name
one family as primary.

## Annual call-count component

| Year | AIS cargo calls | Official container calls | Coverage | Error |
| ---: | ---: | ---: | ---: | ---: |
| 2020 | 2,571 | 1,932 | 1.33 | +33.1% |
| 2021 | 3,313 | 1,772 | 1.87 | +87.0% |
| 2022 | 3,115 | 1,712 | 1.82 | +82.0% |
| 2023 | 2,830 | 1,528 | 1.85 | +85.2% |

The frozen ±20% rule passes in 0/4 years. The present
AIS product covers cargo-class calls across the port area and is not restricted to container terminals, while
the official comparator is container-vessel calls. The mismatch is reported as a failed component; it is not
used to invalidate a separately passing physical GFW/BTS branch or to claim container-call accuracy.

## Branch decision

* GFW spatial policy analysis: **BLOCKED**.
* Annual container-call claims: **BLOCKED**.
* Individual waiting, anchor/berth state and Pillar-B claims: **BLOCKED**.
