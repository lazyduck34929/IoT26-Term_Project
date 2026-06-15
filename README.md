# Documentary for IoT26 Term Project

<img width="1210" height="1378" alt="image" src="https://github.com/user-attachments/assets/ffd5860a-b9e8-4c63-84e5-abc8b9156d28" />

---

<br>
<br>
<br>

<h2>Title: AIoT Smart Recycling System</h1>
---
<h2>Introduce</h2>

This is a smart recycling bin system that combines object recognition based on YOLO v8 nano with IoT sensors (ultrasonic, temperature and humidity) to automatically sort waste and visualize real-time hygiene status and usage pattern statistics on a dashboard.

<br>
<br>
<br>

<h2>Key Features</h2>

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

<br>
<br>
<br>

<h2>Demonstration execution results</h2>
<h4>Execution screenshot in raspberryPi kernel</h4>
<img width="1447" height="891" alt="image" src="https://github.com/user-attachments/assets/1466d1ab-2428-458a-bd89-261457541d38" />

<br>
<br>

<h4>Demonstration screenshot & GIF</h4>
<img width="400" height="225" alt="term_project_demo" src="https://github.com/user-attachments/assets/723d4235-e4a4-4b0f-be34-c4d30c2738e8" />

<br>
<br>

<img width="640" height="480" alt="image" src="https://github.com/user-attachments/assets/9ef62925-a4b4-4df5-9de4-666c3f56e4c6" />

<br>
<br>

<h4>Dashboard screen</h4>
<img width="1210" height="1378" alt="image" src="https://github.com/user-attachments/assets/1b09b8dc-b7a5-4169-8ec2-2cfaeb4bcd9a" />
You can view statistics for the entire dataset or for a specific user. (In the screenshot above, the statistics are for a specific user.)

---

<br>
<br>
<br>

<h2>Why Cloud?(Conclusion & Key Benefits)</h2>
<h4>1. Resource Optimization for Edge Devices</h4>

- Lightweight Storage Management: By immediately offloading environmental data and detection event logs to the cloud rather than locally, we have fundamentally prevented the potential for capacity saturation and file system corruption on the Raspberry Pi's internal MicroSD card.

- Intensive Computing Resources: By separating heavy processes such as dashboard statistical aggregation, computation, and web server hosting to AWS EC2, we have optimized the Raspberry Pi so that its limited resources can be fully focused on real-time YOLO AI inference and sensor I/O control.



<h4>2. Data Centralization and System Scalability</h4>

- Multi-Device Synchronization: Since the Flask server acts as a data hub, real-time JSON data can be streamed to a single AWS instance for integrated management without conflicts, even if multiple smart collection bins are deployed in the future. 

- Decoupled structure: The system is completely separated into an Edge area responsible for data collection and inference and a Cloud area responsible for data storage and visualization, enabling individual function enhancement and maintenance without interdependence.



<h4>3. Real-time Accessibility and Enhanced Management Efficiency</h4>

- Web-based Global Monitoring: Overcoming the limitations of local networks, you can access the dashboard from anywhere with an internet connection to monitor key indicators in real time, such as usage patterns by time of day, hygiene status of collection bins, and the latest disposal history.

<br>
<br>
<br>

<h2>Various statistical data from the old version</h2>
---
<h4>Note: This section shows what statistics can be generated from the data, but deals with statistics that were omitted during the web page integration process.</h4>
<br>
<h4>Therefore, the contents of this section should be viewed solely in terms of data scalability, demonstrating that statistics can be utilized in such diverse ways.</h4>
---

<h4>Ratio of recyclable waste types</h4>
<img width="2548" height="1250" alt="image" src="https://github.com/user-attachments/assets/43ac8a82-87cd-4d2f-bd5e-b33a89625d99" />

<br>
<br>

<h4>Hourly and monthly temperature and humidity trend statistics by specific year (or all years)</h4>
<img width="2551" height="1253" alt="image" src="https://github.com/user-attachments/assets/c8353d2d-f038-41e5-bec8-230f38ff59a9" />

<br>
<br>

<h4>Monthly usage pattern statistics by specific year(or entire year) (Hourly data also exists in the latest version.)</h4>
<img width="2552" height="1265" alt="image" src="https://github.com/user-attachments/assets/83169226-b8aa-4e40-853c-9083b03adb93" />

















