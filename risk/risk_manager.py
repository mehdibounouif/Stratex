from config import RiskConfig

class RiskManager:
    def __init__(self):
        self.config = RiskConfig()
        self.current_portfolio_value = 1000
        self.current_cach = 200
        self.num_positions = 0
        print("Using test risk manager (Message for B3aybach)")

    def check_position_size(self, size):
        """Check if position size is limited"""
        if size > self.config.MAX_POSITION_SIZE:
            return False, f"Position size {size:.1%} exceeds max {self.config.MAX_POSITION_SIZE} "
        return True, "Position size Ok"
    