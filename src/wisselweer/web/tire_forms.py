"""Formulieren voor bandengroepen: veldspecificaties en parsing (los van de routes)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ValidationError

from wisselweer.core.models import TireType
from wisselweer.tires.schemas import MAX_TIRES, TireGroupIn
from wisselweer.web.forms import Field, Form, Parser, bind

# Veldnamen van een groep (zonder voorvoegsel). Het formulier voor een nieuwe set heeft vier
# regels met voorvoegsel g1_ .. g4_; de formulieren voor één groep gebruiken geen voorvoegsel.
GROUP_KEYS = ("quantity", "dot_code", "purchase_date", "brand", "model", "positions")
PMSF_TYPES = (TireType.WINTER, TireType.ALL_SEASON)


def pmsf_relevant(tire_type: TireType | None) -> bool:
    return tire_type in PMSF_TYPES


def group_fields(
    prefix: str = "",
    *,
    brand_model: bool = True,
    positions: bool = True,
    pmsf: bool = False,
    pmsf_follows_type: bool = False,
    quantity_label: str = "tire.quantity",
    quantity_help: str | None = None,
) -> list[Field]:
    """Velden van één groep. `pmsf_follows_type`: de checkbox hoort bij een formulier met een
    `type`-keuze en verdwijnt (via CSS) zolang zomerbanden gekozen zijn."""
    fields = [
        Field(
            f"{prefix}quantity",
            quantity_label,
            kind="number",
            help=quantity_help,
            attrs={"min": "1", "max": str(MAX_TIRES), "inputmode": "numeric"},
        ),
        Field(f"{prefix}dot_code", "tire.dot", help="tire.dot_help", attrs={"maxlength": "20"}),
        Field(f"{prefix}purchase_date", "tire.purchase_date", kind="date"),
    ]
    if brand_model:
        fields += [
            Field(f"{prefix}brand", "tire.group_brand", attrs={"maxlength": "80"}),
            Field(f"{prefix}model", "tire.group_model", attrs={"maxlength": "80"}),
        ]
    if positions:
        fields.append(
            Field(
                f"{prefix}positions",
                "tire.positions",
                help="tire.positions_help",
                attrs={"maxlength": "20", "placeholder": "LV,RV"},
            )
        )
    if pmsf:
        fields.append(
            Field(
                f"{prefix}has_3pmsf",
                "tire.pmsf",
                kind="checkbox",
                help="tire.pmsf_help",
                icon="3pmsf",
                wrapper_class="only-winter" if pmsf_follows_type else "",
            )
        )
    return fields


def _row_filled(values: dict[str, str], prefix: str) -> bool:
    return any(values.get(prefix + k, "").strip() for k in GROUP_KEYS)


def group_rows(values: dict[str, str], errors: dict[str, str]) -> list[dict[str, Any]]:
    """De vier regels van het formulier voor een nieuwe set: regel 1 altijd zichtbaar, de andere
    ingeklapt tenzij ze ingevuld zijn of een fout bevatten."""
    rows = []
    for i in range(1, MAX_TIRES + 1):
        prefix = f"g{i}_"
        main = i == 1
        fields = group_fields(
            prefix,
            brand_model=not main,
            positions=not main,
            pmsf=True,
            pmsf_follows_type=True,
        )
        bound = bind(fields, {f"{prefix}quantity": "4", **values} if main else values, errors)
        has_error = any(f.error for f in bound)
        rows.append(
            {
                "index": i,
                "extra": not main,
                "open": not main and (_row_filled(values, prefix) or has_error),
                "fields": bound,
            }
        )
    return rows


def parse_group(
    p: Parser,
    prefix: str = "",
    *,
    relevant_3pmsf: bool,
    default_quantity: int | None = None,
) -> dict[str, Any]:
    """Leest de velden van één groep; fouten komen in `p.errors` onder de veldnaam."""
    qty_name = f"{prefix}quantity"
    qty = p.integer(qty_name, minimum=1, maximum=MAX_TIRES, required=default_quantity is None)
    if qty is None and qty_name not in p.errors:
        qty = default_quantity
    return {
        "quantity": qty,
        "dot_code": p.text(f"{prefix}dot_code", max_len=20),
        "purchase_date": p.date(f"{prefix}purchase_date"),
        "brand": p.text(f"{prefix}brand", max_len=80),
        "model": p.text(f"{prefix}model", max_len=80),
        "positions": p.text(f"{prefix}positions", max_len=20),
        "has_3pmsf": bool(p.form.get(f"{prefix}has_3pmsf")) if relevant_3pmsf else None,
    }


def build_model(p: Parser, prefix: str, model: type[BaseModel], data: dict[str, Any]) -> Any:
    """Maakt het pydantic-model; veldfouten komen onder de (voorvoegsel-)veldnaam in `p.errors`."""
    try:
        return model(**data)
    except ValidationError as exc:
        for err in exc.errors():
            name = str(err["loc"][0]) if err["loc"] else ""
            p.fail(f"{prefix}{name}" if name in data else f"{prefix}quantity")
        return None


def parse_new_groups(p: Parser, form: Form, tire_type: TireType | None) -> list[TireGroupIn]:
    """Regels 1-4 van het formulier voor een nieuwe set. Regel 1 telt altijd (aantal standaard 4);
    de andere regels alleen als ze iets bevatten."""
    relevant = pmsf_relevant(tire_type)
    out: list[TireGroupIn] = []
    for i in range(1, MAX_TIRES + 1):
        prefix = f"g{i}_"
        if i > 1 and not _row_filled(form.values(), prefix):
            continue
        data = parse_group(
            p, prefix, relevant_3pmsf=relevant, default_quantity=4 if i == 1 else None
        )
        group = build_model(p, prefix, TireGroupIn, data)
        if group is not None and not any(k.startswith(prefix) for k in p.errors):
            out.append(group)
    return out
