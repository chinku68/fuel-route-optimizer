/* Display the existing API response; no browser-side geocoding or routing calls. */
(() => {
  "use strict";
  const byId = (id) => document.getElementById(id);
  const form = byId("route-form");
  const button = byId("submit-route");
  const money = (value) => value == null ? "Unavailable" : new Intl.NumberFormat("en-US", {
    style: "currency", currency: "USD",
  }).format(value);
  const number = (value, digits = 2) => Number(value).toLocaleString("en-US", {
    maximumFractionDigits: digits,
  });

  if (!window.L) {
    byId("error").textContent = "The map library could not load. Check your internet connection and refresh this page.";
    byId("error").hidden = false;
    button.disabled = true;
    return;
  }

  const map = L.map("map").setView([39.5, -98.35], 4);
  const tiles = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);
  tiles.on("tileerror", () => {
    byId("status").textContent = "Some background map tiles could not load. Your route and fuel results can still be displayed.";
  });
  let routeLayer;
  const stopMarkers = new Map();

  function addLine(parent, text, tag = "div", className = "") {
    const element = document.createElement(tag);
    element.textContent = text;
    element.className = className;
    parent.append(element);
    return element;
  }

  function popupContent(properties) {
    const container = document.createElement("div");
    if (properties.type !== "fuel_stop") {
      addLine(container, properties.type === "start" ? "Start" : "Destination", "strong", "popup-title");
      addLine(container, properties.label);
      return container;
    }
    addLine(container, `${properties.stop_number}. ${properties.name}`, "strong", "popup-title");
    addLine(container, `${properties.city}, ${properties.state}`);
    addLine(container, `$${number(properties.price_per_gallon, 5)} per gallon`);
    addLine(container, `Buy ${number(properties.gallons_purchased, 3)} gallons · ${money(properties.cost)}`);
    addLine(container, `At route mile ${number(properties.route_mile)}`);
    const approximate = !["address", "venue"].includes(properties.coordinate_quality);
    addLine(container, approximate ? "Approximate station location" : "Matched station location");
    return container;
  }

  function renderTrip(data) {
    const summary = data.fuel_summary;
    byId("trip-title").textContent = `${data.start.location} → ${data.finish.location}`;
    byId("distance").textContent = `${number(data.trip.distance_miles)} mi`;
    byId("duration").textContent = `${number(data.trip.duration_hours)} hr`;
    byId("stop-count").textContent = summary.number_of_fuel_stops;
    byId("gallons").textContent = `${number(summary.total_gallons)} gal`;
    byId("refueling-cost").textContent = money(summary.total_refueling_cost);
    byId("total-cost").textContent = money(summary.total_fuel_cost);
    const approximate = data.fuel_stops.filter((stop) => !["address", "venue"].includes(stop.coordinate_quality)).length;
    byId("accuracy-note").textContent =
      (approximate ? `${approximate} of ${data.fuel_stops.length} fuel stops use approximate locations. ` : "") +
      "Extra road distance to reach stations is excluded from fuel calculations. Range checks use approximate positions along the displayed route.";
    byId("price-note").hidden = !summary.message;
    byId("price-note").textContent = summary.message || "";
    byId("results").hidden = false;

    stopMarkers.clear();
    routeLayer = L.geoJSON(data.map, {
      style: { color: "#2563eb", weight: 5, opacity: 0.85 },
      pointToLayer(feature, latlng) {
        const properties = feature.properties;
        if (properties.type === "fuel_stop") {
          return L.marker(latlng, {
            title: `${properties.stop_number}. ${properties.name}`,
            icon: L.divIcon({
              className: "fuel-pin", html: String(Number(properties.stop_number)),
              iconSize: [30, 30], iconAnchor: [15, 15],
            }),
          });
        }
        return L.circleMarker(latlng, {
          radius: 9, color: "#fff", weight: 2, fillOpacity: 1,
          fillColor: properties.type === "start" ? "#17865e" : "#c53645",
        });
      },
      onEachFeature(feature, layer) {
        if (feature.properties.type === "route") return;
        layer.bindPopup(popupContent(feature.properties));
        if (feature.properties.type === "fuel_stop") stopMarkers.set(feature.properties.stop_number, layer);
      },
    }).addTo(map);
    map.invalidateSize();
    const bounds = routeLayer.getBounds();
    if (bounds.isValid()) map.fitBounds(bounds, { padding: [25, 25], maxZoom: 12 });

    byId("stop-help").textContent = data.fuel_stops.length
      ? "Select a stop to see its location and planned purchase."
      : "No fuel stop is needed. Your starting tank covers this trip.";
    data.fuel_stops.forEach((stop, index) => {
      const item = document.createElement("li");
      const stopButton = document.createElement("button");
      stopButton.type = "button";
      stopButton.className = "stop-button";
      addLine(stopButton, stop.name, "strong");
      addLine(stopButton, `${stop.city}, ${stop.state}`, "span");
      addLine(stopButton, `$${number(stop.price_per_gallon, 5)}/gal · Buy ${number(stop.gallons_purchased, 3)} gal`, "span");
      addLine(stopButton, `${money(stop.cost)} · Mile ${number(stop.route_mile)}`, "span");
      stopButton.addEventListener("click", () => {
        const marker = stopMarkers.get(index + 1);
        if (marker) {
          map.setView(marker.getLatLng(), 11);
          marker.openPopup();
          byId("map").scrollIntoView({ behavior: "smooth", block: "center" });
        }
      });
      item.append(stopButton);
      byId("fuel-stops").append(item);
    });
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (button.disabled) return;
    button.disabled = true;
    button.textContent = "Planning…";
    byId("error").hidden = true;
    byId("results").hidden = true;
    byId("fuel-stops").replaceChildren();
    byId("stop-help").textContent = "Finding your route and fuel stops…";
    if (routeLayer) {
      map.removeLayer(routeLayer);
      routeLayer = null;
    }
    byId("status").textContent = "Finding your driving route and planning fuel purchases…";
    try {
      const response = await fetch(form.dataset.apiUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": form.querySelector('[name="csrfmiddlewaretoken"]').value,
        },
        body: JSON.stringify({ start: byId("start").value.trim(), finish: byId("finish").value.trim() }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Could not plan this trip. Please try again.");
      renderTrip(data);
      byId("status").textContent = "Your trip is ready. Click a fuel marker or a stop in the list for details.";
    } catch (error) {
      byId("error").textContent = error.message || "Could not reach the API. Check that Django is running.";
      byId("error").hidden = false;
      byId("status").textContent = "The trip could not be planned. Check the message above.";
      byId("stop-help").textContent = "Try again to see your fuel stops.";
    } finally {
      button.disabled = false;
      button.textContent = "Plan my trip";
    }
  });
})();
