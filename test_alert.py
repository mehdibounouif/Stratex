from dotenv import load_dotenv
load_dotenv()

from system.alert_manager import alert_manager

alert_manager.send(
    subject="BUY executed — AAPL",
    body="Shares: 10\nPrice: $189.50\nValue: $1,895.00\nConfidence: 78%\nReason: RSI oversold at 23.4",
    level="trade"
)
