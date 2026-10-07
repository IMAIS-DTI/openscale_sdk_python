"""OpenScale SDK for automations: configuration, dry run, masked logs, summary, artifacts and an API client.

Contract: https://openscale.clickip.com.br/guias/automacoes-como-codigo/ (OpenScale ≥ 1.11.333,
runner ≥ 0.3.1).
"""

from .automation import EXIT_CONFIG, EXIT_FAILURE, EXIT_INTERRUPTED, EXIT_OK, Automation, ConfigError
from .client import DryRunSkipped, OpenScaleClient, OpenScaleError
from .manifest import load_manifest, validate_manifest
from .masking import MASK, mask_email, mask_phone

__version__ = "0.1.0"

__all__ = [
    "Automation", "ConfigError", "OpenScaleClient", "OpenScaleError", "DryRunSkipped",
    "validate_manifest", "load_manifest", "mask_phone", "mask_email", "MASK",
    "EXIT_OK", "EXIT_FAILURE", "EXIT_CONFIG", "EXIT_INTERRUPTED", "__version__",
]
