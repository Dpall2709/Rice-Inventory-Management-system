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
      // The template supplies the translated titles; English is the fallback.
      btn.title = dark
        ? (btn.getAttribute("data-title-light") || "Switch to light mode")
        : (btn.getAttribute("data-title-dark") || "Switch to dark mode");
    });
  }

  on("[data-toggle-theme]", "click", function () {
    var next = currentTheme() === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", next);
    store("theme", next);
    paintThemeButton();
  });

  /* ------------------------------------------------------------ back button */

  // The browser's own history is the wrong thing to follow here: after saving a
  // payment it would take you straight back into the payment form you just
  // submitted. Instead the app keeps a short trail of the pages you actually
  // browse (lists, ledgers, bills) and leaves forms out of it, so Back always
  // lands on a page you would want to see again.

  var TRAIL_KEY = "rb:trail";
  var isFormPage = body.getAttribute("data-nav") === "form";

  function here() {
    return window.location.pathname + window.location.search;
  }

  function readTrail() {
    try {
      var saved = JSON.parse(window.sessionStorage.getItem(TRAIL_KEY));
      return Array.isArray(saved) ? saved : [];
    } catch (e) {
      return [];
    }
  }

  function writeTrail(trail) {
    try {
      window.sessionStorage.setItem(TRAIL_KEY, JSON.stringify(trail.slice(-40)));
    } catch (e) {}
  }

  // Record this page, unless it is a form.
  if (!isFormPage) {
    var trail = readTrail();
    var current = here();

    // Reloading, or landing back here after saving a form, changes nothing.
    if (trail[trail.length - 1] !== current) {
      var seenAt = trail.lastIndexOf(current);
      var entry = (window.performance && performance.getEntriesByType)
        ? performance.getEntriesByType("navigation")[0]
        : null;
      var viaBrowserBack = entry && entry.type === "back_forward";

      if (viaBrowserBack && seenAt !== -1) {
        // The browser's own Back button: step back along the trail.
        trail = trail.slice(0, seenAt + 1);
      } else {
        // Clicked through to a page seen earlier: it is now the latest page,
        // and the page you came from stays behind it.
        if (seenAt !== -1) {
          trail.splice(seenAt, 1);
        }
        trail.push(current);
      }
      writeTrail(trail);
    }
  }

  on("[data-back]", "click", function (e, button) {
    e.preventDefault();

    var trail = readTrail();
    var current = here();
    var at = trail.lastIndexOf(current);

    // Step off the current page (a form page is not on the trail at all, so
    // the last entry is exactly the page the form was opened from).
    if (at !== -1) {
      trail = trail.slice(0, at);
    }

    var target = trail.length ? trail[trail.length - 1] : button.getAttribute("data-back-fallback") || "/";
    writeTrail(trail);
    window.location.href = target;
  });

  // Alt + ArrowLeft does the same thing from the keyboard.
  document.addEventListener("keydown", function (e) {
    if (e.altKey && e.key === "ArrowLeft" && !e.target.matches("input, textarea, select")) {
      var button = document.querySelector("[data-back]");
      if (button) {
        e.preventDefault();
        button.click();
      }
    }
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
    confirmTitle.textContent = el.getAttribute("data-confirm-title")
      || modal.getAttribute("data-default-title")
      || "Please confirm";
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

  // The same, without the sign - for an advance, which is shown as "₹ X adv".
  document.querySelectorAll(".inr-abs[data-value]").forEach(function (el) {
    el.textContent = formatINR(Math.abs(Number(el.getAttribute("data-value"))));
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
