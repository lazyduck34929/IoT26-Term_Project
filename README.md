# IoT26 Term Project - AIoT Smart Recycling System

<img width="1210" height="1378" alt="image" src="https://github.com/user-attachments/assets/ffd5860a-b9e8-4c63-84e5-abc8b9156d28" />

---

<br>
<br>
<br>

<h2>Title: RecycleOps</h1>
<h2>Introduce</h2>

This is a smart recycling bin system that combines object recognition based on YOLO v8 nano with IoT sensors (ultrasonic, temperature and humidity) to automatically sort waste and visualize real-time hygiene status and usage pattern statistics on a dashboard.

<br>
<br>
<br>

<h2>Used Dataset</h2>
<h4>yolov8-trash-detections Computer Vision Model</h4>
<img width="1557" height="897" alt="image" src="https://github.com/user-attachments/assets/dc3b0289-5b32-4097-aeba-9b86f08b97e8" />

<br>
<h4>The dataset can be downloaded from roboflow.
https://universe.roboflow.com/fyp-bfx3h/yolov8-trash-detections</h4>

<br>
<br>
<br>

<h2>Key Features</h2>

<h4>Edge Side(raspberry_PI)</h4>
- YOLO v8-based Object Recognition: Identifies recyclable waste (plastic, cans, paper, glass, etc.) with minimal error by applying a multi-frame voting system (decide_by_votes).

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

<h2>Why we use Cloud?(Key Benefits)</h2>
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

<h2>The process of integrating Raspberry Pi and AWS</h2>
<h4>Registering an SSH Public Key for External Device Access</h4>

Proceed with configuring the authentication key to enable secure, password-free SSH remote access to the AWS EC2 instance from an external environment (local development PC or edge device).

While connected to the EC2 instance server, execute the following commands sequentially.


<h4>1. Create SSH configuration directory and grant permissions</h4>

mkdir -p ~/.ssh

<h4>2. Add local PC's SSH Public Key to the authorized_keys file</h4>

echo 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAs57dDR59SOgnfBwZFh1bQXS5fJegXWR2108cZW8NiE gjwlg-recycleops' >> ~/.ssh/authorized_keys

<h4>3. Set directory and file permissions to comply with SSH security policies (Required)</h4>

chmod 700 ~/.ssh

chmod 600 ~/.ssh/authorized_keys

<h4>4. Check the bottom of the file to verify that the public key has been successfully registered</h4>

tail -n 3 ~/.ssh/authorized_keys
<img width="1097" height="88" alt="image" src="https://github.com/user-attachments/assets/6a45f58c-e00a-4ed0-a34f-8ce0f5d023ca" />

<br>
<br>
<br>

<h2>Flask Server Directory Structure and the Purpose of Each File</h2>
<img width="276" height="361" alt="image" src="https://github.com/user-attachments/assets/954f5f4f-67f0-4141-90bf-0a3c77689a14" />

<br>
<h4>`server.py` (Backend - Flask App)</h4>

- API Endpoint Hosting: Provides a REST API (`POST /api/events`) and a dashboard data retrieval API (`GET /api/events`) to securely receive real-time data from external edge devices such as Raspberry Pi.

- Data Validation and Standardization: Handles whitelist-based authentication via the `X-API-Key` header and converts missing or invalid data types into safe values ​​(`safe_float`, `safe_int`) (Normalize).

- Lightweight Data Logging (Database Replacement): After checking for duplicates in received structured JSON data (filtering by `event_id`), it loads (appends) the data line by line into the `detection_events.jsonl` file, which is excellent for scalability and preventing data loss.

<br>

<h4>`dashboard.html` (Frontend - Structure)</h4>

- Building the User Interface Framework: A Markdown/HTML5 file that defines the basic structure and layout of the real-time statistics monitoring screen. Component Placement: Includes a top widget card area to display the total number of data points, average AI reliability, etc., a chart canvas (`canvas`) area where statistical graphs by type will be drawn, and a recent event log table structure that will be updated in real time.

<br>

<h4>`dashboard.js` (Frontend - Logic & Dynamic Control)</h4>

- Real-time Data Communication: While the web browser is open, it periodically calls the backend server's API (`GET /api/events`) to retrieve the latest waste separation data in real time.

- Dynamic DOM Manipulation and Chart Visualization: It processes the retrieved JSON log data using JavaScript to update the dashboard's numeric widgets in real time, and integrates with libraries such as Chart.js to dynamically draw graphs showing usage patterns or waste disposal statistics by type.

<br>
<br>
<br>

<h2>Demonstration execution results</h2>
<h4>Execution screenshot in raspberryPi kernel</h4>
<img width="1447" height="891" alt="image" src="https://github.com/user-attachments/assets/1466d1ab-2428-458a-bd89-261457541d38" />

<br>
<br>

<h4>Demonstration screenshot & GIFs</h4>
<img width="400" height="225" alt="term_project_demo" src="https://github.com/user-attachments/assets/723d4235-e4a4-4b0f-be34-c4d30c2738e8" />

<br>
<br>

<img width="640" height="480" alt="image" src="https://github.com/user-attachments/assets/9ef62925-a4b4-4df5-9de4-666c3f56e4c6" />

<br>
<br>

<img width="400" height="711" alt="KakaoTalk_20260616_095950237" src="https://github.com/user-attachments/assets/34282d6d-21c9-418d-b4ef-0afd389ca33e" />

<br>
<br>
`


<h4>Dashboard screen</h4>
<img width="1210" height="1378" alt="image" src="https://github.com/user-attachments/assets/1b09b8dc-b7a5-4169-8ec2-2cfaeb4bcd9a" />
You can view statistics for the entire dataset or for a specific user. (In the screenshot above, the statistics are for a specific user.)

---

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

















