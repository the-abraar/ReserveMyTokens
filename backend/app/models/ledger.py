from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Numeric, Enum
from sqlalchemy.orm import relationship
import enum
from datetime import datetime
from ..database import Base

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class TransactionStatus(str, enum.Enum):
    PENDING = "PENDING"
    COMMITTED = "COMMITTED"
    ROLLED_BACK = "ROLLED_BACK"

class LedgerTransaction(Base):
    __tablename__ = "ledger_transactions"
    
    id = Column(Integer, primary_key=True, index=True)
    description = Column(String)
    status = Column(Enum(TransactionStatus), default=TransactionStatus.PENDING)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    postings = relationship("LedgerPosting", back_populates="transaction")

class LedgerPosting(Base):
    __tablename__ = "ledger_postings"
    
    id = Column(Integer, primary_key=True, index=True)
    transaction_id = Column(Integer, ForeignKey("ledger_transactions.id"))
    account_id = Column(Integer, ForeignKey("users.id"))
    amount = Column(Numeric(precision=20, scale=4))
    currency = Column(String, default="TOKENS")
    created_at = Column(DateTime, default=datetime.utcnow)
    
    transaction = relationship("LedgerTransaction", back_populates="postings")
    account = relationship("User")

class UsageReceipt(Base):
    __tablename__ = "usage_receipts"
    
    id = Column(Integer, primary_key=True, index=True)
    transaction_id = Column(Integer, ForeignKey("ledger_transactions.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    service_id = Column(String)
    tokens_consumed = Column(Numeric(precision=20, scale=4))
    created_at = Column(DateTime, default=datetime.utcnow)
    
    transaction = relationship("LedgerTransaction")
    user = relationship("User")
