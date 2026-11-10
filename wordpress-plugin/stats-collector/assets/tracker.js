/* Stats Collector: cookieless counting. Sends one view, then visible reading time, "read" and share clicks. */
(function () {
  "use strict";
  var c = window.scConfig;
  if (!c || !window.fetch || navigator.webdriver) return;
  var token = null, seconds = 0, read = false, shares = 0, last = Date.now(), active = Date.now(), maxScroll = 0, sent = "";

  function send(force) {
    if (!token) return;
    var body = JSON.stringify({ t: token, s: Math.round(seconds), r: read ? 1 : 0, sh: shares });
    if (body === sent && !force) return;
    sent = body;
    if (navigator.sendBeacon) navigator.sendBeacon(c.engage, new Blob([body], { type: "text/plain" }));
    else fetch(c.engage, { method: "POST", body: body, keepalive: true, credentials: "omit" });
  }

  function tick() {
    var now = Date.now();
    // Count time only while the tab is visible and the reader did something in the last 30 seconds.
    if (!document.hidden && now - active < 30000) seconds += Math.min(now - last, 5000) / 1000;
    last = now;
    var doc = document.documentElement;
    var depth = (window.scrollY + window.innerHeight) / Math.max(doc.scrollHeight, 1);
    maxScroll = Math.max(maxScroll, depth);
    // Read: 30 seconds of reading, or scrolled through three quarters of the page in at least 10 seconds.
    if (seconds >= 30 || (maxScroll >= 0.75 && seconds >= 10)) read = true;
  }

  ["scroll", "mousemove", "keydown", "touchstart", "click"].forEach(function (e) {
    window.addEventListener(e, function () { active = Date.now(); }, { passive: true });
  });

  var SHARE = /facebook\.com\/(sharer|share)|twitter\.com\/(intent|share)|x\.com\/intent|wa\.me\/|api\.whatsapp\.com\/send|linkedin\.com\/(sharing|shareArticle)|t\.me\/share|bsky\.app\/intent|reddit\.com\/submit|pinterest\.com\/pin\/create|^mailto:.*body=/i;
  document.addEventListener("click", function (e) {
    var el = e.target && e.target.closest ? e.target.closest("a,button,[data-sc-share]") : null;
    if (!el) return;
    var href = el.getAttribute("href") || "";
    if (el.hasAttribute("data-sc-share") || SHARE.test(href)) { shares += 1; send(true); }
  }, true);

  fetch(c.view, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "omit",
    body: JSON.stringify({ post: c.post, ref: document.referrer || "" }),
  }).then(function (r) { return r.json(); }).then(function (d) {
    token = d && d.t;
    if (!token) return;
    setInterval(tick, 1000);
    setInterval(function () { send(false); }, 15000);
    document.addEventListener("visibilitychange", function () { if (document.hidden) { tick(); send(true); } });
    window.addEventListener("pagehide", function () { tick(); send(true); });
  }).catch(function () {});
})();
