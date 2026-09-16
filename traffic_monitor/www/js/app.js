// Main app logic: view switching, route list, the add/edit editor with
// its map preview, and the usage bar (ROADMAP.md M4).
(() => {
  const DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const REFRESH_MS = 15000;

  const state = {
    unitSystem: "metric",
    routes: [],
    statusById: {},
    editingRouteId: null, // null = creating a new route
    preview: null, // last RouteCalculation from /api/routes/preview
    selectedIndex: 0,
    map: null,
    refreshTimer: null,
  };

  const el = (id) => document.getElementById(id);

  // -- view switching --------------------------------------------------

  function showList() {
    el("view-editor").hidden = true;
    el("view-list").hidden = false;
    stopAutoRefresh();
    startAutoRefresh();
    refreshList();
  }

  function showEditor() {
    stopAutoRefresh();
    el("view-list").hidden = true;
    el("view-editor").hidden = false;
    if (!state.map) {
      state.map = RouteMap.create("preview-map");
    }
    // A freshly-shown Leaflet map in a container that was previously
    // display:none needs a nudge to compute its size correctly.
    setTimeout(() => state.map.invalidateSize(), 50);
  }

  function startAutoRefresh() {
    state.refreshTimer = setInterval(refreshList, REFRESH_MS);
  }

  function stopAutoRefresh() {
    if (state.refreshTimer) clearInterval(state.refreshTimer);
    state.refreshTimer = null;
  }

  // -- status banner + usage bar ----------------------------------------

  async function refreshBanner() {
    try {
      const status = await Api.status();
      state.unitSystem = status.unit_system;
      const banner = el("config-banner");
      if (!status.api_key_configured) {
        banner.textContent = "No TomTom API key configured yet. Set one in the add-on's Configuration tab, then restart it.";
        banner.hidden = false;
      } else if (!status.mqtt_connected) {
        banner.textContent = "Not connected to an MQTT broker yet. Entities won't appear in Home Assistant until it is.";
        banner.hidden = false;
      } else {
        banner.hidden = true;
      }
    } catch {
      // /api/status should never fail; if it does, just leave the banner alone.
    }
  }

  async function refreshUsage() {
    try {
      const usage = await Api.usage();
      renderUsage(usage);
    } catch {
      el("usage-bar").hidden = true;
    }
  }

  function renderUsage(usage) {
    const bar = el("usage-bar");
    bar.hidden = false;
    const pct = Math.min(100, Math.round(usage.usage_ratio * 100));
    el("usage-fill").style.width = `${pct}%`;
    el("usage-fill").className = usage.exhausted ? "usage-fill exhausted" : usage.warning ? "usage-fill warning" : "usage-fill";
    el("usage-label").textContent = `${usage.used_30d.toLocaleString()} / ${usage.monthly_limit.toLocaleString()} API requests this month (${pct}%)`;
  }

  // -- route list --------------------------------------------------------

  async function refreshList() {
    try {
      const [routes, statusById] = await Promise.all([Api.listRoutes(), Api.allRouteStatus()]);
      state.routes = routes;
      state.statusById = statusById;
      renderRouteList();
    } catch (err) {
      if (err.status !== 503) console.error("Failed to refresh routes", err);
      state.routes = [];
      renderRouteList();
    }
    refreshBanner();
    refreshUsage();
  }

  function trafficBadge(level) {
    const labels = { free_flow: "Free flow", light: "Light", moderate: "Moderate", heavy: "Heavy" };
    return `<span class="badge badge-${level}">${labels[level] || level}</span>`;
  }

  function formatDistance(km) {
    if (state.unitSystem === "imperial") return `${(km / 1.60934).toFixed(1)} mi`;
    return `${km.toFixed(1)} km`;
  }

  function renderRouteList() {
    const container = el("route-list");
    container.innerHTML = "";
    el("route-count-label").textContent = state.routes.length
      ? `${state.routes.length} route${state.routes.length === 1 ? "" : "s"}`
      : "";

    if (!state.routes.length) {
      el("empty-state").hidden = false;
      return;
    }
    el("empty-state").hidden = true;

    for (const route of state.routes) {
      const status = state.statusById[route.id];
      const card = document.createElement("div");
      card.className = "route-card" + (route.enabled ? "" : " disabled");

      let statusHtml;
      if (!route.enabled) {
        statusHtml = `<span class="muted">Disabled</span>`;
      } else if (!status) {
        statusHtml = `<span class="muted">Waiting for first poll&hellip;</span>`;
      } else {
        const staleTag = status.stale ? ` <span class="muted">(stale)</span>` : "";
        const windowTag = !status.in_active_window ? ` <span class="muted">&middot; outside active window</span>` : "";
        statusHtml =
          `<strong>${status.duration_minutes} min</strong>` +
          (status.delay_minutes > 0 ? ` <span class="muted">(+${status.delay_minutes} min delay)</span>` : "") +
          ` &middot; ${formatDistance(status.distance)} &middot; ${trafficBadge(status.traffic_level)}` +
          staleTag +
          windowTag;
      }

      card.innerHTML = `
        <div class="route-card-main">
          <div class="route-card-title">
            ${escapeHtml(route.name)}
            ${route.avoid_tolls ? '<span class="pill">no tolls</span>' : ""}
            ${route.schedule.windows.length ? '<span class="pill">windowed</span>' : ""}
          </div>
          <div class="route-card-status">${statusHtml}</div>
          <div class="route-card-addresses muted">${escapeHtml(route.origin_address)} &rarr; ${escapeHtml(route.destination_address)}</div>
        </div>
        <div class="route-card-actions">
          <button class="btn-icon" data-action="edit" title="Edit">&#9998;</button>
          <button class="btn-icon" data-action="toggle" title="${route.enabled ? "Disable" : "Enable"}">${route.enabled ? "&#9208;" : "&#9654;"}</button>
          <button class="btn-icon btn-danger" data-action="delete" title="Delete">&#128465;</button>
        </div>
      `;

      card.querySelector('[data-action="edit"]').addEventListener("click", () => openEditor(route.id));
      card.querySelector('[data-action="toggle"]').addEventListener("click", () => toggleEnabled(route));
      card.querySelector('[data-action="delete"]').addEventListener("click", () => deleteRoute(route));
      container.appendChild(card);
    }
  }

  async function toggleEnabled(route) {
    try {
      await Api.updateRoute(route.id, { ...routeToWriteBody(route), enabled: !route.enabled });
      refreshList();
    } catch (err) {
      alert(`Could not update route: ${err.message}`);
    }
  }

  async function deleteRoute(route) {
    if (!confirm(`Delete "${route.name}"? This removes its entities from Home Assistant.`)) return;
    try {
      await Api.deleteRoute(route.id);
      refreshList();
    } catch (err) {
      alert(`Could not delete route: ${err.message}`);
    }
  }

  function routeToWriteBody(route) {
    return {
      name: route.name,
      origin_address: route.origin_address,
      destination_address: route.destination_address,
      avoid_tolls: route.avoid_tolls,
      poll_interval_minutes: route.poll_interval_minutes,
      schedule: route.schedule,
      enabled: route.enabled,
      selected_alternative_points: route.selected_alternative_points,
    };
  }

  // -- editor: schedule sub-widget ---------------------------------------

  function renderDayCheckboxes(selectedDays) {
    const wrap = el("schedule-days");
    wrap.innerHTML = DAY_LABELS.map(
      (label, i) => `
      <label class="day-checkbox">
        <input type="checkbox" value="${i}" ${selectedDays.includes(i) ? "checked" : ""}>
        ${label}
      </label>`
    ).join("");
  }

  function readSelectedDays() {
    return Array.from(el("schedule-days").querySelectorAll("input:checked")).map((i) => parseInt(i.value, 10));
  }

  function addWindowRow(win) {
    const row = document.createElement("div");
    row.className = "window-row";
    row.innerHTML = `
      <input type="time" class="window-start" value="${win ? win.start.slice(0, 5) : "07:00"}">
      <span>to</span>
      <input type="time" class="window-end" value="${win ? win.end.slice(0, 5) : "09:00"}">
      <button type="button" class="btn-icon" data-action="remove-window">&times;</button>
    `;
    row.querySelector('[data-action="remove-window"]').addEventListener("click", () => row.remove());
    el("schedule-windows").appendChild(row);
  }

  function readWindows() {
    return Array.from(el("schedule-windows").querySelectorAll(".window-row")).map((row) => ({
      start: row.querySelector(".window-start").value,
      end: row.querySelector(".window-end").value,
    }));
  }

  // -- editor: main --------------------------------------------------------

  function resetEditorForm() {
    el("route-form").reset();
    el("field-name").value = "";
    el("field-origin").value = "";
    el("field-destination").value = "";
    el("field-avoid-tolls").checked = false;
    el("field-poll-interval").value = "15";
    el("field-enabled").checked = true;
    renderDayCheckboxes([0, 1, 2, 3, 4]);
    el("schedule-windows").innerHTML = "";
    state.preview = null;
    state.selectedIndex = 0;
    el("alternatives-list").innerHTML = "";
    el("preview-error").hidden = true;
    if (state.map) RouteMap.clear(state.map);
  }

  async function openEditor(routeId) {
    resetEditorForm();
    state.editingRouteId = routeId || null;
    el("editor-title").textContent = routeId ? "Edit Route" : "Add Route";
    el("btn-delete-in-editor").hidden = !routeId;

    if (routeId) {
      const route = await Api.getRoute(routeId);
      el("field-name").value = route.name;
      el("field-origin").value = route.origin_address;
      el("field-destination").value = route.destination_address;
      el("field-avoid-tolls").checked = route.avoid_tolls;
      el("field-poll-interval").value = route.poll_interval_minutes;
      el("field-enabled").checked = route.enabled;
      renderDayCheckboxes(route.schedule.days);
      for (const win of route.schedule.windows) addWindowRow(win);
      if (route.selected_alternative_points) {
        // We don't re-run a preview automatically (that would spend API
        // budget just from opening the editor) -- the map stays empty
        // until "Preview route" is pressed, but the pin itself is
        // preserved on save unless the user explicitly re-picks.
        state.preservedSelection = route.selected_alternative_points;
      }
    } else {
      renderDayCheckboxes([0, 1, 2, 3, 4]);
    }

    showEditor();
  }

  async function handlePreview() {
    const origin = el("field-origin").value.trim();
    const destination = el("field-destination").value.trim();
    if (!origin || !destination) {
      alert("Enter both an origin and destination first.");
      return;
    }
    const btn = el("btn-preview");
    btn.disabled = true;
    btn.textContent = "Loading route options…";
    el("preview-error").hidden = true;
    try {
      state.preview = await Api.previewRoute({
        origin_address: origin,
        destination_address: destination,
        avoid_tolls: el("field-avoid-tolls").checked,
      });
      state.selectedIndex = 0;
      state.preservedSelection = null; // a fresh preview supersedes any preserved pin
      renderAlternativesList();
      RouteMap.renderAlternatives(state.map, state.preview, state.selectedIndex, state.unitSystem, selectAlternative);
    } catch (err) {
      el("preview-error").textContent = err.status === 429 ? "Monthly API budget exhausted -- try again next month, or free up budget by disabling a route." : `Could not calculate route: ${err.message}`;
      el("preview-error").hidden = false;
    } finally {
      btn.disabled = false;
      btn.textContent = "Preview route";
    }
  }

  function selectAlternative(index) {
    state.selectedIndex = index;
    renderAlternativesList();
    RouteMap.renderAlternatives(state.map, state.preview, state.selectedIndex, state.unitSystem, selectAlternative);
  }

  function renderAlternativesList() {
    const list = el("alternatives-list");
    list.innerHTML = "";
    state.preview.routes.forEach((alt, i) => {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "alternative-item" + (i === state.selectedIndex ? " selected" : "");
      item.innerHTML = `${i === 0 ? "Fastest now" : `Alternative ${i}`}: ${RouteMap.summaryLabel(alt.summary, state.unitSystem)}`;
      item.addEventListener("click", () => selectAlternative(i));
      list.appendChild(item);
    });
  }

  async function handleSave(ev) {
    ev.preventDefault();
    const name = el("field-name").value.trim();
    const origin = el("field-origin").value.trim();
    const destination = el("field-destination").value.trim();
    if (!name || !origin || !destination) {
      alert("Name, origin, and destination are all required.");
      return;
    }

    const selectedPoints = state.preview
      ? state.preview.routes[state.selectedIndex].points
      : state.preservedSelection || null;

    const body = {
      name,
      origin_address: origin,
      destination_address: destination,
      avoid_tolls: el("field-avoid-tolls").checked,
      poll_interval_minutes: parseInt(el("field-poll-interval").value, 10) || 15,
      schedule: { days: readSelectedDays(), windows: readWindows() },
      enabled: el("field-enabled").checked,
      selected_alternative_points: selectedPoints,
    };

    const btn = el("btn-save");
    btn.disabled = true;
    try {
      if (state.editingRouteId) {
        await Api.updateRoute(state.editingRouteId, body);
      } else {
        await Api.createRoute(body);
      }
      showList();
    } catch (err) {
      alert(`Could not save route: ${err.message}`);
    } finally {
      btn.disabled = false;
    }
  }

  async function handleDeleteInEditor() {
    if (!state.editingRouteId) return;
    if (!confirm("Delete this route? This removes its entities from Home Assistant.")) return;
    try {
      await Api.deleteRoute(state.editingRouteId);
      showList();
    } catch (err) {
      alert(`Could not delete route: ${err.message}`);
    }
  }

  function escapeHtml(s) {
    const div = document.createElement("div");
    div.textContent = s;
    return div.innerHTML;
  }

  // -- wiring --------------------------------------------------------------

  function init() {
    el("btn-add-route").addEventListener("click", () => openEditor(null));
    el("btn-cancel-editor").addEventListener("click", showList);
    el("btn-preview").addEventListener("click", handlePreview);
    el("btn-add-window").addEventListener("click", () => addWindowRow(null));
    el("route-form").addEventListener("submit", handleSave);
    el("btn-delete-in-editor").addEventListener("click", handleDeleteInEditor);
    showList();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
