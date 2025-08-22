import time               # For sleeping between sensor reads
import threading          # To run sensor reads in a background thread
import queue              # For safely passing data from the sensor thread to the main thread
import numpy as np        # For numerical operations on the sensor data
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from gdx import gdx     # Import the GDX module for sensor data

# ============================================================
# SETUP AND INITIALIZATION
# ============================================================

# Create an instance of the GDX device.
gdx_device = gdx.gdx()

# -------------------------------
# Experiment & Visualization Parameters
# -------------------------------
time_between_readings = 0.05  # Time between sensor reads (50 milliseconds)
max_points = 200              # Number of data points to display on the plot

# -------------------------------
# Initialize the GDX Device
# -------------------------------
# Open the connection to the GDX device via USB.
gdx_device.open(connection='usb')
# Allow the user to select the sensors.
gdx_device.select_sensors()
# Get a list of sensor info strings (e.g., "Force (N)") for the enabled sensors.
sensor_headers = gdx_device.enabled_sensor_info()
num_sensors = len(sensor_headers)

# -------------------------------
# Prepare Data Arrays for Plotting
# -------------------------------
# Create a fixed x-axis: a time axis spanning max_points values.
x_data = np.linspace(-max_points * time_between_readings, 0, max_points)
# Create a 2D numpy array to hold sensor data (one row per sensor).
y_data = np.zeros((num_sensors, max_points))

# -------------------------------
# Set Up the Plot (Matplotlib Figure)
# -------------------------------
fig, ax = plt.subplots()   # Create a new figure and axes
# Define some colors to use for different sensor lines (cycling through if needed)
colors = ['r', 'b', 'k']
lines = []  # List to store the Line2D objects

# Create a line on the plot for each sensor.
for i in range(num_sensors):
    # Plot a line with the initial data (all zeros) for sensor i.
    line, = ax.plot(x_data, y_data[i],
                    color=colors[i % len(colors)],
                    label=sensor_headers[i])
    lines.append(line)

# Configure plot axes:
ax.set_xlim(x_data[0], x_data[-1])  # Fix the x-axis limits
ax.set_ylim(-1, 1)                  # Set the y-axis limits (assumed normalized)
ax.set_xlabel("Time (s)")           # Label for x-axis
ax.set_ylabel("Sensor Readings")    # Label for y-axis
ax.legend()                         # Display a legend for the sensor lines

# -------------------------------
# Start Data Collection on the GDX Device
# -------------------------------
# The start method expects the sampling interval in milliseconds.
gdx_device.start(int(time_between_readings * 1000))


# ============================================================
# BACKGROUND SENSOR READING SETUP
# ============================================================

# Create a thread-safe queue to hold sensor data readings.
data_queue = queue.Queue(maxsize=100)

# Create an Event object to signal the background thread to stop.
stop_event = threading.Event()

def sensor_reading_thread():
    """
    Continuously read sensor data from the GDX device and push the
    readings into the queue until signaled to stop.
    """
    while not stop_event.is_set():
        # Read the current sensor measurements.
        measurements = gdx_device.read()
        if measurements is not None:
            try:
                # Put the measurements into the queue without blocking.
                data_queue.put_nowait(measurements)
            except queue.Full:
                # If the queue is full, skip this measurement to avoid blocking.
                pass
        # Sleep a little to reduce CPU usage. Adjust the sleep duration if needed.
        time.sleep(time_between_readings / 2)

# Start the sensor reading thread as a daemon (it will close when the main program exits).
thread = threading.Thread(target=sensor_reading_thread, daemon=True)
thread.start()


# ============================================================
# REAL-TIME PLOTTING WITH MATPLOTLIB
# ============================================================

def init():
    """
    Initialization function for the animation.
    Resets the data in the plot lines to zeros.
    """
    for line in lines:
        # Set each line's data to zeros.
        line.set_ydata(np.zeros_like(x_data))
    return lines

def update(frame):
    """
    Update function called by the animation. This function:
      - Reads all available sensor measurements from the queue.
      - Shifts old data left, and appends new measurements.
      - Updates the plot lines with the latest data.
    """
    # Process all available data in the queue.
    while True:
        try:
            # Try to get a measurement without waiting.
            measurements = data_queue.get_nowait()
        except queue.Empty:
            # Exit the loop if no more data is available.
            break

        # For each sensor reading in the measurement:
        for i, value in enumerate(measurements):
            # Normalize the sensor value (e.g., dividing by 50 to scale it)
            normalized_value = np.clip(value / 50, -1, 1)
            # Shift the data left (discarding the oldest data point)
            y_data[i, :-1] = y_data[i, 1:]
            # Insert the new sensor value at the end of the array.
            y_data[i, -1] = normalized_value

    # Update the line objects with the new data.
    for i, line in enumerate(lines):
        line.set_ydata(y_data[i])
    return lines

# Set up the animation:
# FuncAnimation calls the update function at intervals specified (in ms).
ani = FuncAnimation(fig,         # Figure to update
                    update,      # Function to call to update the data
                    init_func=init,   # Function to initialize the plot (for blitting)
                    interval=time_between_readings * 1000,  # Update interval in ms
                    blit=True)   # Use blitting for improved performance

# Inform the user that real-time visualization has started.
print("Real-time visualization started. Close the graph window to stop.")

# Display the plot window. The animation runs until the window is closed.
plt.show()


# ============================================================
# CLEANUP AFTER THE WINDOW IS CLOSED
# ============================================================

# Signal the background sensor reading thread to stop.
stop_event.set()
# Wait until the sensor reading thread has fully stopped.
thread.join()
# Stop the sensor data collection on the GDX device.
gdx_device.stop()
# Close the connection to the GDX device.
gdx_device.close()
