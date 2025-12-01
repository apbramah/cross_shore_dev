import tkinter as tk
from tkinter import ttk
import socket
import time

UDP_IP = "192.168.60.87"  # Change this to your target IP
UDP_PORT = 8888

map_zoom = lambda value: (value + 0)
map_iris = lambda value: (value + 512) >> 4
map_focus = lambda value: (value + 512) >> 4
map_pitch = lambda value: int(value * 0.2)

def send_udp_message(values):
    # Pack values into a UDP message
    values[1] = map_pitch(values[1])
    values[3] = map_zoom(values[3])
    values[4] = map_focus(values[4])
    values[5] = map_iris(values[5])
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('', UDP_PORT))  # Bind to the specified source port
    sock.sendto(bytes([0xDE, 0xFD, (values[3] >> 8) & 0xFF, values[3] & 0xFF,
                       (values[4] >> 8) & 0xFF, values[4] & 0xFF,
                       (values[5] >> 8) & 0xFF, values[5] & 0xFF,
                       (values[0] >> 8) & 0xFF, values[0] & 0xFF,
                       (values[1] >> 8) & 0xFF, values[1] & 0xFF,
                       (values[2] >> 8) & 0xFF, values[2] & 0xFF,
                       0x00, 0x00]), (UDP_IP, UDP_PORT))
    sock.close()

def update_values():
    values = [int(slider.get()) for slider in sliders]
    send_udp_message(values)
    root.after(50, update_values)  # Schedule the next update after 50ms

def set_slider_values(values):
    for slider, value in zip(sliders, values):
        slider.set(value)

class ButtonWithLongPress(ttk.Button):
    def __init__(self, master=None, **kwargs):
        super().__init__(master, **kwargs)
        self.bind("<ButtonPress>", self.on_press)
        self.bind("<ButtonRelease>", self.on_release)
        self.long_press_duration = 1000  # Duration for long press in milliseconds
        self.press_time = None
        self.stored_values = [0] * 6  # Initialize with default slider values

    def on_press(self, event):
        self.press_time = time.time()
        self.after(self.long_press_duration, self.check_long_press)

    def on_release(self, event):
        if self.press_time:
            elapsed = time.time() - self.press_time
            if elapsed < self.long_press_duration / 1000:
                # Short press detected
                set_slider_values(self.stored_values)
            self.press_time = None

    def check_long_press(self):
        if self.press_time and (time.time() - self.press_time) >= self.long_press_duration / 1000:
            # Long press detected
            self.stored_values = [int(slider.get()) for slider in sliders]
            print(f"Stored values for button {self['text']}: {self.stored_values}")
            self.press_time = None

root = tk.Tk()
root.title("EX Head Controller Relative")

sliders = []

# Labels for sliders
slider_names = ["Yaw", "Pitch", "Roll", "Zoom", "Focus", "Iris"]

# Create and place sliders
for name in slider_names:
    frame = ttk.Frame(root)
    frame.pack(fill=tk.BOTH, expand=True)
    
    label = ttk.Label(frame, text=name)
    label.pack(side=tk.TOP, pady=5)
    
    slider = ttk.Scale(frame, from_=-512, to=512, orient=tk.HORIZONTAL, length=200)
    slider.set(0)
    value_var = tk.IntVar(value=0)  # Variable to hold the current value

    # Live value label
    value_label = ttk.Label(frame, textvariable=value_var)
    value_label.pack(side=tk.RIGHT, padx=5)

    # Entry box to type value
    entry = ttk.Entry(frame, width=5)
    entry.pack(side=tk.RIGHT, padx=5)
    entry.insert(0, "0")

    def on_slider_move(event, var=value_var, e=entry):
        val = int(float(event.widget.get()))
        var.set(val)
        e.delete(0, tk.END)
        e.insert(0, str(val))

    def on_entry_change(event, s=slider, var=value_var):
        try:
            val = int(event.widget.get())
            s.set(val)
            var.set(val)
        except ValueError:
         pass  # ignore non-integer input

    slider.config(command=lambda val, var=value_var, e=entry: on_slider_move(val, var, e))
    entry.bind("<Return>", on_entry_change)
    slider.pack(side=tk.TOP)
    sliders.append(slider)

buttons = []

# Create and place buttons
for i in range(4):
    button = ButtonWithLongPress(root, text=f"Position {i + 1}")
    button.pack(side=tk.LEFT, padx=5, pady=5)
    buttons.append(button)

# Sequencer function to press buttons with a 3s delay
sequencer_enabled = False

def press_buttons_sequentially(index=0):
    if sequencer_enabled:
        buttons[index].event_generate("<ButtonPress>")
        buttons[index].event_generate("<ButtonRelease>")
        next_index = (index + 1) % len(buttons)
        root.after(2000, press_buttons_sequentially, next_index)

def toggle_sequencer():
    global sequencer_enabled
    sequencer_enabled = not sequencer_enabled
    if sequencer_enabled:
        sequencer_button.config(text="Disable Sequencer")
        press_buttons_sequentially()
    else:
        sequencer_button.config(text="Enable Sequencer")

# Create the sequencer toggle button
sequencer_button = ttk.Button(root, text="Enable Sequencer", command=toggle_sequencer)
sequencer_button.pack(side=tk.BOTTOM, pady=10)

# Start the update loop
update_values()

root.mainloop()
