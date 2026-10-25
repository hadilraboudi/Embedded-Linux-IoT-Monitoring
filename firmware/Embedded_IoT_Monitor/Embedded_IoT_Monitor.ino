#include <SimpleDHT.h>

// Embedded Linux IoT Monitoring System
// Arduino UNO R3

// Sensor pins
const int pirPin = 2;
const int dhtPin = 3;
const int trigPin = 12;
const int echoPin = 11;

// DHT11 sensor
SimpleDHT11 dht11(dhtPin);

// Measurement interval
const unsigned long interval = 2500;
unsigned long lastMeasurement = 0;

void setup() {

  Serial.begin(9600);

  pinMode(pirPin, INPUT);
  pinMode(trigPin, OUTPUT);
  pinMode(echoPin, INPUT);

  digitalWrite(trigPin, LOW);
}

void loop() {

  if (millis() - lastMeasurement >= interval) {

    lastMeasurement = millis();

    // PIR motion detection
    int motion = digitalRead(pirPin);

    // Ultrasonic distance measurement
    digitalWrite(trigPin, LOW);
    delayMicroseconds(2);

    digitalWrite(trigPin, HIGH);
    delayMicroseconds(10);
    digitalWrite(trigPin, LOW);

    unsigned long duration =
        pulseIn(echoPin, HIGH, 30000UL);

    // Temperature and humidity
    byte temperature = 0;
    byte humidity = 0;

    int result = dht11.read(
      &temperature,
      &humidity,
      NULL
    );

    // Transmit JSON to Linux
    Serial.print("{\"pir\":");
    Serial.print(motion);

    Serial.print(",\"distance_cm\":");

    if (duration > 0) {
      float distance = duration * 0.0343 / 2.0;
      Serial.print(distance, 1);
    } else {
      Serial.print("null");
    }

    Serial.print(",\"temperature\":");

    if (result == SimpleDHTErrSuccess) {
      Serial.print((int)temperature);
    } else {
      Serial.print("null");
    }

    Serial.print(",\"humidity\":");

    if (result == SimpleDHTErrSuccess) {
      Serial.print((int)humidity);
    } else {
      Serial.print("null");
    }

    Serial.println("}");
  }
}
