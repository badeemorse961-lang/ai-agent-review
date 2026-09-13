# Typed read-only intentes for Batch 1 — Dashboard projection only.
# No execution/mutation/authorization intents included.

from typing import Optional
from dataclasses import dataclass

@dataclass(frozen=True)
class ProjectDiscoveryIntent:
    workspace_root: str

@dataclass(frozen=True)
class StateClassifyIntent:
    workspace_root: str

@dataclass(frozen=True)
class ConnectionHealthIntent:
    pass

@dataclass(frozen=True)
class GitInspectIntent:
    workspace_root: str

@dataclass(frozen=True)
class EvidenceRetrieveIntent:
    workspace_root: str

@dataclass(frozen=True)
class SafeStopInspectIntent:
    workspace_root: str
