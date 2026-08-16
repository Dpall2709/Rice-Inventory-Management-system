from ..base_imports import *

@login_required
def add_purchase(request):
    mills = Mill.objects.all().order_by("mill_name")
    products = Product.objects.filter(is_active=True).order_by("rice_name")

    if request.method == "POST":
        mill_id = request.POST.get("mill")
        invoice_no = request.POST.get("invoice_no")
        purchase_date = request.POST.get("purchase_date")

        # multiple row values
        product_ids = request.POST.getlist("product[]")
        bag_weights = request.POST.getlist("bag_weight[]")
        bag_counts = request.POST.getlist("bag_count[]")
        rates = request.POST.getlist("purchase_price[]")  # ✅ rate per KG

        total_amount = 0

        with transaction.atomic():
            purchase = Purchase.objects.create(
                mill_id=mill_id,
                invoice_no=invoice_no,
                purchase_date=purchase_date,
                total_amount=0
            )

            for i in range(len(product_ids)):
                if not product_ids[i]:
                    continue

                bw = int(bag_weights[i] or 0)        # ✅ bag weight (50 default)
                bc = int(bag_counts[i] or 0)         # ✅ bag count
                rate = float(rates[i] or 0)          # ✅ rate per KG

                # ✅ Rule B: amount = bags * bag_weight * rate_per_kg
                line_total = bc * bw * rate
                total_amount += line_total

                PurchaseItem.objects.create(
                    purchase=purchase,
                    product_id=product_ids[i],
                    bag_weight=bw,
                    bag_count=bc,
                    purchase_price=rate
                )

            purchase.total_amount = total_amount
            purchase.save()

        messages.success(request, "✅ Purchase saved successfully!")
        return redirect("purchase_list")

    return render(request, "core/add_purchase.html", {"mills": mills, "products": products})
