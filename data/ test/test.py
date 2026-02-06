import sqlite3
def insert_data(ticker, date, open_price, high, low, close, volume):
    conn = sqlite3.connect("trading_data.db")
    print("is connected with database")
    cursor = conn.cursor()
    sql = """
        INSERT OR IGNORE INTO stock_prices(ticker, date, open, high, low, close, volume)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """
    cursor.execute(sql, (ticker, date, open_price, high, low, close, volume))
    conn.commit()
    conn.close()
    print("dane")

insert_data("AAPL", "2026-02-04 10:00:00", 150.0, 155.0, 148.0, 154.0, 1000000)
insert_data("TSLA", "2026-02-04 10:00:00", 150.0, 155.0, 148.0, 154.0, 1000000)
insert_data("TSLA", "2026-02-03 10:00:00", 150.0, 155.0, 148.0, 154.0, 1000000)
