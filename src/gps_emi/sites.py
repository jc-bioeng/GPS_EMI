"""Sedes operativas: coincidencia exacta con las geocercas reportadas."""
from collections.abc import Iterable

EMI_SITES = ("EMI Medellin_Poblado", "EMI_Medellin_Taller")


def matching_sites(zones: Iterable[str]) -> tuple[str, ...]:
    reported = set(zones)
    return tuple(site for site in EMI_SITES if site in reported)


def validate_site(site: str) -> None:
    if site not in EMI_SITES:
        raise ValueError("Sede no permitida.")
