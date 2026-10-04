/* ==========================================================================
   Repeating item rows for the purchase and sale forms.

   The previous version of this file contained Django template tags
   ({% for product in products %}) inside a STATIC file, which the browser
   never renders - so every dropdown it created was empty. The options are now
   read from a <template id="rowTemplate"> element rendered by Django, which is
   the correct way to do this.
   ========================================================================== */

(function () {
  "use strict";

  var rowIndex = 0;

  function recalc() {
    var grand = 0;

    document.querySelectorAll("[data-item-row]").forEach(function (row) {
      var weight = parseFloat(row.querySelector('[name="bag_weight[]"]')?.value || 0);
      var count = parseFloat(row.querySelector('[name="bag_count[]"]')?.value || 0);
      var rate = parseFloat(row.querySelector('[name="purchase_price[]"]')?.value || 0);

      var kg = weight * count;
      var total = kg * rate;

      var kgCell = row.querySelector("[data-row-kg]");
      var totalCell = row.querySelector("[data-row-total]");
      if (kgCell) kgCell.textContent = kg ? kg.toFixed(2) : "0";
      if (totalCell) {
        totalCell.textContent = window.formatINR ? window.formatINR(total) : total.toFixed(2);
      }

      grand += total;
    });

    var grandCell = document.querySelector("[data-grand-total]");
    if (grandCell) {
      grandCell.textContent = window.formatINR ? window.formatINR(grand) : grand.toFixed(2);
    }

    var grandInput = document.querySelector('[name="total_amount"]');
    if (grandInput) grandInput.value = grand.toFixed(2);
  }

  function addRow() {
    var template = document.getElementById("rowTemplate");
    var tbody = document.querySelector("[data-item-rows]");
    if (!template || !tbody) return;

    var fragment = template.content.cloneNode(true);
    tbody.appendChild(fragment);
    rowIndex++;
    recalc();
  }

  document.addEventListener("click", function (e) {
    if (e.target.closest("[data-add-row]")) {
      e.preventDefault();
      addRow();
    }

    var remove = e.target.closest("[data-remove-row]");
    if (remove) {
      e.preventDefault();
      var rows = document.querySelectorAll("[data-item-row]");
      if (rows.length <= 1) return;           // never leave the form with no rows
      remove.closest("[data-item-row]").remove();
      recalc();
    }
  });

  document.addEventListener("input", function (e) {
    if (e.target.closest("[data-item-row]")) recalc();
  });

  document.addEventListener("DOMContentLoaded", function () {
    if (document.querySelector("[data-item-rows]")) {
      if (!document.querySelector("[data-item-row]")) addRow();
      recalc();
    }
  });

  window.addItemRow = addRow;   // kept for any inline onclick still in a template
})();
