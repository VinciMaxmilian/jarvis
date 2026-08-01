"""Contratos e configuração compartilhados. Este pacote não importa nenhum outro."""

from packages.shared.contracts import (
    Capability,
    CapabilityManifest,
    CapabilityPermissions,
    CapabilityStatus,
    ChatMessage,
    Conversation,
    Event,
    EventType,
    Goal,
    GoalStatus,
    MessageRole,
    Task,
    TaskStatus,
    ToolSpec,
    utcnow,
)
from packages.shared.settings import Settings, get_settings

__all__ = [
    "Capability",
    "CapabilityManifest",
    "CapabilityPermissions",
    "CapabilityStatus",
    "ChatMessage",
    "Conversation",
    "Event",
    "EventType",
    "Goal",
    "GoalStatus",
    "MessageRole",
    "Settings",
    "Task",
    "TaskStatus",
    "ToolSpec",
    "get_settings",
    "utcnow",
]
