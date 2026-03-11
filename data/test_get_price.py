# test_get_price_history.py

from data.data_engineer import DataEngineer

de = DataEngineer()

# ─────────────────────────────────────────
# TEST 1 — Normal fetch (cache or API)
# ─────────────────────────────────────────
print("\n TEST 1 — Normal fetch (365 days)")
print("=====================================================")
df = de.get_price_history("AAPL", days=365)
print("=====================================================")
if df is not None and not df.empty:
    print(f"  ✅ PASS — got {len(df)} rows")
    print(f"  Columns: {list(df.columns)}")
    print(df.tail(3))
else:
    print("  ❌ FAIL — returned None or empty")