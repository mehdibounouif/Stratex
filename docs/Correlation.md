===============================================================

Correlation measures how two assets move together based on their returns (not prices).

calculate Pearson correlation:
- Step 1: Get price data:
Assume two stocks: A and B:
| Day | Price A | Price B |
| --- | ------- | ------- |
| 1   | 100     | 50      |
| 2   | 102     | 51      |
| 3   | 101     | 50      |
| 4   | 103     | 52      |
| 5   | 104     | 54      |
- Step 2: Convert prices → returns:
| Day | Return A                    | Return B                 |
| --- | --------------------------- | ------------------------ |
| 2   | (102−100)/100 = **0.020**   | (51−50)/50 = **0.020**   |
| 3   | (101−102)/102 = **-0.0098** | (50−51)/51 = **-0.0196** |
| 4   | (103−101)/101 = **0.0198**  | (52−50)/50 = **0.040**   |
| 5   | (104−103)/103 = **0.0097**  | (54−52)/52 = **0.0385**  |

- Step 3: Find the mean return of each asset:
sum retrns / total returns
Mean A ≈ 0.0099
Mean B ≈ 0.0197

- Step 4: Subtract the mean (deviation):
Deviation = Today’s return − Average return
| Day | Return A | Mean A | A Deviation | Return B | Mean B | B Deviation |
| --- | -------- | ------ | ----------- | -------- | ------ | ----------- |
| 1   | 0.0200   | 0.0099 | **+0.0101** | 0.0200   | 0.0197 | **+0.0003** |
| 2   | -0.0098  | 0.0099 | **-0.0197** | -0.0196  | 0.0197 | **-0.0393** |
| 3   | 0.0198   | 0.0099 | **+0.0099** | 0.0400   | 0.0197 | **+0.0203** |
| 4   | 0.0097   | 0.0099 | **-0.0002** | 0.0385   | 0.0197 | **+0.0188** |
This centers both assets around zero, which is required for correlation.

- Step 5: Covariance (Do they move together?):
Multiply the deviations row by row.
| Day | A Deviation | B Deviation | Product       |
| --- | ----------- | ----------- | ------------- |
| 1   | +0.0101     | +0.0003     | **+0.000003** |
| 2   | -0.0197     | -0.0393     | **+0.000774** |
| 3   | +0.0099     | +0.0203     | **+0.000201** |
| 4   | -0.0002     | +0.0188     | **-0.000004** |

Why signs matter
(+ × +) → positive → move together
(− × −) → positive → move together
(+ × −) → negative → move opposite

Covariance Formula (applied):
Covariance = Sum of products / (n − 1).
Cov(A, B) ≈ (0.000974) / 3 ≈ 0.000325

- Step 6: Normalize → Correlation:

Standard Deviations (volatility):
| Asset | Std Deviation |
| ----- | ------------- |
| A     | 0.012         |
| B     | 0.023         |

Correlation Formula: Cov(A,B) / (σA × σB)
Correlation = 0.000325 / (0.012 × 0.023)
Correlation ≈ 0.87

Final result:
| Value  | Meaning                     |
| ------ | --------------------------- |
| 0.87   | Strong positive correlation |
| > 0.80 | Too similar                 |
| Result | Violates MAX_CORRELATION    |

==================================================================