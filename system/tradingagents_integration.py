from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG
from config import BaseConfig, TradingConfig
from data.data_enginner import data_access
from datetime import datetime
import json
import os

class TradingAgentsIntegration:
    """
    Wrapper for TradingAgents that integrates with our system
    """
    
    def __init__(self, use_our_data=True):
        """
        Initialize TradingAgents
        
        Args:
            use_our_data: If True, use Person 1's data instead of TradingAgents fetching
        """
        print("🤖 Initializing TradingAgents Integration...")
        
        # Configure TradingAgents
        config = DEFAULT_CONFIG.copy()
        
        # Use our team's model preferences
        config["deep_think_llm"] = TradingConfig.TRADINGAGENTS_MODEL
        config["quick_think_llm"] = TradingConfig.TRADINGAGENTS_MODEL
        config["max_debate_rounds"] = TradingConfig.TRADINGAGENTS_DEBATE_ROUNDS
        
        # If using our data, configure TradingAgents to use it
        if use_our_data:
            print("  ℹ️  Configured to use our data")
            # NOTE: This requires modifying TradingAgents config
            # For now, TradingAgents will fetch its own data
            # TODO: Connect to our data once available
        
        # Initialize TradingAgents
        self.ta = TradingAgentsGraph(debug=False, config=config)
        self.use_our_data = use_our_data
        
        print("✅ TradingAgents Integration ready")
    
    def analyze(self, ticker, date=None):
        """
        Run TradingAgents analysis on a stock
        
        Args:
            ticker: Stock symbol
            date: Date to analyze (YYYY-MM-DD), default: today
        
        Returns:
            dict: Standardized signal format
        """
        if date is None:
            date = datetime.now().strftime('%Y-%m-%d')
        
        print(f"\n🤖 Running TradingAgents analysis: {ticker}")
        print(f"   Date: {date}")
        print(f"   This may take 3-5 minutes...")
        
        try:
            # Run TradingAgents
            start_time = datetime.now()
            _, decision = self.ta.propagate(ticker, date)
            end_time = datetime.now()
            
            duration = (end_time - start_time).total_seconds()
            print(f"   ✅ Analysis complete ({duration:.1f}s)")
            
            # Convert to our standard format
            standardized = self._standardize_output(decision)
            
            # Save raw output
            self._save_raw_output(ticker, date, decision)
            
            return standardized
            
        except Exception as e:
            print(f"   ❌ TradingAgents analysis failed: {e}")
            
            return {
                'ticker': ticker,
                'action': 'HOLD',
                'confidence': 0.0,
                'source': 'TradingAgents',
                'error': str(e),
                'reasoning': f"TradingAgents analysis failed: {e}",
                'timestamp': datetime.now().isoformat()
            }
    
    def _standardize_output(self, ta_decision):
        """
        Convert TradingAgents output to our standard signal format
        
        Our standard format:
        {
            'ticker': str,
            'action': 'BUY'|'SELL'|'HOLD',
            'confidence': float (0-1),
            'current_price': float,
            'target_price': float (optional),
            'stop_loss': float (optional),
            'reasoning': str,
            'source': 'TradingAgents',
            'timestamp': str
        }
        """
        return {
            'ticker': ta_decision.get('ticker', 'UNKNOWN'),
            'action': ta_decision.get('action', 'HOLD'),
            'confidence': ta_decision.get('conviction', 0.0),
            'current_price': ta_decision.get('current_price', 0.0),
            'target_price': ta_decision.get('target_price'),
            'stop_loss': ta_decision.get('stop_loss'),
            'reasoning': ta_decision.get('reasoning', 'No reasoning provided'),
            'source': 'TradingAgents',
            'timestamp': datetime.now().isoformat(),
            'raw_output': ta_decision  # Keep full output for reference
        }
    
    def _save_raw_output(self, ticker, date, decision):
        """Save raw TradingAgents output for debugging"""
        output_dir = 'system/tradingagents_output'
        os.makedirs(output_dir, exist_ok=True)
        
        filename = f"{ticker}_{date}_{datetime.now().strftime('%H%M%S')}.json"
        filepath = os.path.join(output_dir, filename)
        
        with open(filepath, 'w') as f:
            json.dump(decision, f, indent=2)
        
        print(f"   💾 Raw output saved: {filepath}")
    
    def analyze_multiple(self, tickers, date=None):
        """
        Analyze multiple stocks (WARNING: Expensive and slow!)
        
        Args:
            tickers: List of stock symbols
            date: Date to analyze
        
        Returns:
            list: List of standardized signals
        """
        print(f"\n🤖 Running TradingAgents on {len(tickers)} stocks...")
        print(f"   ⚠️  This will take {len(tickers) * 4} minutes and cost ~${len(tickers) * 0.5:.2f}")
        
        results = []
        
        for i, ticker in enumerate(tickers):
            print(f"\n[{i+1}/{len(tickers)}] Analyzing {ticker}...")
            
            signal = self.analyze(ticker, date)
            results.append(signal)
        
        print(f"\n✅ Completed analysis of {len(tickers)} stocks")
        return results

# Global instance
tradingagents = TradingAgentsIntegration()

# Example usage
if __name__ == "__main__":
    print("Testing TradingAgents Integration...")
    
    # Test single stock
    signal = tradingagents.analyze('AAPL')
    
    print("\n" + "="*70)
    print("SIGNAL FROM TRADINGAGENTS:")
    print("="*70)
    print(f"Ticker: {signal['ticker']}")
    print(f"Action: {signal['action']}")
    print(f"Confidence: {signal['confidence']:.0%}")
    print(f"Reasoning: {signal['reasoning'][:200]}...")
    print("="*70)