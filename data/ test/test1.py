import sqlite3

conn = sqlite3.connect("trading_data.db")
cursor = conn.cursor()
sql = "SELECT * FROM stock_prices WHERE ticker = ? ORDER BY date DESC"
cursor.execute(sql, ("TSLA",))
rows = cursor.fetchall()
for row in rows:
    print(row)
conn.close()
