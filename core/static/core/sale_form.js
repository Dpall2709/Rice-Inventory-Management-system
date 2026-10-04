/* ==========================================================================
   Sale invoice entry - live totals.

   Mirrors core/services/sale_service.py:

       line taxable   = bags x bag weight x rate
       line GST       = taxable x GST% (0 when the invoice has no GST)
       CGST/SGST or IGST from the chosen tax type
       invoice total  = rounded to whole rupees
       freight        = total kg / 1000 x rate per ton (not on the invoice)
       commission     = per bag / per quintal / % of taxable

   The server recalculates everything on save, and checks the stock - this is
   only so the person typing sees the invoice add up as they go.
   ========================================================================== */

(function () {
  "use strict";

  var form = document.getElementById("saleForm");
  if (!form) return;

  var data = JSON.parse(document.getElementById("sale-data").textContent || "{}");
  var text = JSON.parse(document.getElementById("sale-i18n").textContent || "{}");

  var rowsBody = document.getElementById("itemRows");
  var template = document.getElementById("emptyLine");
  var totalForms = form.querySelector('input[name$="-TOTAL_FORMS"]');
  var prefix = totalForms.name.replace("-TOTAL_FORMS", "");

  var taxSelect = form.querySelector("[data-tax-type]");
  var customerSelect = form.querySelector("[data-customer]");
  var brokerSelect = form.querySelector("[data-broker]");
  var commissionType = form.querySelector("[data-commission-type]");
  var commissionRate = form.querySelector("[data-commission-rate]");

  function money(n) {
    return (Math.round((Number(n) || 0) * 100) / 100).toFixed(2);
  }

  function inr(n) {
    return window.formatINR ? window.formatINR(n) : money(n);
  }

  function num(el) {
    return parseFloat((el && el.value) || 0) || 0;
  }

  function setAll(selector, value) {
    form.querySelectorAll(selector).forEach(function (el) { el.textContent = value; });
  }

  function setText(scope, selector, value) {
    var el = scope.querySelector(selector);
    if (el) el.textContent = value;
  }

  /* ---------------------------------------------------------- per line */

  function lineInfo(row) {
    var product = row.querySelector("[data-product]");
    var weight = row.querySelector('[data-cell="bag_weight"]');
    return {
      productId: product ? product.value : "",
      product: product && data.products ? data.products[product.value] : null,
      weight: weight ? String(parseInt(weight.value || 0, 10)) : "0",
    };
  }

  // Lots of one product that still have stock, oldest first.
  function lotsOf(productId, weight) {
    var result = [];
    Object.keys(data.lots || {}).forEach(function (id) {
      var lot = data.lots[id];
      if (String(lot.product) !== String(productId)) return;
      if (weight && String(lot.bag_weight) !== String(weight)) return;
      result.push(Object.assign({ id: id }, lot));
    });
    return result;
  }

  // Only lots of the chosen product and bag size make sense for a line.
  function refreshLots(row) {
    var select = row.querySelector("[data-lot]");
    if (!select) return;

    var info = lineInfo(row);
    var current = select.value;

    Array.prototype.forEach.call(select.options, function (opt) {
      if (!opt.value) return;
      var lot = data.lots && data.lots[opt.value];
      var fits = lot && String(lot.product) === info.productId && String(lot.bag_weight) === info.weight;
      if (lot) opt.textContent = lot.label;
      // Keep the saved lot visible on edit even if it no longer has stock.
      opt.hidden = !fits && opt.value !== current;
      opt.disabled = !lot && opt.value !== current;
    });

    if (current) {
      var chosen = data.lots && data.lots[current];
      if (chosen && (String(chosen.product) !== info.productId || String(chosen.bag_weight) !== info.weight)) {
        select.value = "";
      }
    }

    // Say which mill "oldest first" will take from, so the choice is visible.
    var auto = select.querySelector('option[value=""]');
    if (auto) {
      var fitting = info.productId ? lotsOf(info.productId, info.weight) : [];
      if (!auto.dataset.base) auto.dataset.base = auto.textContent;
      if (!info.productId) {
        auto.textContent = auto.dataset.base;
      } else if (fitting.length) {
        var first = fitting[0];
        auto.textContent = auto.dataset.base + " → " + first.mill + " · " + first.date +
          (fitting.length > 1 ? " (+" + (fitting.length - 1) + ")" : "");
      } else {
        auto.textContent = text.noLot || "No stock of this bag size";
      }
    }
  }

  function onProductChange(row) {
    var info = lineInfo(row);

    // The bag size must be one you actually have: if this product has no
    // stock in the size typed, switch to the size of its oldest lot.
    if (info.productId) {
      var weightInput = row.querySelector('[data-cell="bag_weight"]');
      var sameSize = lotsOf(info.productId, info.weight);
      var any = lotsOf(info.productId);
      if (weightInput && !sameSize.length && any.length) {
        weightInput.value = any[0].bag_weight;
        info = lineInfo(row);
      }
    }
    var gst = row.querySelector('[data-cell="gst"]');
    if (info.product && gst && !gst.dataset.touched) {
      gst.value = info.product.gst;
    }
    refreshLots(row);
    recalculate();
  }

  /* ---------------------------------------------------------- totals */

  function recalculate() {
    var taxType = taxSelect ? taxSelect.value : "cgst_sgst";

    var bags = 0, kg = 0, taxable = 0, gstTotal = 0, cost = 0;
    var askedPerStock = {};

    rowsBody.querySelectorAll("[data-line]").forEach(function (row) {
      var del = row.querySelector('input[type="checkbox"][name$="-DELETE"]');
      if (del && del.checked) {
        row.style.display = "none";
        return;
      }

      var info = lineInfo(row);
      var weight = num(row.querySelector('[data-cell="bag_weight"]'));
      var count = num(row.querySelector('[data-cell="bag_count"]'));
      var rate = num(row.querySelector('[data-cell="rate"]'));
      var gstPct = taxType === "none" ? 0 : num(row.querySelector('[data-cell="gst"]'));

      var lineKg = weight * count;
      var lineTaxable = Math.round(lineKg * rate * 100) / 100;
      var lineGst = Math.round(lineTaxable * gstPct) / 100;

      bags += count;
      kg += lineKg;
      taxable += lineTaxable;
      gstTotal += lineGst;

      setText(row, '[data-cell="kg"]', lineKg ? money(lineKg) : "0");
      setText(row, '[data-cell="taxable"]', inr(lineTaxable));
      setText(row, '[data-cell="line_total"]', inr(lineTaxable + lineGst));

      // Stock left for this rice and bag size, minus what earlier lines ask for.
      var stockCell = row.querySelector('[data-cell="stock"]');
      var hint = row.querySelector('[data-cell="hint"]');
      if (info.product) {
        var key = info.productId + ":" + info.weight;
        var inStock = (info.product.stock && info.product.stock[info.weight]) || 0;
        var usedBefore = askedPerStock[key] || 0;
        askedPerStock[key] = usedBefore + count;
        var left = inStock - usedBefore;

        if (stockCell) {
          var otherSizes = Object.keys(info.product.stock || {})
            .filter(function (w) { return w !== info.weight && info.product.stock[w] > 0; })
            .map(function (w) { return info.product.stock[w] + " × " + w + " kg"; });
          stockCell.textContent = left > 0
            ? left + " " + (text.bags || "bags")
            : (text.noStock || "none") + (otherSizes.length ? " (" + (text.inOther || "have") + " " + otherSizes.join(", ") + ")" : "");
          stockCell.classList.toggle("is-short", count > left);
          stockCell.title = count > left ? (text.notEnough || "") : "";
        }
        if (hint) {
          hint.textContent = info.product.cost_per_kg
            ? (text.suggested || "Your cost") + " ₹" + money(info.product.cost_per_kg) + "/kg · " +
              (text.sellAt || "sell at least") + " ₹" + money(info.product.suggested_per_kg)
            : "";
        }
        cost += lineKg * (info.product.cost_per_kg || 0);
      } else {
        if (stockCell) { stockCell.textContent = "—"; stockCell.classList.remove("is-short"); }
        if (hint) hint.textContent = "";
      }
    });

    var cgst = 0, sgst = 0, igst = 0;
    if (taxType === "cgst_sgst") {
      cgst = Math.round(gstTotal / 2 * 100) / 100;
      sgst = gstTotal - cgst;
    } else if (taxType === "igst") {
      igst = gstTotal;
    }

    var beforeRound = taxable + cgst + sgst + igst;
    var total = Math.round(beforeRound);
    var advance = num(form.querySelector("[data-advance]"));

    setAll('[data-total="bags"]', bags);
    setAll('[data-total="kg"]', money(kg));
    setAll('[data-total="taxable"]', inr(taxable));
    setAll('[data-total="lines"]', inr(beforeRound));

    setAll('[data-sum="bags"]', bags);
    setAll('[data-sum="kg"]', money(kg));
    setAll('[data-sum="taxable"]', inr(taxable));
    setAll('[data-sum="cgst"]', inr(cgst));
    setAll('[data-sum="sgst"]', inr(sgst));
    setAll('[data-sum="igst"]', inr(igst));
    setAll('[data-sum="round"]', money(total - beforeRound));
    setAll('[data-sum="total"]', inr(total));
    setAll('[data-sum="advance"]', inr(advance));
    setAll('[data-sum="due"]', inr(Math.max(total - advance, 0)));

    form.querySelectorAll("[data-tax-label]").forEach(function (el) {
      var which = el.getAttribute("data-tax-label");
      var show = (which === "igst" && taxType === "igst") ||
                 (which !== "igst" && taxType === "cgst_sgst");
      el.style.display = show ? "" : "none";
    });

    // Freight: total from the rate per ton, or the advance + balance when no rate.
    var ton = kg / 1000;
    var paidByUs = num(form.querySelector('[data-transport="dealer"]'));
    var paidByParty = num(form.querySelector('[data-transport="customer"]'));
    var freight = Math.round(ton * num(form.querySelector('[data-transport="rate"]')) * 100) / 100;
    if (!freight) freight = paidByUs + paidByParty;
    var freightBy = form.querySelector("[data-freight-by]");
    freightBy = freightBy ? freightBy.value : "us";
    setAll('[data-sum="ton"]', ton.toFixed(3));
    setAll('[data-sum="freight"]', inr(freight));
    setAll('[data-sum="freight_due"]', inr(Math.max(freight - paidByUs - paidByParty, 0)));
    setAll('[data-sum="freight_cut"]', inr(paidByParty));
    form.querySelectorAll("[data-freight-us]").forEach(function (el) { el.style.display = freightBy === "us" ? "" : "none"; });

    // Broker commission (on the dispatched weight here; settled on the received weight).
    var commission = 0;
    var hasBroker = brokerSelect && brokerSelect.value;
    if (hasBroker) {
      var rate = num(commissionRate);
      var type = commissionType ? commissionType.value : "per_bag";
      if (type === "per_bag") commission = rate * bags;
      else if (type === "per_quintal") commission = rate * kg / 100;
      else if (type === "percent") commission = taxable * rate / 100;
    }
    form.querySelectorAll("[data-broker-only]").forEach(function (el) {
      el.style.display = hasBroker ? "" : "none";
    });
    setAll('[data-sum="commission"]', inr(commission));

    // What the party will actually pay, and your profit on the truck.
    var cdPct = num(form.querySelector("[data-cd]"));
    var cd = Math.round(total * cdPct) / 100;
    var brokerPaidBy = form.querySelector("[data-broker-paid-by]");
    var collectFrom = form.querySelector("[data-collect-from]");
    var brokerCollects = hasBroker && collectFrom && collectFrom.value === "broker";
    var partyPaysBroker = hasBroker && ((brokerPaidBy && brokerPaidBy.value === "customer") || brokerCollects);
    var brokerageCut = partyPaysBroker ? commission : 0;
    var commissionUs = partyPaysBroker ? 0 : commission;
    var freightAdj = freightBy === "us" ? -paidByParty : (freightBy === "customer" ? paidByUs : 0);
    var net = total - cd - brokerageCut + freightAdj;
    // Loading charge = weight x the company's loading rate, until typed by hand.
    var loadingInput = form.querySelector("[data-loading]");
    var weighbridge = num(form.querySelector("[data-loading-weight]"));
    if (loadingInput && !loadingInput.dataset.touched && data.loading_rate) {
      loadingInput.value = (Math.round((weighbridge || kg) * data.loading_rate * 100) / 100).toFixed(2);
    }
    var loading = num(loadingInput);
    var freightCost = freightBy === "us" ? freight : 0;
    var income = taxable - cd - brokerageCut;

    setAll('[data-sum="cd"]', inr(cd));
    setAll('[data-sum="brokerage_cut"]', inr(brokerageCut));
    setAll('[data-sum="freight_adj"]', (freightAdj < 0 ? "− " : "+ ") + inr(Math.abs(freightAdj)));
    setAll('[data-sum="net"]', inr(net));
    setAll('[data-sum="due"]', inr(Math.max(net - advance, 0)));
    form.querySelectorAll("[data-show-cd]").forEach(function (el) { el.style.display = cd ? "" : "none"; });
    form.querySelectorAll("[data-show-brokerage-cut]").forEach(function (el) { el.style.display = brokerageCut ? "" : "none"; });
    form.querySelectorAll("[data-show-freight-adj]").forEach(function (el) { el.style.display = freightAdj ? "" : "none"; });

    var profit = income - cost - loading - freightCost - commissionUs;
    setAll('[data-sum="income"]', inr(income));
    setAll('[data-sum="cost"]', inr(cost));
    setAll('[data-sum="loading"]', inr(loading));
    setAll('[data-sum="freight_cost"]', inr(freightCost));
    setAll('[data-sum="commission2"]', inr(commissionUs));
    setAll('[data-sum="profit"]', inr(profit));
    var profitLine = form.querySelector('[data-sum="profit"]');
    if (profitLine) profitLine.closest(".sell-line").classList.toggle("is-loss", profit < 0);
  }

  /* ---------------------------------------------------------- customer */

  function showCustomer(fillTax) {
    var card = form.querySelector("[data-buyer]");
    var customer = customerSelect && data.customers ? data.customers[customerSelect.value] : null;
    if (!card) return;

    if (!customer) {
      card.hidden = true;
      return;
    }

    card.hidden = false;
    setText(card, "[data-buyer-name]", customer.name);
    setText(card, "[data-buyer-address]", customer.address || "—");
    setText(card, "[data-buyer-gst]", customer.gst || "—");
    setText(card, "[data-buyer-state]", customer.state || "—");
    setText(card, "[data-buyer-shipping]", customer.shipping || customer.address || "—");

    var cdInput = form.querySelector("[data-cd]");
    var viaBroker = brokerSelect && brokerSelect.value;
    if (fillTax && cdInput && !cdInput.dataset.touched && !viaBroker) {
      cdInput.value = customer.cd || 0;
    }

    // Same state -> CGST + SGST, other state -> IGST. Never undo "No GST".
    if (fillTax && taxSelect && taxSelect.value !== "none" && customer.tax_type) {
      taxSelect.value = customer.tax_type;
    }
  }

  function onBrokerChange(fill) {
    var broker = brokerSelect && data.brokers ? data.brokers[brokerSelect.value] : null;
    var collectFrom = form.querySelector("[data-collect-from]");
    var cdInput = form.querySelector("[data-cd]");
    if (fill) {
      if (broker) {
        if (commissionType) commissionType.value = broker.type;
        if (commissionRate) commissionRate.value = broker.rate;
        // A broker sale: he collects, cuts his brokerage and the CD.
        if (collectFrom) collectFrom.value = "broker";
        if (cdInput && !cdInput.dataset.touched) cdInput.value = broker.cd || 0;
      } else {
        // Direct sale: the customer pays, no brokerage; CD only if the customer takes one.
        if (collectFrom) collectFrom.value = "customer";
        var customer = customerSelect && data.customers ? data.customers[customerSelect.value] : null;
        if (cdInput && !cdInput.dataset.touched) cdInput.value = customer ? (customer.cd || 0) : 0;
      }
    }
    recalculate();
  }

  /* ---------------------------------------------------------- add/remove lines */

  function addLine() {
    var index = parseInt(totalForms.value, 10);
    var html = template.innerHTML.replace(/__prefix__/g, index);
    var tmp = document.createElement("tbody");
    tmp.innerHTML = html.trim();
    var row = tmp.firstElementChild;
    rowsBody.appendChild(row);
    totalForms.value = index + 1;
    refreshLots(row);
    recalculate();
    var first = row.querySelector("select, input");
    if (first) first.focus();
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
      var visible = rowsBody.querySelectorAll('[data-line]:not([style*="display: none"])').length;
      if (visible <= 1) {
        row.querySelectorAll("input:not([type=hidden]):not([type=checkbox]), select").forEach(function (el) {
          if (el.matches('[data-cell="bag_weight"]')) el.value = 50;
          else el.value = "";
        });
      } else if (del) {
        del.checked = true;
      }
      recalculate();
    }
  });

  form.addEventListener("input", function (e) {
    if (e.target.matches('[data-cell="gst"]') || e.target.matches("[data-cd]") || e.target.matches("[data-loading]")) e.target.dataset.touched = "1";
    if (e.target.matches('[data-cell="bag_weight"]')) refreshLots(e.target.closest("[data-line]"));
    recalculate();
  });

  form.addEventListener("change", function (e) {
    var target = e.target;
    if (target.matches("[data-product]")) onProductChange(target.closest("[data-line]"));
    else if (target === customerSelect) { showCustomer(true); recalculate(); }
    else if (target === brokerSelect) onBrokerChange(true);
    else recalculate();
  });

  // Rows coming back from a failed save (or an invoice being edited) keep
  // the GST already on them; a fresh row takes it from the product.
  rowsBody.querySelectorAll("[data-line]").forEach(function (row) {
    var gst = row.querySelector('[data-cell="gst"]');
    var product = row.querySelector("[data-product]");
    if (gst && product && product.value && gst.value !== "") gst.dataset.touched = "1";
    refreshLots(row);
  });

  showCustomer(false);
  onBrokerChange(brokerSelect && brokerSelect.value && commissionRate && commissionRate.value === "");
  recalculate();
})();
