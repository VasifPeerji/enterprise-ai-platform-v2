"""
📁 File: src/database/models/conversation.py
Layer: Database (Infrastructure)
Purpose: Conversation and Message models for chat history
Depends on: src/database/base, src/database/models/user
Used by: Chat endpoints, memory system

Conversation: A chat session between user and AI
Message: Individual messages within a conversation
"""

from enum import Enum
from typing import Optional
from uuid import UUID

from sqlmodel import Field, SQLModel

from src.database.base import BaseDBModel


class MessageRole(str, Enum):
    """Role of message sender."""
    
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ConversationStatus(str, Enum):
    """Status of conversation."""
    
    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"


class ConversationBase(SQLModel):
    """Base fields for Conversation."""
    
    tenant_id: UUID = Field(
        ...,
        foreign_key="tenants.id",
        description="Tenant this conversation belongs to",
        index=True,
    )
    user_id: UUID = Field(
        ...,
        foreign_key="users.id",
        description="User who created this conversation",
        index=True,
    )
    
    title: str = Field(
        default="New Conversation",
        max_length=500,
        description="Conversation title",
    )
    
    status: ConversationStatus = Field(
        default=ConversationStatus.ACTIVE,
        description="Conversation status",
        index=True,
    )
    
    # Metrics
    message_count: int = Field(
        default=0,
        description="Total number of messages",
    )
    total_tokens: int = Field(
        default=0,
        description="Total tokens used",
    )
    total_cost_usd: float = Field(
        default=0.0,
        description="Total cost (USD)",
    )
    
    # Metadata
    meta_json: Optional[str] = Field(
        default=None,
        alias="metadata",
        description="Additional metadata (JSON string)",
    )


class Conversation(BaseDBModel, ConversationBase, table=True):
    """
    Conversation database model.
    
    Represents a chat session between a user and the AI.
    """
    
    __tablename__ = "conversations"


class ConversationCreate(SQLModel):
    """Schema for creating a new conversation."""
    
    tenant_id: UUID
    user_id: UUID
    title: str = "New Conversation"


class ConversationUpdate(SQLModel):
    """Schema for updating a conversation."""
    
    title: Optional[str] = None
    status: Optional[ConversationStatus] = None
    meta_json: Optional[str] = Field(default=None, alias="metadata")


class ConversationRead(SQLModel):
    """Schema for reading a conversation."""
    
    id: str  # UUID as string
    tenant_id: str
    user_id: str
    title: str
    status: ConversationStatus
    message_count: int
    total_tokens: int
    total_cost_usd: float
    created_at: str
    updated_at: str


# ==========================================
# MESSAGE MODEL
# ==========================================


class MessageBase(SQLModel):
    """Base fields for Message."""
    
    conversation_id: UUID = Field(
        ...,
        foreign_key="conversations.id",
        description="Conversation this message belongs to",
        index=True,
    )
    
    role: MessageRole = Field(
        ...,
        description="Role of message sender",
        index=True,
    )
    
    content: str = Field(
        ...,
        description="Message content",
    )
    
    # Model Information
    model_id: Optional[str] = Field(
        default=None,
        description="Model used to generate response (if assistant)",
    )
    model_name: Optional[str] = Field(
        default=None,
        description="Full model name",
    )
    
    # Token Usage
    input_tokens: Optional[int] = Field(
        default=None,
        description="Input tokens (if assistant)",
    )
    output_tokens: Optional[int] = Field(
        default=None,
        description="Output tokens (if assistant)",
    )
    total_tokens: Optional[int] = Field(
        default=None,
        description="Total tokens (if assistant)",
    )
    
    # Cost & Performance
    cost_usd: Optional[float] = Field(
        default=None,
        description="Cost of this message (USD)",
    )
    latency_ms: Optional[float] = Field(
        default=None,
        description="Response latency (ms)",
    )
    
    # Routing Information
    routing_reasoning: Optional[str] = Field(
        default=None,
        description="Why this model was selected",
    )
    query_complexity: Optional[str] = Field(
        default=None,
        description="Detected query complexity",
    )
    
    # Metadata
    meta_json: Optional[str] = Field(
        default=None,
        alias="metadata",
        description="Additional metadata (JSON string)",
    )


class Message(BaseDBModel, MessageBase, table=True):
    """
    Message database model.
    
    Represents a single message in a conversation.
    """
    
    __tablename__ = "messages"


class MessageCreate(SQLModel):
    """Schema for creating a new message."""
    
    conversation_id: UUID
    role: MessageRole
    content: str
    model_id: Optional[str] = None
    model_name: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    latency_ms: Optional[float] = None
    routing_reasoning: Optional[str] = None
    query_complexity: Optional[str] = None


class MessageRead(SQLModel):
    """Schema for reading a message."""
    
    id: str  # UUID as string
    conversation_id: str
    role: MessageRole
    content: str
    model_id: Optional[str]
    model_name: Optional[str]
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    total_tokens: Optional[int]
    cost_usd: Optional[float]
    latency_ms: Optional[float]
    routing_reasoning: Optional[str]
    query_complexity: Optional[str]
    created_at: str
