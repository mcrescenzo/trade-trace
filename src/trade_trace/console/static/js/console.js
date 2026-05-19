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
    /* htmx is loaded with `defer`, so dispatch a synthetic event
       so any element with `hx-trigger="manual"` refreshes. Falls
       back to a full reload if htmx didn't load. */
    if (window.htmx) {
      window.htmx.trigger(document.body, "tt:refresh");
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

  /* Filter state lives in the URL hash, so reload/share works
     without any server-side preference write. Forms with
     `data-filter-form` push their fields onto location.hash on
     submit and rehydrate on page load. */
  function setupFilterState() {
    function decodeHash() {
      var raw = window.location.hash.replace(/^#/, "");
      if (!raw) return {};
      var out = {};
      var pairs = raw.split("&");
      for (var i = 0; i < pairs.length; i++) {
        var kv = pairs[i].split("=");
        if (kv.length === 2) {
          out[decodeURIComponent(kv[0])] = decodeURIComponent(kv[1]);
        }
      }
      return out;
    }
    var state = decodeHash();
    var forms = document.querySelectorAll("form[data-filter-form]");
    for (var i = 0; i < forms.length; i++) {
      var form = forms[i];
      for (var key in state) {
        var input = form.querySelector("[name='" + key + "']");
        if (input) input.value = state[key];
      }
      form.addEventListener("submit", function (ev) {
        ev.preventDefault();
        var data = new FormData(ev.target);
        var parts = [];
        data.forEach(function (value, name) {
          if (value) parts.push(encodeURIComponent(name) + "=" + encodeURIComponent(value));
        });
        window.location.hash = parts.join("&");
        refreshNow();
      });
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    syncTzToggle();
    setupRefreshButton();
    setupPollControl();
    setupFilterState();
  });
})();
