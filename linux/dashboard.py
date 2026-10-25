"""Local Flask dashboard for the Arduino + Ubuntu IoT gateway."""

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from flask import Flask, jsonify, render_template_string

app = Flask(__name__)
DB_PATH = Path(__file__).resolve().parent / "sensor_data.db"


def get_snapshot():
    """Read the newest measurement and the row count from SQLite."""
    with closing(sqlite3.connect(DB_PATH)) as db:
        db.row_factory = sqlite3.Row
        latest = db.execute(
            "SELECT * FROM measurements ORDER BY id DESC LIMIT 1"
        ).fetchone()
        total = db.execute("SELECT COUNT(*) FROM measurements").fetchone()[0]

    latest = dict(latest) if latest is not None else None
    sensor_online = False
    if latest and latest.get("timestamp"):
        try:
            recorded_at = datetime.fromisoformat(latest["timestamp"])
            if recorded_at.tzinfo is not None:
                elapsed = (
                    datetime.now(timezone.utc)
                    - recorded_at.astimezone(timezone.utc)
                ).total_seconds()
                sensor_online = 0 <= elapsed <= 10
        except (ValueError, TypeError):
            pass

    distance = latest.get("distance_cm") if latest else None
    obstacle_alert = (
        sensor_online and distance is not None and distance <= 20
    )

    temperature = latest.get("temperature") if latest else None
    high_temperature_alert = (
        sensor_online and temperature is not None and temperature >= 30
    )

    return {
        "latest": latest,
        "total": total,
        "sensor_online": sensor_online,
        "obstacle_alert": obstacle_alert,
        "high_temperature_alert": high_temperature_alert,
    }


@app.route("/api/status")
def api_status():
    return jsonify(get_snapshot())


@app.route("/api/history")
def api_history():
    with closing(sqlite3.connect(DB_PATH)) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            """SELECT timestamp, temperature, humidity, distance_cm, pir
               FROM measurements ORDER BY id DESC LIMIT 60"""
        ).fetchall()
    return jsonify([dict(row) for row in reversed(rows)])


@app.route("/api/alerts")
def api_alerts():
    """Return the latest alert transitions recorded by iot_gateway.py."""
    with closing(sqlite3.connect(DB_PATH)) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            """SELECT timestamp, alert_type, event, value
               FROM alert_events ORDER BY id DESC LIMIT 20"""
        ).fetchall()
    return jsonify([dict(row) for row in rows])


HTML = r"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Embedded Linux IoT Dashboard</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <style>
    * { box-sizing: border-box; }
    body { margin: 0; padding: 34px 18px 60px; background: #0f172a;
           color: #f8fafc; font-family: Arial, sans-serif; }
    main { max-width: 1160px; margin: auto; }
    header { text-align: center; }
    h1 { color: #38bdf8; margin-bottom: 10px; }
    .subtitle, .muted { color: #94a3b8; }
    #connectionStatus { margin-top: 18px; font-weight: bold; color: #f59e0b; }
    #connectionStatus.live { color: #22c55e; }
    #obstacleAlert { background: #7f1d1d; border: 2px solid #ef4444;
                     border-radius: 12px; text-align: center; padding: 18px;
                     margin: 22px 0; font-weight: bold; font-size: 20px; }
    #temperatureAlert { background: #78350f; border: 2px solid #f59e0b;
                        border-radius: 12px; text-align: center; padding: 18px;
                        margin: 16px 0; font-weight: bold; font-size: 19px; }
    [hidden] { display: none !important; }
    .cards { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr));
             gap: 15px; margin: 32px 0 14px; }
    .card, .chart-card { background: #1e293b; border: 1px solid #334155;
                         border-radius: 12px; padding: 20px; }
    .card { text-align: center; }
    .card h3 { margin: 0 0 16px; font-size: 16px; }
    .value { color: #22c55e; font-size: 25px; font-weight: bold; overflow-wrap: anywhere; }
    #lastUpdate { text-align: center; font-size: 13px; margin: 18px 0 32px; }
    h2 { margin: 28px 0 8px; }
    .charts { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
              gap: 16px; margin-top: 18px; }
    .chart-card h3 { margin: 0 0 12px; font-size: 15px; }
    .canvas-wrap { position: relative; height: 245px; }
    #chartError { text-align: center; color: #fbbf24; }
    .alerts-panel { margin-top: 32px; background: #1e293b;
                    border: 1px solid #334155; border-radius: 12px;
                    padding: 20px; overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; min-width: 500px; }
    th, td { text-align: left; padding: 12px; border-bottom: 1px solid #334155; }
    th { color: #93c5fd; font-size: 13px; }
    tr:last-child td { border-bottom: none; }
    .event-start { color: #f87171; font-weight: 700; }
    .event-resolved { color: #4ade80; font-weight: 700; }
    #alertsError { color: #fbbf24; }
    @media (max-width: 1000px) {
      .cards { grid-template-columns: repeat(3, minmax(0, 1fr)); }
      .charts { grid-template-columns: 1fr; }
    }
    @media (max-width: 570px) {
      .cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .value { font-size: 21px; }
    }
  </style>
</head>
<body>
<main>
  <header>
    <h1>Embedded Linux IoT Dashboard</h1>
    <p class="subtitle">Arduino UNO + Ubuntu Linux · HC-SR501 · HC-SR04 · DHT11</p>
    <div id="connectionStatus">● Checking for recent data...</div>
  </header>

  <div id="obstacleAlert" role="alert" hidden>
    ⚠️ OBSTACLE DETECTED!
    <div style="font-size: 15px; margin-top: 8px;">
      Object within 20 cm: <span id="obstacleDistance">—</span>
    </div>
  </div>

  <div id="temperatureAlert" role="alert" hidden>
    ⚠️ HIGH TEMPERATURE!
    <div style="font-size: 15px; margin-top: 8px;">
      Measured temperature is at least 30 °C: <span id="highTemperature">—</span>
    </div>
  </div>

  <section class="cards">
    <div class="card"><h3>🌡️ Temperature</h3><div class="value" id="temperature">—</div></div>
    <div class="card"><h3>💧 Humidity</h3><div class="value" id="humidity">—</div></div>
    <div class="card"><h3>📏 Distance</h3><div class="value" id="distance">—</div></div>
    <div class="card"><h3>🚶 Motion</h3><div class="value" id="motion">—</div></div>
    <div class="card"><h3>💾 Measurements</h3><div class="value" id="total">0</div></div>
  </section>
  <p class="muted" id="lastUpdate">No measurements yet</p>

  <h2>Sensor History</h2>
  <p class="muted">Last 60 measurements · automatically updated every 3 seconds</p>
  <p id="chartError" hidden>Charts could not load. Check that Ubuntu can access the Chart.js CDN.</p>
  <section class="charts">
    <div class="chart-card"><h3>Temperature (°C)</h3><div class="canvas-wrap"><canvas id="temperatureChart"></canvas></div></div>
    <div class="chart-card"><h3>Humidity (%)</h3><div class="canvas-wrap"><canvas id="humidityChart"></canvas></div></div>
    <div class="chart-card"><h3>Distance (cm)</h3><div class="canvas-wrap"><canvas id="distanceChart"></canvas></div></div>
  </section>

  <section class="alerts-panel" aria-label="Recent alert events">
    <h2 style="margin-top: 0">Alert History</h2>
    <p class="muted">Most recent 20 alert transitions · updated every 3 seconds</p>
    <p id="alertsError" hidden>Alert history could not be loaded.</p>
    <table>
      <thead>
        <tr><th>Time</th><th>Alert</th><th>Event</th><th>Sensor value</th></tr>
      </thead>
      <tbody id="alertRows"><tr><td colspan="4">Loading alerts...</td></tr></tbody>
    </table>
  </section>
</main>
<script>
  const element = id => document.getElementById(id);
  const reading = (value, unit) => value == null ? '—' : `${Number(value).toFixed(1)} ${unit}`;

  async function updateStatus() {
    try {
      const response = await fetch('/api/status', {cache: 'no-store'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      const latest = data.latest;

      element('temperature').textContent = latest ? reading(latest.temperature, '°C') : '—';
      element('humidity').textContent = latest ? reading(latest.humidity, '%') : '—';
      element('distance').textContent = latest ? reading(latest.distance_cm, 'cm') : '—';
      element('motion').textContent = !latest ? '—' : (latest.pir === 1 ? 'DETECTED' : 'NO MOTION');
      element('total').textContent = data.total;
      element('lastUpdate').textContent = latest ? `Last measurement: ${latest.timestamp}` : 'No measurements yet';

      const status = element('connectionStatus');
      status.textContent = data.sensor_online ? '● LIVE — Receiving Sensor Data' : '● NO RECENT SENSOR DATA';
      status.classList.toggle('live', data.sensor_online);

      element('obstacleAlert').hidden = !data.obstacle_alert;
      if (data.obstacle_alert) {
        element('obstacleDistance').textContent = reading(latest.distance_cm, 'cm');
      }
      element('temperatureAlert').hidden = !data.high_temperature_alert;
      if (data.high_temperature_alert) {
        element('highTemperature').textContent = reading(latest.temperature, '°C');
      }
    } catch (error) {
      element('connectionStatus').textContent = '● DASHBOARD DATA UNAVAILABLE';
      element('connectionStatus').classList.remove('live');
      element('obstacleAlert').hidden = true;
      element('temperatureAlert').hidden = true;
      console.error('Status request failed:', error);
    }
  }

  let charts = null;
  function createChart(canvasId, label, color) {
    return new Chart(element(canvasId), {
      type: 'line',
      data: {labels: [], datasets: [{label, data: [], borderColor: color,
                backgroundColor: color, tension: 0.15, pointRadius: 2,
                spanGaps: false}]},
      options: {responsive: true, maintainAspectRatio: false,
        animation: false,
        plugins: {legend: {display: false}},
        scales: {
          x: {ticks: {color: '#94a3b8', maxTicksLimit: 6}, grid: {color: '#334155'}},
          y: {ticks: {color: '#94a3b8'}, grid: {color: '#334155'}}
        }
      }
    });
  }

  async function updateHistory() {
    if (!charts) return;
    try {
      const response = await fetch('/api/history', {cache: 'no-store'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const rows = await response.json();
      const labels = rows.map(r => new Date(r.timestamp).toLocaleTimeString());
      const series = [
        ['temperature', rows.map(r => r.temperature)],
        ['humidity', rows.map(r => r.humidity)],
        ['distance', rows.map(r => r.distance_cm)]
      ];
      for (const [key, values] of series) {
        charts[key].data.labels = labels;
        charts[key].data.datasets[0].data = values;
        charts[key].update('none');
      }
    } catch (error) {
      console.error('History request failed:', error);
    }
  }

  // Display transitions previously logged by the Linux IoT gateway.
  async function updateAlerts() {
    try {
      const response = await fetch('/api/alerts', {cache: 'no-store'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const rows = await response.json();
      const table = element('alertRows');
      table.replaceChildren();
      if (rows.length === 0) {
        const tr = document.createElement('tr');
        const td = document.createElement('td');
        td.colSpan = 4;
        td.textContent = 'No alert events recorded yet.';
        tr.appendChild(td);
        table.appendChild(tr);
      }
      for (const row of rows) {
        const tr = document.createElement('tr');
        const units = row.alert_type === 'OBSTACLE' ? 'cm'
                    : row.alert_type === 'HIGH_TEMPERATURE' ? '°C' : '';
        const values = [
          new Date(row.timestamp).toLocaleString(),
          row.alert_type.replaceAll('_', ' '),
          row.event,
          row.value == null ? '—' : `${Number(row.value).toFixed(1)} ${units}`
        ];
        for (const [index, value] of values.entries()) {
          const td = document.createElement('td');
          td.textContent = value;
          if (index === 2) {
            td.className = row.event === 'STARTED' ? 'event-start' : 'event-resolved';
          }
          tr.appendChild(td);
        }
        table.appendChild(tr);
      }
      element('alertsError').hidden = true;
    } catch (error) {
      element('alertsError').hidden = false;
      console.error('Alert history request failed:', error);
    }
  }

  if (typeof Chart !== 'undefined') {
    charts = {
      temperature: createChart('temperatureChart', 'Temperature', '#fb923c'),
      humidity: createChart('humidityChart', 'Humidity', '#38bdf8'),
      distance: createChart('distanceChart', 'Distance', '#22c55e')
    };
  } else {
    element('chartError').hidden = false;
  }

  function refresh() { updateStatus(); updateHistory(); updateAlerts(); }
  refresh();
  setInterval(refresh, 3000);
</script>
</body>
</html>
"""


@app.route("/")
def dashboard():
    return render_template_string(HTML)


if __name__ == "__main__":
    # Development server accessible only inside Ubuntu itself.
    app.run(host="127.0.0.1", port=5000)
