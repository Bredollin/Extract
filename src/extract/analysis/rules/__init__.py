"""Analysis rules, grouped by area.

Modules are imported in priority order: within one severity, findings from a rule
registered earlier are listed first.
"""

from extract.analysis.rules import storage, memory, cpu, system, network  # noqa: F401, I001
from extract.analysis.rules.base import RULES, Context, Role, Rule, fmt
from extract.analysis.rules.memory import memory_channel

__all__ = ["RULES", "Context", "Role", "Rule", "fmt", "memory_channel"]
