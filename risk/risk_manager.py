from config import RiskConfig

class RiskManager:
    def __init__(self):
        self.config = RiskConfig()
        self.current_portfolio_value = 1000
        self.current_cach = 200
        self.num_positions = 0
        print("Using test risk manager (Message for B3aybach)")
