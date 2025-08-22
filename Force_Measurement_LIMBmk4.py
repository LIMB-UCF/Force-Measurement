import time
import numpy as np
from pylsl import StreamInfo, StreamOutlet, local_clock
from gdx import gdx
from PyQt5 import QtWidgets, QtCore
import pyqtgraph as pg
import sys
import csv
import os
import random
import datetime
from collections import deque

# ---- Constants ----
SAMPLE_RATE = 50  # samples per second
STREAM_NAME = "ForceSensor"
STREAM_TYPE = "Force"

class ForceExperimentTab(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setWindowTitle("Laboratory for Interaction of Machine and Brain (LIMB) - Vernier GoDirect Hand Dynamometer - Force Measurement Experiment")
        self.setGeometry(100, 100, 1200, 600)

        # === Main Layout ===
        self.main_layout = QtWidgets.QHBoxLayout(self)

        self.start_time = None

        # --- Generate Trial Arrays BEFORE visualization starts ---
        # Generate 120 trials: 3 grip types x 4 MVC levels x 10 trials each.
        conditions = []
        for grip in ["IndexPinch", "MiddlePinch", "FullGrasp"]:
            for mvc in ["20", "40", "60", "80"]:
                for _ in range(5):
                    conditions.append(f"{grip}{mvc}")
        random.shuffle(conditions)
        self.trial_array1 = conditions

        conditions_2 = []
        for grip in ["IndexPinch", "MiddlePinch", "FullGrasp"]:
            for mvc in ["20", "40", "60", "80"]:
                for _ in range(5):
                    conditions_2.append(f"{grip}{mvc}")
        random.shuffle(conditions_2)
        self.trial_array2 = conditions_2
        
        self.phase_events_logged = set()

        # --- Timestamped CSV for Logging Experiment Events ---
        timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M")
        self.csv_filename = f"experiment_timestamps_{timestamp_str}.csv"

        # Initialize CSV file with headers
        with open(self.csv_filename, "w", newline="") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(["Section", "Event", "TrialID", "Timestamp"])

        # Initialize Section
        self.current_section = 1
        self.trial_in_progress = False  # Ensures we don't restart trials infinitely
        self.experiment_ended = False  #  Prevents duplicate logging of SectionStop

        # Write trial orders to CSV:
        # Try to get the ParticipantID from mvc_results.csv
        participant_id = "Unknown"
        mvc_data = self.load_last_participant_mvc()
        if mvc_data is not None:
            # Adjust the key below if your CSV uses a different header for ParticipantID
            participant_id = mvc_data.get("ParticipantID", "Unknown")

        # Create a filename with the timestamp and ParticipantID
        timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M")
        trial_filename = f"trial_orders_{timestamp_str}_{participant_id}.csv"

        # Write the trial orders to the new file
        with open(trial_filename, "w", newline="") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(["trial_list1"] + self.trial_array1)
            writer.writerow(["trial_list2"] + self.trial_array2)

        # --- Initialize Trial Management Variables ---
        self.current_trial_array = self.trial_array1  
        self.current_trial_index = 0
        self.current_trial_id = self.current_trial_array[self.current_trial_index]
        self.trial_label = QtWidgets.QLabel("")
        self.trial_label.setAlignment(QtCore.Qt.AlignCenter)
        self.trial_label.setStyleSheet("font-size: 48px; color: black;")
        self.trial_label.setText(self.current_trial_id)

        # --- Left Panel: Instructions + Static Force Guidance ---
        self.left_panel = QtWidgets.QVBoxLayout()
        self.top_left_panel = QtWidgets.QVBoxLayout()

        self.mvc_display_label = QtWidgets.QLabel("")
        self.mvc_display_label.setAlignment(QtCore.Qt.AlignCenter)
        self.mvc_display_label.setStyleSheet("font-size: 12px; color: black;")
        self.top_left_panel.addWidget(self.mvc_display_label)

        self.instruction_label = QtWidgets.QLabel("Press 'Start' \n to begin.")
        self.instruction_label.setAlignment(QtCore.Qt.AlignCenter)
        self.instruction_label.setStyleSheet("font-size: 36px; font-weight: bold; color: black;")
        # Use expanding size policy so it scales with the window
        self.instruction_label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.top_left_panel.addWidget(self.instruction_label)
        self.top_left_panel.addWidget(self.trial_label)

        self.button_layout = QtWidgets.QHBoxLayout()
        self.start_button = QtWidgets.QPushButton("Start")
        self.load_mvc_button = QtWidgets.QPushButton("Load MVC")
        self.start_button.clicked.connect(self.start_experiment)
        self.load_mvc_button.clicked.connect(self.load_last_mvc)
        self.button_layout.addWidget(self.start_button)
        self.button_layout.addWidget(self.load_mvc_button)
        self.top_left_panel.addLayout(self.button_layout)

        # Add the top part (instructions, labels, buttons) to left_panel
        self.left_panel.addLayout(self.top_left_panel)

        # Bottom Half: Static Force Guidance Plot (Left Panel)
        self.trapezoid_widget = pg.PlotWidget()
        self.trapezoid_widget.setYRange(-0.1, 1.1)
        self.trapezoid_widget.setXRange(0, 30)
        self.trapezoid_widget.setLabel('left', "Force (N)")
        self.trapezoid_widget.setLabel('bottom', "Time (s)")
        self.trapezoid_widget.setTitle("Force Guidance")
        self.trapezoid_widget.showGrid(x=False, y=False)
        self.trapezoid_widget.getAxis('bottom').setTickSpacing(major=5, minor=5)
        self.left_panel.addWidget(self.trapezoid_widget)

        # Wrap the left_panel in a QWidget container
        self.left_panel_widget = QtWidgets.QWidget()
        self.left_panel_widget.setLayout(self.left_panel)
        # Use an expanding size policy
        self.left_panel_widget.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)

        # --- Right Panel: Dynamic Force Measurement & Dynamic Trapezoid ---
        self.right_panel = QtWidgets.QVBoxLayout()
        self.graphWidget = pg.PlotWidget()
        self.graphWidget.setLabel('left', "Normalized Force (0-1)")
        self.graphWidget.setLabel('bottom', "Time (s)")
        self.graphWidget.setTitle("Grip Force Measurement")
        self.graphWidget.showGrid(x=False, y=False)
        self.graphWidget.getAxis('bottom').setTickSpacing(major=5, minor=5)
        self.graphWidget.setYRange(-0.1, 1.1)
        self.graphWidget.setXRange(0, 30)
        self.right_panel.addWidget(self.graphWidget)

        # Wrap the right_panel in a QWidget container
        self.right_panel_widget = QtWidgets.QWidget()
        self.right_panel_widget.setLayout(self.right_panel)
        self.right_panel_widget.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)

        # Now add both panels' container widgets to the main layout with stretch factors.
        self.main_layout.addWidget(self.left_panel_widget, 1)
        self.main_layout.addWidget(self.right_panel_widget, 3)


        # --- Left Panel Static Trapezoid (Force Guidance) ---
        # Set static trapezoid based on current trial's MVC level:
        mvc_normalized = int(self.current_trial_id[-2:]) / 100.0  # e.g., "pinchOne20" -> 20 -> 0.20
        self.trapezoid_x = [0, 10, 15, 25, 30]
        self.trapezoid_y = [0, 0, mvc_normalized, mvc_normalized, 0]
        self.trapezoid_curve = self.trapezoid_widget.plot(self.trapezoid_x, self.trapezoid_y,
                                                          pen=pg.mkPen('y', width=3))
        self.trapezoid_dot = self.trapezoid_widget.plot([0], [0], pen=None,
                                                        symbol='o', symbolSize=8,
                                                        symbolBrush='w', symbolPen='w')

        # --- Right Panel Dynamic Plots ---
        self.force_curve = self.graphWidget.plot([0], [0], pen='g')
        self.force_dot = self.graphWidget.plot([0], [0], pen=None,
                                               symbol='o', symbolSize=8,
                                               symbolBrush='w', symbolPen='w')
        self.trapezoid_main_curve = self.graphWidget.plot([], [], pen=pg.mkPen('y', width=3))
        self.trapezoid_main_dot = self.graphWidget.plot([0], [0], pen=None,
                                                        symbol='o', symbolSize=8,
                                                        symbolBrush='w', symbolPen='w')

        # --- LSL Streaming Setup (Unchanged) ---
        self.info = StreamInfo(STREAM_NAME, STREAM_TYPE, 4, SAMPLE_RATE, 'float32', 'force_stream_001')
        self.outlet = StreamOutlet(self.info)

        # --- Initialize Go Direct Sensor ---
        self.gdx = gdx.gdx()
        self.gdx.open(connection='usb', device_to_open='GDX-HD 155003H9')
        self.gdx.select_sensors([1, 2, 3, 4])
        self.gdx.start(20)

        # --- Data Buffers for Dynamic (Right) Plots ---
        self.max_samples = int(SAMPLE_RATE * 30)  # 30 seconds worth of data
        self.force_data = deque(maxlen=self.max_samples)
        self.time_data = deque(maxlen=self.max_samples)
        self.trapezoid_main_time_data = deque(maxlen=self.max_samples)
        self.trapezoid_main_force_data = deque(maxlen=self.max_samples)

        # --- Timer Setup ---
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update_plot)
        self.experiment_running = False
        self.time_elapsed = 0
        self.trial_start_time = 0  # to track individual trial durations

        # --- MVC for Normalization ---
        # Default values; these should be updated via load_last_mvc()
        self.full_grasp_mvc = 100  
        self.pinchOne_mvc = 100
        self.pinchTwo_mvc = 100

    def start_trial(self):

        self.phase_events_logged = set()

        """Start a new trial and log the TrialStart event."""
        if not self.experiment_running or self.trial_in_progress:
            return  # Prevent duplicate trial starts

        self.trial_in_progress = True  # Mark that a trial is now running

        # Ensure the trial ID is set properly and log TrialStart.
        self.current_trial_id = self.current_trial_array[self.current_trial_index]
        self.trial_label.setText(self.current_trial_id)
        self.trial_start_time = self.time_elapsed

        self.log_event(self.current_section, "TrialStart", self.current_trial_id)

        # Initialize the phase events tracker for this trial.
        self.phase_events_logged = set()

        # Update static trapezoid on the left
        mvc_normalized = int(self.current_trial_id[-2:]) / 100.0
        self.trapezoid_y = [0, 0, mvc_normalized, mvc_normalized, 0]
        self.trapezoid_curve.setData(self.trapezoid_x, self.trapezoid_y)

    def check_phase_boundaries(self, cycle_time):
        """
        Check if the current cycle_time has crossed any phase boundary that hasn't yet been logged.
        The boundaries (in seconds) and their corresponding events are defined in the list below.
        """
        # Define boundaries and events:
        phase_events = [
        (0, "RestPhaseStart"),
        (5, "RestPhaseStop"),    # At 5s, Rest ends…
        (5, "GetReadyStart"),    # …and Get Ready begins.
        (10, "GetReadyStop"),    # At 10s, Get Ready ends…
        (10, "RampUpPhaseStart"),# …and Ramp-Up begins.
        (15, "RampUpPhaseStop"), # At 15s, Ramp-Up ends…
        (15, "HoldPhaseStart"),  # …and Hold begins.
        (25, "HoldPhaseStop"),   # At 25s, Hold ends…
        (25, "RampDownPhaseStart"),  # …and Ramp-Down begins.
        (30, "RampDownPhaseStop")    # At 30s, Ramp-Down ends.
        ]
        
        for boundary, event in phase_events:
            if cycle_time >= boundary and event not in self.phase_events_logged:
                self.log_event(self.current_section, event, self.current_trial_id)
                self.phase_events_logged.add(event)
     

    def log_event(self, section, event, trial_id=""):
        """Log an event with an LSL-based timestamp to the CSV file."""
        timestamp = local_clock()  # Get precise LSL local time
        with open(self.csv_filename, "a", newline="") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow([section, event, trial_id, timestamp])

    def get_reference_force(self, t):
        """Return the reference force for time t (for the trapezoid),
           using the current trial's MVC level."""
        mvc_normalized = int(self.current_trial_id[-2:]) / 100.0
        if 0 <= t < 10:
            return 0
        elif 10 <= t < 15:
            return mvc_normalized * (t - 10) / 5
        elif 15 <= t < 25:
            return mvc_normalized
        elif 25 <= t < 30:
            return mvc_normalized * (1 - ((t - 25) / 5))
        return 0

    def load_last_mvc(self):
        """Load the last MVC data from CSV and update the display label.
           Also store the MVC values for each grip type."""
        mvc_data = self.load_last_participant_mvc()
        if mvc_data:
            try:
                self.full_grasp_mvc = float(mvc_data.get('Full Grasp (Grip)', '100'))
            except ValueError:
                self.full_grasp_mvc = 100
            try:
                self.pinchOne_mvc = float(mvc_data.get('Pinch (Index Finger)', '100'))
            except ValueError:
                self.pinchOne_mvc = 100
            try:
                self.pinchTwo_mvc = float(mvc_data.get('Pinch (Middle Finger)', '100'))
            except ValueError:
                self.pinchTwo_mvc = 100

            text = (
                f"Full Grasp: {self.full_grasp_mvc} N, \n"
                f"Index Pinch: {mvc_data.get('Pinch (Index Finger)', 'N/A')} N, \n"
                f"Middle Pinch: {mvc_data.get('Pinch (Middle Finger)', 'N/A')} N \n"
            )
            self.mvc_display_label.setText(text)
            mvc_percentages = self.calculate_mvc_percentages(mvc_data)
            self.save_mvc_percentages(mvc_percentages)
        else:
            self.mvc_display_label.setText("No MVC data found.")
            self.full_grasp_mvc = 100
            self.pinchOne_mvc = 100
            self.pinchTwo_mvc = 100

    def load_last_participant_mvc(self):
        """Reads the CSV file and returns the last participant's MVC data as a dictionary."""
        filename = "mvc_results.csv"
        if not os.path.exists(filename):
            return None
        last_row = None
        with open(filename, "r", newline="") as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                last_row = row
        return last_row

    def calculate_mvc_percentages(self, mvc_data):
        """Calculate 20%, 40%, 60%, and 80% of MVC for each motion."""
        percentages = [20, 40, 60, 80]
        motions = ['Full Grasp (Grip)', 'Pinch (Index Finger)', 'Pinch (Middle Finger)']
        mvc_percentages = {motion: {} for motion in motions}
        for motion in motions:
            if motion in mvc_data:
                mvc_value = float(mvc_data[motion])
                for percent in percentages:
                    mvc_percentages[motion][f"{percent}%"] = mvc_value * (percent / 100.0)
        return mvc_percentages

    def save_mvc_percentages(self, mvc_percentages):
        """Save the MVC percentages to a CSV and JSON file."""
        csv_filename = "mvc_percentages.csv"
        json_filename = "mvc_percentages.json"
        with open(csv_filename, "w", newline="") as csvfile:
            fieldnames = ['Motion', '20%', '40%', '60%', '80%']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for motion, percentages in mvc_percentages.items():
                row = {'Motion': motion}
                row.update(percentages)
                writer.writerow(row)
        with open(json_filename, "w") as jsonfile:
            import json
            json.dump(mvc_percentages, jsonfile, indent=4)

    def start_experiment(self):
        """Start the experiment, clear old dynamic data, and initialize trial timing."""
        self.log_event(self.current_section, "SectionStart")
        #self.start_trial()
        self.experiment_running = True
        self.start_time = time.time()
        self.trial_start_time = self.time_elapsed = 0
        self.force_data.clear()
        self.time_data.clear()
        self.trapezoid_main_time_data.clear()
        self.trapezoid_main_force_data.clear()
        # Reset x-axis ranges
        self.graphWidget.setXRange(0, 30)
        self.trapezoid_widget.setXRange(0, 30)
        self.timer.start(5)

    def stop_experiment(self):
        """Stop the experiment and finalize data logging."""
        if not self.experiment_running or self.experiment_ended:
            return  #  Prevent multiple logs of SectionStop

        self.log_event(self.current_section, "SectionStop")  #  Logs only once
        self.experiment_ended = True  #  Mark experiment as ended

        self.experiment_running = False
        self.timer.stop()
        self.instruction_label.setText("Experiment \n Stopped.")
        self.instruction_label.setStyleSheet("font-size: 36px; font-weight: bold; color: black;")
        self.gdx.stop()
        self.gdx.close()
        print("Experiment finished. Data saved to", self.csv_filename)


    def start_break(self):
        """Initiate a 5-minute break."""
        self.log_event(self.current_section, "SectionStop")
        self.log_event(self.current_section, "BreakStart")
        self.instruction_label.setText("Break time! Please rest for 5 minutes.")
        self.timer.stop()  # Stop the main update timer
        # Use a single-shot QTimer to trigger resetting after 5 minutes (5 * 60 * 1000 ms)
        QtCore.QTimer.singleShot(5 * 60 * 1000, self.prepare_next_array)

    def prepare_next_array(self):
        """Reset the experiment for the next trial array.
        Everything resets (dynamic data, timers, plots) except that the second trial array remains loaded.
        The user must press Start to resume the experiment."""
        self.log_event(self.current_section, "BreakStop")

        # Move to Section 2
        self.current_section = 2

        # Switch to the second trial array and reset trial variables
        self.current_trial_array = self.trial_array2
        self.current_trial_index = 0
        self.current_trial_id = self.current_trial_array[self.current_trial_index]
        self.trial_label.setText(self.current_trial_id)
        
        # Reset experiment timing so that time_elapsed and trial_start_time start at 0
        self.start_time = 0
        self.trial_start_time = 0
        self.time_elapsed = 0

        # Clear all dynamic data buffers (right panel)
        self.force_data.clear()
        self.time_data.clear()
        self.trapezoid_main_time_data.clear()
        self.trapezoid_main_force_data.clear()
        
        # Clear the dynamic plots on the right panel
        self.force_curve.setData([], [])
        self.force_dot.setData([], [])
        self.trapezoid_main_curve.setData([], [])
        self.trapezoid_main_dot.setData([], [])
        
        # Reset the static trapezoid on the left (set it to the rest state for the new trial)
        mvc_normalized = int(self.current_trial_id[-2:]) / 100.0  # e.g., for "FullGrasp40" -> 0.40
        self.trapezoid_y = [0, 0, mvc_normalized, mvc_normalized, 0]
        self.trapezoid_curve.setData(self.trapezoid_x, self.trapezoid_y)
        
        # Inform the user that the break is over and they must press Start to resume
        self.instruction_label.setText("Break is over. Press Start to resume the experiment.")
        # At this point, the main timer remains stopped until the user clicks Start.


    def update_plot(self):
        """Update dynamic force plot and dynamic trapezoid (right panel),
           update the moving dot on the static guidance plot (left panel),
           and handle trial transitions."""
        if not self.experiment_running:
            return

        self.time_elapsed = time.time() - self.start_time
        cycle_time = self.time_elapsed % 30

        self.check_phase_boundaries(cycle_time)

        # Read sensor measurements
        measurements = self.gdx.read()
        if measurements is None or len(measurements) != 4:
            return
        
        # LSL streaming
        timestamp = local_clock()
        self.outlet.push_sample(measurements, timestamp)

        # Select MAX_FORCE based on current trial's grip type
        if self.current_trial_id.startswith("FullGrasp"):
            MAX_FORCE = self.full_grasp_mvc
        elif self.current_trial_id.startswith("IndexPinch"):
            MAX_FORCE = self.pinchOne_mvc
        elif self.current_trial_id.startswith("MiddlePinch"):
            MAX_FORCE = self.pinchTwo_mvc
        else:
            MAX_FORCE = self.full_grasp_mvc

        MIN_FORCE = 0
        raw_force = measurements[0]
        new_force = (raw_force - MIN_FORCE) / (MAX_FORCE - MIN_FORCE)
        new_force = max(0, min(new_force, 1))
        ref_force = self.get_reference_force(cycle_time)

        # Append new data to dynamic buffers (right panel)
        self.force_data.append(new_force)
        self.time_data.append(self.time_elapsed)
        self.trapezoid_main_time_data.append(self.time_elapsed)
        self.trapezoid_main_force_data.append(ref_force)

        # In update_plot(), after reading sensor data, etc.
        current_trial_duration = self.time_elapsed - self.trial_start_time
        if current_trial_duration >= 30:
        # Log the final phase stop if needed.
            if hasattr(self, 'phase_events_logged') and self.phase_events_logged:
                # Optionally, log a stop for the last phase (or you can leave that to the next trial)
                pass
            self.log_event(self.current_section, "TrialEnd", self.current_trial_id)
            self.trial_in_progress = False
            self.current_trial_index += 1
            if self.current_trial_index >= len(self.current_trial_array):
                if self.current_trial_array is self.trial_array1:
                    self.start_break()
                else:
                    self.stop_experiment()
                return  # Exit update_plot() immediately.
            # else:
            #     # Move to next trial in the current array.
            #     self.current_trial_id = self.current_trial_array[self.current_trial_index]
            #     self.trial_label.setText(self.current_trial_id)
            #     self.trial_start_time = self.time_elapsed
            #     self.log_event(self.current_section, "TrialStart", self.current_trial_id)
            #     # Update static trapezoid on the left based on the new trial's MVC level.
            #     mvc_normalized = int(self.current_trial_id[-2:]) / 100.0
            #     self.trapezoid_y = [0, 0, mvc_normalized, mvc_normalized, 0]
            #     self.trapezoid_curve.setData(self.trapezoid_x, self.trapezoid_y)
          
            self.start_trial()

        self.update_phase_instruction(cycle_time)

        # Smooth scrolling for dynamic right plot
        window_size = 30
        shift_point = window_size / 2
        if self.time_elapsed > shift_point:
            self.graphWidget.setXRange(self.time_elapsed - shift_point, self.time_elapsed + shift_point)

        # Update dynamic force measurement plot (green curve)
        self.force_curve.setData(list(self.time_data), list(self.force_data))
        self.force_dot.setData([self.time_data[-1]], [self.force_data[-1]])
        # Update dynamic trapezoid (yellow curve)
        self.trapezoid_main_curve.setData(list(self.trapezoid_main_time_data), list(self.trapezoid_main_force_data))
        self.trapezoid_main_dot.setData([self.trapezoid_main_time_data[-1]], [self.trapezoid_main_force_data[-1]])
        # Update moving dot on static left guidance plot
        self.trapezoid_dot.setData([cycle_time], [ref_force])
  
    def update_phase_instruction(self, cycle_time):
        """Update the instruction label based on the current phase with a countdown."""
        if 0 <= cycle_time < 5:
            time_remaining = 10 - cycle_time
            self.instruction_label.setText(f"Rest Phase\n({int(time_remaining)}s)")
            self.instruction_label.setStyleSheet("color: green; font-size: 48px;")
        elif 5 <= cycle_time < 10:
            time_remaining = 10 - cycle_time
            blink = int(cycle_time * 3) % 2 == 0  # Toggle every 0.5 seconds
            if blink:
                self.instruction_label.setText(f"Get Ready!\n({int(time_remaining)}s)")
                self.instruction_label.setStyleSheet("color: red; font-size: 48px;")
            else:
                self.instruction_label.setText("")  # Clear the text to make it disappear

        elif 10 <= cycle_time < 15:
            time_remaining = 15 - cycle_time
            self.instruction_label.setText(f"Ramp-Up Phase\n({int(time_remaining)}s)")
            self.instruction_label.setStyleSheet("color: blue; font-size: 48px;")
        elif 15 <= cycle_time < 25:
            time_remaining = 25 - cycle_time
            self.instruction_label.setText(f"Hold Phase\n({int(time_remaining)}s)")
            self.instruction_label.setStyleSheet("color: orange; font-size: 48px;")
        elif 25 <= cycle_time < 30:
            time_remaining = 30 - cycle_time
            self.instruction_label.setText(f"Ramp-Down Phase\n({int(time_remaining)}s)")
            self.instruction_label.setStyleSheet("color: purple; font-size: 48px;")


    def closeEvent(self, event):
        """Handle the GUI close event."""
        self.stop_experiment()
        event.accept()

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    main = ForceExperimentTab()
    main.showMaximized()
    sys.exit(app.exec_())
