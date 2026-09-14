"""Loads every v1 config file and cross-checks it against the taxonomy.

Called by the composition root; components get only their part.
"""

from dataclasses import dataclass
from pathlib import Path

from triage.config import ConfigError, ConfigModel, SemVer, load_model
from triage.contracts import Taxonomy
from triage.v1.extractor import ExtractorConfig
from triage.v1.itsm import ItsmConfig
from triage.v1.parser import ParserConfig
from triage.v1.priority_matrix import PriorityMatrixConfig
from triage.v1.queue import QueueConfig
from triage.v1.routing_table import RoutingConfig
from triage.v1.rule_engine import RuleSet
from triage.v1.sla import SlaConfig
from triage.v1.storage import StorageConfig


class ParsingConfig(ConfigModel):
    """config/parsing.yaml"""

    version: SemVer
    parser: ParserConfig
    extractor: ExtractorConfig


class RuntimeConfig(ConfigModel):
    """config/runtime.yaml"""

    version: SemVer
    storage: StorageConfig
    queue: QueueConfig
    itsm: ItsmConfig


@dataclass(frozen=True, slots=True)
class V1Config:
    parsing: ParsingConfig
    rules: RuleSet
    priority: PriorityMatrixConfig
    routing: RoutingConfig
    sla: SlaConfig
    runtime: RuntimeConfig
    templates_dir: Path


def load_v1_config(config_dir: Path, taxonomy: Taxonomy) -> V1Config:
    config = V1Config(
        parsing=load_model(ParsingConfig, config_dir / "parsing.yaml"),
        rules=load_model(RuleSet, config_dir / "rules.yaml"),
        priority=load_model(PriorityMatrixConfig, config_dir / "priority_matrix.yaml"),
        routing=load_model(RoutingConfig, config_dir / "routing.yaml"),
        sla=load_model(SlaConfig, config_dir / "sla.yaml"),
        runtime=load_model(RuntimeConfig, config_dir / "runtime.yaml"),
        templates_dir=config_dir / "templates",
    )
    problems = [
        *(f"rules.yaml: {p}" for p in config.rules.violations(taxonomy)),
        *(f"routing.yaml: {p}" for p in config.routing.violations(taxonomy)),
    ]
    if problems:
        raise ConfigError("config does not match taxonomy.yaml:\n  " + "\n  ".join(problems))
    return config
