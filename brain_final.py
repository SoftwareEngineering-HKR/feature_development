"""
This file has been fully pair-programmed by Razmus and Marcus.
"""

############################## CONNECTIONS IMPORT ########################
import socket
from websocket import create_connection
import threading
import requests
import sys
import os
import json
import numpy as np
from brainflow.board_shim import BoardShim, BrainFlowInputParams, BoardIds
import time
import customtkinter as ctk
from keyboard import keyboard as user_keyboard
from PIL import Image
import pyautogui
import speech_recognition as sr
from dotenv import load_dotenv

load_dotenv()


def resource_path(relative_path):
    """ Get absolute path to resource """
    base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


############################## INITIALIZATION ###########################
class Client:
    def __init__(self, host, port):
        self.host = host
        self.port = port 
        self.access_token = None
        self.refresh_token = None
        self.mouse_x = 0
        self.mouse_y = 0
        self.mouse_locked = False
        self.state_listner = None
        self.recording = False
        self.postgress_connect_flag = False
        self.openbci_connect_flag = False
        self.board = None
        self.state = {}

########################### CONNECTIONS SERVER ##########################
    def connect_to_postgres(self):
        while True:
            while not self.postgress_connect_flag:
                try:
                    self.postgress_connect = create_connection(f"ws://{self.host}:{os.getenv('PORT2')}/?token={self.access_token}")
                    print(f"Connected to PostgreSQL WebSocket at {self.host}:{os.getenv('PORT2')}/")
                    self.postgress_connect_flag = True
                    self.fetch_device_states()
                except Exception as e:
                    print(f"PostgreSQL WebSocket connection failed: {e}")
                    if not self.refresh_tokens():
                        print("Retrying...")
                time.sleep(2)
            time.sleep(5)

    def fetch_device_states(self):
        while True:
            try:
                message = self.postgress_connect.recv()
                print(f"Received PostgreSQL message: {message}")

                message = json.loads(message)
                if (message.get("type") == "inital devices"):
                    devices = message["payload"]["devices"]
                    print("Initial devices received:", devices)
                    added_types = set()
                    for device in devices:
                        room = device["room"]
                        if (not room):
                            continue
                        if (room.lower() == "bedroom"):
                            dtype = device["type"]
                            if dtype in {"light", "window", "door", "fan", "buzz", "temperature", "humidity", "display"} and dtype not in added_types:
                                self.state[device["id"]] = device
                                #assign value 0 if None or not a valid int
                                raw_value = self.state[device["id"]]["value"]
                                try:
                                    value = float(raw_value) if raw_value is not None else 0
                                except (ValueError, TypeError):
                                    value = 0
                                self.state[device["id"]]["value"] = value
                                added_types.add(dtype)
                    print(f"Initial state updated: {self.state}")
                elif (message.get("type") == "update value"):
                    device_id = message["payload"]["deviceID"]
                    new_value = message["payload"]["content"]
                    print(f"The new value is {new_value}")
                    if device_id in self.state:
                        if (self.state[device_id]["type"] == "display"):
                            self.state[device_id]["value"] = new_value if new_value is not None else 0
                        else:
                            self.state[device_id]["value"] = float(new_value)
                            print(f"Updated {device_id} to {new_value}")
                            print(f"Current state after updating: {self.state}")
                elif (message.get("type") == "added new device"):
                    device = message["payload"]["content"]
                    device_id = device["id"]
                    self.state[device_id] = device
                    if (device["room"] == "bedroom" and device["type"] in {"light", "window", "door", "fan", "buzz", "temperature", "humidity", "display"} and device["type"] not in {d["type"] for d in self.state.values()}):
                        self.state[device["id"]] = device
                        print(f"New device added: {self.state}")
                elif (message.get("type") == "removed device from user"):
                    device_id = message["payload"]["deviceID"]
                    if device_id in self.state:
                        del self.state[device_id]
                        print(f"Device removed: {device_id}")
                self.postgress_connect_flag = True
            except Exception as e:
                print(f"Error receiving PostgreSQL message: {e}")
                self.postgress_connect_flag = False
                return

################################ OPENBCI ###############################

    def Openbci(self):
        params = BrainFlowInputParams()
        params.serial_port = "COM3"

        while True:
            try:
                self.board = BoardShim(BoardIds.CYTON_BOARD.value, params)
                self.board.prepare_session()
                self.board.start_stream()
                print("BrainFlow streaming started")

                # Start logic threads
                threading.Thread(target=self.handle_jaw, daemon=True).start()
                threading.Thread(target=self.mouse, daemon=True).start()
                threading.Thread(target=self.handle_lock, daemon=True).start()
                self.openbci_connect_flag = True

                empty_count = 0
                last_timestamp = None
                timestamp_channel = BoardShim.get_timestamp_channel(BoardIds.CYTON_BOARD.value)
                while True:
                    data = self.board.get_current_board_data(32)
                    #print(f"Data shape: {data.shape}")
                    if data.shape[1] == 0:
                        empty_count += 1
                        #print(f"No data from board ({empty_count})")
                    else:
                        timestamps = data[timestamp_channel]
                        if last_timestamp is not None and np.all(timestamps <= last_timestamp):
                            empty_count += 1
                            #print(f"Stale data from board ({empty_count})")
                        else:
                            empty_count = 0
                        if len(timestamps) > 0:
                            last_timestamp = timestamps[-1]
                    if empty_count > 5:  # e.g. 5 cycles of no/stale data
                        self.openbci_connect_flag = False
                        raise RuntimeError("Lost connection to Cyton board (no new data)")
                    time.sleep(3)

            except Exception as e:
                #print(f"BrainFlow error: {e}")
                #print("Retrying connection to Cyton board in 5 seconds...")
                try:
                    if self.board is not None:
                        self.board.release_session()
                except Exception:
                    pass
                time.sleep(5)  # Wait before retrying

############################## MOUSE CONTROL #############################
    def mouse(self):
        accel_channels = BoardShim.get_accel_channels(BoardIds.CYTON_BOARD.value)

        try:
            while True:
                data = self.board.get_current_board_data(64)

                if data.shape[1] == 0:
                    continue

                accel = data[accel_channels, :]

                avg_x = np.mean(accel[0])
                avg_y = np.mean(accel[1])

                THRESHOLD = 0.25
                SENSITIVITY = 25

                move_x = 0
                move_y = 0

                if abs(avg_x) > THRESHOLD:
                    move_x = int((avg_x - np.sign(avg_x) * THRESHOLD) * SENSITIVITY)

                if abs(avg_y) > THRESHOLD:
                    move_y = int((avg_y - np.sign(avg_y) * THRESHOLD) * SENSITIVITY)

                if move_x != 0 or move_y != 0:
                    pyautogui.moveRel(move_x, move_y, _pause=False)

                time.sleep(0.005)

        except KeyboardInterrupt:
            print("Stopping mouse control...")

    def handle_jaw(self):

        eeg_channels = BoardShim.get_eeg_channels(BoardIds.CYTON_BOARD.value)

        bite_cooldown = False
        last_bite_time = 0
        cooldown_time = 0.5

        try:
            while True:

                data = self.board.get_current_board_data(32)

                if data.shape[1] == 0:
                    continue

                eeg = data[eeg_channels, :]
                Kake = eeg[2]

                current_time = time.time()
                kake_std = np.std(Kake)
                #Change this depending on how sensitive the signal is, you can print kake_std to see typical values when biting vs not biting. You want to set it high enough to avoid false positives but low enough to reliably detect bites.
                if kake_std > 30 and not bite_cooldown and not self.mouse_locked:
                    print(f"Bite detected! std={kake_std:.1f}")
                    pyautogui.click()
                    bite_cooldown = True
                    last_bite_time = current_time

                if bite_cooldown and (current_time - last_bite_time) > cooldown_time:
                    bite_cooldown = False

                time.sleep(0.01)

        except KeyboardInterrupt:
            print("Stopping...")

    def handle_lock(self):

        eeg_channels = BoardShim.get_eeg_channels(BoardIds.CYTON_BOARD.value)

        hold_start_time = None
        holding = False

        try:
            while True:

                data = self.board.get_current_board_data(32)

                if data.shape[1] == 0:
                    continue

                eeg = data[eeg_channels, :]
                Kake = eeg[2]

                current_time = time.time()
                kake_std = np.std(Kake)

                if kake_std > 20:
                    if hold_start_time is None:
                        hold_start_time = current_time
                    elif not holding and (current_time - hold_start_time) > 1.5:
                        self.mouse_locked = not self.mouse_locked
                        holding = True

                        if self.state_listner:
                            print(f"{'Mouse Disabled' if self.mouse_locked else 'Mouse Enabled'}")
                            self.state_listner.configure(
                                text="Mouse Disabled" if self.mouse_locked else "Mouse Enabled"
                            )
                            r.update_idletasks()

                    elif not holding:
                        elapsed = current_time - hold_start_time
                        if self.state_listner and elapsed > 0.5:
                            self.state_listner.configure(text=f"{elapsed:.1f}s / 1.5s")

                else:
                    hold_start_time = None
                    holding = False

                time.sleep(0.05)

        except KeyboardInterrupt:
            print("Stopping...")

################################## TALK ###############################

    def handle_talk_button(self, talk_button, keybd = None, window_button = None, door_button = None, light_button = None, fan_button = None, buzzer_button = None, backend_connected = None):
        if self.recording:
            return

        self.state_listner.configure(text="Listening...", text_color="green")
        self.recording = True
        window_button.configure(state="disabled")
        door_button.configure(state="disabled")
        light_button.configure(state="disabled")
        fan_button.configure(state="disabled")
        buzzer_button.configure(state="disabled")
        r.update_idletasks()

        # Start recording in separate thread
        threading.Thread(target=self.google_speech_recognition, args=(keybd, talk_button, window_button, door_button, light_button, fan_button, buzzer_button, backend_connected)).start()

    def google_speech_recognition(self, keybd = None, talk_button = None, window_button = None, door_button = None, light_button = None, fan_button = None, buzzer_button = None, backend_connected = None):
        try:
            rec = sr.Recognizer()
            rec.pause_threshold = 1.0
            rec.energy_threshold = 400

            with sr.Microphone(sample_rate=16000) as source:
                print("Listening... (speak now)")
                rec.adjust_for_ambient_noise(source, duration=0.5)
                audio_data = rec.listen(source)
                print("Processing...")

            text = rec.recognize_google(audio_data, language="en")
            text = self.pross_google_speech_recognition(text, keybd, backend_connected)

            print(f"Google Speech Recognition: {text}")
            window_in_state = any(device["type"] == "window" for device in self.state.values())
            door_in_state = any(device["type"] == "door" for device in self.state.values())
            fan_in_state = any(device["type"] == "fan" for device in self.state.values())
            buzzer_in_state = any(device["type"] == "buzz" for device in self.state.values())
            light_in_state = any(device["type"] == "light" for device in self.state.values())
            if (window_in_state):
                window_button.configure(state="normal")
            if (door_in_state):
                door_button.configure(state="normal")
            if (light_in_state):
                light_button.configure(state="normal")
            if (fan_in_state):
                fan_button.configure(state="normal")
            if (buzzer_in_state):
                buzzer_button.configure(state="normal")

        except sr.UnknownValueError:
            print("Google Speech Recognition could not understand audio")
            if backend_connected:
                self.state_listner.configure(text=f"Couldn't understand audio", text_color="red")
                
        except sr.RequestError as e:
            print(f"Could not request results from Google Speech Recognition service; {e}")
        finally:
            self.state_listner.configure(text=f"Mouse Enabled", text_color="black")
            self.recording = False
            r.update_idletasks()

    def pross_google_speech_recognition(self, text, keybd, backend_connected):
        text = text.lower()
        text = text.replace(".", "")
        ## LIGHT ##
        if ("light" in text and "on" in text):
            for device_id, device in self.state.items():
                if device["type"] == "light":
                    user.postgress_connect.send(json.dumps({"type": "update value", "payload": {"id": device_id, "value": 1}}))
                    break
        elif ("light" in text and "off" in text):
            for device_id, device in self.state.items():
                if device["type"] == "light":
                    user.postgress_connect.send(json.dumps({"type": "update value", "payload": {"id": device_id, "value": 0}}))
                    break
        elif ("door" in text and "open" in text):
            for device_id, device in self.state.items():
                if device["type"] == "door":
                    user.postgress_connect.send(json.dumps({"type": "update value", "payload": {"id": device_id, "value": 1}}))
                    break
        elif ("door" in text and "close" in text):
            for device_id, device in self.state.items():
                if device["type"] == "door":
                    user.postgress_connect.send(json.dumps({"type": "update value", "payload": {"id": device_id, "value": 0}}))
                    break
        elif ("window" in text and "open" in text):
            for device_id, device in self.state.items():
                if device["type"] == "window":
                    user.postgress_connect.send(json.dumps({"type": "update value", "payload": {"id": device_id, "value": 1}}))
                    break
        elif ("window" in text and "close" in text):
            for device_id, device in self.state.items():
                if device["type"] == "window":
                    user.postgress_connect.send(json.dumps({"type": "update value", "payload": {"id": device_id, "value": 0}}))
                    break
        elif ("fan" in text and "on" in text):
            for device_id, device in self.state.items():
                if device["type"] == "fan":
                    user.postgress_connect.send(json.dumps({"type": "update value", "payload": {"id": device_id, "value": 1}}))
                    break
        elif ("fan" in text and "off" in text):
            for device_id, device in self.state.items():
                if device["type"] == "fan":
                    user.postgress_connect.send(json.dumps({"type": "update value", "payload": {"id": device_id, "value": 0}}))
                    break
        elif ("buzzer" in text):
            for device_id, device in self.state.items():
                if device["type"] == "buzz":
                    user.postgress_connect.send(json.dumps({"type": "update value", "payload": {"id": device_id, "value": 1}}))
                    break
        elif "keyboard" in text or "keyboard." in text:
            r.after(100, lambda: user_keyboard(master=r, widget=keybd, postgress_connect=self.postgress_connect, layout="qwerty"))

        else:
            backend_connected.configure(text="Could Not Fetch Data", text_color="red")
            
        return text

####################### GUI LOGIN AND CREATE USER ######################

    def login(self):
        r.deiconify()
        r.title("Login")
        #r.attributes("-fullscreen", True)

        # Get screen size for responsive design
        r.update_idletasks()
        screen_width = r.winfo_screenwidth()
        screen_height = r.winfo_screenheight()

        # Calculate sizes based on screen
        entry_width = min(int(screen_width * 0.3), 800)
        entry_height = int(screen_height * 0.06)
        button_height = int(screen_height * 0.08)

        # Calculate font sizes based on screen height
        title_font_size = int(screen_height * 0.05)
        label_font_size = int(screen_height * 0.025)
        entry_font_size = int(screen_height * 0.022)
        button_font_size = int(screen_height * 0.028)
        small_font_size = int(screen_height * 0.015)

        # Create login frame
        login_frame = ctk.CTkFrame(r, fg_color="transparent")
        login_frame.place(relx=0, rely=0, relwidth=1, relheight=1)

        # Configure grid for centering
        login_frame.grid_rowconfigure(0, weight=1)
        login_frame.grid_rowconfigure(1, weight=0)
        login_frame.grid_rowconfigure(2, weight=0)
        login_frame.grid_rowconfigure(3, weight=0)
        login_frame.grid_rowconfigure(4, weight=0)
        login_frame.grid_rowconfigure(5, weight=0)
        login_frame.grid_rowconfigure(6, weight=0)
        login_frame.grid_rowconfigure(7, weight=0)
        login_frame.grid_rowconfigure(8, weight=0)
        login_frame.grid_rowconfigure(9, weight=0)
        login_frame.grid_rowconfigure(10, weight=1)
        login_frame.grid_columnconfigure(0, weight=1)
        login_frame.grid_columnconfigure(1, weight=0)
        login_frame.grid_columnconfigure(2, weight=1)

        ## TITLE ##
        title_label = ctk.CTkLabel(login_frame, text="Welcome", font=("sans-serif", title_font_size, "bold"))
        title_label.grid(row=1, column=1, pady=int(screen_height*0.04))

        ## ERROR MESSAGE ##
        error_label = ctk.CTkLabel(login_frame, text="", font=("sans-serif", label_font_size, "bold"), text_color="red")
        error_label.grid(row=2, column=1, pady=int(screen_height*0.01))

        ############## USERNAME ############
        username_label = ctk.CTkLabel(login_frame, text="Username:", font=("sans-serif", label_font_size, "bold"))
        username_label.grid(row=3, column=1, pady=int(screen_height*0.015), sticky="w")
        username_entry = ctk.CTkEntry(login_frame, width=entry_width, height=entry_height, 
                                       font=("sans-serif", entry_font_size, "bold"), corner_radius=corner_radius_entry, text_color="black")
        username_entry.grid(row=4, column=1, pady=int(screen_height*0.01))
        # USERNAME fEEDBACK #
        username_feedback_label = ctk.CTkLabel(login_frame, text="", font=("sans-serif", small_font_size, "bold"), text_color="gray")
        username_feedback_label.grid(row=5, column=1, pady=int(screen_height*0.005), sticky="w")

        def update_username_feedback():
            username = username_entry.get()
            if username:
                errors = self.validate_username(username)
                if errors:
                    username_feedback_label.configure(text="✗ Invalid Username", text_color="red")
                else:
                    username_feedback_label.configure(text="✓ Valid Username", text_color="green")
            else:
                username_feedback_label.configure(text="")

        username_entry.bind("<KeyRelease>", lambda e: update_username_feedback())


        ########## PASSWORD ###########
        password_label = ctk.CTkLabel(login_frame, text="Password:", font=("sans-serif", label_font_size, "bold"))
        password_label.grid(row=6, column=1, pady=int(screen_height*0.015), sticky="w")

        password_frame = ctk.CTkFrame(login_frame, fg_color="transparent")
        password_frame.grid(row=7, column=1, pady=int(screen_height*0.01), sticky="ew")
        password_frame.grid_columnconfigure(0, weight=1)
        password_frame.grid_columnconfigure(1, weight=1)
        
        password_entry = ctk.CTkEntry(password_frame, show="*", width=entry_width - 100, height=entry_height, 
                                       font=("sans-serif", entry_font_size, "bold"), corner_radius=corner_radius_entry, text_color="black")
        password_entry.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        # PASSWORD FEEDBACK #
        password_feedback_label = ctk.CTkLabel(login_frame, text="", font=("sans-serif", small_font_size, "bold"), text_color="gray")
        password_feedback_label.grid(row=8, column=1, pady=int(screen_height*0.005), sticky="w")
                
        def update_password_feedback():
            password = password_entry.get()
            if password:
                password_error = self.validate_password(password)
                if password_error:
                    password_feedback_label.configure(text="✗ Invalid Password", text_color="red")
                else:
                    password_feedback_label.configure(text="✓ Valid Password", text_color="green")
            else:
                password_feedback_label.configure(text="")

        def toggle_password_visibility():
            if password_entry.cget("show") == "*":
                password_entry.configure(show="")
                toggle_button.configure(text="Hide")
            else:
                password_entry.configure(show="*")
                toggle_button.configure(text="Show")
        
        toggle_button = ctk.CTkButton(password_frame, text="Show", text_color="white", width=100, height=entry_height,
                                      font=("sans-serif", int(entry_font_size), "bold"), 
                                      corner_radius=corner_radius_button, command=toggle_password_visibility,
                                      fg_color="blue", hover_color="#005C00")
        toggle_button.grid(row=0, column=1)

        password_entry.bind("<KeyRelease>", lambda e: update_password_feedback())

        def attempt_login():
            username = username_entry.get()
            password = password_entry.get()
            
            # Validate username
            if not username or len(username) < 3:
                username_feedback_label.configure(text="Username must be at least 3 characters", text_color="red")
                return False
            
            # Validate password
            if not password or len(password) < 8 :
                password_feedback_label.configure(text="Password cannot be empty or less than 8 characters", text_color="red")
                return False

            #Send to database and verify
            try:
                response = requests.post(f"http://{self.host}:{self.port}/login", 
                            json={"username": username,
                                  "password": password}
                            )
                print(f"response in attempt_login is {response}")
                if response.status_code == 200:
                    data = response.json()
                    self.access_token = data["accessToken"]
                    if "jwt" in response.cookies:
                        self.refresh_token = response.cookies["jwt"]
                    print("Login successful")
                    login_frame.after(1000, lambda: [login_frame.destroy(), self.start_gui()])
                    error_label.configure(text="✓ Login Successful!", text_color="green")

                    threading.Thread(target=user.connect_to_postgres, daemon=True).start()
                    threading.Thread(target = user.Openbci, daemon=True).start()

                    return
                else:
                    print(f"Login failed")
                    error_label.configure(text="✗ Invalid Username or Password", text_color="red")
                    return
            except Exception as e:
                print(f"Error during login request: {e}")
                error_label.configure(text="Error connecting to server", text_color="red")
                return

        #### BUTTONS ####
        login_button = ctk.CTkButton(login_frame, text_color="white", text="Sign In", command=attempt_login, 
                                      width=entry_width, height=button_height, 
                                      font=("sans-serif", button_font_size, "bold"), 
                                      corner_radius=corner_radius_button, fg_color="blue", hover_color="#005C00")
        login_button.grid(row=9, column=1, pady=int(screen_height*0.025))
        
        create_button = ctk.CTkButton(login_frame, text_color="white", text="Create Account",
                                       command=lambda: [login_frame.destroy(), self.create_user()], 
                                       width=entry_width, height=button_height, 
                                       font=("sans-serif", button_font_size, "bold"), 
                                       corner_radius=corner_radius_button, fg_color="blue", hover_color="#005C00")
        create_button.grid(row=10, column=1, pady=int(screen_height*0.01), sticky="n")

    def validate_password(self, password):
        errors = []
        
        if len(password) < 8:
            errors.append("✗ At least 8 characters")
        
        if not any(c.isupper() for c in password):
            errors.append("✗ At least one uppercase letter (A-Z)")

        if not any(c.islower() for c in password):
            errors.append("✗ At least one lowercase letter (a-z)")

        if not any(c.isdigit() for c in password):
            errors.append("✗ At least one digit (0-9)")

        special_chars = "!@#$%^&*"
        if not any(c in special_chars for c in password):
            errors.append(f"✗ At least one special character ({special_chars})")

        return errors

    def validate_username(self, username):
        errors = []

        if len(username) < 3:
            errors.append("✗ At least 3 characters")

        if not all(c.isalnum() or c == "_" for c in username):
            errors.append("✗ Only letters, numbers and underscore (_)")

        return errors

    def create_user(self):
        r.title("Create User")
        
        r.update_idletasks()
        screen_width = r.winfo_screenwidth()
        screen_height = r.winfo_screenheight()
        
        # Calculate sizes based on screen
        entry_width = min(int(screen_width * 0.3), 800)
        entry_height = int(screen_height * 0.06)
        button_height = int(screen_height * 0.08)
        
        # Calculate font sizes
        title_font_size = int(screen_height * 0.05)
        label_font_size = int(screen_height * 0.025)
        entry_font_size = int(screen_height * 0.022)
        button_font_size = int(screen_height * 0.028)
        small_font_size = int(screen_height * 0.015)
        
        # Create register frame
        register_frame = ctk.CTkFrame(r, fg_color="transparent")
        register_frame.place(relx=0, rely=0, relwidth=1, relheight=1)
        
        # Configure grid for centering
        register_frame.grid_rowconfigure(0, weight=1)
        register_frame.grid_rowconfigure(1, weight=0)
        register_frame.grid_rowconfigure(2, weight=0)
        register_frame.grid_rowconfigure(3, weight=0)
        register_frame.grid_rowconfigure(4, weight=0)
        register_frame.grid_rowconfigure(5, weight=0)
        register_frame.grid_rowconfigure(6, weight=0)
        register_frame.grid_rowconfigure(7, weight=0)
        register_frame.grid_rowconfigure(8, weight=0)
        register_frame.grid_rowconfigure(9, weight=0)
        register_frame.grid_rowconfigure(10, weight=0)
        register_frame.grid_rowconfigure(11, weight=0)
        register_frame.grid_rowconfigure(12, weight=0)
        register_frame.grid_rowconfigure(13, weight=0)
        register_frame.grid_rowconfigure(14, weight=0)
        register_frame.grid_rowconfigure(15, weight=0)
        register_frame.grid_rowconfigure(16, weight=1)
        register_frame.grid_columnconfigure(0, weight=1)
        register_frame.grid_columnconfigure(1, weight=0)
        register_frame.grid_columnconfigure(2, weight=1)

        # Title
        title_label = ctk.CTkLabel(register_frame, text="Create Account", font=("sans-serif", title_font_size, "bold"))
        title_label.grid(row=1, column=1, pady=int(screen_height*0.035))

        # Error message label
        error_label = ctk.CTkLabel(register_frame, text="", font=("sans-serif", label_font_size), text_color="red")
        error_label.grid(row=2, column=1, pady=int(screen_height*0.01))

        # Username
        username_label = ctk.CTkLabel(register_frame, text="Username:", font=("sans-serif", label_font_size, "bold"))
        username_label.grid(row=3, column=1, pady=int(screen_height*0.012), sticky="w")
        username_entry = ctk.CTkEntry(register_frame, width=entry_width, height=entry_height, 
                                       font=("sans-serif", entry_font_size), corner_radius=corner_radius_entry, text_color="black")
        username_entry.grid(row=4, column=1, pady=int(screen_height*0.008))

        # Password
        password_label = ctk.CTkLabel(register_frame, text="Password:", font=("sans-serif", label_font_size, "bold"))
        password_label.grid(row=6, column=1, pady=int(screen_height*0.012), sticky="w")
        
        password_frame = ctk.CTkFrame(register_frame, fg_color="transparent")
        password_frame.grid(row=7, column=1, pady=int(screen_height*0.008), sticky="ew")
        password_frame.grid_columnconfigure(0, weight=1)
        password_frame.grid_columnconfigure(1, weight=0)

        password_entry = ctk.CTkEntry(password_frame, show="*", width=entry_width - 60, height=entry_height, 
                                       font=("sans-serif", entry_font_size, "bold"), corner_radius=corner_radius_entry)
        password_entry.grid(row=0, column=0, sticky="ew", padx=(0, 5))

        def toggle_password_visibility():
            if password_entry.cget("show") == "*":
                password_entry.configure(show="")
                toggle_password_button.configure(text="Hide")
            else:
                password_entry.configure(show="*")
                toggle_password_button.configure(text="Show")

        toggle_password_button = ctk.CTkButton(password_frame, text="Show", width=70, height=entry_height,font=("sans-serif", int(entry_font_size * 0.7), "bold"),
        corner_radius=corner_radius_button, command=toggle_password_visibility,
        fg_color="blue", hover_color="#005C00")
        toggle_password_button.grid(row=0, column=1)

        username_requirements_label = ctk.CTkLabel(register_frame, text="", font=("sans-serif", small_font_size, "bold"), text_color="black", justify="left")
        username_requirements_label.grid(row=5, column=1, pady=int(screen_height*0.005), sticky="w")

        # Password requirements label
        requirements_label = ctk.CTkLabel(register_frame, text="", font=("sans-serif", small_font_size, "bold"), text_color="black", justify="left")
        requirements_label.grid(row=8, column=1, pady=int(screen_height*0.005), sticky="w")

        # Confirm Password
        confirm_label = ctk.CTkLabel(register_frame, text="Confirm Password:", font=("sans-serif", label_font_size, "bold"))
        confirm_label.grid(row=9, column=1, pady=int(screen_height*0.012), sticky="w")

        confirm_password_frame = ctk.CTkFrame(register_frame, fg_color="transparent")
        confirm_password_frame.grid(row=10, column=1, pady=int(screen_height*0.008), sticky="ew")
        confirm_password_frame.grid_columnconfigure(0, weight=1)
        confirm_password_frame.grid_columnconfigure(1, weight=0)

        confirm_password_entry = ctk.CTkEntry(confirm_password_frame, show="*", width=entry_width - 60, height=entry_height,
        font=("sans-serif", entry_font_size, "bold"), corner_radius=corner_radius_entry)
        confirm_password_entry.grid(row=0, column=0, sticky="ew", padx=(0, 5))

        def toggle_confirm_password_visibility():
            if confirm_password_entry.cget("show") == "*":
                confirm_password_entry.configure(show="")
                toggle_confirm_button.configure(text="Hide")
            else:
                confirm_password_entry.configure(show="*")
                toggle_confirm_button.configure(text="Show")
        
        toggle_confirm_button = ctk.CTkButton(confirm_password_frame, text="Show", width=70, height=entry_height, font=("sans-serif", int(entry_font_size * 0.7), "bold"), 
        corner_radius=corner_radius_button, command=toggle_confirm_password_visibility,
        fg_color="blue", hover_color="#005C00")
        toggle_confirm_button.grid(row=0, column=1)

        # Confirm password feedback
        confirm_feedback_label = ctk.CTkLabel(register_frame, text="", font=("sans-serif", small_font_size, "bold"), text_color="gray")
        confirm_feedback_label.grid(row=11, column=1, pady=int(screen_height*0.005), sticky="w")

        def update_username_feedback():
            username = username_entry.get()
            if username:
                errors = self.validate_username(username)
                feedback_text = "\n".join(errors)
                username_requirements_label.configure(text=feedback_text)
            else:
                username_requirements_label.configure(text="")

        def update_password_feedback():
            password = password_entry.get()
            if password:
                errors = self.validate_password(password)
                feedback_text = "\n".join(errors)
                requirements_label.configure(text=feedback_text)
            else:
                requirements_label.configure(text="")

        def update_confirm_feedback():
            password = password_entry.get()
            confirm_password = confirm_password_entry.get()
            
            if confirm_password:
                if password == confirm_password:
                    confirm_feedback_label.configure(text="✓ Passwords match", text_color="green")
                else:
                    confirm_feedback_label.configure(text="✗ Passwords do not match", text_color="red")
            else:
                confirm_feedback_label.configure(text="")

        # Bind events for real-time updates
        password_entry.bind("<KeyRelease>", lambda e: update_password_feedback())
        confirm_password_entry.bind("<KeyRelease>", lambda e: update_confirm_feedback())
        
        username_entry.bind("<KeyRelease>", lambda e: update_username_feedback())

        def attempt_register():
            username = username_entry.get()
            password = password_entry.get()
            confirm_password = confirm_password_entry.get()

            # Validate username
            username_errors = self.validate_username(username)
            if any("✗" in err for err in username_errors):
                error_message = "Username requirements:\n" + "\n".join(username_errors)
                error_label.configure(text=error_message, text_color="red")
                return

            # Validate password
            password_errors = self.validate_password(password)
            if any("✗" in err for err in password_errors):
                error_message = "Password requirements:\n" + "\n".join(password_errors)
                error_label.configure(text=error_message, text_color="red")
                return

            # Validate passwords match
            if password != confirm_password:
                error_label.configure(text="Passwords do not match!", text_color="red")
                return

            try:
                response = requests.post(f"http://{self.host}:{self.port}/signup", 
                            json={"username": username,
                                  "password": password
                                  }
                            )
                print(f"the response is {response}")
                if response.status_code == 200:
                    data = response.json()
                    self.access_token = data["accessToken"]
                    if "jwt" in response.cookies:
                        self.refresh_token = response.cookies["jwt"]
                        error_label.configure(text="User created! Returning to login...", text_color="green")
                        register_frame.after(1500, lambda: [register_frame.destroy(), self.login()])
                    print("User created successfully")
                    
                elif response.status_code == 400:
                    print("User already exists")
                    error_label.configure(text="User already exists", text_color="red")
                    return
                else:
                    print(f"Registration failed: {response.text}")
                    error_label.configure(text="Registration failed", text_color="red")
                    return
            except Exception as e:
                print(f"Error during registration request: {e}")
                error_label.configure(text="Error connecting to server", text_color="red")
                return

        # Buttons
        register_button = ctk.CTkButton(register_frame, text="Register", command=attempt_register,
                                         width=entry_width, height=button_height, 
                                         font=("sans-serif", button_font_size, "bold"),
                                         corner_radius=corner_radius_button, fg_color="blue", hover_color="#005C00")
        register_button.grid(row=12, column=1, pady=int(screen_height*0.02))
        
        def go_back_to_login():
            register_frame.destroy()
            self.login()
        
        back_button = ctk.CTkButton(register_frame, text="Back to Login", 
                                     command=go_back_to_login,
                                     width=entry_width, height=button_height, 
                                     font=("sans-serif", button_font_size, "bold"),
                                     corner_radius=corner_radius_button, fg_color="blue", hover_color="#005C00")
        back_button.grid(row=16, column=1, pady=int(screen_height*0.01), sticky="n")

    def refresh_tokens(self):
        try:
            response = requests.post(f"http://{self.host}:{self.port}/refresh", 
                        cookies={"jwt": self.refresh_token})
            if response.status_code == 200:
                data = response.json()
                self.access_token = data["accessToken"]
                if "jwt" in response.cookies:
                    self.refresh_token = response.cookies["jwt"]
                print("Tokens refreshed successfully")
                return True
            else:
                print("Failed to refresh tokens")
                return False
        except Exception as e:
            print(f"Error during token refresh: {e}")
            return False
        
    def toggle_light(self):
        light_device = next((dev for dev in self.state.values() if dev.get("type") == "light"), None)
        if light_device:
            light_id = light_device["id"]
            current_value = light_device["value"]
            new_value = 1 if current_value == 0 else 0
            self.postgress_connect.send(json.dumps({
                "type": "update value",
                "payload": {"id": light_id, "value": new_value}
            }))
            
    def toggle_door(self):
        door_device = next((dev for dev in self.state.values() if dev.get("type") == "door"), None)
        if door_device:
            door_id = door_device["id"]
            current_value = door_device["value"]
            new_value = 1 if current_value == 0 else 0
            self.postgress_connect.send(json.dumps({
                "type": "update value",
                "payload": {"id": door_id, "value": new_value}
            }))

    def toggle_window(self):
        window_device = next((dev for dev in self.state.values() if dev.get("type") == "window"), None)
        if window_device:
            window_id = window_device["id"]
            current_value = window_device["value"]
            new_value = 1 if current_value == 0 else 0
            self.postgress_connect.send(json.dumps({
                "type": "update value",
                "payload": {"id": window_id, "value": new_value}
            }))
    
    def toggle_fan(self):
        fan_device = next((dev for dev in self.state.values() if dev.get("type") == "fan"), None)
        if fan_device:
            fan_id = fan_device["id"]
            current_value = fan_device["value"]
            new_value = 1 if current_value == 0 else 0
            self.postgress_connect.send(json.dumps({
                "type": "update value",
                "payload": {"id": fan_id, "value": new_value}
            }))

############################ GUI HOMEPAGE ###############################

    def start_gui(self):
        r.title('House Control')
        r.attributes("-fullscreen", True)

        r.update_idletasks()
        screen_width = r.winfo_screenwidth() / 1.5
        screen_height = r.winfo_screenheight() / 1.5

        pad = max(int(screen_width * 0.01), 8)
        cell_width = int((screen_width - (pad * 5)) / 4)
        top_row_height = int(screen_height * 0.55)
        button_size = max(min(cell_width, int(top_row_height * 0.9)), 160)
        image_size = int(button_size)
        entry_width = int(screen_width * 0.9)
        entry_height = int(screen_height * 0.2)
        entry_font_size = max(int(screen_height * 0.04), 18)
        
        r.grid_rowconfigure(0, weight=1)
        r.grid_rowconfigure(1, weight=1)
        r.grid_rowconfigure(2, weight=1)
        r.grid_rowconfigure(3, weight=1)
        r.grid_rowconfigure(4, weight=1)
        r.grid_rowconfigure(5, weight=1)
        r.grid_rowconfigure(6, weight=1)

        r.grid_columnconfigure(0, weight=1)
        r.grid_columnconfigure(1, weight=1)
        r.grid_columnconfigure(2, weight=1)
        r.grid_columnconfigure(3, weight=1)

       ########## IMAGES ##########

        light_on = ctk.CTkImage(light_image=Image.open(resource_path("light_on.png")),
                    size=(image_size, image_size))
        light_off = ctk.CTkImage(light_image=Image.open(resource_path("light_off.png")),
                    size=(image_size, image_size))
        door_open = ctk.CTkImage(light_image=Image.open(resource_path("door_open_2.png")),
                    size=(image_size/1.3, image_size))
        door_closed = ctk.CTkImage(light_image=Image.open(resource_path("door_closed_2.png")),
                    size=(image_size/1.3, image_size))
        window_open = ctk.CTkImage(light_image=Image.open(resource_path("window_open_2.png")),
                    size=(image_size, image_size))
        window_closed = ctk.CTkImage(light_image=Image.open(resource_path("window_closed_2.png")),
                    size=(image_size, image_size))
        talk_image = ctk.CTkImage(light_image=Image.open(resource_path("talk_2.png")),
                    size=(image_size, image_size))
        fan_on = ctk.CTkImage(light_image=Image.open(resource_path("fan_on.png")),
                    size=(image_size, image_size))
        fan_off = ctk.CTkImage(light_image=Image.open(resource_path("fan_off.png")),
                    size=(image_size, image_size))
        buzzer = ctk.CTkImage(light_image=Image.open(resource_path("buzzer.png")),
                    size=(image_size, image_size))
        

        ########## FAILURE COMMANDS ##########

        backend_connected = ctk.CTkLabel(r, text="Could Not Fetch Data" if not self.postgress_connect_flag else "OpenBCI Not Connected" if not self.openbci_connect_flag else "", font=("sans-serif", entry_font_size, "bold"))
        backend_connected.grid(row=0, column=0, columnspan=4, padx=pad, pady=pad, sticky="nsew")

        # Status label for lock/unlock

        self.state_listner = ctk.CTkLabel(r, text="Mouse Enabled", font=("sans-serif", entry_font_size, "bold"))
        self.state_listner.grid(row=1, column=0, columnspan=4, padx=pad, pady=pad, sticky="nsew")

       ########## LIGHT BUTTON ##########

        # Find the first light device in state
        light_device = next((dev for dev in self.state.values() if dev.get("type") == "light"), None)

        if light_device:
            light_id = light_device["id"]
            light_value = light_device["value"]
            light_online = light_device["online"]
            light_button = ctk.CTkButton(
                r,
                text="",
                fg_color="blue",
                corner_radius=corner_radius_button,
                hover_color="#005C00",
                width=button_size,
                height=button_size,
                image=light_on if light_value == 1 else light_off,
                command=lambda:
                    self.toggle_light()
                )
            light_status_label = ctk.CTkLabel(
                r,
                text="Online",
                font=("sans-serif", entry_font_size, "bold"),
                text_color="green"
            )
        else:
            # No light found
            light_button = ctk.CTkButton(
                r,
                text="",
                fg_color="gray",
                state="disabled",
                width=button_size,
                height=button_size,
                image=light_off
            )
            light_status_label = ctk.CTkLabel(
                r,
                text="Offline",
                font=("sans-serif", entry_font_size, "bold"),
                text_color="red"
            )

        light_button.grid(row=2, column=0, padx=pad, pady=pad, sticky="nsew")
        light_status_label.grid(row=3, column=0, padx=pad, pady=(0, pad), sticky="nsew")

       ########## DOOR BUTTON ##########

        # Find the first door device in state
        door_device = next((dev for dev in self.state.values() if dev.get("type") == "door"), None)

        if door_device:
            door_id = door_device["id"]
            door_value = door_device["value"]
            door_online = door_device["online"]
            door_button = ctk.CTkButton(
                r,
                text="",
                fg_color="blue",
                corner_radius=corner_radius_button,
                hover_color="#005C00",
                width=button_size,
                height=button_size,
                image=door_closed,
                command=lambda: self.toggle_door()
            )
            door_status_label = ctk.CTkLabel(
                r,
                text="Online",
                font=("sans-serif", entry_font_size, "bold"),
                text_color="green" if door_online else "red"
            )
        else:
            door_button = ctk.CTkButton(
                r,
                text="",
                fg_color="gray",
                state="disabled",
                width=button_size,
                height=button_size,
                image=door_closed
            )
            door_status_label = ctk.CTkLabel(
                r,
                text="Offline",
                font=("sans-serif", entry_font_size, "bold"),
                text_color="red"
            )

        door_button.grid(row=2, column=1, padx=pad, pady=pad, sticky="nsew")
        door_status_label.grid(row=3, column=1, padx=pad, pady=(0, pad), sticky="nsew")

        ########## WINDOW BUTTON ##########
        
        # Find the first window device in state
        window_device = next((dev for dev in self.state.values() if dev.get("type") == "window"), None)
        
        if window_device:
            window_id = window_device["id"]
            window_value = window_device["value"]
            window_online = window_device["online"]
            window_button = ctk.CTkButton(
                r,
                text="",
                fg_color="blue",
                corner_radius=corner_radius_button,
                hover_color="#005C00",
                width=button_size,
                height=button_size,
                image=window_open if window_value == 1 else window_closed,
                command=lambda: 
                    self.toggle_window()
            )
            window_status_label = ctk.CTkLabel(
                r,
                text="Online",
                font=("sans-serif", entry_font_size, "bold"),
                text_color="green" if window_online else "red"
            )
        else:
            window_button = ctk.CTkButton(
                r,
                text="",
                fg_color="gray",
                state="disabled",
                width=button_size,
                height=button_size,
                image=window_closed
            )
            window_status_label = ctk.CTkLabel(
                r,
                text="Offline",
                font=("sans-serif", entry_font_size, "bold"),
                text_color="red"
            )
        window_button.grid(row=2, column=2, padx=pad, pady=pad, sticky="nsew")
        window_status_label.grid(row=3, column=2, padx=pad, pady=(0, pad), sticky="nsew")


        ########## FAN BUTTON ##########

        # Find the first fan device in state
        fan_device = next((dev for dev in self.state.values() if dev.get("type") == "fan"), None)

        fan_speed_frame = ctk.CTkFrame(r, fg_color="transparent")
        fan_speed_frame.grid(row=6, column=0, padx=pad, pady=(0, pad), sticky="nsew")
        fan_speed_frame.grid_columnconfigure(0, weight=1)
        fan_speed_frame.grid_columnconfigure(1, weight=1)
        fan_speed_frame.grid_columnconfigure(2, weight=1)
        fan_speed_frame.grid_rowconfigure(0, weight=1)

        if fan_device:
            fan_id = fan_device["id"]
            fan_value = fan_device["value"]
            fan_online = fan_device.get("online", True)
            fan_button = ctk.CTkButton(
                r,
                text="",
                fg_color="blue",
                corner_radius=corner_radius_button,
                hover_color="#005C00",
                width=button_size,
                height=button_size,
                image=fan_on if fan_value else fan_off,
                command=lambda: self.toggle_fan()
            )
            fan_status_label = ctk.CTkLabel(
                r,
                text="Online",
                font=("sans-serif", entry_font_size, "bold"),
                text_color="green" if fan_online else "red"
            )
            # Fan speed buttons (enabled)
            fan_low_button = ctk.CTkButton(
                fan_speed_frame, text="Low", width=button_size//2.5, height=button_size//2.5,
                font=("sans-serif", int(entry_font_size * 0.8), "bold"), corner_radius=corner_radius_button,
                fg_color="blue", hover_color="#005C00"
            )
            fan_low_button.grid(row=1, column=0, padx=pad//2, pady=pad//2)
            fan_medium_button = ctk.CTkButton(
                fan_speed_frame, text="Medium", width=button_size//2.5, height=button_size//2.5,
                font=("sans-serif", int(entry_font_size * 0.8), "bold"), corner_radius=corner_radius_button,
                fg_color="blue", hover_color="#005C00"
            )
            fan_medium_button.grid(row=1, column=1, padx=pad//2, pady=pad//2)
            fan_high_button = ctk.CTkButton(
                fan_speed_frame, text="High", width=button_size//2.5, height=button_size//2.5,
                font=("sans-serif", int(entry_font_size * 0.8), "bold"), corner_radius=corner_radius_button,
                fg_color="blue", hover_color="#005C00"
            )
            fan_high_button.grid(row=1, column=2, padx=pad//2, pady=pad//2)
        else:
            fan_button = ctk.CTkButton(
                r,
                text="",
                fg_color="gray",
                state="disabled",
                width=button_size,
                height=button_size,
                image=fan_off
            )
            fan_status_label = ctk.CTkLabel(
                r,
                text="Offline",
                font=("sans-serif", entry_font_size, "bold"),
                text_color="red"
            )
            # Fan speed buttons (disabled/gray)
            fan_low_button = ctk.CTkButton(
                fan_speed_frame, text="Low", width=button_size//2.5, height=button_size//2.5,
                font=("sans-serif", int(entry_font_size * 0.8), "bold"), corner_radius=corner_radius_button,
                state="disabled", fg_color="gray"
            )
            fan_low_button.grid(row=1, column=0, padx=pad//2, pady=pad//2)
            fan_medium_button = ctk.CTkButton(
                fan_speed_frame, text="Medium", width=button_size//2.5, height=button_size//2.5,
                font=("sans-serif", int(entry_font_size * 0.8), "bold"), corner_radius=corner_radius_button,
                state="disabled", fg_color="gray"
            )
            fan_medium_button.grid(row=1, column=1, padx=pad//2, pady=pad//2)
            fan_high_button = ctk.CTkButton(
                fan_speed_frame, text="High", width=button_size//2.5, height=button_size//2.5,
                font=("sans-serif", int(entry_font_size * 0.8), "bold"), corner_radius=corner_radius_button,
                state="disabled", fg_color="gray"
            )
            fan_high_button.grid(row=1, column=2, padx=pad//2, pady=pad//2)

        fan_button.grid(row=4, column=0, padx=pad, pady=pad, sticky="nsew")
        fan_status_label.grid(row=5, column=0, padx=pad, pady=(0, pad), sticky="nsew")

        ########## BUZZER BUTTON ##########
        
        buzzer_device = next((dev for dev in self.state.values() if dev.get("type") == "buzz"), None)

        if buzzer_device:
            buzzer_id = buzzer_device["id"]
            buzzer_value = buzzer_device["value"]
            buzzer_online = buzzer_device["online"]
            buzzer_button = ctk.CTkButton(
                r,
                text="",
                fg_color="blue",
                corner_radius=corner_radius_button,
                hover_color="#005C00",
                width=button_size,
                height=button_size,
                image=buzzer,
                command=lambda: user.postgress_connect.send(json.dumps({
                    "type": "update value",
                    "payload": {"id": buzzer_id, "value": 1 if buzzer_value == 0 else 0}
                }))
            )
            buzzer_status_label = ctk.CTkLabel(
                r,
                text="Online",
                font=("sans-serif", entry_font_size, "bold"),
                text_color="green" if buzzer_online else "red"
            )
        else:
            buzzer_button = ctk.CTkButton(
                r,
                text="",
                fg_color="gray",
                state="disabled",
                width=button_size,
                height=button_size,
                image=buzzer
            )
            buzzer_status_label = ctk.CTkLabel(
                r,
                text="Offline",
                font=("sans-serif", entry_font_size, "bold"),
                text_color="red"
            )
        buzzer_button.grid(row=4, column=1, padx=pad, pady=pad, sticky="nsew")
        buzzer_status_label.grid(row=5, column=1, padx=pad, pady=(0, pad), sticky="nsew")

        ########## TEMPERATURE LABEL ##########

        temperature_device = next((dev for dev in self.state.values() if dev.get("type") == "temperature"), None)
        if temperature_device:
            temperature_value = temperature_device["value"]
            temperature_online = temperature_device["online"]
            temperature_status_label = ctk.CTkLabel(
                r,
                text=f"Temperature: {temperature_value}°C" if temperature_online else "Temperature: N/A",
                font=("sans-serif", entry_font_size, "bold"),
                text_color="red" if not temperature_online else "green" if 20 <= temperature_value <= 25 else "blue" if temperature_value < 20 else "red"
            )
        else:
            temperature_status_label = ctk.CTkLabel(
                r,
                text="Temperature: N/A",
                font=("sans-serif", entry_font_size, "bold"),
                text_color="red"
            )
        temperature_status_label.grid(row=2, column=3, padx=pad, pady=pad, sticky="nsew")
        

        ########## HUMIDITY LABEL ##########

        humidity_device = next((dev for dev in self.state.values() if dev.get("type") == "humidity"), None)
        if humidity_device:
            humidity_value = float(humidity_device["value"])
            humidity_online = humidity_device["online"]
            humidity_status_label = ctk.CTkLabel(
                r,
                text=f"Humidity: {humidity_value}%" if humidity_online else "Humidity: N/A",
                font=("sans-serif", entry_font_size, "bold"),
                text_color="red" if not humidity_online else "green" if 40 <= humidity_value <= 60 else "blue" if humidity_value < 40 else "red"
            )
        else:
            humidity_status_label = ctk.CTkLabel(
                r,
                text="Humidity: N/A",
                font=("sans-serif", entry_font_size, "bold"),
                text_color="red"
            )
        humidity_status_label.grid(row=4, column=3, padx=pad, pady=pad, sticky="nsew")
        

        ########## KEYBOARD ##########
        self.keybd = ctk.CTkEntry(r, placeholder_text_color="black", justify="center", font=("sans-serif", entry_font_size, "bold"), width=entry_width, height=entry_height, border_width=20, border_color="blue", corner_radius=corner_radius_entry)
        self.keybd.grid(row=6, column=1, columnspan=3, padx=pad, pady=(0, pad), sticky="nsew")
        self.keybd.bind("<Enter>", lambda e: self.keybd.configure(border_color="green"))
        self.keybd.bind("<Leave>", lambda e: self.keybd.configure(border_color="blue"))
        self.keybd.bind("<FocusIn>", lambda event: user_keyboard(master=r, widget=self.keybd, postgress_connect=self.postgress_connect, layout="qwerty"))
        
        ########## TALK BUTTON ##########

        talk_button = ctk.CTkButton(r, fg_color="blue",hover_color="#005C00", corner_radius=corner_radius_button, width=button_size, height=button_size, text="", image=talk_image, command=lambda: self.handle_talk_button(talk_button, self.keybd, window_button, door_button, light_button, fan_button, buzzer_button, backend_connected))
        talk_button.grid(row=4, column=2, padx=pad, pady=pad, sticky="nsew")

        self.update_gui(r, light_button, light_on, light_off, light_status_label, door_button, door_status_label, door_open, door_closed, window_button, window_status_label, window_open, window_closed, backend_connected, fan_button, fan_status_label, fan_on, fan_off, temperature_status_label, humidity_status_label, buzzer_status_label, self.keybd, buzzer_button)

    def update_gui(self, root, light_button, light_on, light_off, light_status_label, door_button, door_status_label, door_open, door_closed, window_button, window_status_label, window_open, window_closed, backend_connected, fan_button, fan_status_label, fan_on, fan_off, temperature_status_label, humidity_status_label, buzzer_status_label, keybd, buzzer_button):
        try:
            if self.state:
                light_status = next((dev["value"] for dev in self.state.values() if dev.get("type") == "light"), None)
                light_online = next((dev["online"] for dev in self.state.values() if dev.get("type") == "light"), None)
                if (light_status):
                    light_button.configure(fg_color="blue")
                    light_button.configure(hover_color="#005C00")
                    light_button.configure(state="normal")
                if(not light_online):
                    light_button.configure(fg_color="gray")
                    light_button.configure(hover_color="gray")
                    light_button.configure(state="disabled")

                #print(f"GUI Light status: {light_status}")
                #print(f"GUI Light online: {light_online}")

                door_status = next((dev["value"] for dev in self.state.values() if dev.get("type") == "door"), None)
                door_online = next((dev["online"] for dev in self.state.values() if dev.get("type") == "door"), None)
                if (door_status):
                    door_button.configure(fg_color="blue")
                    door_button.configure(hover_color="#005C00")
                    door_button.configure(state="normal")
                if(not door_online):
                    door_button.configure(fg_color="gray")
                    door_button.configure(hover_color="gray")
                    door_button.configure(state="disabled")
                #print(f"GUI Door status: {door_status}")
                #print(f"GUI Door online: {door_online}")

                window_status = next((dev["value"] for dev in self.state.values() if dev.get("type") == "window"), None)
                window_online = next((dev["online"] for dev in self.state.values() if dev.get("type") == "window"), None)
                if (window_status):
                    window_button.configure(fg_color="blue")
                    window_button.configure(hover_color="#005C00")
                    window_button.configure(state="normal")
                if(not window_online):
                    window_button.configure(fg_color="gray")
                    window_button.configure(hover_color="gray")
                    window_button.configure(state="disabled")

                #print(f"GUI Window status: {window_status}")
                #print(f"GUI Window online: {window_online}")

                light_button.configure(image=light_on if light_status == 1 else light_off)
                light_status_label.configure(text="Online" if light_online == True else "Offline", text_color="green" if light_online == True else "red")

                door_button.configure(image=door_open if door_status == 1 else door_closed)
                door_status_label.configure(text="Online" if door_online == True else "Offline", text_color="green" if door_online == True else "red")
                window_button.configure(image=window_open if window_status == 1 else window_closed)
                window_status_label.configure(text="Online" if window_online == True else "Offline", text_color="green" if window_online == True else "red")

                fan_button.configure(image=fan_on if next((dev["value"] for dev in self.state.values() if dev.get("type") == "fan"), None) else fan_off)
                fan_online = next((dev.get("online", True) for dev in self.state.values() if dev.get("type") == "fan"), None)
                fan_status_label.configure(text="Online" if fan_online == True else "Offline", text_color="green" if fan_online == True else "red")
                if (fan_online):
                    fan_button.configure(fg_color="blue")
                    fan_button.configure(hover_color="#005C00")
                    fan_button.configure(state="normal")
                if(not fan_online):
                    fan_button.configure(fg_color="gray")
                    fan_button.configure(hover_color="gray")
                    fan_button.configure(state="disabled")


            ########## TEMPERATURE ##########
                temperature_device = next((dev for dev in self.state.values() if dev.get("type") == "temperature"), None)

                if temperature_device:

                    if (int(temperature_device["value"]) >= 20 and int(temperature_device["value"]) <= 25):
                        temperature_status_label.configure(text=f"Temperature: {temperature_device['value']}°C", text_color="green")
                    if (int(temperature_device["value"]) < 20):
                        temperature_status_label.configure(text=f"Temperature: {temperature_device['value']}°C", text_color="blue")
                    if (int(temperature_device["value"]) > 25):
                        temperature_status_label.configure(text=f"Temperature: {temperature_device['value']}°C", text_color="red")

                humidity_device = next((dev for dev in self.state.values() if dev.get("type") == "humidity"), None)
                if (humidity_device):
                    if (int(humidity_device["value"]) >= 40 and int(humidity_device["value"]) <= 60):
                        humidity_status_label.configure(text=f"Humidity: {humidity_device['value']}%", text_color="green")
                    else:
                        humidity_status_label.configure(text=f"Humidity: {humidity_device['value']}%", text_color="red")

                        
            ######## BUZZER ##########
                buzzer_device = next((dev for dev in self.state.values() if dev.get("type") == "buzz"), None)
                if buzzer_device:
                    buzzer_status_label.configure(text="Online" if buzzer_device["online"] == True else "Offline", text_color="green" if buzzer_device["online"] == True else "red")
                if(not buzzer_device):
                    buzzer_status_label.configure(text="Offline", text_color="red")
                    buzzer_button.configure(fg_color="gray")
                    buzzer_button.configure(hover_color="gray")
                    buzzer_button.configure(state="disabled")

            ########## KEYBOARD ENTRY UPDATE (SAFE) ##########
            # Only update the keyboard entry if not focused and value is different
            # You must pass the keybd widget to this function for this to work
                if hasattr(self, 'keybd') and self.keybd is not None:
                    device_keyboard_value = self.state.get('02F283B88670', {}).get('value', None)
                    if not self.keybd.focus_get():
                        if device_keyboard_value is not None and self.keybd.get() != str(device_keyboard_value):
                            self.keybd.delete(0, 'end')
                            self.keybd.insert(0, str(device_keyboard_value))

            ########## FAILURES ##########
            if not self.postgress_connect_flag:
                backend_connected.configure(text="Could Not Fetch Data", text_color="red")
            elif not self.openbci_connect_flag:
                backend_connected.configure(text="OpenBCI Not Connected (Check USB or Batteries)", text_color="red")
            else:
                backend_connected.configure(text="")
            #print("in updating gui")

        except Exception as e:
            print(f"Error updating GUI: {e}")

        root.after(1000, self.update_gui, root, light_button, light_on, light_off, light_status_label, door_button, door_status_label, door_open, door_closed, window_button, window_status_label, window_open, window_closed, backend_connected, fan_button, fan_status_label, fan_on, fan_off, temperature_status_label, humidity_status_label, buzzer_status_label, keybd, buzzer_button)


##### Global #####
host=os.getenv("HOST")
port = int(os.getenv("PORT"))

r = ctk.CTk()
r.attributes("-fullscreen", True)
user = Client(host, port)

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0

corner_radius_button = 12
corner_radius_entry = 8

##### MAIN #####
def main():
    # Show login window after mainloop starts
    r.after(100, user.login)
    #r.after(100, user.start_gui)

    # Starta mainloop
    r.mainloop()

main()