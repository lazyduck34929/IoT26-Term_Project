# Documentary for IoT26 Term Project

<h2>Title: AIoT Smart Recycling System</h1>
---
<h2>Introduce</h2>

This is a smart recycling bin system that combines object recognition based on YOLO v8 nano with IoT sensors (ultrasonic, temperature and humidity) to automatically sort waste and visualize real-time hygiene status and usage pattern statistics on a dashboard.

---
<h2>Key Features</h2>
---
<h4>Edge Side(raspberry_PI)</h4>
- YOLO v11-based Object Recognition: Identifies recyclable waste (plastic, cans, paper, glass, etc.) with minimal error by applying a multi-frame voting system (decide_by_votes).

- Smart Sensor Control: Dynamically controls hardware (camera, buzzer) by detecting object approach using ultrasonic sensors (energy saving and malfunction prevention).

- HW-136/TTP229 Keypad Login: User session management functions (Key 1-7 login, Key 8 logout) and integration with individual waste disposal statistics.

- Environmental Monitoring: Measures temperature and humidity inside the collection bin using an SHT30 sensor, classifies hygiene grades (GOOD, CAUTION, WARNING), and performs local CSV logging every 10 seconds.

---
<h4>Cloud Side(AWS EC2)</h4>
- Flask REST API Server: Reliably receives JSON-formatted data from edge devices after secure verification (X-API-Key).

- JSON Lines (JSONL)-based lightweight data storage: Applies lightweight, loss-free cumulative loading technology.

- Statistical Dashboard Visualization: Provides real-time data on total accumulated data, daily detection counts, average AI confidence, emission charts by category, usage patterns by time of day, and recent event logs.








