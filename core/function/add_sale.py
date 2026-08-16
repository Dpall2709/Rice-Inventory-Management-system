# Django Core
from django.shortcuts import render, redirect
from django.contrib import messages
from django.utils import timezone
from django.db import transaction

# Models
from ..models import (
    Product,
    Broker,
    PurchaseItem,
    Sale,
    SaleItem,
    Mill
)

# Python Standard Library
import json

# Decimal
from decimal import Decimal, InvalidOperation


def _d(v, default="0"):
    """Safe Decimal conversion."""
    try:
        if v is None or str(v).strip() == "":
            return Decimal(default)
        return Decimal(str(v).strip())
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def add_sale(request):
    company = request.user.userprofile.company

    products = (
        Product.objects
        .filter(
            company=company,
            is_active=True
        )
        .order_by("rice_name")
    )

    # Only this company's mills
    mills = (
        Mill.objects
        .filter(company=company)
        .order_by("mill_name")
    )

    # Only this company's brokers
    brokers = (
        Broker.objects
        .filter(company=company)
        .order_by("broker_name")
    )

    # Purchase stock only from this company
    purchase_items = (
        PurchaseItem.objects
        .filter(
            purchase__company=company
        )
        .select_related(
            "product",
            "purchase",
            "purchase__mill"
        )
    )

    purchase_items_json = json.dumps([
        {
            "id": pi.id,
            "product_id": pi.product_id,
            "bag_weight": pi.bag_weight,
            "label": (
                f"{pi.purchase.invoice_no} / "
                f"{pi.purchase.mill.mill_name} / "
                f"Buy ₹{pi.purchase_price}/KG / "
                f"{pi.bag_weight}kg bag"
            ),
        }
        for pi in purchase_items
    ])

    # =========================================================
    # GET
    # =========================================================
    if request.method == "GET":

        draft = request.session.get(
            "sale_draft"
        ) or {}

        draft_lists = request.session.get(
            "sale_draft_lists"
        ) or {}

        return render(
            request,
            "core/add_sale.html",
            {
                "products": products,
                "brokers": brokers,
                "mills": mills,
                "purchase_items_json": purchase_items_json,

                "draft": draft,

                "draft_purchase_items": (
                    draft_lists.get(
                        "purchase_item",
                        []
                    )
                ),

                "draft_row_bags": (
                    draft_lists.get(
                        "row_bags",
                        []
                    )
                ),

                "draft_lists": draft_lists,
            }
        )

    step = (
        request.POST.get("step") or ""
    ).strip()

    # =========================================================
    # STORE FORM DATA IN SESSION
    # =========================================================

    # request.session["sale_draft"] = dict(
    #     request.POST.items()
    # )

    request.session["sale_draft"] = {

    "sale_date": request.POST.get(
        "sale_date",
        ""
    ),

    "customer_name": request.POST.get(
        "customer_name",
        ""
    ),

    "customer_gst": request.POST.get(
        "customer_gst",
        ""
    ),

    "broker_id": request.POST.get(
        "broker_id",
        ""
    ),

    "vehicle_number": request.POST.get(
        "vehicle_number",
        ""
    ),

    "driver_name": request.POST.get(
        "driver_name",
        ""
    ),

    "transporter_name": request.POST.get(
        "transporter_name",
        ""
    ),

    "advance_received": request.POST.get(
        "advance_received",
        "0"
    ),

    "transport_rate_per_ton": request.POST.get(
        "transport_rate_per_ton",
        "0"
    ),

    "transport_paid_by_dealer": request.POST.get(
        "transport_paid_by_dealer",
        "0"
    ),

    "transport_paid_by_customer": request.POST.get(
        "transport_paid_by_customer",
        "0"
    ),
}

    request.session["sale_draft_lists"] = {
        "product_id": request.POST.getlist(
            "product_id[]"
        ),
        "bag_weight": request.POST.getlist(
            "bag_weight[]"
        ),
        "total_bags": request.POST.getlist(
            "total_bags[]"
        ),
        "rate_per_kg": request.POST.getlist(
            "rate_per_kg[]"
        ),
        "gst_percent": request.POST.getlist(
            "gst_percent[]"
        ),
        "purchase_item": request.POST.getlist(
            "purchase_item[]"
        ),
        "row_bags": request.POST.getlist(
            "row_bags[]"
        ),
    }

    request.session.modified = True

    draft = request.session.get(
        "sale_draft"
    ) or {}

    draft_lists = request.session.get(
        "sale_draft_lists"
    ) or {}

    # =========================================================
    # REVIEW STEP
    # =========================================================
    if step == "review":

        # ---------------- CALCULATIONS ----------------

        total_kg = Decimal("0")
        taxable_amount = Decimal("0")
        total_bags = 0
        gst_total = Decimal("0")

        for i in range(
            len(draft_lists["product_id"])
        ):

            bw = _d(
                draft_lists["bag_weight"][i]
            )

            bags = _d(
                draft_lists["total_bags"][i]
            )

            rate = _d(
                draft_lists["rate_per_kg"][i]
            )

            gst_p = _d(
                draft_lists["gst_percent"][i]
            )

            kg = bw * bags
            tax = kg * rate

            gst = (
                tax * gst_p
            ) / Decimal("100")

            total_kg += kg
            taxable_amount += tax
            gst_total += gst
            total_bags += int(bags)

        rice_total = (
            taxable_amount + gst_total
        )

        advance = _d(
            draft.get("advance_received")
        )

        rice_due = (
            rice_total - advance
        )

        transport_rate = _d(
            draft.get(
                "transport_rate_per_ton"
            )
        )

        t_dealer = _d(
            draft.get(
                "transport_paid_by_dealer"
            )
        )

        t_customer = _d(
            draft.get(
                "transport_paid_by_customer"
            )
        )

        transport_charge = (
            (total_kg / Decimal("1000"))
            * transport_rate
        )

        transport_due = (
            transport_charge
            - (t_dealer + t_customer)
        )

        # ---------------- BREAKUP ----------------

        breakup_rows = []

        buy_cost_total = Decimal("0")

        for pid, bags_str in zip(
            draft_lists["purchase_item"],
            draft_lists["row_bags"]
        ):

            if not pid:
                continue

            try:

                pi = (
                    PurchaseItem.objects
                    .select_related(
                        "purchase",
                        "purchase__mill"
                    )
                    .get(id=int(pid))
                )

            except PurchaseItem.DoesNotExist:
                continue

            bags = int(bags_str or 0)

            kg = (
                Decimal(bags)
                * Decimal(pi.bag_weight)
            )

            amount = (
                kg * pi.purchase_price
            )

            buy_cost_total += amount

            breakup_rows.append({
                "invoice_no": (
                    pi.purchase.invoice_no
                ),
                "mill_name": (
                    pi.purchase.mill.mill_name
                ),
                "bag_weight": pi.bag_weight,
                "bags": bags,
                "kg": kg,
                "buy_rate": (
                    pi.purchase_price
                ),
                "amount": amount,
            })

        profit_estimate = (
            rice_total - buy_cost_total
        )

        grand_total = (
            rice_total + transport_charge
        )

        return render(
            request,
            "core/sale_review.html",
            {

                "sale_date": (
                    draft.get("sale_date")
                ),

                "customer_name": (
                    draft.get("customer_name")
                ),

                "customer_gst": (
                    draft.get("customer_gst")
                ),

                "vehicle_number": (
                    draft.get("vehicle_number")
                ),

                "driver_name": (
                    draft.get("driver_name")
                ),

                "transporter_name": (
                    draft.get("transporter_name")
                ),

                "total_bags": total_bags,
                "total_kg": total_kg,

                "rate_per_kg": (
                    draft_lists[
                        "rate_per_kg"
                    ][0]
                    if draft_lists[
                        "rate_per_kg"
                    ]
                    else 0
                ),

                "taxable_amount": (
                    taxable_amount
                ),

                "gst_amount": gst_total,

                "gst_percent": (
                    draft_lists[
                        "gst_percent"
                    ][0]
                    if draft_lists[
                        "gst_percent"
                    ]
                    else 0
                ),

                "rice_total": rice_total,

                "advance_received": advance,

                "rice_due": rice_due,

                "transport_rate_per_ton": (
                    transport_rate
                ),

                "transport_charge": (
                    transport_charge
                ),

                "transport_paid_by_dealer": (
                    t_dealer
                ),

                "transport_paid_by_customer": (
                    t_customer
                ),

                "transport_due": (
                    transport_due
                ),

                "breakup_rows": breakup_rows,

                "buy_cost_total": (
                    buy_cost_total
                ),

                "profit_estimate": (
                    profit_estimate
                ),

                "grand_total": (
                    grand_total
                ),
            }
        )

    # =========================================================
    # SAVE STEP
    # =========================================================
    if step == "save":

        if not draft:

            messages.error(
                request,
                "Draft not found."
            )

            return redirect("add_sale")

        # ---------------- SCALARS ----------------

        sale_date = (
            draft.get("sale_date")
            or str(
                timezone.now().date()
            )
        )

        customer_name = (
            draft.get(
                "customer_name"
            ) or ""
        ).strip()

        customer_gst = (
            draft.get(
                "customer_gst"
            ) or ""
        ).strip()

        broker_id = (
            draft.get("broker_id")
            or None
        )

        vehicle_number = (
            draft.get(
                "vehicle_number"
            ) or ""
        ).strip()

        driver_name = (
            draft.get(
                "driver_name"
            ) or ""
        ).strip()

        transporter_name = (
            draft.get(
                "transporter_name"
            ) or ""
        ).strip()

        advance_received = _d(
            draft.get(
                "advance_received"
            )
        )

        transport_rate_per_ton = _d(
            draft.get(
                "transport_rate_per_ton"
            )
        )

        transport_paid_by_dealer = _d(
            draft.get(
                "transport_paid_by_dealer"
            )
        )

        transport_paid_by_customer = _d(
            draft.get(
                "transport_paid_by_customer"
            )
        )

        # ---------------- PRODUCTS ----------------

        product_ids = (
            draft_lists.get(
                "product_id",
                []
            )
        )

        bag_weights = (
            draft_lists.get(
                "bag_weight",
                []
            )
        )

        total_bags_list = (
            draft_lists.get(
                "total_bags",
                []
            )
        )

        rates = (
            draft_lists.get(
                "rate_per_kg",
                []
            )
        )

        gst_percents = (
            draft_lists.get(
                "gst_percent",
                []
            )
        )

        if (
            not product_ids
            or all(
                not x
                for x in product_ids
            )
        ):

            messages.error(
                request,
                "At least one product required."
            )

            return redirect("add_sale")

        # ---------------- CALCULATIONS ----------------

        total_kg = Decimal("0")
        taxable_amount = Decimal("0")
        total_bags = 0

        for i in range(
            len(product_ids)
        ):

            if not product_ids[i]:
                continue

            bw = _d(
                bag_weights[i]
            )

            bags = _d(
                total_bags_list[i]
            )

            rate = _d(
                rates[i]
            )

            kg = bw * bags

            total_kg += kg

            taxable_amount += (
                kg * rate
            )

            total_bags += int(bags)

        gst_percent = _d(
            gst_percents[0]
            if gst_percents
            else 0
        )

        gst_amount = (
            taxable_amount
            * gst_percent
        ) / Decimal("100")

        rice_total = (
            taxable_amount
            + gst_amount
        )

        rice_due = (
            rice_total
            - advance_received
        )

        # ---------------- TRANSPORT ----------------

        transport_charge = (
            (
                total_kg
                / Decimal("1000")
            )
            * transport_rate_per_ton
        )

        transport_due = (
            transport_charge
            - (
                transport_paid_by_dealer
                + transport_paid_by_customer
            )
        )

        # ---------------- BREAKUP ----------------

        purchase_item_ids = (
            draft_lists.get(
                "purchase_item",
                []
            )
        )

        row_bags_list = (
            draft_lists.get(
                "row_bags",
                []
            )
        )

        if (
            len(purchase_item_ids)
            != len(row_bags_list)
        ):

            messages.error(
                request,
                "Breakup mismatch."
            )

            return redirect(
                "add_sale"
            )

        breakup_sum = sum(
            int(x or 0)
            for x in row_bags_list
        )

        if breakup_sum != int(total_bags):

            messages.error(
                request,
                (
                    f"Breakup must match "
                    f"total bags "
                    f"({breakup_sum} != "
                    f"{total_bags})"
                )
            )

            return redirect(
                "add_sale"
            )

        breakup_rows = []

        for pid, bags_str in zip(
            purchase_item_ids,
            row_bags_list
        ):

            bags = int(
                bags_str or 0
            )

            if bags <= 0:
                continue

            try:

                pi = (
                    PurchaseItem.objects
                    .select_related(
                        "purchase",
                        "purchase__mill"
                    )
                    .get(id=int(pid))
                )

            except PurchaseItem.DoesNotExist:
                continue

            kg = (
                Decimal(bags)
                * Decimal(pi.bag_weight)
            )

            breakup_rows.append({
                "purchase_item": pi,
                "bags": bags,
                "kg": kg,
                "buy_rate": (
                    pi.purchase_price
                ),
                "buy_amount": (
                    kg
                    * pi.purchase_price
                ),
            })

        if not breakup_rows:

            messages.error(
                request,
                "Please add internal stock breakup."
            )

            return redirect(
                "add_sale"
            )

        broker = (
            Broker.objects
            .filter(id=broker_id)
            .first()
            if broker_id else None
        )

        # =====================================================
        # SAVE
        # =====================================================

        with transaction.atomic():

            sale = Sale.objects.create(
                company=company,

                invoice_no=(
                    f"SALE-"
                    f"{timezone.now().strftime('%Y%m%d%H%M%S')}"
                ),

                customer_name=customer_name,
                customer_gst=customer_gst,
                broker=broker,
                sale_date=sale_date,

                vehicle_number=vehicle_number,
                driver_name=driver_name,
                transporter_name=transporter_name,

                transport_rate_per_ton=(
                    transport_rate_per_ton
                ),

                transport_charge=(
                    transport_charge
                ),

                transport_paid_by_dealer=(
                    transport_paid_by_dealer
                ),

                transport_paid_by_customer=(
                    transport_paid_by_customer
                ),

                total_quantity_kg=(
                    total_kg
                ),

                taxable_amount=(
                    taxable_amount
                ),

                gst_percent=gst_percent,
                gst_amount=gst_amount,

                total_amount=rice_total,

                advance_received=(
                    advance_received
                ),

                balance_amount=rice_due,
            )

            # ---------------- SALE ITEMS ----------------

            for i in range(
                len(product_ids)
            ):

                if not product_ids[i]:
                    continue

                product = (
                    Product.objects.get(
                        id=int(
                            product_ids[i]
                        )
                    )
                )

                bw = _d(
                    bag_weights[i]
                )

                bags = int(
                    _d(
                        total_bags_list[i]
                    )
                )

                rate = _d(
                    rates[i]
                )

                kg = (
                    bw
                    * Decimal(bags)
                )

                amount = (
                    kg * rate
                )

                SaleItem.objects.create(

                    sale=sale,

                    product=product,

                    mill=(
                        breakup_rows[0][
                            "purchase_item"
                        ]
                        .purchase.mill
                    ),

                    bag_weight=int(bw),

                    bag_count=bags,

                    rate_per_kg=rate,

                    total_weight=kg,

                    amount=amount,
                )

        # =====================================================
        # CLEAR SESSION
        # =====================================================

        request.session.pop(
            "sale_draft",
            None
        )

        request.session.pop(
            "sale_draft_lists",
            None
        )

        request.session.modified = True

        messages.success(
            request,
            "Sale saved successfully ✅"
        )

        return redirect(
            "sale_detail",
            sale.id
        )

    return redirect("add_sale")