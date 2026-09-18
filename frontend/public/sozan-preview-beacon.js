(function () {
  if (window.parent === window) return;
  var params = new URLSearchParams(location.search);
  var browse = params.get("sozan") === "browse";
  var hoverBox;
  var selectBox;
  var tagLabel;
  var selected;
  var STORE = "sozan-preview-patches";

  function pathNow() {
    var url = new URL(location.href);
    url.searchParams.delete("sozan");
    url.searchParams.delete("t");
    var query = url.searchParams.toString();
    return url.pathname + (query ? "?" + query : "") + url.hash;
  }

  function report(extra) {
    var payload = {
      source: "sozan-preview",
      path: pathNow(),
      title: document.title || "",
      href: location.href,
      mode: browse ? "browse" : "design",
    };
    if (extra) {
      for (var key in extra) payload[key] = extra[key];
    }
    window.parent.postMessage(payload, "*");
  }

  function loadPatches() {
    try {
      var raw = sessionStorage.getItem(STORE);
      var parsed = raw ? JSON.parse(raw) : [];
      return Array.isArray(parsed) ? parsed : [];
    } catch (err) {
      return [];
    }
  }

  function savePatches(list) {
    try {
      sessionStorage.setItem(STORE, JSON.stringify(list));
    } catch (err) {
      /* ignore quota */
    }
  }

  function replaceText(find, replace) {
    if (!find || !replace || find === replace) return;
    var walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    var node;
    while ((node = walk.nextNode())) {
      if (!node.parentElement || node.parentElement.getAttribute("data-sozan-ui")) continue;
      var value = node.nodeValue || "";
      if (value.indexOf(find) === -1) continue;
      node.nodeValue = value.replace(find, replace);
      break;
    }
  }

  function applyColors(colors) {
    if (!colors) return;
    var root = document.documentElement;
    var style = document.querySelector("style[data-sozan-theme]");
    if (!style) {
      style = document.createElement("style");
      style.setAttribute("data-sozan-ui", "1");
      style.setAttribute("data-sozan-theme", "1");
      document.documentElement.appendChild(style);
    }
    var rules = [];
    Object.keys(colors).forEach(function (key) {
      var value = String(colors[key] || "").trim();
      if (!value) return;
      root.style.setProperty("--" + key, value);
      root.style.setProperty("--brand-" + key, value);
      rules.push("--" + key + ":" + value);
      rules.push("--brand-" + key + ":" + value);
    });
    if (rules.length) style.textContent = ":root{" + rules.join(";") + "}";
    var last = {};
    try {
      last = JSON.parse(sessionStorage.getItem(STORE + "-colors") || "{}");
    } catch (err) {
      last = {};
    }
    Object.keys(colors).forEach(function (key) {
      var next = String(colors[key] || "").trim();
      var prev = String(last[key] || "").trim();
      if (prev && next && prev.toLowerCase() !== next.toLowerCase()) {
        replaceColorValue(prev, next);
      }
      if (next) last[key] = next;
    });
    try {
      sessionStorage.setItem(STORE + "-colors", JSON.stringify(last));
    } catch (err) {
      /* ignore quota */
    }
  }

  function replaceColorValue(from, to) {
    var nodes = document.querySelectorAll("[style], [fill], [stroke]");
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      if (el.getAttribute && el.getAttribute("data-sozan-ui")) continue;
      ["style", "fill", "stroke"].forEach(function (attr) {
        var raw = el.getAttribute(attr);
        if (!raw || raw.toLowerCase().indexOf(from.toLowerCase()) === -1) return;
        el.setAttribute(attr, raw.split(from).join(to));
      });
    }
  }

  function applyPatch(patch, persist) {
    if (!patch) return;
    if (patch.reset) {
      try {
        sessionStorage.removeItem(STORE);
        sessionStorage.removeItem(STORE + "-colors");
      } catch (err) {
        /* ignore */
      }
      location.reload();
      return;
    }
    if (patch.find && patch.replace) replaceText(patch.find, patch.replace);
    if (patch.colors) applyColors(patch.colors);
    if (persist && !patch.reload) {
      var list = loadPatches();
      list.push(patch);
      savePatches(list);
    }
  }

  function boxEl(kind) {
    var node = document.createElement("div");
    node.setAttribute("data-sozan-ui", "1");
    node.style.cssText =
      "position:fixed;pointer-events:none;z-index:2147483646;border-radius:4px;box-sizing:border-box;" +
      (kind === "select"
        ? "border:2px solid #C45C26;background:rgba(196,92,38,0.12);"
        : "border:1.5px solid #E8A87C;background:rgba(232,168,124,0.10);");
    document.documentElement.appendChild(node);
    return node;
  }

  function place(box, el) {
    if (!box || !el || !el.getBoundingClientRect) {
      if (box) box.style.display = "none";
      return;
    }
    var r = el.getBoundingClientRect();
    if (r.width < 2 && r.height < 2) {
      box.style.display = "none";
      return;
    }
    box.style.display = "block";
    box.style.top = Math.max(0, r.top) + "px";
    box.style.left = Math.max(0, r.left) + "px";
    box.style.width = Math.max(0, r.width) + "px";
    box.style.height = Math.max(0, r.height) + "px";
  }

  function meaningful(el) {
    if (!el || el.nodeType !== 1) return null;
    if (el.getAttribute && el.getAttribute("data-sozan-ui")) return null;
    var tag = String(el.tagName || "").toLowerCase();
    if (!tag || tag === "html" || tag === "body" || tag === "script" || tag === "style" || tag === "svg") {
      return el.parentElement ? meaningful(el.parentElement) : null;
    }
    return el;
  }

  function ownText(el) {
    var bits = [];
    var child = el.firstChild;
    while (child) {
      if (child.nodeType === 3) {
        var piece = String(child.textContent || "").replace(/\s+/g, " ").trim();
        if (piece) bits.push(piece);
      }
      child = child.nextSibling;
    }
    return bits.join(" ").trim();
  }

  function describe(el) {
    var tag = String(el.tagName || "").toLowerCase();
    var text = String(el.getAttribute("aria-label") || el.getAttribute("alt") || ownText(el) || el.innerText || "")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 80);
    return { tag: tag, text: text };
  }

  function showLabel(el) {
    if (!tagLabel) {
      tagLabel = document.createElement("div");
      tagLabel.setAttribute("data-sozan-ui", "1");
      tagLabel.style.cssText =
        "position:fixed;z-index:2147483647;pointer-events:none;background:#C45C26;color:#fff;font:11px/1.3 sans-serif;padding:3px 6px;border-radius:4px;max-width:220px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;";
      document.documentElement.appendChild(tagLabel);
    }
    var info = describe(el);
    var r = el.getBoundingClientRect();
    tagLabel.textContent = info.text ? info.tag + " · " + info.text : info.tag;
    tagLabel.style.display = "block";
    tagLabel.style.top = Math.max(8, r.top - 22) + "px";
    tagLabel.style.left = Math.max(8, r.left) + "px";
  }

  var push = history.pushState;
  history.pushState = function () {
    push.apply(this, arguments);
    report();
  };
  var replace = history.replaceState;
  history.replaceState = function () {
    replace.apply(this, arguments);
    report();
  };
  window.addEventListener("popstate", report);
  window.addEventListener("hashchange", report);

  window.addEventListener("message", function (event) {
    if (event.source !== window.parent) return;
    var data = event.data;
    if (!data || data.source !== "sozan-panel") return;
    if (data.type === "reset") {
      applyPatch({ reset: true }, false);
      return;
    }
    if (data.type === "apply") applyPatch(data.patch || {}, true);
  });

  if (!browse) {
    hoverBox = boxEl("hover");
    selectBox = boxEl("select");
    document.addEventListener(
      "mousemove",
      function (event) {
        var el = meaningful(event.target);
        if (!el || el === selected) {
          place(hoverBox, null);
          return;
        }
        place(hoverBox, el);
      },
      true,
    );
    document.addEventListener(
      "click",
      function (event) {
        var el = meaningful(event.target);
        if (!el) return;
        event.preventDefault();
        event.stopPropagation();
        selected = el;
        place(selectBox, el);
        place(hoverBox, null);
        showLabel(el);
        report({ pick: describe(el) });
      },
      true,
    );
    window.addEventListener("scroll", function () {
      if (selected) {
        place(selectBox, selected);
        showLabel(selected);
      }
    }, true);
  }

  function boot() {
    loadPatches().forEach(function (patch) {
      applyPatch(patch, false);
    });
    report();
  }

  if (document.readyState === "complete") boot();
  else window.addEventListener("load", boot);
})();
