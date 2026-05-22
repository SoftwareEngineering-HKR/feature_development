"""
This file has been fully pair-programmed by Razmus and Marcus.
"""

import json

import customtkinter as ctk
import speech_recognition as sr 
import threading
import os
import platform
from gtts import gTTS
from playsound import playsound
import subprocess


is_uppercase = False
is_functional = False

# Define the key layouts
normal_keys_qwertz = [
    ['q', 'w', 'e', 'r', 't', 'z', 'u', 'i', 'o', 'p'],
    ['a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l', 'mic'],
    ['▲', 'y', 'x', 'c', 'v', 'b', 'n', 'm', '←'],
    ['func', ',', ' ', '.', 'ok']
]

normal_keys_qwerty = [
    ['q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p'],
    ['a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l', 'mic'],
    ['▲', 'z', 'x', 'c', 'v', 'b', 'n', 'm', '←'],
    ['func', ',', ' ', '.', 'ok']
]

functional_keys = [
    ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0'],
    ['@', '#', '&', '_', '-', '(', ')', '=', '%'],
    ['▲', '"', '*', "'", ':', '/', '!', '+', '←', '?'],
    ['func', ',', ' ', '.', 'ok']
]

keys = normal_keys_qwertz  # Default to QWERTZ

def keyboard(master, widget, layout, postgress_connect=None):
    global normal_keys_qwertz, normal_keys_qwerty, keys

    if layout == "qwertz":
        keys = normal_keys_qwertz
    elif layout == "qwerty":
        keys = normal_keys_qwerty

    # Return text as ctk.StringVar()
    # return_txt = ctk.StringVar()

    screen_width = master.winfo_screenwidth()
    screen_height = master.winfo_screenheight()

    def close_keyboard(event=None):
        keyboard_frame.destroy()
        entry_frame.destroy()

    def update_keys():
        for frame in keyboard_frame.winfo_children():
            for widget in frame.winfo_children():
                widget.destroy()

        for i, row in enumerate(keys):
            frame = ctk.CTkFrame(keyboard_frame)
            if i == 1:
                frame.grid(row=i, column=0, padx=int((screen_width / len(keys[2])) / 2), sticky="nsew")
            else:
                frame.grid(row=i, column=0, sticky="nsew")
            for j, key in enumerate(row):
                if key == ',':
                    display_key = ';' if is_uppercase else ','
                elif key == '.':
                    display_key = ':' if is_uppercase else '.'
                else:
                    display_key = key.upper() if is_uppercase and key not in ['func', ' ', 'ok', '←'] else key.lower()
                key_btn = ctk.CTkButton(frame, text=display_key, font=("Arial", font_size, "bold"), text_color="black", command=lambda k=display_key: on_key_press(k))
                frame.rowconfigure(0, weight=1)
                frame.columnconfigure(j, weight=1)
                keyboard_frame.rowconfigure(i, weight=1)
                key_btn.grid(row=0, column=j, padx=5, pady=5, sticky="nsew")

        # Update special keys row
        """special_row_frame = ctk.CTkFrame(keyboard_frame)
        for j, key in enumerate(special_keys_row):
            if key == ',':
                display_key = ';' if is_uppercase else ','
            elif key == '.':
                display_key = ':' if is_uppercase else '.'
            else:
                display_key = key.upper() if is_uppercase and key not in ['func', ' ', 'ok', '←'] else key.lower()
            key_btn = ctk.CTkButton(special_row_frame, text=display_key, font=("Arial", font_size, "bold"), text_color="black", command=lambda k=display_key: on_key_press(k))
            special_row_frame.columnconfigure(j, weight=1)
            key_btn.grid(row=0, column=j, padx=5, pady=5, sticky="nsew")
            if key == " ":
                special_row_frame.columnconfigure(j, weight=8)
        keyboard_frame.rowconfigure(len(keys), weight=1)
        special_row_frame.grid(row=len(keys), column=0, sticky="nsew")"""

    def on_key_press(key):
        global is_uppercase, is_functional, keys

        if key == "←":
            txt_entry.delete(len(txt_entry.get()) - 1, 'end')  # Delete the last character
        elif key == "▲":
            is_uppercase = not is_uppercase
            update_keys()
        elif key == 'func':
            is_functional = not is_functional
            keys = functional_keys if is_functional else (normal_keys_qwerty if layout == "qwerty" else normal_keys_qwertz)
            update_keys()
        elif key == 'ok':
            print("OK Pressed, value to send:")
            value = txt_entry.get()
            print(f"Value: {value}")
            widget.delete(0, ctk.END)
            if value != "":
                widget.insert('end', value)
                print(f"Postgress Connect: {postgress_connect}")
                if postgress_connect:
                    print(f"Updating deviceTest4 with value: {value}")
                    
                    postgress_connect.send(json.dumps({"type": "update value", "payload": {"id": "02F283B88670", "value": value}}))
            master.focus()
            close_keyboard()
        elif key == 'mic':
            threading.Thread(target=google_speech_recognition_keyboard, daemon=True).start()
        else:
            txt_entry.insert('end', key)
            keys 

    def google_speech_recognition_keyboard():
        try:
            rec = sr.Recognizer()
            rec.pause_threshold = 1.0
            rec.energy_threshold = 400

            with sr.Microphone(sample_rate=16000) as source:
                print("Listening... (speak now)")
                listen_text = ctk.CTkLabel(entry_frame, text="Listening...",text_color="green" ,font=("Arial", int(font_size), "bold"))
                listen_text.grid(row=2, column=1, columnspan=5)
                rec.adjust_for_ambient_noise(source, duration=0.5)
                audio_data = rec.listen(source)
                listen_text.destroy()
                print("Processing...")
            text = rec.recognize_google(audio_data, language="en")
            text = text.lower()
            if "delete" in text:
                txt_entry.delete(0, ctk.END)
            else:
                print(f"Recognized Text: {text}")
                txt_entry.insert('end', text)
        except sr.UnknownValueError:
            txt_info_warning = ctk.CTkLabel(entry_frame, text="Google Speech Recognition could not understand audio",text_color="red" ,font=("Arial", int(font_size), "bold"))
            txt_info_warning.grid(row=3, column=1, columnspan=4)
            print("Google Speech Recognition could not understand audio")
        except sr.RequestError as e:
            txt_info_warning_internet = ctk.CTkLabel(entry_frame, text="Could not request results from Google Speech Recognition service",text_color="red" ,font=("Arial", int(font_size), "bold"))
            txt_info_warning_internet.grid(row=3, column=1, columnspan=4)
            print(f"Could not request results from Google Speech Recognition service; {e}")
            

    # Create keyboard and layout
    keyboard_frame = ctk.CTkToplevel()
    #keyboard_frame.attributes("-topmost", True)
    keyboard_frame.overrideredirect(True)
    keyboard_frame.resizable(False, False)
    font_size = keyboard_frame.winfo_height() / 4
    x = 0
    y = screen_height - (screen_height // 2)
    keyboard_frame.geometry('%dx%d+%d+%d' % (screen_width, screen_height / 2, x, y))
    keyboard_frame.columnconfigure(0, weight=1)

    # Last row for extra keys
    """special_keys_row = ['func', ',', ' ', '.', 'ok']
    special_row_frame = ctk.CTkFrame(keyboard_frame)
    for j, key in enumerate(special_keys_row):
        key_btn = ctk.CTkButton(special_row_frame, text=key, font=("Arial", font_size, "bold"), text_color="black", command=lambda k=key: on_key_press(k))
        special_row_frame.columnconfigure(j, weight=1)
        key_btn.grid(row=0, column=j, padx=5, pady=5, sticky="nsew")
        if key == " ":
            special_row_frame.columnconfigure(j, weight=8)
    keyboard_frame.rowconfigure(len(keys), weight=1)
    special_row_frame.grid(row=len(keys), column=0, sticky="nsew")"""

    for i, row in enumerate(keys):
        frame = ctk.CTkFrame(keyboard_frame)
        if i == 1:
            frame.grid(row=i, column=0, padx=int((screen_width / len(keys[2])) / 2), sticky="nsew")
        else:
            frame.grid(row=i, column=0, sticky="nsew")

        for j, key in enumerate(row):
            key_btn = ctk.CTkButton(frame, text=key, font=("Arial", font_size, "bold"), text_color="black", command=lambda k=key: on_key_press(k))
            frame.rowconfigure(0, weight=1)
            frame.columnconfigure(j, weight=1)
            keyboard_frame.rowconfigure(i, weight=1)
            key_btn.grid(row=0, column=j, padx=5, pady=5, sticky="nsew")

    # Create the keys for the keyboard
    update_keys()

    # Top entry frame for better entry
    entry_frame = ctk.CTkToplevel()
    entry_frame.attributes("-topmost", True)
    entry_frame.overrideredirect(True)
    entry_frame.resizable(False, False)
    entry_frame.focus()
    entry_frame.rowconfigure(0, weight=1)
    entry_frame.rowconfigure(1, weight=1)
    entry_frame.rowconfigure(2, weight=1)
    entry_frame.rowconfigure(3, weight=1)
    entry_frame.columnconfigure((0, 1, 2, 3, 4, 5, 6), weight=1)
    font_size = entry_frame.winfo_height() / 4
    window_height2 = screen_height / 2 - 31
    window_width2 = screen_width
    x = (screen_width / 2) - (window_width2 / 2)
    y = (screen_height / 2) - (window_height2 / 2) * 2
    entry_frame.geometry('%dx%d+%d+%d' % (window_width2, window_height2, x, y))
    txt_entry = ctk.CTkEntry(entry_frame, height=window_height2 / 4, width=window_width2 / 2, corner_radius=8, font=("Arial", font_size, "bold"), justify="center")
    txt_entry.grid(row=1, column=1, sticky="nsew", columnspan=5)
    txt_info  = ctk.CTkLabel(entry_frame, text="Type Your Text Here:", font=("Arial", int(font_size), "bold"))
    txt_info.grid(row=0, column=1, columnspan=5)
    if widget.get() == "What do you want to write?":
        widget.delete(0, ctk.END)
    elif widget.get() == widget.get():
        widget.delete(0, ctk.END)
    txt_entry.insert('end', widget.get())

    keyboard_frame.focus_force()
    txt_entry.focus_set()