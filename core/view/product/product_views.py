"""
Products, and the units and categories they are counted and grouped in.

Nothing here is tied to one trade: a product is counted in a pack unit
(bag, box, carton, piece) and priced per a rate unit (kg, piece, litre),
with a pack size linking the two.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _

from core.forms import ProductCategoryForm, ProductForm, UnitForm
from core.models import Product, ProductCategory, Unit
from core.permissions import manager_required
from core.services.catalog import seed_company_catalog
from core.tenancy import company_of, tenant_object_or_404


@login_required
def product_list(request):
    company = company_of(request)
    q = request.GET.get("q", "").strip()
    category_id = request.GET.get("category", "")

    products = (
        Product.objects.for_company(company)
        .select_related("category", "unit", "rate_unit")
        .order_by("name")
    )
    if q:
        products = products.filter(Q(name__icontains=q) | Q(hsn_code__icontains=q) | Q(sku__icontains=q))
    if category_id.isdigit():
        products = products.filter(category_id=int(category_id))

    return render(request, "core/product_list.html", {
        "products": products,
        "categories": ProductCategory.objects.for_company(company).filter(is_active=True),
        "category_id": category_id,
    })


def _ensure_units(company):
    """Older companies may have no units yet; give them the defaults once."""
    if not Unit.objects.for_company(company).exists():
        seed_company_catalog(company)


@login_required
def add_product(request):
    company = company_of(request)
    _ensure_units(company)

    if request.method == "POST":
        form = ProductForm(request.POST, company=company)
        if form.is_valid():
            product = form.save(commit=False)
            product.company = company
            product.save()
            messages.success(request, "✅ " + _("Product saved successfully!"))
            if request.POST.get("save_and_new"):
                return redirect("add_product")
            return redirect("product_list")
    else:
        form = ProductForm(company=company)

    return render(request, "core/product_form.html", {"form": form, "mode": "add"})


@login_required
def edit_product(request, product_id):
    company = company_of(request)
    product = tenant_object_or_404(Product, request, product_id)
    _ensure_units(company)

    if request.method == "POST":
        form = ProductForm(request.POST, instance=product, company=company)
        if form.is_valid():
            form.save()
            messages.success(request, "✅ " + _("Product updated successfully!"))
            return redirect("product_list")
    else:
        form = ProductForm(instance=product, company=company)

    return render(request, "core/product_form.html", {"form": form, "mode": "edit", "product": product})


@login_required
def units_and_categories(request):
    """One page to add units and categories, and switch them on or off."""
    company = company_of(request)
    _ensure_units(company)

    unit_form = UnitForm(company=company, prefix="unit")
    category_form = ProductCategoryForm(company=company, prefix="cat")

    if request.method == "POST":
        if "add_unit" in request.POST:
            unit_form = UnitForm(request.POST, company=company, prefix="unit")
            if unit_form.is_valid():
                unit = unit_form.save(commit=False)
                unit.company = company
                unit.save()
                messages.success(request, _("Unit “%(name)s” added.") % {"name": unit.name})
                return redirect("units_and_categories")
        elif "add_category" in request.POST:
            category_form = ProductCategoryForm(request.POST, company=company, prefix="cat")
            if category_form.is_valid():
                category = category_form.save(commit=False)
                category.company = company
                category.save()
                messages.success(request, _("Category “%(name)s” added.") % {"name": category.name})
                return redirect("units_and_categories")

    return render(request, "core/units_categories.html", {
        "units": Unit.objects.for_company(company).order_by("-is_active", "name"),
        "categories": ProductCategory.objects.for_company(company).order_by("-is_active", "name"),
        "unit_form": unit_form,
        "category_form": category_form,
    })


@login_required
@manager_required
def toggle_unit(request, unit_id):
    unit = tenant_object_or_404(Unit, request, unit_id)
    if request.method == "POST":
        unit.is_active = not unit.is_active
        unit.save(update_fields=["is_active"])
    return redirect("units_and_categories")


@login_required
@manager_required
def toggle_category(request, category_id):
    category = tenant_object_or_404(ProductCategory, request, category_id)
    if request.method == "POST":
        category.is_active = not category.is_active
        category.save(update_fields=["is_active"])
    return redirect("units_and_categories")
