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

  function parentOrigin() {
    try {
      if (location.ancestorOrigins && location.ancestorOrigins.length) {
        return location.ancestorOrigins[0];
      }
    } catch (err) {}
    try {
      if (document.referrer) return new URL(document.referrer).origin;
    } catch (err) {}
    return "";
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
    var origin = parentOrigin();
    if (!origin) return;
    window.parent.postMessage(payload, origin);
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

  function undoPatches(to) {
    var list = loadPatches().filter(function (patch) {
      return !patch || typeof patch.seq !== "number" || patch.seq <= to;
    });
    savePatches(list);
    try {
      sessionStorage.removeItem(STORE + "-colors");
    } catch (err) {
      /* ignore */
    }
    report({ undone: true });
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
    var out = { tag: tag, text: text };
    var src = imageSrc(el);
    if (src) {
      // a picture's name is its alt text, not the words of whatever sits on top of it
      out.text = String(el.getAttribute("alt") || el.getAttribute("aria-label") || "").replace(/\s+/g, " ").trim().slice(0, 80);
      out.kind = "image";
      out.src = src.slice(0, 1000);
      out.alt = String(el.getAttribute("alt") || "").slice(0, 80);
    } else {
      out.kind = ownText(el) ? "text" : "block";
    }
    return out;
  }

  function imageSrc(el) {
    if (!el || el.nodeType !== 1) return "";
    var tag = String(el.tagName || "").toLowerCase();
    if (tag === "img") return el.currentSrc || el.getAttribute("src") || "";
    try {
      var bg = window.getComputedStyle(el).backgroundImage || "";
      var match = /url\((['"]?)(.*?)\1\)/.exec(bg);
      return match ? match[2] : "";
    } catch (err) {
      return "";
    }
  }

  var FORM_TAGS = { input: 1, textarea: 1, select: 1, option: 1 };

  /** What a finger at (x, y) means: text if the top element carries text, else the picture under it. */
  function targetAt(x, y) {
    var stack = document.elementsFromPoint ? document.elementsFromPoint(x, y) : [document.elementFromPoint(x, y)];
    var top = null;
    var image = null;
    for (var i = 0; i < stack.length; i++) {
      var el = stack[i];
      if (!el || el.nodeType !== 1) continue;
      if (el.getAttribute && el.getAttribute("data-sozan-ui")) continue;
      var tag = String(el.tagName || "").toLowerCase();
      if (tag === "html" || tag === "body") continue;
      if (!top) top = el;
      if (!image && imageSrc(el)) image = el;
    }
    if (!top) return null;
    if (FORM_TAGS[String(top.tagName || "").toLowerCase()]) return null;
    if (ownText(top)) return meaningful(top);
    return meaningful(image || top);
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
    if (data.type === "undo") {
      undoPatches(typeof data.to === "number" ? data.to : 0);
      return;
    }
    if (data.type === "clear") {
      selected = null;
      if (selectBox) selectBox.style.display = "none";
      if (hoverBox) hoverBox.style.display = "none";
      if (tagLabel) tagLabel.style.display = "none";
      return;
    }
    if (data.type === "apply") applyPatch(data.patch || {}, true);
  });

  hoverBox = boxEl("hover");
  selectBox = boxEl("select");

  function selectEl(el, extra) {
    selected = el;
    place(selectBox, el);
    place(hoverBox, null);
    showLabel(el);
    var payload = { pick: describe(el) };
    if (extra) for (var key in extra) payload[key] = extra[key];
    report(payload);
  }

  // A finger held on any part of the page (also while browsing) picks it for editing.
  var LONG_MS = 480;
  var MOVE_PX = 10;
  var press = null;
  var swallowUntil = 0;

  function cancelPress() {
    if (!press) return;
    window.clearTimeout(press.timer);
    window.clearTimeout(press.hint);
    press = null;
    place(hoverBox, null);
  }

  var guard = document.createElement("style");
  guard.setAttribute("data-sozan-ui", "1");
  guard.textContent =
    "html,body{-webkit-touch-callout:none;-webkit-user-select:none;user-select:none}" +
    "input,textarea{-webkit-user-select:text;user-select:text}";
  document.documentElement.appendChild(guard);

  document.addEventListener(
    "pointerdown",
    function (event) {
      cancelPress();
      if (event.pointerType === "mouse" && event.button !== 0) return;
      if (event.target && event.target.closest && event.target.closest("[data-sozan-ui]")) return;
      var x = event.clientX;
      var y = event.clientY;
      var el = targetAt(x, y);
      if (!el) return;
      press = { x: x, y: y, el: el, timer: 0, hint: 0 };
      press.hint = window.setTimeout(function () {
        if (press) place(hoverBox, press.el);
      }, 160);
      press.timer = window.setTimeout(function () {
        var held = press;
        press = null;
        place(hoverBox, null);
        if (!held) return;
        swallowUntil = Date.now() + 900;
        try {
          if (navigator.vibrate) navigator.vibrate(14);
        } catch (err) {
          /* ignore */
        }
        selectEl(held.el, { longPress: true });
      }, LONG_MS);
    },
    true,
  );
  document.addEventListener(
    "pointermove",
    function (event) {
      if (!press) return;
      if (Math.abs(event.clientX - press.x) > MOVE_PX || Math.abs(event.clientY - press.y) > MOVE_PX) cancelPress();
    },
    true,
  );
  ["pointerup", "pointercancel", "dragstart"].forEach(function (name) {
    document.addEventListener(name, cancelPress, true);
  });
  document.addEventListener(
    "contextmenu",
    function (event) {
      if (press || Date.now() < swallowUntil || event.pointerType === "touch") event.preventDefault();
    },
    true,
  );
  document.addEventListener(
    "click",
    function (event) {
      if (Date.now() < swallowUntil) {
        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();
      }
    },
    true,
  );
  window.addEventListener(
    "scroll",
    function () {
      cancelPress();
      if (selected) {
        place(selectBox, selected);
        showLabel(selected);
      }
    },
    true,
  );

  if (!browse) {
    document.addEventListener(
      "mousemove",
      function (event) {
        if (event.pointerType === "touch") return;
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
        selectEl(el);
      },
      true,
    );
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
