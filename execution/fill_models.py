"""
Slippage and commission simulation for realistic backtests.
"""
from logger import get_logger

log = get_logger('execution.fill_models')

class SlippageModel:
    def __init__(self, model='percentage', value=0.001):
        self.model = model
        self.value = value

    def apply(self, price: float, quantity: int, avg_volume: int, action: str) -> float:
        slippage = 0.0
        if self.model == 'percentage':
            slippage = price * self.value
        elif self.model == 'fixed':
            slippage = self.value
        elif self.model == 'volume_based':
            # Impact scales with order_size / avg_volume ratio
            impact_factor = 0.1 
            slippage = (quantity / max(avg_volume, 1)) * price * impact_factor
        
        if action == 'BUY':
            return price + slippage
        elif action == 'SELL':
            return price - slippage
        return price

class CommissionModel:
    def __init__(self, model='per_share', rate=0.005):
        self.model = model
        self.rate = rate

    def calculate(self, quantity: int, price: float) -> float:
        if self.model == 'per_share':
            return max(1.0, quantity * self.rate)
        elif self.model == 'percentage':
            return float(quantity) * price * self.rate
        elif self.model == 'flat':
            return self.rate
        elif self.model == 'zero':
            return 0.0
        return 0.0

class FillSimulator:
    def __init__(self, slippage: SlippageModel = None, commission: CommissionModel = None):
        self.slippage = slippage or SlippageModel()
        self.commission = commission or CommissionModel()

    def simulate_fill(self, price, quantity, avg_volume, action) -> dict:
        fill_price = self.slippage.apply(price, quantity, avg_volume, action)
        comm = self.commission.calculate(quantity, fill_price)
        
        slippage_cost = abs(fill_price - price) * quantity
        total_cost = comm + slippage_cost
        
        if action == 'BUY':
            net_price = fill_price + (comm / quantity if quantity > 0 else 0)
        else:
            net_price = fill_price - (comm / quantity if quantity > 0 else 0)

        return {
            'fill_price': fill_price,
            'commission': comm,
            'slippage_cost': slippage_cost,
            'total_cost': total_cost,
            'net_price': net_price
        }

default_fill_simulator = FillSimulator()
