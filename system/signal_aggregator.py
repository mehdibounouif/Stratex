"""
Signal Aggregator - Combines Multiple Trading Signals
=====================================================

Resolves conflicts between RSI, Momentum, AI, and other signal sources
with intelligent conflict resolution and confidence scoring.

Author: Trading System
Compatible with: system_architect.py, rsi_strategy.py, momentum_strategy.py
"""

from logger import get_logger, setup_logging

setup_logging()
log = get_logger('system.signal_aggregator')


class SignalAggregator:
    """
    Combines multiple trading signals with intelligent conflict resolution.
    
    SUPPORTED STRATEGIES:
    - RSI (Relative Strength Index)
    - Momentum (Price momentum)
    - AI (TradingAgents sentiment/fundamental analysis)
    - Custom strategies (any that return standard signal format)
    
    CONFLICT RESOLUTION LOGIC:
    1. All agree (BUY/BUY/BUY) → High confidence (+15%)
    2. Majority agree (2/3 BUY) → Medium confidence (+5%)
    3. Split decision (1 BUY, 1 SELL, 1 HOLD) → HOLD
    4. Conflict (BUY vs SELL with no HOLD) → HOLD (wait for clarity)
    5. One strong signal, others neutral → Use strong signal at 80% confidence
    
    CONFIDENCE SCORING:
    - 90-100%: Very strong (all sources agree)
    - 75-89%: Strong (majority agree or one very confident)
    - 60-74%: Moderate (weak agreement or single source)
    - 40-59%: Weak (conflicting signals)
    - 0-39%: Very weak (high conflict, default to HOLD)
    """
    
    def __init__(self):
        """Initialize signal aggregator."""
        self.history = []  # Track aggregation history for analysis
        log.info("✅ SignalAggregator initialized")
    
    def combine_two(self, signal1, signal2):
        """
        Combine two signals (e.g., RSI + Momentum).
        
        Parameters
        ----------
        signal1 : dict
            {'action': 'BUY'|'SELL'|'HOLD', 'confidence': 0-100, 'reasoning': str, 'source': str}
        
        signal2 : dict
            Same format as signal1
        
        Returns
        -------
        dict : Combined signal with adjusted confidence
        """
        action1 = signal1['action']
        action2 = signal2['action']
        conf1 = signal1['confidence']
        conf2 = signal2['confidence']
        
        source1 = signal1.get('source', 'Source1')
        source2 = signal2.get('source', 'Source2')
        
        log.info(f"📊 Combining: {source1}={action1}@{conf1}%, {source2}={action2}@{conf2}%")
        
        # ── CASE 1: Both Agree ────────────────────────────────
        if action1 == action2 and action1 != 'HOLD':
            avg_confidence = (conf1 + conf2) / 2
            boosted = min(95, avg_confidence + 10)  # +10% bonus, max 95%
            
            result = {
                'action': action1,
                'confidence': round(boosted, 2),
                'reasoning': f"✅ {source1} + {source2} both signal {action1}",
                'sources': [source1, source2],
                'agreement': 'full'
            }
            
            log.info(f"   ✅ Agreement: {action1} @ {result['confidence']}%")
            return result
        
        # ── CASE 2: Conflict (BUY vs SELL) ────────────────────
        if (action1 == 'BUY' and action2 == 'SELL') or \
           (action1 == 'SELL' and action2 == 'BUY'):
            
            result = {
                'action': 'HOLD',
                'confidence': 40,
                'reasoning': f"⚠️ CONFLICT: {source1} says {action1}, {source2} says {action2} - waiting",
                'sources': [source1, source2],
                'agreement': 'conflict'
            }
            
            log.warning(f"   ⚠️ Conflict: {source1}={action1} vs {source2}={action2} → HOLD")
            return result
        
        # ── CASE 3: One HOLD ───────────────────────────────────
        if action1 == 'HOLD' and action2 != 'HOLD':
            reduced = conf2 * 0.8
            
            result = {
                'action': action2,
                'confidence': round(reduced, 2),
                'reasoning': f"📉 {source2} signal {action2} ({source1} neutral)",
                'sources': [source2],
                'agreement': 'partial'
            }
            
            log.info(f"   📉 {source1} neutral, using {source2}: {action2} @ {result['confidence']}%")
            return result
        
        if action2 == 'HOLD' and action1 != 'HOLD':
            reduced = conf1 * 0.8
            
            result = {
                'action': action1,
                'confidence': round(reduced, 2),
                'reasoning': f"📉 {source1} signal {action1} ({source2} neutral)",
                'sources': [source1],
                'agreement': 'partial'
            }
            
            log.info(f"   📉 {source2} neutral, using {source1}: {action1} @ {result['confidence']}%")
            return result
        
        # ── CASE 4: Both HOLD ──────────────────────────────────
        result = {
            'action': 'HOLD',
            'confidence': 30,
            'reasoning': f"📊 Both {source1} and {source2} recommend HOLD",
            'sources': [source1, source2],
            'agreement': 'full'
        }
        
        log.info(f"   📊 Both sources HOLD")
        return result
    
    def combine_three(self, rsi_signal, momentum_signal, ai_signal=None):
        """
        Combine three signals: RSI + Momentum + AI (optional).
        
        This is the main method for your system since you have RSI + Momentum.
        
        Parameters
        ----------
        rsi_signal : dict
            Signal from RSI strategy
        
        momentum_signal : dict
            Signal from Momentum strategy
        
        ai_signal : dict, optional
            Signal from AI/TradingAgents (if enabled)
        
        Returns
        -------
        dict : Aggregated signal with voting results
        """
        signals = [rsi_signal, momentum_signal]
        if ai_signal:
            signals.append(ai_signal)
        
        return self.combine_multiple(signals)
    
    def combine_multiple(self, signals):
        """
        Combine 3+ signals using majority voting with confidence weighting.
        
        VOTING LOGIC:
        - Count votes for each action (BUY/SELL/HOLD)
        - Winner = most votes
        - Confidence = (winner_votes / total_votes) × avg_confidence
        - Bonus: +5% if majority (>50%), +10% if unanimous
        
        Parameters
        ----------
        signals : list of dict
            List of signal dictionaries
        
        Returns
        -------
        dict : Aggregated signal
        """
        if len(signals) == 0:
            return {
                'action': 'HOLD',
                'confidence': 0,
                'reasoning': 'No signals provided',
                'sources': [],
                'agreement': 'none'
            }
        
        if len(signals) == 1:
            return signals[0]
        
        if len(signals) == 2:
            return self.combine_two(signals[0], signals[1])
        
        # ── Vote Counting ──────────────────────────────────────
        buy_votes = []
        sell_votes = []
        hold_votes = []
        
        for sig in signals:
            action = sig['action']
            source = sig.get('source', 'Unknown')
            conf = sig['confidence']
            
            if action == 'BUY':
                buy_votes.append({'source': source, 'confidence': conf})
            elif action == 'SELL':
                sell_votes.append({'source': source, 'confidence': conf})
            else:
                hold_votes.append({'source': source, 'confidence': conf})
        
        total_votes = len(signals)
        buy_count = len(buy_votes)
        sell_count = len(sell_votes)
        hold_count = len(hold_votes)
        
        log.info(f"📊 Vote count: BUY={buy_count}, SELL={sell_count}, HOLD={hold_count}")
        
        # ── Determine Winner ───────────────────────────────────
        if buy_count > sell_count and buy_count > hold_count:
            winner = 'BUY'
            winner_votes = buy_votes
            winner_count = buy_count
        elif sell_count > buy_count and sell_count > hold_count:
            winner = 'SELL'
            winner_votes = sell_votes
            winner_count = sell_count
        elif hold_count > buy_count and hold_count > sell_count:
            winner = 'HOLD'
            winner_votes = hold_votes
            winner_count = hold_count
        else:
            # Tie - default to HOLD
            winner = 'HOLD'
            winner_votes = hold_votes
            winner_count = hold_count
        
        # ── Calculate Confidence ───────────────────────────────
        # Base: Average confidence of winning votes
        if winner_votes:
            avg_winner_conf = sum(v['confidence'] for v in winner_votes) / len(winner_votes)
        else:
            avg_winner_conf = 40
        
        # Vote strength: What % of votes went to winner
        vote_strength = (winner_count / total_votes) * 100
        
        # Combined confidence: Average of confidence and vote strength
        base_confidence = (avg_winner_conf + vote_strength) / 2
        
        # Bonus for agreement
        if winner_count == total_votes:
            # Unanimous
            final_confidence = min(95, base_confidence + 10)
            agreement = 'unanimous'
        elif winner_count > total_votes / 2:
            # Majority
            final_confidence = min(90, base_confidence + 5)
            agreement = 'majority'
        else:
            # Weak majority or tie
            final_confidence = base_confidence
            agreement = 'weak'
        
        # Build reasoning
        sources_list = [v['source'] for v in winner_votes]
        reasoning = f"{winner_count}/{total_votes} vote {winner}: {', '.join(sources_list)}"
        
        result = {
            'action': winner,
            'confidence': round(final_confidence, 2),
            'reasoning': reasoning,
            'sources': sources_list,
            'agreement': agreement,
            'vote_breakdown': {
                'BUY': buy_count,
                'SELL': sell_count,
                'HOLD': hold_count
            }
        }
        
        log.info(f"   🎯 Winner: {winner} @ {result['confidence']}% ({agreement})")
        
        # Store in history
        self.history.append({
            'timestamp': __import__('datetime').datetime.now(),
            'signals_count': len(signals),
            'result': result
        })
        
        return result
    
    def get_statistics(self):
        """
        Get aggregation statistics from history.
        
        Returns
        -------
        dict : Statistics about signal aggregation performance
        """
        if not self.history:
            return {}
        
        total = len(self.history)
        unanimous = sum(1 for h in self.history if h['result']['agreement'] == 'unanimous')
        majority = sum(1 for h in self.history if h['result']['agreement'] == 'majority')
        conflict = sum(1 for h in self.history if h['result']['agreement'] == 'conflict')
        
        buy_signals = sum(1 for h in self.history if h['result']['action'] == 'BUY')
        sell_signals = sum(1 for h in self.history if h['result']['action'] == 'SELL')
        hold_signals = sum(1 for h in self.history if h['result']['action'] == 'HOLD')
        
        avg_confidence = sum(h['result']['confidence'] for h in self.history) / total
        
        return {
            'total_aggregations': total,
            'unanimous_agreements': unanimous,
            'majority_agreements': majority,
            'conflicts': conflict,
            'buy_signals': buy_signals,
            'sell_signals': sell_signals,
            'hold_signals': hold_signals,
            'avg_confidence': round(avg_confidence, 2),
            'agreement_rate': round((unanimous + majority) / total * 100, 2)
        }


# ══════════════════════════════════════════════════════════════
# DEMO & TESTING
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    
    print("\n" + "="*60)
    print("SIGNAL AGGREGATOR DEMO")
    print("="*60)
    
    aggregator = SignalAggregator()
    
    # ── TEST 1: Two signals agree ──────────────────────────────
    print("\n" + "="*60)
    print("TEST 1: RSI + Momentum Both Agree (BUY)")
    print("="*60)
    
    rsi = {
        'action': 'BUY',
        'confidence': 75,
        'reasoning': 'RSI oversold (22)',
        'source': 'RSI'
    }
    
    momentum = {
        'action': 'BUY',
        'confidence': 80,
        'reasoning': 'Strong upward momentum',
        'source': 'Momentum'
    }
    
    result = aggregator.combine_two(rsi, momentum)
    print(f"\nResult: {result['action']} @ {result['confidence']}%")
    print(f"Reasoning: {result['reasoning']}")
    print(f"Agreement: {result['agreement']}")
    
    # ── TEST 2: Conflict ───────────────────────────────────────
    print("\n" + "="*60)
    print("TEST 2: RSI vs Momentum Conflict (BUY vs SELL)")
    print("="*60)
    
    rsi = {
        'action': 'BUY',
        'confidence': 70,
        'reasoning': 'RSI oversold',
        'source': 'RSI'
    }
    
    momentum = {
        'action': 'SELL',
        'confidence': 65,
        'reasoning': 'Downward momentum',
        'source': 'Momentum'
    }
    
    result = aggregator.combine_two(rsi, momentum)
    print(f"\nResult: {result['action']} @ {result['confidence']}%")
    print(f"Reasoning: {result['reasoning']}")
    print(f"Agreement: {result['agreement']}")
    
    # ── TEST 3: Three signals (RSI + Momentum + AI) ────────────
    print("\n" + "="*60)
    print("TEST 3: RSI + Momentum + AI (Majority BUY)")
    print("="*60)
    
    rsi = {
        'action': 'BUY',
        'confidence': 75,
        'reasoning': 'RSI oversold',
        'source': 'RSI'
    }
    
    momentum = {
        'action': 'BUY',
        'confidence': 70,
        'reasoning': 'Momentum positive',
        'source': 'Momentum'
    }
    
    ai = {
        'action': 'HOLD',
        'confidence': 50,
        'reasoning': 'Mixed sentiment',
        'source': 'AI'
    }
    
    result = aggregator.combine_three(rsi, momentum, ai)
    print(f"\nResult: {result['action']} @ {result['confidence']}%")
    print(f"Reasoning: {result['reasoning']}")
    print(f"Agreement: {result['agreement']}")
    print(f"Vote Breakdown: {result['vote_breakdown']}")
    
    # ── TEST 4: All three conflict ─────────────────────────────
    print("\n" + "="*60)
    print("TEST 4: Complete Disagreement (BUY vs SELL vs HOLD)")
    print("="*60)
    
    rsi = {
        'action': 'BUY',
        'confidence': 75,
        'reasoning': 'RSI oversold',
        'source': 'RSI'
    }
    
    momentum = {
        'action': 'SELL',
        'confidence': 70,
        'reasoning': 'Downward trend',
        'source': 'Momentum'
    }
    
    ai = {
        'action': 'HOLD',
        'confidence': 60,
        'reasoning': 'Uncertain outlook',
        'source': 'AI'
    }
    
    result = aggregator.combine_three(rsi, momentum, ai)
    print(f"\nResult: {result['action']} @ {result['confidence']}%")
    print(f"Reasoning: {result['reasoning']}")
    print(f"Vote Breakdown: {result['vote_breakdown']}")
    
    # ── Statistics ─────────────────────────────────────────────
    print("\n" + "="*60)
    print("AGGREGATION STATISTICS")
    print("="*60)
    
    stats = aggregator.get_statistics()
    for key, value in stats.items():
        print(f"{key}: {value}")
    
    print("\n✅ All tests complete!")
    print("\nUsage in your system:")
    print("  aggregator = SignalAggregator()")
    print("  result = aggregator.combine_three(rsi_signal, momentum_signal, ai_signal)")
    print("  if result['action'] == 'BUY' and result['confidence'] > 70:")
    print("      # Execute trade")