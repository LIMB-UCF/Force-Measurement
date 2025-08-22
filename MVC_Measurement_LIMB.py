import sys
import os
import csv
import json
import time
import threading
import queue
from datetime import datetime
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QLineEdit,
    QSpacerItem, QSizePolicy, QApplication, QMessageBox
)
from PyQt5.QtCore import Qt, QTimer
import pyqtgraph as pg
from gdx import gdx


# ======================== SENSOR INITIALIZATION ========================
class GDXForceSensor:
    def __init__(self):
        self.gdx_device = gdx.gdx()
        
        # self.gdx_device.open(connection='usb')
        try:
            self.gdx_device.open(connection='usb')
        except Exception as e:
            print(f"Error opening sensor: {e}")
            self.gdx_device = None  # Mark the device as unavailable

        self.gdx_device.select_sensors([1])  # Selecting first sensor
        self.gdx_device.start(20)  # 20ms sampling rate
        self.data_queue = queue.Queue()
        self.latest_value = 0  # Store the latest force value
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._read_sensor_data, daemon=True)
        self.thread.start()

    def _read_sensor_data(self):
        while not self.stop_event.is_set():
            try:
                measurements = self.gdx_device.read()
                if measurements and len(measurements) > 0:
                    self.latest_value = measurements[0]
                    self.data_queue.put(measurements[0])
                else:
                    self.latest_value = 0  # Default value if no data
            except Exception as e:
                print(f"Sensor Read Error: {e}")


    def get_force(self):
        """Fetch latest force value without emptying the queue."""
        return self.latest_value

    def stop(self):
        """Stops the sensor and the thread properly."""
        self.stop_event.set()
        self.thread.join()
        try:
            self.gdx_device.stop()
            self.gdx_device.close()
        except Exception as e:
            print(f"Error stopping sensor: {e}")



# ======================== MAIN EXPERIMENT GUI ========================
class MVCExperiment(QWidget):
    def __init__(self):
        super(MVCExperiment, self).__init__()

        self.setWindowTitle("Laboratory for Interaction of Machine and Brain (LIMB) - Vernier GoDirect Hand Dynamometer - MVC Measurement Experiment")
        self.setGeometry(100, 100, 1200, 600)

        self.force_sensor = GDXForceSensor()

        # ==================== LAYOUT SETUP ====================
        self.main_layout = QHBoxLayout(self)

        self.left_panel = QVBoxLayout()
        self.left_widget = QWidget()
        self.left_widget.setFixedWidth(300)
        self.left_widget_layout = QVBoxLayout(self.left_widget)

        # --- Participant ID input ---
        self.participant_layout = QHBoxLayout()
        self.participant_label = QLabel("Participant ID:")
        self.participant_line_edit = QLineEdit()
        self.participant_layout.addWidget(self.participant_label)
        self.participant_layout.addWidget(self.participant_line_edit)
        self.left_widget_layout.addLayout(self.participant_layout)

        # --- Results Display ---
        self.results_display = QLabel("Results:")
        self.results_display.setWordWrap(True)
        self.left_widget_layout.addWidget(self.results_display)

        # Spacer to push later widgets toward the bottom
        self.left_widget_layout.addItem(QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding))

        # --- Motion Selection Dropdown ---
        self.motion_dropdown = QComboBox()
        self.motion_dropdown.addItem("Choose the motion")  # Placeholder
        self.motion_dropdown.addItems(["Full Grasp (Grip)", "Pinch (Index Finger)", "Pinch (Middle Finger)"])
        self.motion_dropdown.setCurrentIndex(0)
        self.left_widget_layout.addWidget(self.motion_dropdown)

        # --- Start and Stop Buttons ---
        self.button_layout = QHBoxLayout()
        self.start_button = QPushButton("Start")
        self.stop_button = QPushButton("Stop")
        self.start_button.setFixedSize(120, 40)
        self.stop_button.setFixedSize(120, 40)
        self.button_layout.addWidget(self.start_button)
        self.button_layout.addWidget(self.stop_button)
        self.left_widget_layout.addLayout(self.button_layout)

        self.left_panel.addWidget(self.left_widget)
        self.main_layout.addLayout(self.left_panel)

        # ==================== RIGHT PANEL (Graph & MVC Display) ====================
        self.right_panel = QVBoxLayout()

        # MVC Force Graph setup (x-range: 0 to 30 seconds)
        self.plotWidget = pg.PlotWidget()
        self.plotWidget.setLabel('left', "Force (N)")
        self.plotWidget.setLabel('bottom', "Time (s)")
        self.plotWidget.setTitle("MVC Measurement")
        self.plotWidget.showGrid(x=True, y=True)
        self.plotWidget.setYRange(0, 600)
        self.plotWidget.setXRange(0, 30)
        self.right_panel.addWidget(self.plotWidget, 3)

        # Plot elements for updating
        self.force_curve = self.plotWidget.plot([], [], pen=pg.mkPen('g', width=2))
        self.force_dot = self.plotWidget.plot([], [], pen=None, symbol='o', symbolSize=8, symbolBrush='w')

        # Maximum Force / Results Label (displayed below the plot)
        self.mvc_value_label = QLabel(
            "Final MVC Results:\n"
            "Trial 1 Average (5-10s): --\n"
            "Trial 2 Average (20-25s): --\n"
            "Overall Average: --"
        )
        self.mvc_value_label.setAlignment(Qt.AlignCenter)
        self.mvc_value_label.setStyleSheet("font-size: 20px; font-weight: bold; color: blue;")
        self.right_panel.addWidget(self.mvc_value_label, 1)

        # Countdown/Instruction Label
        self.countdown_label = QLabel("Select a movement from the dropdown menu and press Start when ready.")
        self.countdown_label.setAlignment(Qt.AlignCenter)
        self.countdown_label.setStyleSheet("font-size: 20px; font-weight: bold; color: red;")
        self.countdown_label.setFixedHeight(50)
        self.right_panel.addWidget(self.countdown_label, 1)

        # Trial Counter Label
        self.trial_counter_label = QLabel("Trial: 0 / 2")
        self.trial_counter_label.setAlignment(Qt.AlignCenter)
        self.trial_counter_label.setStyleSheet("font-size: 18px; font-weight: bold; color: blue;")
        self.trial_counter_label.setFixedHeight(30)
        self.right_panel.addWidget(self.trial_counter_label, 1)

        self.main_layout.addLayout(self.right_panel, 3)

        # ==================== DATA STORAGE & TIMERS ====================
        self.time_data = []
        self.force_data = []
        # Dictionary to store results per motion.
        self.results = {}

        # Define phases and durations:
        self.phase = None  
        self.global_start_time = None  
        self.phase_start_time = None  
        self.phase_durations = {
            "pre_trial1": 5,
            "trial1": 5,
            "rest": 10,
            "trial2": 5,
            "post_trial2": 5
        }


        # Initialize your force sensor
        # self.force_sensor = ForceSensor()

        # Create a queue for safe data exchange between the thread and GUI
        self.force_queue = queue.Queue()

        # Event to stop the background thread
        self.sensor_stop_event = threading.Event()

        # Start the background thread to continuously fetch force sensor data
        self.force_thread = threading.Thread(target=self.sensor_reading_thread, daemon=True)
        self.force_thread.start()


        # Timer for updating the plot (every 50ms)
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_measurement)

        # Timer for blinking "GO!" during trial phases
        self.blink_timer = QTimer()
        self.blink_timer.timeout.connect(self.toggle_go_visibility)
        self.blink_state = True

        # Connections
        self.start_button.clicked.connect(self.start_experiment)
        self.motion_dropdown.currentIndexChanged.connect(self.enable_start_button)
        self.stop_button.clicked.connect(self.stop_measurement)
    
    def sensor_reading_thread(self):
        """Continuously read sensor data in a background thread and push it into the queue."""
        while not self.sensor_stop_event.is_set():
            new_force = self.force_sensor.get_force()
            try:
                self.force_queue.put((time.time(), new_force), timeout=0.05)  # Prevent data loss
            except queue.Full:
                print("Queue is full, skipping force value")  # Debugging message
            
            time.sleep(0.02)  # Ensure delay matches sensor sampling rate



    def update_measurement(self):
        """Updates the plot and records data based on the current phase (called every 50ms)."""
        if self.global_start_time is None:
            return

        current_time = time.time() - self.global_start_time
        phase_elapsed = time.time() - self.phase_start_time if self.phase_start_time else 0

        new_force = 0  # Default force value for non-trial phases

        # Determine phase-based behavior
        if self.phase == "pre_trial1":
            remaining = int(self.phase_durations["pre_trial1"] - phase_elapsed)
            self.countdown_label.setText(f"Starting in {remaining}...")
        elif self.phase == "trial1":
            while not self.force_queue.empty():
                _, new_force = self.force_queue.get()
        elif self.phase == "rest":
            remaining = int(self.phase_durations["rest"] - phase_elapsed)
            self.countdown_label.setText(f"Rest for {remaining} seconds...")
        elif self.phase == "trial2":
            while not self.force_queue.empty():
                _, new_force = self.force_queue.get()
        elif self.phase == "post_trial2":
            remaining = int(self.phase_durations["post_trial2"] - phase_elapsed)
            self.countdown_label.setText(f"DONE, Now Rest! ({remaining})")

        # Store time and force data for plotting
        self.time_data.append(current_time)
        self.force_data.append(new_force)

        # **Limit data storage to last 1500 samples (~30s at 50ms interval)**
        if len(self.time_data) > 1500:  
            self.time_data.pop(0)
            self.force_data.pop(0)

        # Update the plot
        self.force_curve.setData(self.time_data, self.force_data)
        if self.time_data:
            self.force_dot.setData([self.time_data[-1]], [self.force_data[-1]])


    def update_mvc_label(self, trial1=None, trial2=None, overall=None):
        """
        Updates the MVC results label. If a value is None, displays '--'.
        """
        trial1_str = f"{trial1:.2f} N" if trial1 is not None else "--"
        trial2_str = f"{trial2:.2f} N" if trial2 is not None else "--"
        overall_str = f"{overall:.2f} N" if overall is not None else "--"

        text = (
            f"Final MVC Results:\n"
            f"Trial 1 Average (5-10s): {trial1_str}\n"
            f"Trial 2 Average (20-25s): {trial2_str}\n"
            f"Overall Average: {overall_str}"
        )
        self.mvc_value_label.setText(text)

    def enable_start_button(self):
        if self.motion_dropdown.currentIndex() == 0:
            self.start_button.setEnabled(False)
        else:
            self.start_button.setEnabled(True)

    def start_experiment(self):
        """Begins the entire sequence of phases after clearing previous data/plot."""
        if self.motion_dropdown.currentIndex() == 0:
            return  # Do nothing if no valid motion is selected.
        self.start_button.setEnabled(False)
        
        # Clear previous data, reset the plot, and reset the MVC label:
        self.time_data = []
        self.force_data = []
        self.force_curve.setData([], [])
        self.force_dot.setData([], [])
        self.update_mvc_label(trial1=None, trial2=None, overall=None)
        
        self.global_start_time = time.time()
        self.phase = "pre_trial1"
        self.phase_start_time = self.global_start_time
        self.trial_counter_label.setText("Trial: 0 / 2")
        self.countdown_label.setStyleSheet("font-size: 20px; font-weight: bold; color: red;")
        self.timer.start(50)  # Start updating the plot and recording data

        # Transition from pre_trial1 to trial1 after 5 seconds
        QTimer.singleShot(self.phase_durations["pre_trial1"] * 1000, self.start_trial1)

    def start_trial1(self):
        """Starts first trial measurement (Phase 2: 5-10s)."""
        self.phase = "trial1"
        self.phase_start_time = time.time()
        self.trial_counter_label.setText("Trial: 1 / 2")
        self.blink_state = True
        self.blink_timer.start(500)  # Blink "GO!" every 500ms

        # End trial1 after 5 seconds
        QTimer.singleShot(self.phase_durations["trial1"] * 1000, self.end_trial1)

    def end_trial1(self):
        """Ends trial 1, computes its average, and updates the label; then begins the rest period."""
        self.blink_timer.stop()
        self.countdown_label.setText("")  # Clear blinking text

        # Compute trial1 average (data between 5 and 10 seconds)
        trial1_forces = [f for t, f in zip(self.time_data, self.force_data) if 5 <= t <= 10]
        avg_trial1 = sum(trial1_forces) / len(trial1_forces) if trial1_forces else 0
        self.update_mvc_label(trial1=avg_trial1, trial2=None, overall=None)

        self.phase = "rest"
        self.phase_start_time = time.time()
        QTimer.singleShot(self.phase_durations["rest"] * 1000, self.start_trial2)

    def start_trial2(self):
        """Starts second trial measurement (Phase 4: 20-25s)."""
        self.phase = "trial2"
        self.phase_start_time = time.time()
        self.trial_counter_label.setText("Trial: 2 / 2")
        self.blink_state = True
        self.blink_timer.start(500)
        QTimer.singleShot(self.phase_durations["trial2"] * 1000, self.end_trial2)

    def end_trial2(self):
        """Ends trial 2, computes its average, and updates the label; then begins the post-trial rest."""
        self.blink_timer.stop()

        # Compute trial2 average (data between 20 and 25 seconds)
        trial2_forces = [f for t, f in zip(self.time_data, self.force_data) if 20 <= t <= 25]
        avg_trial2 = sum(trial2_forces) / len(trial2_forces) if trial2_forces else 0

        # Re-compute trial1 average to include in the update
        trial1_forces = [f for t, f in zip(self.time_data, self.force_data) if 5 <= t <= 10]
        avg_trial1 = sum(trial1_forces) / len(trial1_forces) if trial1_forces else 0

        self.update_mvc_label(trial1=avg_trial1, trial2=avg_trial2, overall=None)

        self.phase = "post_trial2"
        self.phase_start_time = time.time()
        self.countdown_label.setStyleSheet("font-size: 20px; font-weight: bold; color: red;")
        self.countdown_label.setText("DONE, Now Rest!")
        QTimer.singleShot(self.phase_durations["post_trial2"] * 1000, self.finish_experiment)


    def toggle_go_visibility(self):
        """Toggles the visibility of the 'GO!' message during trial phases."""
        if self.blink_state:
            self.countdown_label.setText("GO!")
        else:
            self.countdown_label.setText("")
        self.blink_state = not self.blink_state

    def stop_measurement(self):
        """Stops data acquisition and force sensor thread."""
        self.timer.stop()
        self.blink_timer.stop()
        
        # Signal the thread to stop and ensure it exits before stopping the sensor
        self.sensor_stop_event.set()
        self.force_thread.join()  # Wait for the sensor thread to fully stop
        
        try:
            # self.force_sensor.stop_sensor()
            self.force_sensor.stop()
        except Exception as e:
            print(f"Error stopping sensor: {e}")

        self.countdown_label.setText("Measurement stopped.")



    def update_results_display(self):
        """Updates the left panel to show the participant's ID and the computed results for each motion."""
        participant_id = self.participant_line_edit.text().strip() or "Unknown"
        display_text = f"Participant ID: {participant_id}\nResults:\n"
        for motion, avg in self.results.items():
            display_text += f"{motion}: {avg:.2f} N\n"
        self.results_display.setText(display_text)

    
    def finish_experiment(self):
        """Stops timers, computes overall MVC, and updates the final results display."""
        self.timer.stop()
        self.countdown_label.setText("")
        # Compute overall average from trial1 and trial2 data
        trial1_forces = [f for t, f in zip(self.time_data, self.force_data) if 5 <= t <= 10]
        trial2_forces = [f for t, f in zip(self.time_data, self.force_data) if 20 <= t <= 25]
        avg_trial1 = sum(trial1_forces) / len(trial1_forces) if trial1_forces else None
        avg_trial2 = sum(trial2_forces) / len(trial2_forces) if trial2_forces else None
        if avg_trial1 is not None and avg_trial2 is not None:
            overall_avg = (avg_trial1 + avg_trial2) / 2
        else:
            overall_avg = avg_trial1 if avg_trial1 is not None else avg_trial2


        self.update_mvc_label(trial1=avg_trial1, trial2=avg_trial2, overall=overall_avg)
        motion = self.motion_dropdown.currentText()
        self.results[motion] = overall_avg if overall_avg is not None else 0
        self.update_results_display()
        
        # If all three motions have been measured for this participant, save the results.
        if len(self.results) == 3:
            QMessageBox.information(self, "Experiment Complete", "MVC measurement has been successfully recorded.")
            self.save_results_to_csv()


    def save_results_to_csv(self):
        """Saves the current participant's MVC results for all motions to CSV and JSON."""
        filename = "mvc_results.csv"
        json_filename = "mvc_results.json"
        file_exists = os.path.isfile(filename)
        
        # Define CSV columns
        fieldnames = ["ParticipantID", "Date", "Time",
                    "Full Grasp (Grip)", "Pinch (Index Finger)", "Pinch (Middle Finger)"]
        
        current_time = datetime.now()
        date_str = current_time.strftime("%Y-%m-%d")
        time_str = current_time.strftime("%H:%M:%S")
        participant_id = self.participant_line_edit.text().strip() or "Unknown"

        row = {
            "ParticipantID": participant_id,
            "Date": date_str,
            "Time": time_str,
            "Full Grasp (Grip)": self.results.get("Full Grasp (Grip)", ""),
            "Pinch (Index Finger)": self.results.get("Pinch (Index Finger)", ""),
            "Pinch (Middle Finger)": self.results.get("Pinch (Middle Finger)", "")
        }

        # Save to CSV
        with open(filename, "a", newline="") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)
        
        # Save to JSON
        with open(json_filename, "a") as json_file:
            json.dump(row, json_file)
            json_file.write("\n")  # Newline for readability

        print(f"Saved MVC results for participant {participant_id} to {filename} and {json_filename}")
        self.results = {}  # Clear the results for the next participant



import atexit   # Import the atexit module to handle program exit for proper sensor cleanup

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MVCExperiment()
    window.show()

    # Ensure the sensor stops properly when the program exits
    atexit.register(window.force_sensor.stop)

    sys.exit(app.exec_())


