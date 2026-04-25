"""Signal generation module for onchain sniper functionality.

This module generates trading signals based on blockchain events and
integrates with existing quantitative trading strategies.
"""

import logging
import time
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

from .database import (
    OnchainEvent, EventType, Signal, SignalType, Chain,
    get_onchain_database
)
from bot.config_web3 import get_web3_config
from quant.backtest.strategies.base_strategies import (
    BaseStrategy, create_strategy,
    MovingAverageCrossover, BollingerBandsStrategy,
    RSIStrategy, MACDStrategy, CombinedStrategy
)

logger = logging.getLogger(__name__)


class EventScorer:
    """Scores blockchain events based on various factors."""

    def __init__(self, config):
        self.config = config
        self.scoring_rules = self._load_scoring_rules()

    def _load_scoring_rules(self) -> Dict[str, Dict[str, Any]]:
        """Load scoring rules for different event types."""
        return {
            EventType.TOKEN_CREATED: {
                'base_score': 80,
                'amount_multiplier': 0.1,  # per ETH in creation cost
                'time_decay_hours': 24,  # score decays over 24 hours
                'max_score': 100,
            },
            EventType.LARGE_TRANSFER: {
                'base_score': 60,
                'amount_multiplier': 0.5,  # per 10 ETH transferred
                'threshold_eth': 10.0,
                'max_score': 90,
            },
            EventType.LIQUIDITY_ADDED: {
                'base_score': 70,
                'amount_multiplier': 0.2,  # per 10 ETH liquidity
                'threshold_eth': 5.0,
                'max_score': 95,
            },
            EventType.LIQUIDITY_REMOVED: {
                'base_score': 40,
                'amount_multiplier': 0.3,  # per 10 ETH removed
                'threshold_eth': 5.0,
                'max_score': 80,
            },
            EventType.CONTRACT_INTERACTION: {
                'base_score': 30,
                'amount_multiplier': 0.1,
                'max_score': 60,
            },
            EventType.VOLUME_SURGE: {
                'base_score': 50,
                'volume_multiplier': 0.01,  # per 100% volume increase
                'max_score': 85,
            },
        }

    def score_event(self, event: OnchainEvent) -> float:
        """Score a blockchain event based on its type and characteristics."""
        event_type = event.event_type

        if event_type not in self.scoring_rules:
            logger.debug(f"No scoring rules for event type: {event_type}")
            return 0.0

        rules = self.scoring_rules[event_type]
        score = rules['base_score']

        # Apply amount-based scoring
        if event.amount and 'amount_multiplier' in rules:
            amount_eth = event.amount
            if event_type == EventType.LARGE_TRANSFER:
                # Score based on amount above threshold
                threshold = rules.get('threshold_eth', 0)
                if amount_eth > threshold:
                    excess = amount_eth - threshold
                    score += excess / 10.0 * rules['amount_multiplier'] * 100
            else:
                score += amount_eth * rules['amount_multiplier'] * 10

        # Apply time decay for new tokens
        if event_type == EventType.TOKEN_CREATED:
            hours_old = (datetime.utcnow() - event.detected_at).total_seconds() / 3600
            decay_hours = rules.get('time_decay_hours', 24)
            if decay_hours > 0:
                decay_factor = max(0, 1 - (hours_old / decay_hours))
                score *= decay_factor

        # Cap the score
        max_score = rules.get('max_score', 100)
        score = min(max_score, max(0, score))

        logger.debug(f"Scored event {event.id} ({event_type}): {score:.1f}")
        return score


class RiskAssessor:
    """Assesses risks associated with tokens and trading opportunities."""

    def __init__(self, config):
        self.config = config
        self.blacklist = set()
        self._load_blacklist()

    def _load_blacklist(self):
        """Load blacklisted addresses from config."""
        try:
            web3_config = get_web3_config()
            # This would load from database or config file
            # For now, use empty set
            self.blacklist = set()
        except Exception as e:
            logger.error(f"Failed to load blacklist: {e}")
            self.blacklist = set()

    def assess_token_risk(self, token_address: str, event_data: Dict[str, Any]) -> Tuple[float, List[str]]:
        """Assess risk level of a token (0.0-1.0, higher is riskier)."""
        risk_score = 0.0
        risk_factors = []

        # Check blacklist
        if token_address.lower() in self.blacklist:
            risk_score = 1.0
            risk_factors.append("Token is blacklisted")
            return risk_score, risk_factors

        # Check if it's a new token (higher risk)
        event_type = event_data.get('event_type')
        if event_type == EventType.TOKEN_CREATED:
            risk_score += 0.3
            risk_factors.append("Newly created token")

        # Check liquidity (if available)
        liquidity_eth = event_data.get('liquidity_eth', 0)
        if liquidity_eth < self.config.min_liquidity_eth:
            risk_score += 0.4
            risk_factors.append(f"Low liquidity ({liquidity_eth:.1f} ETH)")

        # Check transaction amount (very large transfers might be suspicious)
        amount_eth = event_data.get('amount', 0)
        if amount_eth > 1000:  # Very large amount
            risk_score += 0.2
            risk_factors.append("Very large transaction")

        # Cap risk score
        risk_score = min(1.0, risk_score)

        return risk_score, risk_factors

    def calculate_position_size(self, score: float, risk_score: float, available_capital: float) -> float:
        """Calculate appropriate position size based on score and risk."""
        if risk_score >= 0.8:  # Too risky
            return 0.0

        # Base allocation based on score (0-100 maps to 0-10% of capital)
        base_allocation = (score / 100.0) * 0.1

        # Reduce allocation based on risk
        risk_adjustment = 1.0 - risk_score
        adjusted_allocation = base_allocation * risk_adjustment

        # Apply config limits
        max_trade = self.config.max_trade_eth
        position_size = min(available_capital * adjusted_allocation, max_trade)

        # Ensure minimum trade size
        if position_size < self.config.min_trade_eth:
            return 0.0

        return position_size


class TechnicalAnalyzer:
    """Integrates with existing quantitative strategies for technical analysis."""

    def __init__(self):
        self.strategies = self._initialize_strategies()

    def _initialize_strategies(self) -> Dict[str, BaseStrategy]:
        """Initialize technical analysis strategies."""
        return {
            'ma_crossover': MovingAverageCrossover(fast_period=5, slow_period=20),
            'bollinger_bands': BollingerBandsStrategy(period=20, std_dev=2.0),
            'rsi': RSIStrategy(period=14, overbought=70, oversold=30),
            'macd': MACDStrategy(fast_period=12, slow_period=26, signal_period=9),
            'combined': CombinedStrategy(ma_fast=5, ma_slow=20, rsi_period=14),
        }

    def analyze_with_strategies(self, price_data: pd.DataFrame) -> Dict[str, Any]:
        """Analyze price data using all available strategies."""
        if price_data.empty or len(price_data) < 20:
            return {'buy_signals': 0, 'sell_signals': 0, 'consensus': 'hold'}

        results = {}
        buy_signals = 0
        sell_signals = 0

        for name, strategy in self.strategies.items():
            try:
                signals = strategy(price_data)
                latest = signals.iloc[-1]

                if latest.get('buy', False):
                    buy_signals += 1
                elif latest.get('sell', False):
                    sell_signals += 1

                results[name] = {
                    'buy': bool(latest.get('buy', False)),
                    'sell': bool(latest.get('sell', False)),
                    'hold': bool(latest.get('hold', True)),
                }
            except Exception as e:
                logger.warning(f"Strategy {name} analysis failed: {e}")
                results[name] = {'buy': False, 'sell': False, 'hold': True}

        # Determine consensus
        total_strategies = len(self.strategies)
        if buy_signals > total_strategies * 0.6:  # >60% buy signals
            consensus = 'buy'
        elif sell_signals > total_strategies * 0.6:  # >60% sell signals
            consensus = 'sell'
        else:
            consensus = 'hold'

        results['summary'] = {
            'buy_signals': buy_signals,
            'sell_signals': sell_signals,
            'total_strategies': total_strategies,
            'consensus': consensus,
        }

        return results

    def get_technical_signal(self, price_data: pd.DataFrame) -> Tuple[SignalType, float]:
        """Get technical trading signal and confidence."""
        analysis = self.analyze_with_strategies(price_data)
        summary = analysis.get('summary', {})

        consensus = summary.get('consensus', 'hold')
        buy_signals = summary.get('buy_signals', 0)
        total_strategies = summary.get('total_strategies', 1)

        if consensus == 'buy':
            signal_type = SignalType.BUY
            confidence = buy_signals / total_strategies
        elif consensus == 'sell':
            signal_type = SignalType.SELL
            confidence = summary.get('sell_signals', 0) / total_strategies
        else:
            signal_type = SignalType.HOLD
            confidence = 0.5  # Neutral confidence

        return signal_type, confidence


class OnchainSignalGenerator:
    """Main signal generator for onchain sniper functionality."""

    def __init__(self, web3_config=None):
        self.config = web3_config or get_web3_config()
        self.database = get_onchain_database()
        self.scorer = EventScorer(self.config)
        self.risk_assessor = RiskAssessor(self.config)
        self.technical_analyzer = TechnicalAnalyzer()

        logger.info("Onchain signal generator initialized")

    def process_pending_events(self, limit: int = 50) -> List[Signal]:
        """Process pending events and generate signals."""
        events = self.database.get_unprocessed_events(limit)
        signals = []

        for event in events:
            try:
                signal = self.generate_signal_from_event(event)
                if signal:
                    signals.append(signal)
                    # Mark event as processed
                    self._mark_event_processed(event.id, signal.id)
            except Exception as e:
                logger.error(f"Failed to generate signal for event {event.id}: {e}")
                # Mark event as processed even if failed to avoid infinite retry
                self._mark_event_processed(event.id, None)

        logger.info(f"Generated {len(signals)} signals from {len(events)} events")
        return signals

    def generate_signal_from_event(self, event: OnchainEvent) -> Optional[Signal]:
        """Generate trading signal from a single blockchain event."""
        # Extract event data
        event_data = self._extract_event_data(event)

        # Score the event
        score = self.scorer.score_event(event)

        # Assess token risk
        token_address = event.token_address or event.contract_address
        if not token_address:
            logger.warning(f"Event {event.id} has no token/contract address")
            return None

        risk_score, risk_factors = self.risk_assessor.assess_token_risk(
            token_address, event_data
        )

        # Skip if too risky
        if risk_score >= 0.8:
            logger.info(f"Skipping token {token_address}: too risky ({risk_factors})")
            return None

        # TODO: Get price data for technical analysis
        # For now, use event-based signal generation
        signal_type, confidence = self._generate_event_based_signal(event, score, risk_score)

        # Calculate position size (simplified)
        # In production, this would use available capital from wallet
        available_capital = self.config.max_trade_eth
        position_size = self.risk_assessor.calculate_position_size(
            score, risk_score, available_capital
        )

        if position_size <= 0:
            logger.debug(f"Position size too small for event {event.id}")
            return None

        # Create signal data
        signal_data = {
            'signal_type': signal_type,
            'chain': event.chain,
            'token_address': token_address,
            'token_symbol': event_data.get('token_symbol'),
            'token_name': event_data.get('token_name'),
            'base_token': self._get_base_token_for_chain(event.chain),
            'confidence_score': confidence,
            'risk_score': risk_score,
            'expected_return': self._estimate_expected_return(event, score, risk_score),
            'suggested_amount_eth': position_size,
            'suggested_price': event_data.get('price'),  # TODO: Get current price
            'stop_loss': self._calculate_stop_loss(event_data, risk_score),
            'take_profit': self._calculate_take_profit(event_data, score),
            'signal_data': {
                'event_id': event.id,
                'event_type': event.event_type,
                'event_score': score,
                'risk_factors': risk_factors,
                'amount_eth': event.amount,
            },
            'generated_at': datetime.utcnow(),
            'expires_at': datetime.utcnow() + timedelta(hours=1),  # Signals expire in 1 hour
            'processed': False,
        }

        # Save signal to database
        signal = self.database.add_signal(signal_data)
        if signal:
            logger.info(f"Generated {signal_type} signal for {token_address} "
                       f"(score: {score:.1f}, confidence: {confidence:.1f})")

        return signal

    def _extract_event_data(self, event: OnchainEvent) -> Dict[str, Any]:
        """Extract relevant data from event."""
        data = {
            'event_type': event.event_type,
            'amount': event.amount,
            'amount_usd': event.amount_usd,
            'chain': event.chain,
        }

        # Parse event-specific data from JSON
        if event.event_data:
            try:
                import json
                event_json = json.loads(event.event_data) if isinstance(event.event_data, str) else event.event_data
                data.update(event_json)
            except Exception as e:
                logger.debug(f"Failed to parse event data for event {event.id}: {e}")

        return data

    def _generate_event_based_signal(self, event: OnchainEvent, score: float, risk_score: float) -> Tuple[SignalType, float]:
        """Generate signal based on event type and scores."""
        event_type = event.event_type

        # Map event types to signal types
        if event_type == EventType.TOKEN_CREATED:
            if score > 70 and risk_score < 0.5:
                signal_type = SignalType.BUY
                confidence = min(0.8, score / 100.0)
            else:
                signal_type = SignalType.HOLD
                confidence = 0.5

        elif event_type == EventType.LARGE_TRANSFER:
            # Large transfer to exchange might be selling pressure
            # Large transfer from exchange might be accumulation
            # For now, default to cautious approach
            if score > 60 and event.amount and event.amount > 50:
                signal_type = SignalType.BUY if self._is_accumulation(event) else SignalType.SELL
                confidence = min(0.7, score / 100.0)
            else:
                signal_type = SignalType.HOLD
                confidence = 0.5

        elif event_type == EventType.LIQUIDITY_ADDED:
            signal_type = SignalType.BUY
            confidence = min(0.75, score / 100.0)

        elif event_type == EventType.LIQUIDITY_REMOVED:
            signal_type = SignalType.SELL
            confidence = min(0.65, score / 100.0)

        else:
            signal_type = SignalType.HOLD
            confidence = 0.5

        # Adjust confidence based on risk
        confidence *= (1.0 - risk_score * 0.5)

        return signal_type, confidence

    def _is_accumulation(self, event: OnchainEvent) -> bool:
        """Check if a large transfer indicates accumulation (buying) or distribution (selling)."""
        # This is simplified - in production, you would check if the destination
        # is a known exchange address (distribution) or private wallet (accumulation)
        # For now, assume transfers to contracts might be selling to DEX
        if event.to_address and event.to_address.lower().startswith('0x'):
            # Check if it looks like a contract address (has code)
            # This would require Web3 connection
            return False
        return True  # Assume accumulation

    def _get_base_token_for_chain(self, chain: Chain) -> str:
        """Get base token address for a chain (WETH, WBNB, etc.)."""
        base_tokens = {
            Chain.ETHEREUM: "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",  # WETH
            Chain.BSC: "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",  # WBNB
            Chain.ARBITRUM: "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",  # WETH
            Chain.POLYGON: "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",  # WMATIC
            Chain.AVALANCHE: "0xB31f66AA3C1e785363F0875A1B74E27b85FD66c7",  # WAVAX
        }
        return base_tokens.get(chain, "")

    def _estimate_expected_return(self, event: OnchainEvent, score: float, risk_score: float) -> float:
        """Estimate expected return percentage."""
        # Base expected return based on score
        base_return = (score / 100.0) * 50  # Up to 50% return

        # Adjust for risk
        risk_adjustment = 1.0 - risk_score
        adjusted_return = base_return * risk_adjustment

        # Add event-type specific adjustments
        if event.event_type == EventType.TOKEN_CREATED:
            adjusted_return *= 1.5  # New tokens can have higher volatility
        elif event.event_type == EventType.LIQUIDITY_ADDED:
            adjusted_return *= 1.2  # Liquidity addition is generally positive

        return min(100.0, max(0.0, adjusted_return))

    def _calculate_stop_loss(self, event_data: Dict[str, Any], risk_score: float) -> float:
        """Calculate stop loss price percentage."""
        # Base stop loss based on risk
        base_stop_loss = 0.10  # 10%

        # Adjust for risk (riskier tokens need tighter stops)
        risk_adjustment = 1.0 + risk_score
        stop_loss = base_stop_loss * risk_adjustment

        return min(0.20, stop_loss)  # Max 20% stop loss

    def _calculate_take_profit(self, event_data: Dict[str, Any], score: float) -> float:
        """Calculate take profit price percentage."""
        # Base take profit based on score
        base_take_profit = 0.30  # 30%

        # Adjust for score (higher score = higher target)
        score_adjustment = score / 100.0
        take_profit = base_take_profit * (1.0 + score_adjustment)

        return min(1.0, take_profit)  # Max 100% take profit

    def _mark_event_processed(self, event_id: int, signal_id: Optional[int]) -> None:
        """Mark an event as processed."""
        session = self.database.get_session()
        try:
            event = session.query(OnchainEvent).filter(OnchainEvent.id == event_id).first()
            if event:
                event.processed = True
                event.signal_id = signal_id
                session.commit()
                logger.debug(f"Marked event {event_id} as processed")
        except Exception as e:
            logger.error(f"Failed to mark event {event_id} as processed: {e}")
            session.rollback()
        finally:
            session.close()

    def get_stats(self) -> Dict[str, Any]:
        """Get signal generator statistics."""
        stats = self.database.get_stats()
        stats['generator'] = {
            'scoring_rules': len(self.scorer.scoring_rules),
            'strategies': len(self.technical_analyzer.strategies),
            'config': {
                'max_trade_eth': self.config.max_trade_eth,
                'min_liquidity_eth': self.config.min_liquidity_eth,
            }
        }
        return stats