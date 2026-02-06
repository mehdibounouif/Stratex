import sqlite3

# 1. Connect to database
conn = sqlite3.connect("trading_data.db")
cursor = conn.cursor()

# 2. Write SELECT query
sql = "SELECT * FROM stock_prices WHERE ticker = ? ORDER BY date DESC"

# 3. Execute query
cursor.execute(sql, ("TSLA",))

# 4. Get all rows
rows = cursor.fetchall()

# 5. Print the data
for row in rows:
    print(row)

# 6. Close connection
conn.close()
