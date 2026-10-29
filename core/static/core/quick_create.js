/* ==========================================================================
   Quick create - add a customer, supplier or product from a sale or
   purchase screen without leaving it.

   A button such as

       <button type="button" data-quick-create="customer"
               data-quick-url="/quick/customer/" data-quick-target="#id_customer">

   opens a pop-up with the form from the server. On save the new record is
   added to the target dropdown (and to every other dropdown of the same
   kind, e.g. all product selects on the lines) and selected. A
   "quick-created" event is then fired on the document with
   { kind, id, label, data, select } so the page script can store the extra
   details (GST, state, pack size...) it uses to fill other fields.
   ========================================================================== */

(function () {
  "use strict";

  var backdrop = null;
  var body = null;
  var current = null;   // { kind, url, select }

  function ensureModal() {
    if (backdrop) return;
    backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    backdrop.hidden = true;
    backdrop.innerHTML = '<div class="modal modal-wide" role="dialog" aria-modal="true"><div data-quick-body></div></div>';
    document.body.appendChild(backdrop);
    body = backdrop.querySelector("[data-quick-body]");

    backdrop.addEventListener("click", function (e) {
      if (e.target === backdrop || e.target.closest("[data-quick-cancel]")) close();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !backdrop.hidden) close();
    });
    backdrop.addEventListener("submit", function (e) {
      if (!e.target.matches("[data-quick-form]")) return;
      e.preventDefault();
      submit(e.target);
    });
  }

  function close() {
    if (!backdrop) return;
    backdrop.hidden = true;
    body.innerHTML = "";
    if (current && current.select) current.select.focus();
    current = null;
  }

  function show(html) {
    body.innerHTML = html;
    backdrop.hidden = false;
    var first = body.querySelector("input:not([type=hidden]), select, textarea");
    if (first) first.focus();
  }

  function open(button) {
    ensureModal();
    var targetSel = button.getAttribute("data-quick-target");
    var select = null;
    if (targetSel === "row") {
      var row = button.closest("[data-line]");
      select = row ? row.querySelector("select[data-product]") : null;
    } else if (targetSel) {
      select = document.querySelector(targetSel);
    }
    current = { kind: button.getAttribute("data-quick-create"), url: button.getAttribute("data-quick-url"), select: select };

    show('<p class="muted">…</p>');
    fetch(current.url, { headers: { "X-Requested-With": "fetch" }, credentials: "same-origin" })
      .then(function (r) { return r.text(); })
      .then(show)
      .catch(function () { close(); });
  }

  function addOption(select, id, label) {
    var exists = select.querySelector('option[value="' + id + '"]');
    if (!exists) {
      var opt = document.createElement("option");
      opt.value = id;
      opt.textContent = label;
      select.appendChild(opt);
    }
  }

  function submit(formEl) {
    var button = formEl.querySelector('[type="submit"]');
    if (button) button.disabled = true;

    fetch(current.url, {
      method: "POST",
      body: new FormData(formEl),
      headers: { "X-Requested-With": "fetch" },
      credentials: "same-origin",
    }).then(function (response) {
      var type = response.headers.get("Content-Type") || "";
      if (response.ok && type.indexOf("application/json") !== -1) {
        return response.json().then(done);
      }
      return response.text().then(show);   // the form again, with its errors
    }).catch(function () {
      if (button) button.disabled = false;
    });
  }

  function done(result) {
    var kind = current.kind;
    var select = current.select;

    // Every dropdown of this kind gets the new option, including the
    // template used for new lines, so later lines can pick it too.
    document.querySelectorAll('[data-quick-kind="' + kind + '"]').forEach(function (el) {
      addOption(el, result.id, result.label);
    });
    document.querySelectorAll("template").forEach(function (tpl) {
      tpl.content.querySelectorAll('[data-quick-kind="' + kind + '"]').forEach(function (el) {
        addOption(el, result.id, result.label);
      });
    });

    var detail = { kind: kind, id: String(result.id), label: result.label, data: result.data || {}, select: select };
    document.dispatchEvent(new CustomEvent("quick-created", { detail: detail }));

    if (select) {
      addOption(select, result.id, result.label);
      select.value = String(result.id);
      select.dispatchEvent(new Event("change", { bubbles: true }));
    }
    close();
  }

  document.addEventListener("click", function (e) {
    var button = e.target.closest("[data-quick-create]");
    if (!button) return;
    e.preventDefault();
    open(button);
  });
})();
