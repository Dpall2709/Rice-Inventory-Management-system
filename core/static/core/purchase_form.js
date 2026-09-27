/* ==========================================================================
   Purchase bill entry - live totals.

   This mirrors core/services/purchase_service.py exactly:

       goods            = sum(bags x bag weight x rate)
       discount         = spread across lines by value
       taxable          = goods - discount
       GST              = per line, on its discounted value
       CGST/SGST or IGST depending on the chosen tax type
       + freight + labour, then rounded to whole rupees

   The server always recalculates on save - this is only so the person typing
   sees the bill add up as they go.
   ========================================================================== */

(function () {
  "use strict";

  var form = document.getElementById("purchaseForm");
  if (!form) return;

  var rowsBody = document.getElementById("itemRows");
  var template = document.getElementById("emptyLine");
  var taxSelect = form.querySelector("[data-tax-type]");
  var totalForms = form.querySelector("#id_purchaseitem_set-TOTAL_FORMS");

  function money(n) {
    return (Math.round((Number(n) || 0) * 100) / 100).toFixed(2);
  }

  function inr(n) {
    return window.formatINR ? window.formatINR(n) : money(n);
  }

  function num(el) {
    return parseFloat((el && el.value) || 0) || 0;
  }

  function setText(scope, selector, value) {
    var el = scope.querySelector(selector);
    if (el) el.textContent = value;
  }

  /* ---------------------------------------------------------- calculation */

  function recalculate() {
    var lines = [];
    var goods = 0;
    var bags = 0;
    var kg = 0;

    rowsBody.querySelectorAll("[data-line]").forEach(function (row) {
      var del = row.querySelector('input[type="checkbox"][name$="-DELETE"]');
      if (del && del.checked) {
        row.style.display = "none";
        return;
      }

      var weight = num(row.querySelector('[data-cell="bag_weight"]'));
      var count = num(row.querySelector('[data-cell="bag_count"]'));
      var rate = num(row.querySelector('[data-cell="rate"]'));
      var gstPct = num(row.querySelector('[data-cell="gst"]'));

      var lineKg = weight * count;
      var lineGoods = lineKg * rate;

      bags += count;
      kg += lineKg;
      goods += lineGoods;

      lines.push({ row: row, kg: lineKg, goods: lineGoods, gstPct: gstPct });
    });

    var taxType = taxSelect ? taxSelect.value : "cgst_sgst";
    var discount = num(form.querySelector('[name="discount_amount"]'));

    // Transport and labour count towards the MILL'S BILL only when the tick box
    // says the mill charged them. Otherwise they are the buyer's own cost.
    function charge(which) {
        var amount = num(form.querySelector('[data-charge-amount="' + which + '"]'));
        var box = form.querySelector('[data-charge-bymill="' + which + '"]');
        var byMill = box ? box.checked : false;
        return { amount: amount, byMill: byMill, onBill: byMill ? amount : 0, mine: byMill ? 0 : amount };
    }

    var transport = charge("transport");
    var labourCharge = charge("labour");

    var freight = transport.onBill;
    var labour = labourCharge.onBill;

    if (discount > goods) discount = goods;

    var taxable = 0;
    var gstTotal = 0;

    lines.forEach(function (line) {
      var share = goods ? (line.goods / goods) * discount : 0;
      var lineTaxable = Math.max(line.goods - share, 0);
      var lineGst = taxType === "none" ? 0 : (lineTaxable * line.gstPct) / 100;

      taxable += lineTaxable;
      gstTotal += lineGst;

      setText(line.row, '[data-cell="kg"]', line.kg ? money(line.kg) : "0");
      setText(line.row, '[data-cell="taxable"]', inr(lineTaxable));
      setText(line.row, '[data-cell="gst_amount"]', inr(lineGst));
      setText(line.row, '[data-cell="line_total"]', inr(lineTaxable + lineGst));
    });

    var cgst = 0, sgst = 0, igst = 0;
    if (taxType === "cgst_sgst") {
      cgst = gstTotal / 2;
      sgst = gstTotal - cgst;
    } else if (taxType === "igst") {
      igst = gstTotal;
    }

    var beforeRound = taxable + cgst + sgst + igst + freight + labour;
    var total = Math.round(beforeRound);
    var roundOff = total - beforeRound;

    var paid = num(form.querySelector('[name="amount_paid_now"]'));
    var due = Math.max(total - paid, 0);

    // ---- what the rice really costs, and what it must sell for ----
    // Mirrors core/services/costing.py: GST is left out because a registered
    // buyer claims it back, so it is not part of the cost.
    var ownExpenses =
      transport.mine +
      labourCharge.mine +
      num(form.querySelector('[data-expense="other"]'));

    var landed = taxable + freight + labour + ownExpenses;
    var costPerKg = kg ? landed / kg : 0;
    var billRatePerKg = kg ? taxable / kg : 0;
    var extraPerKg = costPerKg - billRatePerKg;

    var margin = num(form.querySelector("[data-margin]"));
    var suggestedPerKg = costPerKg * (1 + margin / 100);
    var avgBag = bags ? kg / bags : 0;

    setText(form, '[data-sum="bill_rate"]', money(billRatePerKg));
    setText(form, '[data-sum="extra_per_kg"]', money(extraPerKg));
    setText(form, '[data-sum="cost_per_kg"]', money(costPerKg));
    setText(form, '[data-sum="suggested_per_kg"]', money(suggestedPerKg));
    setText(form, '[data-sum="suggested_per_bag"]', inr(suggestedPerKg * avgBag));
    setText(form, '[data-sum="avg_bag"]', avgBag ? money(avgBag) : "0");
    setText(form, '[data-sum="expected_profit"]', inr((suggestedPerKg - costPerKg) * kg));

    // table footer
    setText(form, '[data-total="kg"]', money(kg));
    setText(form, '[data-total="taxable"]', inr(taxable));
    setText(form, '[data-total="gst"]', inr(gstTotal));
    setText(form, '[data-total="lines"]', inr(taxable + gstTotal));

    // summary panel
    setText(form, '[data-sum="bags"]', bags);
    setText(form, '[data-sum="kg"]', money(kg));
    setText(form, '[data-sum="goods"]', inr(goods));
    setText(form, '[data-sum="discount"]', inr(discount));
    setText(form, '[data-sum="taxable"]', inr(taxable));
    setText(form, '[data-sum="cgst"]', inr(cgst));
    setText(form, '[data-sum="sgst"]', inr(sgst));
    setText(form, '[data-sum="igst"]', inr(igst));
    setText(form, '[data-sum="freight"]', inr(freight));
    setText(form, '[data-sum="labour"]', inr(labour));
    setText(form, '[data-sum="round"]', (roundOff >= 0 ? "+ " : "− ") + money(Math.abs(roundOff)));
    setText(form, '[data-sum="total"]', inr(total));
    setText(form, '[data-sum="paid"]', inr(paid));
    setText(form, '[data-sum="due"]', inr(due));

    // Show a freight/labour line on the bill only when the mill charged it.
    [["freight", freight], ["labour", labour]].forEach(function (pair) {
      form.querySelectorAll('[data-billline="' + pair[0] + '"]').forEach(function (el) {
        el.style.display = pair[1] > 0 ? "" : "none";
      });
    });

    // Only show the tax rows that apply to this bill.
    form.querySelectorAll("[data-tax-label]").forEach(function (label) {
      var which = label.getAttribute("data-tax-label");
      var show =
        (taxType === "cgst_sgst" && (which === "cgst" || which === "sgst")) ||
        (taxType === "igst" && which === "igst");

      label.style.display = show ? "" : "none";
      var value = label.nextElementSibling;
      if (value) value.style.display = show ? "" : "none";
    });
  }

  /* ------------------------------------------------------ product defaults */

  function applyProduct(select) {
    var row = select.closest("[data-line]");
    if (!row) return;

    var info = (window.PRODUCT_TAX || {})[select.value];
    var hsn = row.querySelector('[data-cell="hsn"]');
    var gstInput = row.querySelector('[data-cell="gst"]');

    if (!info) {
      if (hsn) hsn.textContent = "—";
      return;
    }

    if (hsn) hsn.textContent = info.hsn || "—";

    // Fill the GST rate from the product, unless the user typed one already.
    if (gstInput && !gstInput.dataset.touched) {
      gstInput.value = info.gst;
    }
  }

  /* ------------------------------------------------------------- add/remove */

  function addLine() {
    if (!template || !totalForms) return;

    var index = parseInt(totalForms.value, 10);
    var html = template.innerHTML.replace(/__prefix__/g, index);

    var wrapper = document.createElement("tbody");
    wrapper.innerHTML = html.trim();
    var row = wrapper.querySelector("tr");

    rowsBody.appendChild(row);
    totalForms.value = index + 1;

    var select = row.querySelector("select");
    if (select) select.focus();

    recalculate();
  }

  form.addEventListener("click", function (e) {
    if (e.target.closest("[data-add-line]")) {
      e.preventDefault();
      addLine();
      return;
    }

    var remove = e.target.closest("[data-remove-line]");
    if (remove) {
      e.preventDefault();
      var row = remove.closest("[data-line]");
      var del = row.querySelector('input[type="checkbox"][name$="-DELETE"]');
      var visible = rowsBody.querySelectorAll('[data-line]:not([style*="display: none"])');

      if (visible.length <= 1) return;   // always keep one line on screen

      if (del) {
        // An existing saved line must be marked for deletion, not just removed
        // from the page, or Django will not delete it.
        del.checked = true;
        row.style.display = "none";
      } else {
        row.remove();
      }
      recalculate();
    }
  });

  form.addEventListener("input", function (e) {
    if (e.target.matches('[data-cell="gst"]')) e.target.dataset.touched = "1";
    recalculate();
  });

  form.addEventListener("change", function (e) {
    if (e.target.matches("[data-product]")) applyProduct(e.target);
    recalculate();
  });

  /* ------------------------------------------------- typing conveniences */

  // 1. Enter must NOT submit the bill half-finished. Inside the item table it
  //    moves to the next field, and from the last field it opens a new line.
  form.addEventListener("keydown", function (e) {
    if (e.key !== "Enter") return;

    var field = e.target;
    if (!field.matches("input, select")) return;
    if (field.type === "submit" || field.tagName === "TEXTAREA") return;

    e.preventDefault();

    var row = field.closest("[data-line]");
    if (!row) {
      // Header fields: jump to the first item field instead of submitting.
      var firstCell = rowsBody.querySelector("select, input");
      if (firstCell) firstCell.focus();
      return;
    }

    var cells = Array.prototype.slice.call(
      row.querySelectorAll('select, input[type="number"]')
    );
    var position = cells.indexOf(field);

    if (position > -1 && position < cells.length - 1) {
      cells[position + 1].focus();
      return;
    }

    // Last field of the last row: start the next line, like a till does.
    var rows = rowsBody.querySelectorAll('[data-line]:not([style*="display: none"])');
    if (row === rows[rows.length - 1]) {
      addLine();
    } else {
      var next = row.nextElementSibling;
      var target = next && next.querySelector("select, input");
      if (target) target.focus();
    }
  });

  // 2. Selecting the contents on focus means typing REPLACES the number that is
  //    already there. Without this, a field showing 50 becomes 5030 when
  //    someone types 30 without clearing it first.
  form.addEventListener("focusin", function (e) {
    if (e.target.matches('input[type="number"]')) {
      e.target.select();
    }
  });

  // 3. The mouse wheel over a focused number input silently changes its value,
  //    which is an easy way to corrupt a bill while scrolling the page.
  form.addEventListener("wheel", function (e) {
    if (e.target.matches('input[type="number"]') && document.activeElement === e.target) {
      e.target.blur();
    }
  }, { passive: true });

  // First paint
  rowsBody.querySelectorAll("[data-product]").forEach(applyProduct);
  recalculate();
})();
