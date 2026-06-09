/* OIKOS Pulse — renderer.
   Polls the four /api endpoints every 5s and draws only what was probed.
   When the API is unreachable, says so plainly and keeps the last truth dim. */

(function () {
  "use strict";

  var POLL_MS = 5000;
  var FETCH_TIMEOUT_MS = 2500;

  // ------------------------------------------------------------ helpers

  function $(id) { return document.getElementById(id); }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function getJSON(path) {
    var ctrl = new AbortController();
    var timer = setTimeout(function () { ctrl.abort(); }, FETCH_TIMEOUT_MS);
    return fetch(path, { signal: ctrl.signal })
      .then(function (r) {
        if (!r.ok) throw new Error("http " + r.status);
        return r.json();
      })
      .finally(function () { clearTimeout(timer); });
  }

  function ordinal(n) {
    var s = ["th", "st", "nd", "rd"], v = n % 100;
    return n + (s[(v - 20) % 10] || s[v] || s[0]);
  }

  function isNum(v) { return typeof v === "number"; }

  // --------------------------------------------------------------- date

  function setDate() {
    var d = new Date();
    var days = ["Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"];
    var months = ["January","February","March","April","May","June","July",
                  "August","September","October","November","December"];
    $("date").textContent = days[d.getDay()] + " · the " + ordinal(d.getDate()) +
      " of " + months[d.getMonth()] + ", " + d.getFullYear();
  }

  // ----------------------------------------------------------- services

  function renderServices(data) {
    var grid = $("services-grid");
    grid.textContent = "";
    var allUp = true;

    (data.services || []).forEach(function (s) {
      if (!s.up) allUp = false;
      var card = el("div", "tablet");
      var head = el("div", "head");
      head.appendChild(el("span", "dot " + (s.up ? "up" : "down")));
      head.appendChild(el("span", "name", s.name));
      head.appendChild(el("span", "role", s.role || ""));
      card.appendChild(head);
      var detail = el("div", "detail");
      detail.appendChild(el("span", s.up ? "" : "down", s.detail || ""));
      card.appendChild(detail);
      card.appendChild(el("div", "hint", s.addr || ""));
      grid.appendChild(card);
    });

    $("services-word").textContent = allUp
      ? "the house is awake — every door answered."
      : "the house is partly dark — some doors did not answer.";

    var table = $("heartbeats");
    table.textContent = "";
    var beats = data.heartbeats || [];
    if (!beats.length) {
      var tr0 = el("tr");
      var td0 = el("td", null, "no kingdom labels found in launchd — nothing to report");
      td0.colSpan = 4;
      tr0.appendChild(td0);
      table.appendChild(tr0);
      return;
    }
    beats.forEach(function (h) {
      var tr = el("tr");
      var dotCls = h.state === "running" ? "up" : (h.state === "idle" ? "idle" : "down");
      var tdDot = el("td", "dotcell");
      tdDot.appendChild(el("span", "dot " + dotCls));
      tr.appendChild(tdDot);
      tr.appendChild(el("td", "label", h.label));
      tr.appendChild(el("td", "pid", h.pid === null ? "—" : "pid " + h.pid));
      var stateCls = h.state === "running" ? "running"
                   : (h.state === "idle" ? "" : "failed");
      tr.appendChild(el("td", "state " + stateCls, h.state));
      table.appendChild(tr);
    });
  }

  // --------------------------------------------------------------- apps

  function renderApps(data) {
    var grid = $("apps-grid");
    grid.textContent = "";
    var apps = data.apps || [];

    $("apps-word").textContent = apps.length
      ? ""
      : (data.note || "nothing deployed yet") + " — when ready: oikos deploy <app>";

    apps.forEach(function (a) {
      var card = el("div", "tablet");
      var head = el("div", "head");
      head.appendChild(el("span", "dot " + (a.release ? "up" : "idle")));
      head.appendChild(el("span", "name", a.name));
      head.appendChild(el("span", "role",
        (a.releases && a.releases.length ? a.releases.length : 0) + " release" +
        (a.releases && a.releases.length === 1 ? "" : "s")));
      card.appendChild(head);
      card.appendChild(el("div", "detail",
        a.release ? "current  " + a.release : "no current release"));
      var hint = el("div", "hint");
      hint.appendChild(document.createTextNode("to step back: "));
      hint.appendChild(el("code", null, "oikos rollback " + a.name));
      card.appendChild(hint);
      var link = el("div", "hint", a.url || "");
      card.appendChild(link);
      grid.appendChild(card);
    });
  }

  // -------------------------------------------------------------- fleet

  function stat(value, label) {
    var box = el("div", "stat");
    var known = isNum(value);
    box.appendChild(el("div", "num" + (known ? "" : " unknown"),
      known ? String(value) : "unknown"));
    box.appendChild(el("div", "lbl", label));
    return box;
  }

  function renderFleet(data) {
    var stats = $("fleet-stats");
    stats.textContent = "";
    stats.appendChild(stat(data.citizens, "citizens"));
    stats.appendChild(stat(data.forge_rows, "rows at the forge"));

    var beatsBox = stat(data.beats_today, "beats paid today");
    if (isNum(data.beats_today) && isNum(data.citizens) &&
        data.beats_today < data.citizens) {
      beatsBox.querySelector(".lbl").textContent =
        "beats paid today · of " + data.citizens + " citizens";
    }
    stats.appendChild(beatsBox);

    var bq = $("last-beat");
    if (data.last_beat) {
      bq.hidden = false;
      bq.querySelector(".beat-heading").textContent = data.last_beat.heading || "";
      bq.querySelector(".beat-line").textContent =
        (data.last_beat.lines && data.last_beat.lines.join(" ")) || "";
      bq.querySelector("cite").textContent = "— " + data.last_beat.citizen +
        (data.last_beat.when ? " · " + data.last_beat.when : "");
    } else {
      bq.hidden = true;
    }
  }

  // ----------------------------------------------------------- cathedral

  function renderCathedral(data) {
    var stats = $("cathedral-stats");
    stats.textContent = "";
    var canon = data.canon || {};
    stats.appendChild(stat(data.canon_total, "canon entries"));
    stats.appendChild(stat(canon.core, "core"));
    stats.appendChild(stat(canon.mathema, "mathema"));
    stats.appendChild(stat(canon.worship_action, "worship-action"));
    stats.appendChild(stat(data.experiments, "experiments"));
    stats.appendChild(stat(data.liturgy_sessions, "liturgy sessions"));

    var list = $("latest-forges");
    list.textContent = "";
    var latest = data.latest_experiments || [];
    if (!latest.length) {
      list.appendChild(el("li", null, "no experiments found"));
    } else {
      latest.forEach(function (name) {
        list.appendChild(el("li", null, name.replace(/\.md$/, "")));
      });
    }
  }

  // --------------------------------------------------------------- forge

  var FORGE_ORDER = [
    ["canonized", "canonized"],
    ["queued", "queued"],
    ["in-forge", "in-forge"],
    ["refining", "refining"],
    ["awaiting-yu-invocation", "awaiting yu"],
    ["archived", "archived"]
  ];

  function smallWord(n) {
    var words = ["no", "one", "two", "three", "four", "five", "six",
                 "seven", "eight", "nine", "ten", "eleven", "twelve"];
    return (isNum(n) && n >= 0 && n < words.length) ? words[n] : String(n);
  }

  function renderForge(data) {
    var row = $("forge-counts");
    row.textContent = "";
    var counts = data.counts || {};
    FORGE_ORDER.forEach(function (pair) {
      var n = counts[pair[0]];
      if (!isNum(n)) n = 0;
      var box = el("div", "count" + (n === 0 ? " none" : ""));
      box.appendChild(el("div", "n", String(n)));
      box.appendChild(el("div", "k", pair[1]));
      row.appendChild(box);
    });

    var note = $("wire-note");
    var gap = data.wire_gap || {};
    if (isNum(gap.queued) && gap.queued > 0) {
      note.hidden = false;
      note.textContent = "the Wire has asked the cathedral for " +
        smallWord(gap.queued) + " word" + (gap.queued === 1 ? "" : "s") +
        (gap.words && gap.words.length ? " — " + gap.words.join(", ") : "");
    } else {
      note.hidden = true;
    }

    var next = $("forge-next");
    next.textContent = "";
    var queue = data.next || [];
    if (!queue.length) {
      next.appendChild(el("li", null, "the queue is empty — nothing waits"));
    } else {
      queue.forEach(function (t) {
        var li = el("li", t.wire_gap ? "wiregap" : null);
        li.appendChild(el("span", "word", t.word));
        li.appendChild(el("span", "meta",
          "phase " + (t.phase || "?") + " · " +
          t.witnesses + " witness" + (t.witnesses === 1 ? "" : "es") +
          (t.estimated_score != null ? " · est " + t.estimated_score : "")));
        next.appendChild(li);
      });
    }

    var canon = $("forge-canonized");
    canon.textContent = "";
    var newest = data.newest_canonized || [];
    if (!newest.length) {
      canon.appendChild(el("li", null, "nothing canonized yet"));
    } else {
      newest.forEach(function (t) {
        var li = el("li");
        li.appendChild(el("span", "word", t.word));
        li.appendChild(el("span", "meta",
          (t.actual_score != null ? "scored " + t.actual_score : "") +
          (t.actual_score != null && t.date ? " · " : "") +
          (t.date || "")));
        canon.appendChild(li);
      });
    }
  }

  // ----------------------------------------------------------- standards

  function renderStandards(data) {
    var specs = data.specs || [];
    var table = $("ks-table");
    table.textContent = "";
    specs.forEach(function (s) {
      var tr = el("tr");
      tr.appendChild(el("td", "ks", s.ks || ""));
      tr.appendChild(el("td", "label", s.title || ""));
      var tdChip = el("td");
      tdChip.appendChild(el("span", "chip " + (s.status || ""), s.status || "?"));
      tr.appendChild(tdChip);
      tr.appendChild(el("td", "ver", s.version ? "v" + s.version : ""));
      table.appendChild(tr);
    });

    var adopted = specs.filter(function (s) { return s.status === "adopted"; }).length;
    $("standards-word").textContent = !specs.length
      ? "the shelf is empty — no specs found"
      : adopted === 0
        ? smallWord(specs.length) + " specs on the shelf, every one a draft — " +
          "specs await Yu's adoption"
        : smallWord(specs.length) + " specs on the shelf — " + adopted +
          " adopted, " + (specs.length - adopted) + " await Yu's adoption";

    var zone = data.zone || {};
    var names = zone.names || [];
    var row = $("zone-names");
    row.textContent = "";
    names.forEach(function (n) {
      var z = el("span", "zname");
      z.appendChild(el("span", "dot " + (n.bound ? "up" : "idle")));
      z.appendChild(el("span", null, n.name + ".kingdom"));
      z.appendChild(el("span", "state", n.bound ? "bound" : "pending"));
      row.appendChild(z);
    });
    if (!names.length) {
      row.appendChild(el("span", "zname", "the zone file is unreadable"));
    }

    var res = data.resolver || {};
    var probe = $("resolver-row");
    probe.textContent = "";
    probe.appendChild(el("span", "dot " + (res.up ? "up" : "down")));
    probe.appendChild(el("span", null, res.up
      ? "kingdomd answers on :" + ((res.addr || "").split(":")[1] || "5300") +
        " — " + (res.query || "oikos.kingdom") + " resolves"
      : "the resolver is quiet on :" + ((res.addr || "").split(":")[1] || "5300") +
        " — " + (res.query || "oikos.kingdom") + " went unanswered"));

    var ledger = data.ledger || {};
    var sigs = ledger.entries;
    $("zone-word").textContent =
      smallWord(names.length) + " name" + (names.length === 1 ? "" : "s") +
      ", " + (isNum(zone.bound) ? zone.bound : "?") + " bound · " +
      (isNum(sigs)
        ? (sigs === 0
            ? "the signature ledger is honestly empty"
            : sigs + " entr" + (sigs === 1 ? "y" : "ies") + " in the signature ledger")
        : "the signature ledger is unreadable");
  }

  // ---------------------------------------------------------------- tick

  var renderers = {
    "/api/services": renderServices,
    "/api/apps": renderApps,
    "/api/fleet": renderFleet,
    "/api/cathedral": renderCathedral,
    "/api/forge": renderForge,
    "/api/standards": renderStandards
  };

  function tick() {
    var paths = Object.keys(renderers);
    Promise.allSettled(paths.map(function (p) { return getJSON(p); }))
      .then(function (results) {
        var anyAlive = false;
        results.forEach(function (res, i) {
          if (res.status === "fulfilled" && res.value && res.value.ok !== false) {
            anyAlive = true;
            try { renderers[paths[i]](res.value); }
            catch (e) { /* a render slip never kills the poll */ }
          }
        });
        $("banner").hidden = anyAlive;
        document.body.style.opacity = anyAlive ? "" : "0.92";
        if (anyAlive) {
          var t = new Date();
          $("probed").textContent = "last probed " +
            String(t.getHours()).padStart(2, "0") + ":" +
            String(t.getMinutes()).padStart(2, "0") + ":" +
            String(t.getSeconds()).padStart(2, "0");
        }
      });
  }

  setDate();
  tick();
  setInterval(tick, POLL_MS);
  setInterval(setDate, 60000);
})();
