/* ==========================================================================
   Rice Billing App - interface behaviour
   Plain JavaScript, no framework, no build step.

   Handles: light/dark theme, sidebar collapse, mobile drawer, user menu,
   toasts, confirm dialogs, instant table search, Indian money formatting,
   and the "saving..." state on submit buttons.
   ========================================================================== */

(function () {
  "use strict";

  var root = document.documentElement;
  var body = document.body;

  function on(selector, event, handler) {
    document.addEventListener(event, function (e) {
      var el = e.target.closest(selector);
      if (el) handler(e, el);
    });
  }

  function store(key, value) {
    try { localStorage.setItem(key, value); } catch (e) {}
  }

  function read(key) {
    try { return localStorage.getItem(key); } catch (e) { return null; }
  }

  /* ---------------------------------------------------------------- theme */

  function currentTheme() {
    var set = root.getAttribute("data-theme");
    if (set) return set;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  function paintThemeButton() {
    var dark = currentTheme() === "dark";
    document.querySelectorAll("[data-toggle-theme]").forEach(function (btn) {
      btn.textContent = dark ? "☀️" : "🌙";
      btn.title = dark ? "Switch to light mode" : "Switch to dark mode";
    });
  }

  on("[data-toggle-theme]", "click", function () {
    var next = currentTheme() === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", next);
    store("theme", next);
    paintThemeButton();
  });

  /* -------------------------------------------------------------- sidebar */

  if (read("sidebar") === "collapsed") body.classList.add("sidebar-collapsed");

  on("[data-toggle-sidebar]", "click", function () {
    body.classList.toggle("sidebar-collapsed");
    store("sidebar", body.classList.contains("sidebar-collapsed") ? "collapsed" : "open");
  });

  // Mobile drawer
  on("[data-toggle-nav]", "click", function () {
    body.classList.toggle("nav-open");
  });

  on("[data-close-nav]", "click", function () {
    body.classList.remove("nav-open");
  });

  /* ------------------------------------------------------------ user menu */

  var userMenu = document.getElementById("userMenu");

  on("[data-toggle-user-menu]", "click", function (e) {
    e.stopPropagation();
    if (userMenu) userMenu.hidden = !userMenu.hidden;
  });

  document.addEventListener("click", function (e) {
    if (!userMenu || userMenu.hidden) return;
    if (!e.target.closest(".user-menu-wrap")) userMenu.hidden = true;
  });

  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    if (userMenu) userMenu.hidden = true;
    body.classList.remove("nav-open");
    closeConfirm();
  });

  /* --------------------------------------------------------------- toasts */

  on("[data-close-toast]", "click", function (e, btn) {
    btn.closest(".msg").remove();
  });

  // Success and info messages disappear on their own; errors and warnings stay
  // until the user dismisses them, because they usually need an action.
  document.querySelectorAll(".msg").forEach(function (msg) {
    if (msg.classList.contains("error") || msg.classList.contains("warning")) return;
    setTimeout(function () {
      msg.style.transition = "opacity 300ms, transform 300ms";
      msg.style.opacity = "0";
      msg.style.transform = "translateX(16px)";
      setTimeout(function () { msg.remove(); }, 300);
    }, 5000);
  });

  /* ------------------------------------------------------- confirm dialog */

  var modal = document.getElementById("confirmModal");
  var confirmTitle = document.getElementById("confirmTitle");
  var confirmText = document.getElementById("confirmText");
  var pending = null;

  function closeConfirm() {
    if (modal) modal.hidden = true;
    pending = null;
  }

  // Any element with data-confirm="message" asks first.
  on("[data-confirm]", "click", function (e, el) {
    if (!modal) return;
    e.preventDefault();
    pending = el;
    confirmTitle.textContent = el.getAttribute("data-confirm-title") || "Please confirm";
    confirmText.textContent = el.getAttribute("data-confirm");
    modal.hidden = false;
  });

  on("[data-confirm-cancel]", "click", closeConfirm);

  on("[data-confirm-ok]", "click", function () {
    if (!pending) return closeConfirm();
    var el = pending;
    pending = null;
    if (modal) modal.hidden = true;

    el.removeAttribute("data-confirm");

    if (el.tagName === "FORM") {
      el.submit();
      return;
    }

    if (el.form) {
      // form.submit() does not include the clicked button's name/value, so a
      // button like <button name="action" value="delete"> would lose its
      // instruction. Carry it across in a hidden field.
      if (el.name) {
        var hidden = document.createElement("input");
        hidden.type = "hidden";
        hidden.name = el.name;
        hidden.value = el.value || "";
        el.form.appendChild(hidden);
      }
      el.form.submit();
      return;
    }

    el.click();
  });

  /* -------------------------------------------------- instant table search */

  // <input data-filter="#tableId"> hides rows that do not match as you type.
  on("[data-filter]", "input", function (e, input) {
    var table = document.querySelector(input.getAttribute("data-filter"));
    if (!table) return;

    var needle = input.value.trim().toLowerCase();
    var shown = 0;

    table.querySelectorAll("tbody tr").forEach(function (row) {
      if (row.hasAttribute("data-empty-row")) return;
      var match = row.textContent.toLowerCase().indexOf(needle) !== -1;
      row.hidden = !match;
      if (match) shown++;
    });

    var counter = document.querySelector("[data-filter-count]");
    if (counter) counter.textContent = shown;
  });

  /* ------------------------------------------------------ money formatting */

  // Indian grouping: 12,34,567.89 - applied to any <span class="inr" data-value="...">
  function formatINR(value) {
    var number = Number(value || 0);
    if (isNaN(number)) return value;
    return number.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  window.formatINR = formatINR;

  document.querySelectorAll(".inr[data-value]").forEach(function (el) {
    el.textContent = "₹ " + formatINR(el.getAttribute("data-value"));
  });

  /* --------------------------------------------------- submit button state */

  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (form.hasAttribute("data-no-loading")) return;

    var button = form.querySelector('button[type="submit"], input[type="submit"]');
    if (!button || button.classList.contains("is-loading")) return;

    // Let the browser's own required-field check win first.
    if (typeof form.checkValidity === "function" && !form.checkValidity()) return;

    button.classList.add("is-loading");
    button.disabled = true;

    // If the page does not navigate (validation error returned), release it.
    setTimeout(function () {
      button.classList.remove("is-loading");
      button.disabled = false;
    }, 8000);
  });

  /* ------------------------------------------------------------- shortcuts */

  document.addEventListener("keydown", function (e) {
    if (e.target.matches("input, textarea, select")) return;

    // "/" focuses the first search box on the page.
    if (e.key === "/") {
      var search = document.querySelector('[data-filter], input[name="q"]');
      if (search) {
        e.preventDefault();
        search.focus();
      }
    }
  });

  paintThemeButton();
})();
