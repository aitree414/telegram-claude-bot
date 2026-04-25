"""Risk management module for onchain sniper functionality.

This module provides comprehensive risk management including position sizing,
stop loss/take profit calculation, trade validation, and exposure management.
"""

import logging
import time
from typing import Dict, Optional, Any, Tuple, List
from datetime import datetime, timedelta, date

from bot.config_web3 import get_web3_config
from .database import (
    Trade, TradeStatus, Signal, get_onchain_database,
    OnchainDatabase, Chain
)

logger = logging.getLogger(__name__)


class RiskManager:
    """Comprehensive risk manager for trade validation and risk control."""

    def __init__(self, config=None, database=None):
        """Initialize risk manager.

        Args:
            config: Web3Config instance, defaults to global config
            database: OnchainDatabase instance, defaults to global db
        """
        self.config = config or get_web3_config()
        self.database = database or get_onchain_database()

        # Track daily trade counts and exposure
        self._daily_trades: Dict[str, int] = {}
        self._daily_loss: Dict[str, float] = {}
        self._daily_date: Optional[date] = None
        self._position_cache: Dict[str, float] = {}

        logger.info("Risk manager initialized")

    # ==================== Signal Validation ====================

    def validate_trade(self, signal: Signal) -> Tuple[bool, str]:
        """Validate a trading signal before execution.

        Performs comprehensive checks:
        1. Signal expiration
        2. Blacklist check
        3. Risk score threshold
        4. Daily trade limits
        5. Position size validation
        6. Market conditions

        Args:
            signal: Trading signal to validate

        Returns:
            Tuple of (is_valid, reason)
        """
        # 1. Check signal expiration
        is_expired = self._check_signal_expired(signal)
        if is_expired:
            return False, "Signal has expired"

        # 2. Check token blacklist
        if signal.token_address:
            is_blacklisted = self.database.is_blacklisted(signal.token_address)
            if is_blacklisted:
                return False, "Token is blacklisted"

        # 3. Check risk score threshold
        if signal.risk_score >= 0.8:
            return False, f"Risk score too high: {signal.risk_score:.2f}"

        # 4. Check daily trade limits
        can_trade, reason = self._check_daily_limits()
        if not can_trade:
            return False, reason

        # 5. Check position size
        if signal.suggested_amount_eth:
            valid_amount, amount_reason = self._validate_position_size(
                signal.suggested_amount_eth, signal.chain
            )
            if not valid_amount:
                return False, amount_reason

        # 6. Check confidence threshold
        if signal.confidence_score < 0.3:
            return False, f"Confidence too low: {signal.confidence_score:.2f}"

        # All checks passed
        logger.info(
            f"Trade validation passed for signal {signal.id}: "
            f"{signal.signal_type} {signal.token_symbol or signal.token_address[:10]}..."
        )
        return True, "OK"

    def _check_signal_expired(self, signal: Signal) -> bool:
        """Check if a signal has expired."""
        if signal.expires_at:
            return datetime.utcnow() > signal.expires_at
        return False

    def _check_daily_limits(self) -> Tuple[bool, str]:
        """Check daily trading limits.

        Returns:
            Tuple of (within_limits, reason)
        """
        today = date.today()

        # Reset daily counters if new day
        if self._daily_date != today:
            self._daily_trades = {}
            self._daily_loss = {}
            self._daily_date = today

        # Get daily trade count across all chains
        total_today = sum(self._daily_trades.values())

        if total_today >= self.config.max_daily_trades:
            return False, f"Daily trade limit reached ({self.config.max_daily_trades})"

        # Check daily loss limit
        total_loss_today = sum(self._daily_loss.values())
        if total_loss_today >= self.config.max_daily_loss_eth:
            return False, (
                f"Daily loss limit reached: "
                f"{total_loss_today:.3f}/{self.config.max_daily_loss_eth} ETH"
            )

        return True, "Daily limits OK"

    def _validate_position_size(
        self,
        amount_eth: float,
        chain: Optional[Chain] = None
    ) -> Tuple[bool, str]:
        """Validate position size against limits.

        Args:
            amount_eth: Proposed position size in ETH
            chain: Target chain

        Returns:
            Tuple of (is_valid, reason)
        """
        # Check minimum trade size
        if amount_eth < self.config.min_trade_eth:
            return False, (
                f"Position too small: {amount_eth:.4f} ETH "
                f"(min: {self.config.min_trade_eth} ETH)"
            )

        # Check maximum trade size
        if amount_eth > self.config.max_trade_eth:
            return False, (
                f"Position too large: {amount_eth:.4f} ETH "
                f"(max: {self.config.max_trade_eth} ETH)"
            )

        # Check total position across all chains
        total_position = self._get_total_position()
        if chain:
            chain_position = self._get_chain_position(chain)
            if amount_eth + chain_position > self.config.max_position_eth:
                return False, (
                    f"Chain position limit reached: "
                    f"{chain_position + amount_eth:.4f} ETH "
                    f"(max: {self.config.max_position_eth} ETH)"
                )

        return True, "Position size OK"

    def _get_total_position(self) -> float:
        """Get total open position across all chains."""
        session = self.database.get_session()
        try:
            active_trades = session.query(Trade).filter(
                Trade.status.in_([TradeStatus.PENDING, TradeStatus.EXECUTING, TradeStatus.PARTIAL])
            ).all()

            total = sum(t.amount_eth for t in active_trades if t.amount_eth)
            return total
        except Exception as e:
            logger.error(f"Failed to get total position: {e}")
            return 0.0
        finally:
            session.close()

    def _get_chain_position(self, chain: Chain) -> float:
        """Get total open position for a specific chain."""
        session = self.database.get_session()
        try:
            active_trades = session.query(Trade).filter(
                Trade.status.in_([TradeStatus.PENDING, TradeStatus.EXECUTING, TradeStatus.PARTIAL]),
                Trade.chain == chain
            ).all()

            total = sum(t.amount_eth for t in active_trades if t.amount_eth)
            return total
        except Exception as e:
            logger.error(f"Failed to get chain position for {chain}: {e}")
            return 0.0
        finally:
            session.close()

    # ==================== Position Sizing ====================

    def calculate_position_size(
        self,
        signal: Signal,
        available_capital: float = 0.0,
        method: str = 'kelly'
    ) -> float:
        """Calculate optimal position size for a signal.

        Supports multiple position sizing methods:
        - 'kelly': Kelly Criterion for optimal growth
        - 'fixed': Fixed percentage of capital
        - 'risk_parity': Risk parity based sizing

        Args:
            signal: Trading signal
            available_capital: Available capital in ETH
            method: Position sizing method

        Returns:
            Position size in ETH (0 if no trade)
        """
        if available_capital <= 0:
            available_capital = self.config.max_trade_eth * 5  # Default assumption

        if method == 'kelly':
            return self._kelly_position_size(signal, available_capital)
        elif method == 'risk_parity':
            return self._risk_parity_position_size(signal, available_capital)
        else:  # 'fixed'
            return self._fixed_position_size(signal, available_capital)

    def _kelly_position_size(self, signal: Signal, available_capital: float) -> float:
        """Calculate position size using Kelly Criterion.

        Kelly % = W - (1-W) / R
        where W = win probability, R = win/loss ratio
        """
        # Confidence score as win probability
        win_prob = signal.confidence_score

        # Expected return as win/loss ratio (capped)
        win_loss_ratio = max(1.0, min(5.0, (signal.expected_return or 10) / 5.0))

        # Kelly formula
        kelly_pct = win_prob - ((1 - win_prob) / win_loss_ratio)

        # Apply fractional Kelly (25%) for safety
        kelly_pct = max(0, kelly_pct * 0.25)

        # Calculate position size
        position_size = available_capital * kelly_pct

        # Apply hard limits
        position_size = min(position_size, self.config.max_trade_eth)
        position_size = max(0, position_size)

        # Skip if below minimum
        if position_size < self.config.min_trade_eth:
            return 0.0

        logger.debug(
            f"Kelly position: {position_size:.4f} ETH "
            f"(capital: {available_capital:.4f}, kelly%: {kelly_pct:.4f})"
        )
        return position_size

    def _fixed_position_size(self, signal: Signal, available_capital: float) -> float:
        """Calculate position size as fixed percentage of capital."""
        # Base percentage based on signal confidence
        fixed_pct = 0.02 + (signal.confidence_score * 0.08)  # 2-10% of capital
        position_size = available_capital * fixed_pct

        # Apply hard limits
        position_size = min(position_size, self.config.max_trade_eth)

        # Skip if below minimum
        if position_size < self.config.min_trade_eth:
            return 0.0

        return position_size

    def _risk_parity_position_size(self, signal: Signal, available_capital: float) -> float:
        """Calculate position size based on risk parity.

        Higher risk = smaller position, lower risk = larger position.
        """
        # Inverse relationship with risk score
        risk_factor = 1.0 - signal.risk_score

        # Base allocation: 5% of capital adjusted by risk factor
        base_pct = 0.05 * risk_factor

        # Adjust by confidence
        base_pct *= (0.5 + signal.confidence_score * 0.5)

        position_size = available_capital * base_pct

        # Apply hard limits
        position_size = min(position_size, self.config.max_trade_eth)
        position_size = max(0, position_size)

        if position_size < self.config.min_trade_eth:
            return 0.0

        return position_size

    # ==================== Stop Loss / Take Profit ====================

    def calculate_stop_loss(self, signal: Signal) -> float:
        """Calculate stop loss level for a signal.

        Returns:
            Stop loss price (percentage below entry)
        """
        if signal.stop_loss:
            return signal.stop_loss

        # Dynamic stop loss based on risk
        base_stop = self.config.stop_loss_pct  # 10% default

        # Tighter stop for riskier tokens
        risk_adjustment = 1.0 + signal.risk_score
        stop_loss = base_stop * risk_adjustment

        # Cap at max stop loss
        return min(stop_loss, 0.20)  # Max 20%

    def calculate_take_profit(self, signal: Signal) -> float:
        """Calculate take profit level for a signal.

        Returns:
            Take profit price (percentage above entry)
        """
        if signal.take_profit:
            return signal.take_profit

        # Dynamic take profit based on signal strength
        base_tp = self.config.take_profit_pct  # 30% default

        # Higher take profit for stronger signals
        confidence_adjustment = 0.5 + signal.confidence_score
        take_profit = base_tp * confidence_adjustment

        # Cap at max take profit
        return min(take_profit, 1.0)  # Max 100%

    # ==================== Market Condition Assessment ====================

    def assess_market_conditions(self, chain: Chain) -> Dict[str, Any]:
        """Assess current market conditions for trading.

        Args:
            chain: Chain to assess

        Returns:
            Market condition assessment
        """
        assessment = {
            'chain': chain.value if isinstance(chain, Chain) else str(chain),
            'is_tradable': True,
            'warnings': [],
            'conditions': {},
        }

        # Check cooldown period
        if not self._check_cooldown():
            assessment['is_tradable'] = False
            assessment['warnings'].append("In cooldown period")

        # Check daily loss limit
        total_loss = sum(self._daily_loss.values())
        if total_loss >= self.config.max_daily_loss_eth * 0.5:
            assessment['warnings'].append(
                f"Daily loss at {total_loss:.3f}/{self.config.max_daily_loss_eth} ETH"
            )

        # Check trade frequency
        total_trades = sum(self._daily_trades.values())
        if total_trades >= self.config.max_daily_trades * 0.7:
            assessment['warnings'].append(
                f"Trades today: {total_trades}/{self.config.max_daily_trades}"
            )

        return assessment

    def _check_cooldown(self) -> bool:
        """Check if system is in cooldown period."""
        session = self.database.get_session()
        try:
            # Get last trade execution time
            last_trade = session.query(Trade)\
                .filter(Trade.status == TradeStatus.COMPLETED)\
                .order_by(Trade.executed_at.desc())\
                .first()

            if last_trade and last_trade.executed_at:
                elapsed = (datetime.utcnow() - last_trade.executed_at).total_seconds()
                cooldown_seconds = self.config.cooldown_minutes * 60
                if elapsed < cooldown_seconds:
                    remaining = cooldown_seconds - elapsed
                    logger.debug(f"Cooldown active: {remaining:.0f}s remaining")
                    return False

            return True
        except Exception as e:
            logger.error(f"Failed to check cooldown: {e}")
            return True  # Allow trade on error
        finally:
            session.close()

    # ==================== PnL Monitoring ====================

    def update_trade_pnl(self, trade: Trade, current_price: float) -> Tuple[float, float]:
        """Update unrealized PnL for an active trade.

        Args:
            trade: Active trade
            current_price: Current market price

        Returns:
            Tuple of (pnl_eth, pnl_percent)
        """
        if not trade.entry_price or trade.entry_price == 0:
            return 0.0, 0.0

        price_change = (current_price - trade.entry_price) / trade.entry_price

        if trade.trade_type.value == 'sell':  # Short position
            pnl_percent = -price_change
        else:  # Long position
            pnl_percent = price_change

        pnl_eth = trade.amount_eth * pnl_percent

        return pnl_eth, pnl_percent

    def check_stop_loss_take_profit(
        self,
        trade: Trade,
        current_price: float
    ) -> Optional[str]:
        """Check if stop loss or take profit has been triggered.

        Args:
            trade: Active trade
            current_price: Current price

        Returns:
            'stop_loss', 'take_profit', or None
        """
        if not trade.entry_price or trade.entry_price == 0:
            return None

        price_change = (current_price - trade.entry_price) / trade.entry_price

        if trade.trade_type.value == 'sell':  # Short position
            price_change = -price_change

        # Check stop loss
        if trade.stop_loss and price_change <= -trade.stop_loss:
            logger.info(
                f"Stop loss triggered for trade {trade.id}: "
                f"{price_change*100:.1f}% <= -{trade.stop_loss*100:.1f}%"
            )
            return 'stop_loss'

        # Check take profit
        if trade.take_profit and price_change >= trade.take_profit:
            logger.info(
                f"Take profit triggered for trade {trade.id}: "
                f"{price_change*100:.1f}% >= {trade.take_profit*100:.1f}%"
            )
            return 'take_profit'

        return None

    # ==================== Risk Reporting ====================

    def get_risk_summary(self) -> Dict[str, Any]:
        """Get a summary of current risk state.

        Returns:
            Risk summary dictionary
        """
        total_position = self._get_total_position()
        session = self.database.get_session()
        try:
            active_trades = session.query(Trade).filter(
                Trade.status.in_([TradeStatus.PENDING, TradeStatus.EXECUTING])
            ).count()

            pending_orders = session.query(Trade).filter(
                Trade.status == TradeStatus.PENDING
            ).count()
        except Exception:
            active_trades = 0
            pending_orders = 0
        finally:
            session.close()

        today = date.today()
        if self._daily_date == today:
            daily_trades = sum(self._daily_trades.values())
            daily_loss = sum(self._daily_loss.values())
        else:
            daily_trades = 0
            daily_loss = 0.0

        return {
            'total_open_position_eth': total_position,
            'active_trades': active_trades,
            'pending_orders': pending_orders,
            'daily_trades': daily_trades,
            'daily_trades_max': self.config.max_daily_trades,
            'daily_loss_eth': daily_loss,
            'daily_loss_max_eth': self.config.max_daily_loss_eth,
            'max_trade_eth': self.config.max_trade_eth,
            'cooldown_minutes': self.config.cooldown_minutes,
        }