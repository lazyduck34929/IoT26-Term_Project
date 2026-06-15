const state = {
  events: [],
  selectedUser: "",
};

const trashIds = {
  plastic: "plasticCount",
  paper: "paperCount",
  can: "canCount",
  glass: "glassCount",
};

function pct(value) {
  return `${Math.round(value * 100)}%`;
}

function fmtTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("en-US", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function todayKey() {
  return new Date().toISOString().slice(0, 10);
}

async function loadEvents() {
  const query = state.selectedUser ? `?user_id=${encodeURIComponent(state.selectedUser)}` : "";
  const response = await fetch(`/api/events${query}`);
  state.events = await response.json();
  render();
}

function render() {
  const events = state.events;
  const latest = events[events.length - 1];
  const total = events.length;
  const today = events.filter((event) => String(event.timestamp || "").slice(0, 10) === todayKey()).length;
  const avgConfidence = total
    ? events.reduce((sum, event) => sum + Number(event.confidence || 0), 0) / total
    : 0;

  document.getElementById("totalCount").textContent = total;
  document.getElementById("todayCount").textContent = today;
  document.getElementById("avgConfidence").textContent = pct(avgConfidence);

  const titleUser = state.selectedUser ? state.selectedUser.replace("user_0", "User ") : "All Users";
  document.getElementById("heroTitle").textContent = `${titleUser} recycling report`;
  document.getElementById("heroSubtitle").textContent = total
    ? `${total} recycling event${total === 1 ? "" : "s"} have been stored in AWS.`
    : "No detection events have been received yet.";

  renderClassCounts(events);
  renderPassport(latest);
  renderEnvironment(latest);
  renderHourlyBars(events);
  renderRows(events);

  document.getElementById("lastUpdated").textContent = `Updated ${new Date().toLocaleTimeString("en-US")}`;
}

function renderClassCounts(events) {
  const counts = { plastic: 0, paper: 0, can: 0, glass: 0 };
  for (const event of events) {
    const type = event.trash_type;
    if (Object.prototype.hasOwnProperty.call(counts, type)) {
      counts[type] += 1;
    }
  }

  for (const [type, id] of Object.entries(trashIds)) {
    document.getElementById(id).textContent = counts[type];
  }
}

function renderPassport(event) {
  if (!event) {
    document.getElementById("passportClass").textContent = "No Scan";
    document.getElementById("passportGuide").textContent = "The latest scan result will appear here once recycling events are received.";
    document.getElementById("passportUser").textContent = "-";
    document.getElementById("passportConfidence").textContent = "-";
    document.getElementById("passportTime").textContent = "-";
    return;
  }

  document.getElementById("passportClass").textContent = String(event.trash_type || "unknown").toUpperCase();
  document.getElementById("passportGuide").textContent = event.disposal_guide || "Check the recommended recycling bin.";
  document.getElementById("passportUser").textContent = event.user_label || event.user_id || "-";
  document.getElementById("passportConfidence").textContent = pct(Number(event.confidence || 0));
  document.getElementById("passportTime").textContent = fmtTime(event.timestamp);
}

function renderEnvironment(event) {
  document.getElementById("latestTemp").textContent = event ? `${Number(event.temperature || 0).toFixed(1)} C` : "-";
  document.getElementById("latestHumidity").textContent = event ? `${Number(event.humidity || 0).toFixed(1)} %` : "-";
  document.getElementById("latestStatus").textContent = event ? event.status || "-" : "-";
}

function renderHourlyBars(events) {
  const hourly = Array.from({ length: 24 }, () => 0);
  for (const event of events) {
    const date = new Date(event.timestamp);
    if (!Number.isNaN(date.getTime())) {
      hourly[date.getHours()] += 1;
    }
  }

  const compactHours = [7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18];
  const max = Math.max(1, ...compactHours.map((hour) => hourly[hour]));
  const container = document.getElementById("hourlyBars");
  container.innerHTML = compactHours
    .map((hour) => {
      const height = Math.max(4, Math.round((hourly[hour] / max) * 150));
      return `<div class="bar"><i style="height:${height}px"></i><span>${String(hour).padStart(2, "0")}</span></div>`;
    })
    .join("");
}

function renderRows(events) {
  const rows = events
    .slice(-10)
    .reverse()
    .map((event) => `
      <tr>
        <td>${fmtTime(event.timestamp)}</td>
        <td>${event.user_label || event.user_id || "-"}</td>
        <td>${event.trash_type || "-"}</td>
        <td>${pct(Number(event.confidence || 0))}</td>
        <td>${Number(event.distance_cm || 0).toFixed(1)} cm</td>
        <td>${event.status || "-"}</td>
      </tr>
    `)
    .join("");

  document.getElementById("eventRows").innerHTML = rows || `<tr><td colspan="6">No events yet.</td></tr>`;
}

document.getElementById("userSelect").addEventListener("change", (event) => {
  state.selectedUser = event.target.value;
  loadEvents();
});

loadEvents();
setInterval(loadEvents, 5000);
