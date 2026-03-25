"""
Signal Aggregator - Combines Multiple Trading Signals
=====================================================

Resolves conflicts between RSI, Momentum, AI, and other signal sources
with intelligent conflict resolution and confidence scoring.

Author: Mehdi
"""

from logger import get_logger

log = get_logger('system.signal_aggregator')


class SignalAggregator:
    """
    Combines multiple trading signals with intelligent conflict resolution.
    
    CONFIDENCE SCALE: All inputs and outputs use 0.0–1.0 floats.
    Strategies (RSI, Momentum) return 0.0–1.0.
    If a signal accidentally uses 0–100, _normalize() corrects it.

    SUPPORTED STRATEGIES:
    - RSI (Relative Strength Index)
    - Momentum (Price momentum)
    - AI (TradingAgents sentiment/fundamental analysis)
    - Custom strategies (any that return standard signal format)
    
    CONFLICT RESOLUTION LOGIC:
    1. All agree (BUY/BUY/BUY) → High confidence (+0.10 bonus)
    2. Majority agree (2/3 BUY) → Medium confidence (+0.05 bonus)
    3. Split decision (1 BUY, 1 SELL, 1 HOLD) → HOLD
    4. Conflict (BUY vs SELL with no HOLD) → HOLD (wait for clarity)
    5. One strong signal, others neutral → Use strong signal at 80%
    """
    
    def __init__(self):
        self.history = []
        log.info("✅ SignalAggregator initialized")

    # ── Internal helpers ──────────────────────────────────────────

    @staticmethod
    def _normalize(confidence):
        """
        Normalize confidence to 0.0–1.0 regardless of input scale.

        Strategies should return 0.0–1.0, but this guards against any
        signal that accidentally uses 0–100 integers.
        """
        try:
            c = float(confidence)
            if c > 1.0:
                c = c / 100.0   # 75 → 0.75
            return round(max(0.0, min(1.0, c)), 4)
        except (TypeError, ValueError):
            return 0.0

    def combine_two(self, signal1, signal2):
        """
        Combine two signals (e.g., RSI + Momentum).
        
        Parameters
        ----------
        signal1, signal2 : dict
            {'action': 'BUY'|'SELL'|'HOLD', 'confidence': 0.0-1.0,
             'reasoning': str, 'source': str}
        
        Returns
        -------
        dict : Combined signal. confidence is always 0.0–1.0.
        """
        action1 = signal1['action']
        action2 = signal2['action']
        conf1   = self._normalize(signal1['confidence'])
        conf2   = self._normalize(signal2['confidence'])
        
        source1 = signal1.get('source', signal1.get('strategy', 'Source1'))
        source2 = signal2.get('source', signal2.get('strategy', 'Source2'))
        
        log.info(f"📊 Combining: {source1}={action1}@{conf1:.0%}, {source2}={action2}@{conf2:.0%}")
        
        # ── CASE 1: Both Agree ────────────────────────────────
        if action1 == action2 and action1 != 'HOLD':
            avg_confidence = (conf1 + conf2) / 2
            boosted = min(0.95, avg_confidence + 0.10)  # +10% bonus, cap at 95%
            
            result = {
                'action':     action1,
                'confidence': round(boosted, 4),
                'reasoning':  f"✅ {source1} + {source2} both signal {action1}",
                'sources':    [source1, source2],
                'agreement':  'full'
            }
            log.info(f"   ✅ Agreement: {action1} @ {result['confidence']:.0%}")
            return result
        
        # ── CASE 2: Conflict (BUY vs SELL) ────────────────────
        if (action1 == 'BUY' and action2 == 'SELL') or \
           (action1 == 'SELL' and action2 == 'BUY'):
            result = {
                'action':    'HOLD',
                'confidence': 0.30,
                'reasoning':  f"⚠️ CONFLICT: {source1} says {action1}, {source2} says {action2} — waiting",
                'sources':    [source1, source2],
                'agreement':  'conflict'
            }
            log.warning(f"   ⚠️ Conflict: {source1}={action1} vs {source2}={action2} → HOLD")
            return result
        
        # ── CASE 3: One HOLD ───────────────────────────────────
        if action1 == 'HOLD' and action2 != 'HOLD':
            reduced = round(conf2 * 0.80, 4)
            result = {
                'action':     action2,
                'confidence': reduced,
                'reasoning':  f"📉 {source2} signals {action2} ({source1} neutral)",
                'sources':    [source2],
                'agreement':  'partial'
            }
            log.info(f"   📉 {source1} neutral, using {source2}: {action2} @ {reduced:.0%}")
            return result
        
        if action2 == 'HOLD' and action1 != 'HOLD':
            reduced = round(conf1 * 0.80, 4)
            result = {
                'action':     action1,
                'confidence': reduced,
                'reasoning':  f"📉 {source1} signals {action1} ({source2} neutral)",
                'sources':    [source1],
                'agreement':  'partial'
            }
            log.info(f"   📉 {source2} neutral, using {source1}: {action1} @ {reduced:.0%}")
            return result

        # ── CASE 4: Both HOLD ──────────────────────────────────
        avg_conf = round((conf1 + conf2) / 2, 4)
        result = {
            'action':     'HOLD',
            'confidence': avg_conf,
            'reasoning':  f"⏸️ Both {source1} and {source2} say HOLD",
            'sources':    [source1, source2],
            'agreement':  'hold'
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
        All confidence values normalized to 0.0–1.0.
        """
        if len(signals) == 0:
            return {'action': 'HOLD', 'confidence': 0.0, 'reasoning': 'No signals provided',
                    'sources': [], 'agreement': 'none'}
        if len(signals) == 1:
            return signals[0]
        if len(signals) == 2:
            return self.combine_two(signals[0], signals[1])

        # ── Vote Counting ──────────────────────────────────────
        buy_votes  = []
        sell_votes = []
        hold_votes = []

        for sig in signals:
            action = sig['action']
            source = sig.get('source', sig.get('strategy', 'Unknown'))
            conf   = self._normalize(sig['confidence'])

            if action == 'BUY':
                buy_votes.append({'source': source, 'confidence': conf})
            elif action == 'SELL':
                sell_votes.append({'source': source, 'confidence': conf})
            else:
                hold_votes.append({'source': source, 'confidence': conf})

        total_votes = len(signals)
        buy_count   = len(buy_votes)
        sell_count  = len(sell_votes)
        hold_count  = len(hold_votes)

        log.info(f"📊 Vote count: BUY={buy_count}, SELL={sell_count}, HOLD={hold_count}")

        # ── Determine Winner ───────────────────────────────────
        if buy_count > sell_count and buy_count > hold_count:
            winner, winner_votes, winner_count = 'BUY',  buy_votes,  buy_count
        elif sell_count > buy_count and sell_count > hold_count:
            winner, winner_votes, winner_count = 'SELL', sell_votes, sell_count
        elif hold_count > buy_count and hold_count > sell_count:
            winner, winner_votes, winner_count = 'HOLD', hold_votes, hold_count
        else:
            winner, winner_votes, winner_count = 'HOLD', hold_votes, hold_count  # tie → HOLD

        # ── Calculate Confidence (all on 0.0–1.0 scale) ───────
        if winner_votes:
            avg_winner_conf = sum(v['confidence'] for v in winner_votes) / len(winner_votes)
        else:
            avg_winner_conf = 0.40

        # Vote strength as a 0.0–1.0 fraction
        vote_strength = winner_count / total_votes   # e.g. 2/3 = 0.667

        # Blend signal quality and voting agreement
        base_confidence = (avg_winner_conf + vote_strength) / 2

        if winner_count == total_votes:
            final_confidence = min(0.95, base_confidence + 0.10)  # unanimous bonus
            agreement = 'unanimous'
        elif winner_count > total_votes / 2:
            final_confidence = min(0.90, base_confidence + 0.05)  # majority bonus
            agreement = 'majority'
        else:
            final_confidence = base_confidence
            agreement = 'weak'

        sources_list = [v['source'] for v in winner_votes]
        reasoning    = f"{winner_count}/{total_votes} vote {winner}: {', '.join(sources_list)}"

        result = {
            'action':         winner,
            'confidence':     round(final_confidence, 4),
            'reasoning':      reasoning,
            'sources':        sources_list,
            'agreement':      agreement,
            'vote_breakdown': {'BUY': buy_count, 'SELL': sell_count, 'HOLD': hold_count}
        }

        log.info(f"   🎯 Winner: {winner} @ {result['confidence']:.0%} ({agreement})")

        self.history.append({
            'timestamp':     __import__('datetime').datetime.now(),
            'signals_count': len(signals),
            'result':        result
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