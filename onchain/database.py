"""Database models and operations for onchain sniper functionality.

This module defines the database schema and operations for storing blockchain
events, trade records, performance data, and configuration for the onchain
sniper system. It uses SQLAlchemy ORM for database interactions.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from enum import Enum

from sqlalchemy import create_engine, Column, Integer, String, Float, Text, Boolean, DateTime, JSON, ForeignKey, Enum as SQLEnum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, Session
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

# Create declarative base
Base = declarative_base()


# Enums for database fields
class EventType(str, Enum):
    """Types of blockchain events."""
    TOKEN_CREATED = "token_created"
    LARGE_TRANSFER = "large_transfer"
    LIQUIDITY_ADDED = "liquidity_added"
    LIQUIDITY_REMOVED = "liquidity_removed"
    CONTRACT_INTERACTION = "contract_interaction"
    PRICE_CHANGE = "price_change"
    VOLUME_SURGE = "volume_surge"
    OTHER = "other"


class SignalType(str, Enum):
    """Types of trading signals."""
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    ADJUST_POSITION = "adjust_position"


class TradeStatus(str, Enum):
    """Status of trades."""
    PENDING = "pending"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PARTIAL = "partial"


class Chain(str, Enum):
    """Supported blockchain chains."""
    ETHEREUM = "ethereum"
    BSC = "bsc"
    ARBITRUM = "arbitrum"
    POLYGON = "polygon"
    AVALANCHE = "avalanche"
    SEPOLIA = "sepolia"


# Database models
class OnchainEvent(Base):
    """Stores blockchain events detected by the monitor."""

    __tablename__ = "onchain_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_type = Column(SQLEnum(EventType), nullable=False, index=True)
    chain = Column(SQLEnum(Chain), nullable=False, index=True)
    block_number = Column(Integer, nullable=False, index=True)
    block_timestamp = Column(DateTime, nullable=False, index=True)
    transaction_hash = Column(String(66), nullable=False, index=True)  # 0x + 64 chars
    contract_address = Column(String(42), index=True)  # 0x + 40 chars
    from_address = Column(String(42), index=True)
    to_address = Column(String(42), index=True)
    token_address = Column(String(42), index=True)
    amount = Column(Float)  # Amount in native token (ETH, BNB, etc.)
    amount_usd = Column(Float)  # Estimated USD value
    event_data = Column(JSON)  # Raw event data as JSON
    detected_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    processed = Column(Boolean, default=False, index=True)
    signal_id = Column(Integer, ForeignKey("signals.id"), index=True)  # Associated signal

    # Relationships
    signal = relationship("Signal", back_populates="events")

    def __repr__(self):
        return f"<OnchainEvent(id={self.id}, event_type='{self.event_type}', chain='{self.chain}', tx='{self.transaction_hash[:10]}...')>"


class Signal(Base):
    """Stores trading signals generated from blockchain events."""

    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    signal_type = Column(SQLEnum(SignalType), nullable=False, index=True)
    chain = Column(SQLEnum(Chain), nullable=False, index=True)
    token_address = Column(String(42), nullable=False, index=True)
    token_symbol = Column(String(20))
    token_name = Column(String(100))
    base_token = Column(String(42))  # Usually WETH, WBNB, etc.
    confidence_score = Column(Float, nullable=False)  # 0.0 to 1.0
    risk_score = Column(Float, nullable=False)  # 0.0 to 1.0
    expected_return = Column(Float)  # Expected return percentage
    suggested_amount_eth = Column(Float)  # Suggested trade amount in ETH
    suggested_price = Column(Float)  # Suggested entry price
    stop_loss = Column(Float)  # Stop loss price
    take_profit = Column(Float)  # Take profit price
    signal_data = Column(JSON)  # Additional signal data
    generated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, index=True)
    processed = Column(Boolean, default=False, index=True)
    trade_id = Column(Integer, ForeignKey("trades.id"), index=True)  # Associated trade

    # Relationships
    events = relationship("OnchainEvent", back_populates="signal")
    trade = relationship("Trade", back_populates="signal")

    def __repr__(self):
        return f"<Signal(id={self.id}, type='{self.signal_type}', token='{self.token_address[:10]}...', confidence={self.confidence_score})>"


class Trade(Base):
    """Stores executed trades."""

    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chain = Column(SQLEnum(Chain), nullable=False, index=True)
    token_address = Column(String(42), nullable=False, index=True)
    token_symbol = Column(String(20))
    token_name = Column(String(100))
    trade_type = Column(SQLEnum(SignalType), nullable=False, index=True)  # BUY or SELL
    amount_eth = Column(Float, nullable=False)  # Amount in ETH (or chain native token)
    amount_token = Column(Float, nullable=False)  # Amount in token units
    entry_price = Column(Float, nullable=False)  # Entry price in ETH
    current_price = Column(Float)  # Current price (updated periodically)
    stop_loss = Column(Float)  # Stop loss price
    take_profit = Column(Float)  # Take profit price
    transaction_hash = Column(String(66), nullable=False, index=True)
    gas_used = Column(Integer)  # Gas used in wei
    gas_price_gwei = Column(Float)  # Gas price in Gwei
    transaction_cost_eth = Column(Float)  # Total transaction cost in ETH
    dex = Column(String(50))  # DEX used (Uniswap V2, PancakeSwap, etc.)
    status = Column(SQLEnum(TradeStatus), default=TradeStatus.PENDING, nullable=False, index=True)
    executed_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime)
    trade_data = Column(JSON)  # Additional trade data
    pnl_eth = Column(Float, default=0.0)  # Profit/Loss in ETH
    pnl_percent = Column(Float, default=0.0)  # Profit/Loss percentage
    notes = Column(Text)  # Additional notes

    # Relationships
    signal = relationship("Signal", back_populates="trade")

    def __repr__(self):
        return f"<Trade(id={self.id}, type='{self.trade_type}', token='{self.token_symbol}', amount={self.amount_eth} ETH, status='{self.status}')>"


class Performance(Base):
    """Stores performance metrics and statistics."""

    __tablename__ = "performance"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(DateTime, nullable=False, index=True)  # Date of the performance record
    period = Column(String(20), nullable=False, index=True)  # daily, weekly, monthly
    total_trades = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    losing_trades = Column(Integer, default=0)
    total_volume_eth = Column(Float, default=0.0)
    total_pnl_eth = Column(Float, default=0.0)
    total_pnl_percent = Column(Float, default=0.0)
    win_rate = Column(Float, default=0.0)
    avg_win_eth = Column(Float, default=0.0)
    avg_loss_eth = Column(Float, default=0.0)
    max_drawdown_eth = Column(Float, default=0.0)
    max_drawdown_percent = Column(Float, default=0.0)
    sharpe_ratio = Column(Float, default=0.0)
    sortino_ratio = Column(Float, default=0.0)
    profit_factor = Column(Float, default=0.0)
    best_trade_eth = Column(Float, default=0.0)
    worst_trade_eth = Column(Float, default=0.0)
    metrics_data = Column(JSON)  # Additional metrics

    def __repr__(self):
        return f"<Performance(id={self.id}, date='{self.date}', pnl={self.total_pnl_eth} ETH, win_rate={self.win_rate})>"


class MonitoringRule(Base):
    """Stores monitoring rules and configurations."""

    __tablename__ = "monitoring_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, index=True)
    chain = Column(SQLEnum(Chain), nullable=False, index=True)
    rule_type = Column(String(50), nullable=False)  # token_creation, large_transfer, etc.
    contract_address = Column(String(42), index=True)
    threshold_eth = Column(Float)  # Threshold in ETH
    threshold_usd = Column(Float)  # Threshold in USD
    parameters = Column(JSON)  # Rule-specific parameters
    enabled = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_triggered = Column(DateTime)

    def __repr__(self):
        return f"<MonitoringRule(id={self.id}, name='{self.name}', chain='{self.chain}', enabled={self.enabled})>"


class BlacklistEntry(Base):
    """Stores blacklisted addresses and contracts."""

    __tablename__ = "blacklist"

    id = Column(Integer, primary_key=True, autoincrement=True)
    address = Column(String(42), nullable=False, index=True, unique=True)
    category = Column(String(50), nullable=False, index=True)  # contract, token, wallet
    chain = Column(SQLEnum(Chain), index=True)
    reason = Column(Text)
    source = Column(String(100))  # manual, community, automated
    severity = Column(String(20), default="medium")  # low, medium, high, critical
    added_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    added_by = Column(String(100))
    expires_at = Column(DateTime, index=True)
    active = Column(Boolean, default=True, index=True)
    metadata_json = Column(JSON)  # Additional metadata

    def __repr__(self):
        return f"<BlacklistEntry(id={self.id}, address='{self.address[:10]}...', category='{self.category}')>"


class OrderStatus(str, Enum):
    """Status of orders."""
    PENDING = "pending"
    OPEN = "open"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    FAILED = "failed"


class OrderType(str, Enum):
    """Types of orders."""
    MARKET = "market"
    LIMIT = "limit"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    STOP_LIMIT = "stop_limit"


class Order(Base):
    """Stores order lifecycle information."""

    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    signal_id = Column(Integer, ForeignKey("signals.id"), index=True)
    trade_id = Column(Integer, ForeignKey("trades.id"), index=True)
    chain = Column(SQLEnum(Chain), nullable=False, index=True)
    token_address = Column(String(42), nullable=False, index=True)
    token_symbol = Column(String(20))
    order_type = Column(SQLEnum(OrderType), nullable=False, index=True)
    order_side = Column(SQLEnum(SignalType), nullable=False, index=True)  # BUY or SELL
    status = Column(SQLEnum(OrderStatus), default=OrderStatus.PENDING, nullable=False, index=True)
    amount_eth = Column(Float, nullable=False)
    filled_amount_eth = Column(Float, default=0.0)
    price = Column(Float)  # Limit price for limit orders
    stop_price = Column(Float)  # Trigger price for stop orders
    slippage_bps = Column(Integer, default=500)  # Allowed slippage in basis points
    dex = Column(String(50))  # DEX used
    transaction_hash = Column(String(66), index=True)
    gas_used = Column(Integer)
    gas_price_gwei = Column(Float)
    transaction_cost_eth = Column(Float)
    error_message = Column(Text)
    order_data = Column(JSON)  # Additional order data
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    executed_at = Column(DateTime)
    expires_at = Column(DateTime, index=True)

    def __repr__(self):
        return f"<Order(id={self.id}, type='{self.order_type}', side='{self.order_side}', status='{self.status}')>"


class ExecutionLog(Base):
    """Stores detailed execution logs for auditing and debugging."""

    __tablename__ = "execution_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_id = Column(Integer, ForeignKey("trades.id"), index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), index=True)
    signal_id = Column(Integer, ForeignKey("signals.id"), index=True)
    chain = Column(SQLEnum(Chain), index=True)
    action = Column(String(50), nullable=False, index=True)  # prepare, simulate, approve, swap, complete, fail
    status = Column(String(20), nullable=False)  # started, success, failed
    message = Column(Text)
    tx_hash = Column(String(66), index=True)
    gas_used = Column(Integer)
    gas_price_gwei = Column(Float)
    duration_ms = Column(Integer)  # Action duration in milliseconds
    error_type = Column(String(50))  # Category of error if failed
    error_details = Column(Text)  # Detailed error message
    log_data = Column(JSON)  # Additional context data
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    def __repr__(self):
        return f"<ExecutionLog(id={self.id}, action='{self.action}', status='{self.status}')>"


class OnchainDatabase:
    """Main database manager for onchain sniper functionality."""

    def __init__(self, db_path: str = "data/onchain/onchain.db"):
        """Initialize the database manager.

        Args:
            db_path: Path to SQLite database file.
        """
        self.db_path = db_path
        self.engine = create_engine(f"sqlite:///{db_path}", echo=False)
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)

        # Create tables
        self._create_tables()

        logger.info(f"Onchain database initialized at {db_path}")

    def _create_tables(self) -> None:
        """Create database tables if they don't exist."""
        try:
            Base.metadata.create_all(self.engine)
            logger.info("Database tables created/verified")
        except SQLAlchemyError as e:
            logger.error(f"Failed to create database tables: {e}")
            raise

    def get_session(self) -> Session:
        """Get a new database session."""
        return self.SessionLocal()

    # Event operations
    def add_event(self, event_data: Dict[str, Any]) -> Optional[OnchainEvent]:
        """Add a new blockchain event to the database."""
        session = self.get_session()
        try:
            event = OnchainEvent(**event_data)
            session.add(event)
            session.commit()
            session.refresh(event)
            logger.debug(f"Added event: {event}")
            return event
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"Failed to add event: {e}")
            return None
        finally:
            session.close()

    def get_unprocessed_events(self, limit: int = 100) -> List[OnchainEvent]:
        """Get unprocessed events."""
        session = self.get_session()
        try:
            events = session.query(OnchainEvent)\
                .filter(OnchainEvent.processed == False)\
                .order_by(OnchainEvent.detected_at)\
                .limit(limit)\
                .all()
            return events
        except SQLAlchemyError as e:
            logger.error(f"Failed to get unprocessed events: {e}")
            return []
        finally:
            session.close()

    # Signal operations
    def add_signal(self, signal_data: Dict[str, Any]) -> Optional[Signal]:
        """Add a new trading signal to the database."""
        session = self.get_session()
        try:
            signal = Signal(**signal_data)
            session.add(signal)
            session.commit()
            session.refresh(signal)
            logger.debug(f"Added signal: {signal}")
            return signal
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"Failed to add signal: {e}")
            return None
        finally:
            session.close()

    def get_pending_signals(self, limit: int = 50) -> List[Signal]:
        """Get pending signals (not yet processed)."""
        session = self.get_session()
        try:
            signals = session.query(Signal)\
                .filter(Signal.processed == False)\
                .order_by(Signal.confidence_score.desc())\
                .limit(limit)\
                .all()
            return signals
        except SQLAlchemyError as e:
            logger.error(f"Failed to get pending signals: {e}")
            return []
        finally:
            session.close()

    # Trade operations
    def add_trade(self, trade_data: Dict[str, Any]) -> Optional[Trade]:
        """Add a new trade to the database."""
        session = self.get_session()
        try:
            trade = Trade(**trade_data)
            session.add(trade)
            session.commit()
            session.refresh(trade)
            logger.debug(f"Added trade: {trade}")
            return trade
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"Failed to add trade: {e}")
            return None
        finally:
            session.close()

    def update_trade_status(self, trade_id: int, status: TradeStatus, **kwargs) -> bool:
        """Update trade status and other fields."""
        session = self.get_session()
        try:
            trade = session.query(Trade).filter(Trade.id == trade_id).first()
            if not trade:
                logger.warning(f"Trade {trade_id} not found")
                return False

            trade.status = status
            for key, value in kwargs.items():
                if hasattr(trade, key):
                    setattr(trade, key, value)

            if status == TradeStatus.COMPLETED and not trade.completed_at:
                trade.completed_at = datetime.utcnow()

            session.commit()
            logger.debug(f"Updated trade {trade_id} status to {status}")
            return True
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"Failed to update trade {trade_id}: {e}")
            return False
        finally:
            session.close()

    # Performance operations
    def update_performance(self, period: str = "daily") -> Optional[Performance]:
        """Update performance metrics for the given period."""
        session = self.get_session()
        try:
            # Calculate performance metrics (simplified)
            # In practice, this would involve complex calculations
            today = datetime.utcnow().date()
            period_start = datetime.combine(today, datetime.min.time())

            # Check if performance record already exists for today
            perf = session.query(Performance)\
                .filter(Performance.period == period)\
                .filter(Performance.date >= period_start)\
                .first()

            if not perf:
                perf = Performance(date=datetime.utcnow(), period=period)

            # Calculate metrics (placeholder - implement actual calculations)
            perf.total_trades = session.query(Trade).count()
            perf.winning_trades = session.query(Trade).filter(Trade.pnl_eth > 0).count()
            perf.losing_trades = session.query(Trade).filter(Trade.pnl_eth < 0).count()

            if perf.total_trades > 0:
                perf.win_rate = perf.winning_trades / perf.total_trades

            session.add(perf)
            session.commit()
            session.refresh(perf)
            return perf
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"Failed to update performance: {e}")
            return None
        finally:
            session.close()

    # Blacklist operations
    def add_to_blacklist(self, address: str, category: str, **kwargs) -> Optional[BlacklistEntry]:
        """Add an address to the blacklist."""
        session = self.get_session()
        try:
            # Check if already blacklisted
            existing = session.query(BlacklistEntry)\
                .filter(BlacklistEntry.address == address.lower())\
                .filter(BlacklistEntry.active == True)\
                .first()

            if existing:
                logger.debug(f"Address {address} already in blacklist")
                return existing

            entry = BlacklistEntry(address=address.lower(), category=category, **kwargs)
            session.add(entry)
            session.commit()
            session.refresh(entry)
            logger.info(f"Added {address} to blacklist (category: {category})")
            return entry
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"Failed to add to blacklist: {e}")
            return None
        finally:
            session.close()

    def is_blacklisted(self, address: str) -> bool:
        """Check if an address is blacklisted."""
        session = self.get_session()
        try:
            count = session.query(BlacklistEntry)\
                .filter(BlacklistEntry.address == address.lower())\
                .filter(BlacklistEntry.active == True)\
                .count()
            return count > 0
        except SQLAlchemyError as e:
            logger.error(f"Failed to check blacklist: {e}")
            return False
        finally:
            session.close()

    # Monitoring rule operations
    def add_monitoring_rule(self, rule_data: Dict[str, Any]) -> Optional[MonitoringRule]:
        """Add a new monitoring rule."""
        session = self.get_session()
        try:
            rule = MonitoringRule(**rule_data)
            session.add(rule)
            session.commit()
            session.refresh(rule)
            logger.info(f"Added monitoring rule: {rule.name}")
            return rule
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"Failed to add monitoring rule: {e}")
            return None
        finally:
            session.close()

    def get_active_rules(self, chain: Optional[str] = None) -> List[MonitoringRule]:
        """Get active monitoring rules, optionally filtered by chain."""
        session = self.get_session()
        try:
            query = session.query(MonitoringRule).filter(MonitoringRule.enabled == True)
            if chain:
                query = query.filter(MonitoringRule.chain == chain)
            return query.order_by(MonitoringRule.created_at).all()
        except SQLAlchemyError as e:
            logger.error(f"Failed to get active rules: {e}")
            return []
        finally:
            session.close()

    # Order operations
    def add_order(self, order_data: Dict[str, Any]) -> Optional[Order]:
        """Add a new order to the database."""
        session = self.get_session()
        try:
            order = Order(**order_data)
            session.add(order)
            session.commit()
            session.refresh(order)
            logger.debug(f"Added order: {order}")
            return order
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"Failed to add order: {e}")
            return None
        finally:
            session.close()

    def update_order_status(self, order_id: int, status: OrderStatus, **kwargs) -> bool:
        """Update order status and other fields."""
        session = self.get_session()
        try:
            order = session.query(Order).filter(Order.id == order_id).first()
            if not order:
                logger.warning(f"Order {order_id} not found")
                return False

            order.status = status
            for key, value in kwargs.items():
                if hasattr(order, key):
                    setattr(order, key, value)

            if status in (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.FAILED) and not order.executed_at:
                order.executed_at = datetime.utcnow()

            session.commit()
            logger.debug(f"Updated order {order_id} status to {status}")
            return True
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"Failed to update order {order_id}: {e}")
            return False
        finally:
            session.close()

    def get_pending_orders(self, limit: int = 20) -> List[Order]:
        """Get pending orders for execution."""
        session = self.get_session()
        try:
            orders = session.query(Order)\
                .filter(Order.status.in_([OrderStatus.PENDING, OrderStatus.OPEN]))\
                .order_by(Order.created_at)\
                .limit(limit)\
                .all()
            return orders
        except SQLAlchemyError as e:
            logger.error(f"Failed to get pending orders: {e}")
            return []
        finally:
            session.close()

    # Execution log operations
    def add_execution_log(self, log_data: Dict[str, Any]) -> Optional[ExecutionLog]:
        """Add a new execution log entry."""
        session = self.get_session()
        try:
            log_entry = ExecutionLog(**log_data)
            session.add(log_entry)
            session.commit()
            session.refresh(log_entry)
            logger.debug(f"Added execution log: {log_entry}")
            return log_entry
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"Failed to add execution log: {e}")
            return None
        finally:
            session.close()

    def get_execution_logs(
        self,
        trade_id: Optional[int] = None,
        limit: int = 50
    ) -> List[ExecutionLog]:
        """Get execution logs, optionally filtered by trade."""
        session = self.get_session()
        try:
            query = session.query(ExecutionLog)
            if trade_id is not None:
                query = query.filter(ExecutionLog.trade_id == trade_id)
            return query.order_by(ExecutionLog.created_at.desc()).limit(limit).all()
        except SQLAlchemyError as e:
            logger.error(f"Failed to get execution logs: {e}")
            return []
        finally:
            session.close()

    # Utility methods
    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics."""
        session = self.get_session()
        try:
            stats = {
                "events": session.query(OnchainEvent).count(),
                "signals": session.query(Signal).count(),
                "trades": session.query(Trade).count(),
                "orders": session.query(Order).count(),
                "execution_logs": session.query(ExecutionLog).count(),
                "pending_signals": session.query(Signal).filter(Signal.processed == False).count(),
                "active_trades": session.query(Trade).filter(Trade.status.in_([TradeStatus.PENDING, TradeStatus.EXECUTING])).count(),
                "pending_orders": session.query(Order).filter(Order.status.in_([OrderStatus.PENDING, OrderStatus.OPEN])).count(),
                "blacklist_entries": session.query(BlacklistEntry).filter(BlacklistEntry.active == True).count(),
                "monitoring_rules": session.query(MonitoringRule).filter(MonitoringRule.enabled == True).count(),
            }
            return stats
        except SQLAlchemyError as e:
            logger.error(f"Failed to get stats: {e}")
            return {}
        finally:
            session.close()

    def cleanup_old_data(self, days_to_keep: int = 30) -> int:
        """Clean up old data from the database.

        Args:
            days_to_keep: Number of days of data to keep.

        Returns:
            Number of records deleted.
        """
        session = self.get_session()
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days_to_keep)

            # Delete old processed events
            event_count = session.query(OnchainEvent)\
                .filter(OnchainEvent.processed == True)\
                .filter(OnchainEvent.detected_at < cutoff_date)\
                .delete(synchronize_session=False)

            # Delete old signals (that have been processed and have no associated trades)
            signal_count = session.query(Signal)\
                .filter(Signal.processed == True)\
                .filter(Signal.generated_at < cutoff_date)\
                .filter(Signal.trade_id == None)\
                .delete(synchronize_session=False)

            session.commit()
            logger.info(f"Cleaned up {event_count} events and {signal_count} signals older than {days_to_keep} days")
            return event_count + signal_count
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"Failed to cleanup old data: {e}")
            return 0
        finally:
            session.close()


# Global database instance
_db_instance: Optional[OnchainDatabase] = None

def get_onchain_database(db_path: str = "data/onchain/onchain.db") -> OnchainDatabase:
    """Get the global onchain database instance."""
    global _db_instance
    if _db_instance is None:
        _db_instance = OnchainDatabase(db_path)
    return _db_instance