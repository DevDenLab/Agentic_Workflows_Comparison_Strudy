"""Loads config/agent.yaml, v2's one config file, into the sections each component owns."""

from dataclasses import dataclass
from pathlib import Path

from triage.config import ConfigModel, SemVer, load_model
from triage.v2.agent import AgentConfig
from triage.v2.budget import BudgetConfig
from triage.v2.confidence import ConfidenceConfig
from triage.v2.critic import CriticConfig


class AgentFile(ConfigModel):
    """config/agent.yaml"""

    version: SemVer
    agent: AgentConfig
    critic: CriticConfig
    budget: BudgetConfig
    confidence: ConfidenceConfig


@dataclass(frozen=True, slots=True)
class V2Config:
    agent: AgentConfig
    critic: CriticConfig
    budget: BudgetConfig
    confidence: ConfidenceConfig


def load_v2_config(config_dir: Path) -> V2Config:
    parsed = load_model(AgentFile, config_dir / "agent.yaml")
    return V2Config(
        agent=parsed.agent, critic=parsed.critic, budget=parsed.budget, confidence=parsed.confidence
    )
