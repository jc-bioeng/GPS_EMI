"""Configuración de ejecución de I2, expresada en segundos."""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class WatchConfig:
    polling_interval: float = 30.0
    initial_backoff: float = 5.0
    max_backoff: float = 30.0
    stale_warning_seconds: float = 300.0

    def __post_init__(self):
        for name in ("polling_interval", "initial_backoff", "max_backoff"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} debe ser finito y mayor que cero.")
        if not math.isfinite(self.stale_warning_seconds) or self.stale_warning_seconds < 0:
            raise ValueError("stale_warning_seconds debe ser finito y no negativo.")
        if self.max_backoff < self.initial_backoff:
            raise ValueError("max_backoff debe ser mayor o igual que initial_backoff.")
