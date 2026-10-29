from decimal import Decimal, InvalidOperation


def qty_str(value, places=3):
    """
    A quantity or rate without trailing zeros: 50.000 -> "50", 12.340 -> "12.34",
    12.345 -> "12.345". Used on screens and as stable keys in page data.
    """
    try:
        number = Decimal(value or 0)
    except (InvalidOperation, TypeError, ValueError):
        return str(value)
    number = number.quantize(Decimal(1).scaleb(-places))
    text = format(number, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text
