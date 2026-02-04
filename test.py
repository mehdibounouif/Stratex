import pandas as pd
import numpy as np

# ==========================================
# 1. PANDAS SERIES
# ==========================================
# Imagine we are tracking the sales of a single item, "Apples"
apple_sales_data = [10, 15, 12, 20, 30]
days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']

# Creating the Series
# It has one dimension: Length
series = pd.Series(apple_sales_data, index=days, name="Apple Sales")

print("--- PANDAS SERIES (1D) ---")
print(series)
print("\n")


# ==========================================
# 2. PANDAS DATAFRAME
# ==========================================
# Now imagine we are tracking Apples AND Oranges.
# We need 2 dimensions: Rows (Days) and Columns (Fruit Type)
data = {
    'Apples': [10, 15, 12, 20, 30],
    'Oranges': [5, 8, 7, 10, 12]
}

# Creating the DataFrame
df = pd.DataFrame(data, index=days)

print("--- PANDAS DATAFRAME (2D) ---")
print(df)
print("\n")


# ==========================================
# 3. METRICS (Calculated from Data)
# ==========================================
# Metrics are the insights we derive from the structures above.

print("--- METRICS (Calculations) ---")

# Metric 1: Total items sold (Sum)
total_sales = df.sum() 
print(f"Total Sales per Fruit:\n{total_sales}\n")

# Metric 2: Average daily sales (Mean)
avg_sales = df.mean()
print(f"Average Daily Sales:\n{avg_sales}\n")

# Metric 3: General Statistical Metrics
# .describe() calculates multiple metrics at once (count, mean, std, min, max)
stats = df.describe()
print("Summary Statistics (Key Metrics):")
print(stats)
