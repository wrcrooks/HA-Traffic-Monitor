// Leaflet map rendering for the route preview (ROADMAP.md M4). Uses
// L.circleMarker for origin/destination instead of L.marker's default
// icon, deliberately -- the default icon needs marker-icon.png/2x/shadow
// image assets that would otherwise need vendoring alongside leaflet.js.
const RouteMap = (() => {
  const MUTED_COLOR = "#9aa0a6";
  const SELECTED_COLOR = "#0a7cff";
  const ORIGIN_COLOR = "#1e8e3e";
  const DEST_COLOR = "#d93025";

  function create(elementId) {
    const map = L.map(elementId, { scrollWheelZoom: true });
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap contributors",
    }).addTo(map);
    map.setView([20, 0], 2); // sensible default before any route is loaded
    return map;
  }

  // routeLayerGroup persists across calls so re-rendering (e.g. after
  // picking a different alternative) doesn't leak layers.
  let layerGroup = null;

  function clear(map) {
    if (layerGroup) {
      map.removeLayer(layerGroup);
    }
    layerGroup = L.layerGroup().addTo(map);
  }

  function summaryLabel(summary, unitSystem) {
    const mins = Math.round(summary.duration_seconds / 60);
    const delayMins = Math.round(Math.max(0, summary.duration_seconds - summary.duration_typical_seconds) / 60);
    const distance =
      unitSystem === "imperial"
        ? `${(summary.length_meters / 1609.34).toFixed(1)} mi`
        : `${(summary.length_meters / 1000).toFixed(1)} km`;
    const delayText = delayMins > 0 ? `, +${delayMins} min delay` : "";
    return `${mins} min${delayText} &middot; ${distance}`;
  }

  // Renders every alternative from a RouteCalculation. `selectedIndex`
  // determines which is drawn highlighted; clicking a polyline or its
  // popup's "Select" link calls onSelect(index).
  function renderAlternatives(map, calculation, selectedIndex, unitSystem, onSelect) {
    clear(map);
    if (!calculation.routes.length) return;

    const bounds = [];
    // Draw muted routes first, selected one last so it renders on top.
    const order = calculation.routes
      .map((_, i) => i)
      .sort((a, b) => (a === selectedIndex ? 1 : b === selectedIndex ? -1 : 0));

    for (const i of order) {
      const alt = calculation.routes[i];
      const isSelected = i === selectedIndex;
      const latlngs = alt.points.map((p) => [p.lat, p.lon]);
      if (latlngs.length) bounds.push(...latlngs);

      const line = L.polyline(latlngs, {
        color: isSelected ? SELECTED_COLOR : MUTED_COLOR,
        weight: isSelected ? 5 : 3,
        opacity: isSelected ? 0.95 : 0.55,
      }).addTo(layerGroup);

      const label = summaryLabel(alt.summary, unitSystem);
      line.bindPopup(
        `<strong>${isSelected ? "Selected" : `Alternative ${i + 1}`}</strong><br>${label}` +
          (isSelected ? "" : `<br><a href="#" data-select-index="${i}">Select this route</a>`)
      );
      line.on("click", () => line.openPopup());
      line.on("popupopen", (e) => {
        const link = e.popup._contentNode?.querySelector("[data-select-index]");
        if (link) {
          link.addEventListener("click", (ev) => {
            ev.preventDefault();
            onSelect(i);
          });
        }
      });
    }

    if (calculation.routes[0].points.length) {
      const first = calculation.routes[0].points[0];
      const last = calculation.routes[0].points[calculation.routes[0].points.length - 1];
      L.circleMarker([first.lat, first.lon], {
        radius: 8,
        color: "#fff",
        weight: 2,
        fillColor: ORIGIN_COLOR,
        fillOpacity: 1,
      })
        .bindTooltip("Origin")
        .addTo(layerGroup);
      L.circleMarker([last.lat, last.lon], {
        radius: 8,
        color: "#fff",
        weight: 2,
        fillColor: DEST_COLOR,
        fillOpacity: 1,
      })
        .bindTooltip("Destination")
        .addTo(layerGroup);
    }

    if (bounds.length) {
      map.fitBounds(bounds, { padding: [24, 24] });
    }
  }

  return { create, clear, renderAlternatives, summaryLabel };
})();
