"""
Starting units and categories for a company.

Nothing in the app depends on these lists - they only save a new business
from typing "Kg", "Box", "Carton"... before its first entry. The owner can
add, rename or switch off any of them from Products -> Units & categories.
"""

# name, symbol, can be split into decimals
DEFAULT_UNITS = [
    ("Piece", "pcs", False),
    ("Box", "box", False),
    ("Carton", "ctn", False),
    ("Packet", "pkt", False),
    ("Bag", "bag", False),
    ("Kilogram", "kg", True),
    ("Quintal", "qtl", True),
    ("Ton", "ton", True),
    ("Litre", "ltr", True),
]

INDUSTRY_CATEGORIES = {
    "rice": ["Rice", "Broken rice", "Bran"],
    "agri": ["Grains", "Pulses", "Oilseeds", "Spices"],
    "fmcg": ["Food", "Beverages", "Personal care", "Home care"],
    "biscuit": ["Biscuits", "Cookies", "Rusk", "Confectionery"],
    "grocery": ["Staples", "Packaged food", "Oil & ghee", "Household"],
    "packaging": ["Corrugated boxes", "Poly bags", "Tapes", "Labels"],
    "building": ["Cement", "Steel", "Sand & aggregate", "Bricks & blocks"],
    "general": ["General"],
}


def seed_company_catalog(company, unit_model=None, category_model=None):
    """
    Give `company` the default units and its industry's categories.

    Safe to call again: rows that already exist are left alone. The model
    arguments let a data migration pass its historical models.
    """
    if unit_model is None or category_model is None:
        from core.models import ProductCategory, Unit

        unit_model = unit_model or Unit
        category_model = category_model or ProductCategory

    units = {}
    for name, symbol, allow_decimal in DEFAULT_UNITS:
        unit, _ = unit_model.objects.get_or_create(
            company=company, name=name,
            defaults={"symbol": symbol, "allow_decimal": allow_decimal},
        )
        units[name] = unit

    industry = getattr(company, "industry", "general") or "general"
    for name in INDUSTRY_CATEGORIES.get(industry, INDUSTRY_CATEGORIES["general"]):
        category_model.objects.get_or_create(company=company, name=name)

    return units
