// Loads the vendored RudderStack SDK against this server and wires the demo buttons.
// The source config is supplied locally (getSourceConfig), so the SDK makes no request to
// RudderStack's servers; events go to <this origin>/v1/<type>.
(function () {
  "use strict";
  var config = JSON.parse(document.getElementById("sdk-config").textContent);
  var status = document.getElementById("sdk-status");
  var log = document.getElementById("sent-log");
  var buttons = document.querySelectorAll("[data-send]");

  function setStatus(tag, tagClass, text) {
    status.innerHTML = "";
    var span = document.createElement("span");
    span.className = "tag " + tagClass;
    span.textContent = tag;
    status.appendChild(span);
    status.appendChild(document.createTextNode(" " + text));
  }

  function note(text) {
    var item = document.createElement("li");
    var time = document.createElement("span");
    time.className = "mono";
    time.textContent = new Date().toISOString().slice(11, 19) + " UTC ";
    item.appendChild(time);
    item.appendChild(document.createTextNode(text));
    log.prepend(item);
    log.hidden = false;
  }

  var analytics;
  var ready = false;
  try {
    analytics = new window.rudderanalytics.RudderAnalytics();
    analytics.load(config.writeKey, config.dataPlaneUrl, {
      getSourceConfig: function () {
        return {
          source: { id: "local-demo", name: "Local demo", enabled: true, config: {}, destinations: [] },
        };
      },
      polyfillIfRequired: false,
      logLevel: "WARN",
    });
    analytics.ready(function () {
      ready = true;
      buttons.forEach(function (b) { b.disabled = false; });
      setStatus("✓ Ready", "tag-accepted", "SDK loaded. Events go to " + config.dataPlaneUrl + "/v1/.");
    });
  } catch (err) {
    setStatus("× Failed", "tag-refused", "The SDK did not load: " + err.message + ". Reload the page to retry.");
  }
  setTimeout(function () {
    if (!ready) {
      setStatus("× Failed", "tag-refused", "The SDK did not become ready in 10 seconds. Check the browser console, then reload.");
    }
  }, 10000);

  var actions = {
    page: function () { analytics.page(); return "Sent a page view of this URL."; },
    identify: function () { analytics.identify(config.contactId); return "Identified this browser as " + config.contactId + "."; },
    track: function () { analytics.track("Demo Requested"); return "Sent the Demo Requested milestone."; },
    reset: function () { analytics.reset(); return "Reset identity: later events are anonymous."; },
  };
  buttons.forEach(function (button) {
    button.addEventListener("click", function () {
      note(actions[button.dataset.send]() + " The SDK delivers it within a few seconds.");
    });
  });
})();
