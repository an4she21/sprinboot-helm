"""
Pydantic models for the AI Self-Healing Agent.

Validates Alertmanager webhook payloads, AI decisions,
and remediation results for type safety and documentation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Alertmanager webhook input models
# ---------------------------------------------------------------------------

class AlertStatus(str, Enum):
    FIRING = "firing"
    RESOLVED = "resolved"


class AlertDetail(BaseModel):
    """Single alert inside an Alertmanager webhook payload."""

    status: AlertStatus = AlertStatus.FIRING
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    starts_at: Optional[str] = Field(None, alias="startsAt")
    ends_at: Optional[str] = Field(None, alias="endsAt")
    generator_url: Optional[str] = Field(None, alias="generatorURL")
    fingerprint: Optional[str] = None

    model_config = {"populate_by_name": True}

    @property
    def alertname(self) -> str:
        return self.labels.get("alertname", "unknown")

    @property
    def namespace(self) -> str:
        return self.labels.get("namespace", "default")

    @property
    def pod(self) -> str:
        return self.labels.get("pod", "unknown")

    @property
    def deployment(self) -> str:
        """Derive deployment name from pod name (strip replica-set hash)."""
        pod = self.pod
        if pod and pod != "unknown":
            parts = pod.rsplit("-", 2)
            return parts[0] if len(parts) >= 3 else pod
        return "unknown"

    @property
    def severity(self) -> str:
        return self.labels.get("severity", "warning")

    @property
    def resource_key(self) -> str:
        """Unique key for cooldown dedup: namespace/deployment/alertname."""
        return f"{self.namespace}/{self.deployment}/{self.alertname}"


class AlertmanagerPayload(BaseModel):
    """Top-level Alertmanager webhook payload."""

    receiver: str = ""
    status: AlertStatus = AlertStatus.FIRING
    alerts: list[AlertDetail] = Field(default_factory=list)
    group_key: Optional[str] = Field(None, alias="groupKey")
    common_labels: dict[str, str] = Field(default_factory=dict)
    common_annotations: dict[str, str] = Field(default_factory=dict)
    external_url: Optional[str] = Field(None, alias="externalURL")

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# AI Decision models (NVIDIA NIM response)
# ---------------------------------------------------------------------------

class ActionId(str, Enum):
    RESTART_POD = "RESTART_POD"
    SCALE_UP = "SCALE_UP"
    INVESTIGATE = "INVESTIGATE"
    MANUAL = "MANUAL"


class AIDecision(BaseModel):
    """Structured response expected from NVIDIA NIM (GLM 5.1)."""

    analysis: str = Field(
        ..., description="Detailed reasoning for the chosen action"
    )
    action_id: ActionId = Field(
        ..., description="The remediation action to execute"
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score from 0.0 to 1.0",
    )


# ---------------------------------------------------------------------------
# Remediation result models
# ---------------------------------------------------------------------------

class RemediationResult(BaseModel):
    """Outcome of processing a single alert."""

    pod: str
    namespace: str
    deployment: str
    alertname: str
    action: str
    confidence: float
    result: str
    analysis: Optional[str] = None
    skipped: bool = False
    skip_reason: Optional[str] = None
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    correlation_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Health / readiness models
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str = "healthy"
    nim: str = "unknown"
    eks: str = "unknown"
    uptime_seconds: float = 0.0


class ReadinessResponse(BaseModel):
    ready: bool
    eks_connected: bool
    reason: Optional[str] = None
