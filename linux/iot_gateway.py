"""Embedded IoT gateway: Arduino USB serial -> validated SQLite readings and alerts.

Compatible with the three-sensor Arduino firmware sending newline-delimited JSON:
{"pir":1,"distance_cm":18.3,"temperature":25,"humidity":34}

Run as the 'hodhod' user under embedded-iot-gateway.service.
"""

import json
import math
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import serial
from serial.tools import list_ports

PROJECT_DIR = Path(__file__).resolve().parent
DB_PATH = PROJECT_DIR / "sensor_data.db"
BAUD_RATE = 9600
RECONNECT_DELAY_SECONDS = 3

# Edit these two thresholds to customize your alerts.
OBSTACLE_LIMIT_CM = 20.0
HIGH_TEMPERATURE_LIMIT_C = 30.0


def find_arduino():
    """Find an Arduino UNO, allowing the Linux device name to change."""
    for port in list_ports.comports():
        if (port.vid, port.pid) == (0x2341, 0x0043):
            return port.device
        if "arduino" in (port.description or "").lower():
            return port.device
    return None


def create_tables(db):
    # CREATE TABLE IF NOT EXISTS preserves all previously collected measurements.
    db.execute("""
        CREATE TABLE IF NOT EXISTS measurements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            pir INTEGER,
            distance_cm REAL,
            temperature REAL,
            humidity REAL
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS alert_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            alert_type TEXT NOT NULL,
            event TEXT NOT NULL CHECK (event IN ('STARTED', 'RESOLVED')),
            value REAL
        )
    """)
    db.commit()


def valid_measurement(data):
    if not isinstance(data, dict):
        return False
    required = ("pir", "distance_cm", "temperature", "humidity")
    if not all(k in data for k in required):
        return False
    if type(data["pir"]) is not int or data["pir"] not in (0, 1):
        return False
    for key in required[1:]:
        value = data[key]
        if value is not None and (
            type(value) not in (int, float) or not math.isfinite(value)
        ):
            return False
    # Negative distance cannot represent a valid HC-SR04 reading.
    return data["distance_cm"] is None or data["distance_cm"] >= 0


def record_alert_transition(db, timestamp, alert_type, value, is_active):
    """Log just the change, never duplicate an unchanged active alert.

    State is read from the database so restarting the service does not
    create a second STARTED event for an already-active alert.
    """
    if value is None:
        return  # Invalid/missing sensor data is not evidence of recovery.

    row = db.execute("""
        SELECT event FROM alert_events
        WHERE alert_type = ?
        ORDER BY id DESC LIMIT 1
    """, (alert_type,)).fetchone()
    was_active = row is not None and row[0] == "STARTED"

    if is_active == was_active:
        return

    event = "STARTED" if is_active else "RESOLVED"
    db.execute("""
        INSERT INTO alert_events (timestamp, alert_type, event, value)
        VALUES (?, ?, ?, ?)
    """, (timestamp, alert_type, event, value))
    print(f"ALERT {alert_type} {event}: {value}", flush=True)


def store_measurement(db, data):
    timestamp = datetime.now().astimezone().isoformat(timespec="milliseconds")
    # A measurement and the alert transitions caused by it are committed together.
    with db:
        db.execute("""
            INSERT INTO measurements (
                timestamp, pir, distance_cm, temperature, humidity
            ) VALUES (?, ?, ?, ?, ?)
        """, (
            timestamp, data["pir"], data["distance_cm"],
            data["temperature"], data["humidity"]
        ))
        distance = data["distance_cm"]
        temperature = data["temperature"]
        record_alert_transition(
            db, timestamp, "OBSTACLE", distance,
            distance is not None and distance <= OBSTACLE_LIMIT_CM
        )
        record_alert_transition(
            db, timestamp, "HIGH_TEMPERATURE", temperature,
            temperature is not None and temperature >= HIGH_TEMPERATURE_LIMIT_C
        )
    print(
        f"[{timestamp}] PIR={data['pir']} "
        f"Distance={distance}cm Temp={temperature}C "
        f"Humidity={data['humidity']}% - Saved to SQLite",
        flush=True,
    )


def run():
    db = sqlite3.connect(DB_PATH, timeout=10)
    try:
        create_tables(db)
        print("IoT Gateway: measurements + alert history enabled", flush=True)
        print(f"Database: {DB_PATH}", flush=True)

        while True:
            port = find_arduino()
            if port is None:
                print("Arduino not found. Retrying...", flush=True)
                time.sleep(RECONNECT_DELAY_SECONDS)
                continue

            try:
                print(f"Connecting to {port}...", flush=True)
                with serial.Serial(port, BAUD_RATE, timeout=2) as arduino:
                    # Opening an UNO serial port can reset the board.
                    time.sleep(2)
                    print("Arduino connected. Collecting measurements...", flush=True)
                    while True:
                        raw = arduino.readline()
                        if not raw:
                            continue
                        line = raw.decode("utf-8", errors="replace").strip()
                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError:
                            print(f"Ignoring incomplete JSON: {line}", flush=True)
                            continue
                        if not valid_measurement(data):
                            print(f"Ignoring invalid measurement: {data}", flush=True)
                            continue
                        store_measurement(db, data)
            except (serial.SerialException, OSError) as exc:
                print(f"USB connection lost: {exc}", flush=True)
                print("Attempting reconnection...", flush=True)
                time.sleep(RECONNECT_DELAY_SECONDS)
    finally:
        db.close()
        print("Database closed.", flush=True)


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        print("Monitoring stopped.", flush=True)
