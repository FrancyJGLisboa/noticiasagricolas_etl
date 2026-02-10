"""Brazilian number parsing and date conversion."""

import re
import unicodedata
from datetime import date, datetime
from typing import Optional


def _strip_accents(text: str) -> str:
    """Remove accents from characters: é->e, ã->a, ç->c, etc."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def parse_brazilian_number(text: str) -> Optional[float]:
    """Parse Brazilian-format number to float.

    Examples:
        "126,43" -> 126.43
        "1.234,56" -> 1234.56
        "+0,65" -> 0.65
        "-0,65" -> -0.65
        "11,1525" -> 11.1525
        "-" -> None
        "" -> None
        "s/c" -> None (sem cotação)
    """
    if not text:
        return None

    text = text.strip()
    if not text:
        return None

    # Known non-numeric markers
    lower = text.lower()
    if lower in ("-", "--", "---", "s/c", "*", "**", "***", "n/d", "nd"):
        return None
    # "s/ cotação", "s/ cot", "sem cotação", etc.
    if lower.startswith("s/") or lower.startswith("sem "):
        return None

    # Strip percentage sign if present
    text = text.rstrip("%").strip()

    # Strip leading +
    text = text.lstrip("+")

    if not text:
        return None

    # Brazilian format: dots as thousands separators, comma as decimal
    # Remove thousand separators (dots)
    text = text.replace(".", "")
    # Replace decimal comma with dot
    text = text.replace(",", ".")

    try:
        return float(text)
    except ValueError:
        return None


def parse_variation(text: str) -> Optional[float]:
    """Parse variation value, stripping % and +/- prefix."""
    if not text:
        return None
    text = text.strip().rstrip("%").strip()
    return parse_brazilian_number(text)


def parse_br_date(text: str) -> Optional[date]:
    """Parse Brazilian date format DD/MM/YYYY to date object."""
    text = text.strip()
    try:
        return datetime.strptime(text, "%d/%m/%Y").date()
    except ValueError:
        return None


def parse_fechamento_date(text: str) -> Optional[date]:
    """Parse date from 'Fechamento: DD/MM/YYYY' string."""
    match = re.search(r"(\d{2}/\d{2}/\d{4})", text)
    if match:
        return parse_br_date(match.group(1))
    return None


def slugify_column(header: str) -> str:
    """Convert a table header to a slug for column_name.

    Examples:
        "Valor R$" -> "valor"
        "Variação (%)" -> "variacao_pct"
        "Preço (R$/Sc de 60 kg)" -> "preco"
        "Fechamento (US$/sc 60 kg)" -> "fechamento"
        "Variação (cents/bu)" -> "variacao_cents"
        "Boi Gordo - (R$/@ - à vista)" -> "boi_gordo_vista"
        "Boi Gordo - (R$/@ - prazo 30 dias)" -> "boi_gordo_prazo"
        "Vaca Gorda (R$/@ - à vista)" -> "vaca_gorda_vista"
    """
    h = _strip_accents(header.strip().lower())

    # Normalize "Var." / "Var./" to "variacao" for matching
    h_norm = re.sub(r"\bvar\./?", "variacao ", h)

    # Special patterns
    if re.search(r"variacao.*cents", h_norm):
        return "variacao_cents"
    if re.search(r"variacao.*pontos", h_norm):
        return "variacao_pontos"
    if re.search(r"variacao.*%|variacao.*\(%\)", h_norm):
        return "variacao_pct"
    if "variacao" in h_norm:
        return "variacao"

    # For cattle columns with vista/prazo
    if "vista" in h:
        prefix = re.match(r"([\w\s]+?)[\s-]*\(", h)
        animal = prefix.group(1).strip() if prefix else h.split("(")[0].strip()
        slug = re.sub(r"\s+", "_", animal)
        slug = re.sub(r"[^a-z0-9_]", "", slug)
        return f"{slug}_vista"
    if "prazo" in h:
        prefix = re.match(r"([\w\s]+?)[\s-]*\(", h)
        animal = prefix.group(1).strip() if prefix else h.split("(")[0].strip()
        slug = re.sub(r"\s+", "_", animal)
        slug = re.sub(r"[^a-z0-9_]", "", slug)
        return f"{slug}_prazo"

    # Strip parenthetical content
    h = re.sub(r"\s*\(.*?\)", "", h)
    # Replace @ with "arroba" before stripping special chars
    h = h.replace("@", "arroba")
    # Strip R$, US$, U$, etc
    h = re.sub(r"[rR]\$|[uU][sS]?\$", "", h)
    h = h.strip(" -/")
    # Replace spaces/special chars with underscores
    h = re.sub(r"[^a-z0-9]+", "_", h)
    h = h.strip("_")
    return h or "unknown"


def extract_unit_from_header(header: str) -> str:
    """Extract unit from header like 'Preço (R$/Sc de 60 kg)' -> 'R$/Sc de 60 kg'."""
    match = re.search(r"\(([^)]+)\)", header)
    if match:
        return match.group(1).strip()
    if "R$" in header:
        return "R$"
    return ""
