/* Trade Trace Console — timezone toggle, refresh button, optional
   N-second polling, and filter-state URL encoding. All client-
   side only; no server-side preference writes hit the journal DB
   (the read-only contract from console.md §6 and §9–§10).

   This file is intentionally framework-free vanilla JS. The
   Console's only JS dep is htmx, which lives in
   /static/js/htmx.min.js.
*/

(function () {
  "use strict";

  var TZ_KEY = "trade-trace-console.tz";
  var POLL_KEY = "trade-trace-console.poll";

  function readTzPreference() {
    try {
      return window.localStorage.getItem(TZ_KEY) || "utc";
    } catch (e) {
      return "utc";
    }
  }

  function writeTzPreference(value) {
    try {
      window.localStorage.setItem(TZ_KEY, value);
    } catch (e) {
      /* private window etc. — preference is session-only */
    }
  }

  function applyTzToAllTimestamps(tz) {
    var nodes = document.querySelectorAll("time[data-ts]");
    for (var i = 0; i < nodes.length; i++) {
      var node = nodes[i];
      var iso = node.getAttribute("data-ts");
      if (!iso) continue;
      var date = new Date(iso);
      if (isNaN(date.getTime())) continue;
      if (tz === "local") {
        node.textContent = date.toLocaleString();
      } else {
        node.textContent = date.toISOString();
      }
    }
    document.documentElement.setAttribute("data-tz", tz);
  }

  function currentRoute() {
    return window.location.pathname || "/";
  }

  function syncActiveNav() {
    var route = currentRoute();
    var links = document.querySelectorAll("[data-nav-route]");
    for (var i = 0; i < links.length; i++) {
      var link = links[i];
      var target = link.getAttribute("data-nav-route") || "/";
      var active = target === "/" ? route === "/" : route.indexOf(target) === 0;
      if (active) {
        link.setAttribute("aria-current", "page");
      } else {
        link.removeAttribute("aria-current");
      }
    }
    document.body.setAttribute("data-route", route);
  }

  function setupMobileNav() {
    var toggle = document.querySelector("[data-nav-toggle]");
    var nav = document.querySelector(".tt-nav");
    if (!toggle || !nav) return;
    toggle.addEventListener("click", function () {
      var open = nav.getAttribute("data-open") !== "true";
      nav.setAttribute("data-open", open ? "true" : "false");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
    nav.addEventListener("click", function (ev) {
      if (ev.target && ev.target.tagName === "A") {
        nav.setAttribute("data-open", "false");
        toggle.setAttribute("aria-expanded", "false");
      }
    });
  }

  function syncTzToggle() {
    var tz = readTzPreference();
    var radios = document.querySelectorAll("input[name='tt-tz']");
    for (var i = 0; i < radios.length; i++) {
      if (radios[i].value === tz) radios[i].checked = true;
      radios[i].addEventListener("change", function (ev) {
        writeTzPreference(ev.target.value);
        applyTzToAllTimestamps(ev.target.value);
      });
    }
    applyTzToAllTimestamps(tz);
  }

  function refreshNow() {
    /* htmx is loaded with `defer`; prefer a main-region refresh
       so global controls and preferences stay stable. */
    if (window.htmx && document.querySelector("#tt-main")) {
      window.htmx.ajax("GET", window.location.pathname + window.location.search, {
        target: "#tt-main",
        select: "#tt-main > *",
        swap: "innerHTML"
      });
    } else {
      window.location.reload();
    }
    document.body.setAttribute("data-last-refresh", new Date().toISOString());
  }

  function setupRefreshButton() {
    var btn = document.querySelector("button[data-refresh]");
    if (btn) btn.addEventListener("click", refreshNow);
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "r" && !ev.metaKey && !ev.ctrlKey && !ev.altKey) {
        var tag = (ev.target && ev.target.tagName) || "";
        if (tag !== "INPUT" && tag !== "TEXTAREA") refreshNow();
      }
    });
  }

  function setupPollControl() {
    var select = document.querySelector("select[data-poll-interval]");
    if (!select) return;
    var initial;
    try { initial = window.localStorage.getItem(POLL_KEY) || "0"; } catch (e) { initial = "0"; }
    select.value = initial;
    var pollHandle = null;
    function applyPoll(value) {
      if (pollHandle) { clearInterval(pollHandle); pollHandle = null; }
      var n = parseInt(value, 10) || 0;
      if (n > 0) pollHandle = setInterval(refreshNow, n * 1000);
    }
    applyPoll(select.value);
    select.addEventListener("change", function (ev) {
      try { window.localStorage.setItem(POLL_KEY, ev.target.value); } catch (e) {}
      applyPoll(ev.target.value);
    });
  }

  /* Filter forms use normal GET query parameters so the server sees
     them, rendered rows update from route handlers, and copied URLs are
     shareable. Keep this hook only to normalize empty values before
     submission; do not intercept submit or write hash state. */
  function setupFilterState() {
    var forms = document.querySelectorAll("form[data-filter-form]");
    for (var i = 0; i < forms.length; i++) {
      var form = forms[i];
      if (form.getAttribute("data-filter-bound") === "true") continue;
      form.setAttribute("data-filter-bound", "true");
      form.addEventListener("submit", function (ev) {
        var inputs = ev.target.querySelectorAll("input[name], select[name], textarea[name]");
        for (var j = 0; j < inputs.length; j++) {
          if (inputs[j].value === "") inputs[j].disabled = true;
        }
      });
    }
  }

  function setupCopyButtons() {
    document.addEventListener("click", function (ev) {
      var btn = ev.target && ev.target.closest && ev.target.closest("[data-copy-target]");
      if (!btn) return;
      var id = btn.getAttribute("data-copy-target");
      var target = id ? document.getElementById(id) : null;
      if (!target || !navigator.clipboard) return;
      navigator.clipboard.writeText(target.textContent || "").then(function () {
        var old = btn.textContent;
        btn.textContent = "Copied";
        window.setTimeout(function () { btn.textContent = old; }, 1200);
      }).catch(function () {});
    });
  }

  function afterContentSwap() {
    applyTzToAllTimestamps(readTzPreference());
    setupFilterState();
    syncActiveNav();
  }

  document.addEventListener("DOMContentLoaded", function () {
    syncActiveNav();
    setupMobileNav();
    syncTzToggle();
    setupRefreshButton();
    setupPollControl();
    setupFilterState();
    setupCopyButtons();
  });

  document.addEventListener("htmx:afterSwap", afterContentSwap);
  window.addEventListener("popstate", function () {
    window.setTimeout(syncActiveNav, 0);
  });
})();
