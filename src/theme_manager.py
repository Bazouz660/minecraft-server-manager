"""
Theme management for Minecraft Server Manager GUI with expanded theme options
"""

import tkinter as tk
from tkinter import ttk
import os
import logging

class ThemeManager:
    """Manages application themes for a consistent look and feel"""

    def __init__(self, root, theme_name="system"):
        self.root = root
        self.theme_name = theme_name

        # Available themes
        self.themes = {
            "system": {
                "name": "System Default",
                "bg": None,  # Use system default
                "fg": None,
                "accent": "#007bff",
                "button_bg": None,
                "entry_bg": None,
                "warning": "#ffc107",
                "error": "#dc3545",
                "success": "#28a745"
            },
            "light": {
                "name": "Light",
                "bg": "#f8f9fa",
                "fg": "#212529",
                "accent": "#007bff",
                "button_bg": "#e9ecef",
                "entry_bg": "#ffffff",
                "warning": "#ffc107",
                "error": "#dc3545",
                "success": "#28a745"
            },
            "dark": {
                "name": "Dark",
                "bg": "#212529",
                "fg": "#f8f9fa",
                "accent": "#0d6efd",
                "button_bg": "#343a40",
                "entry_bg": "#343a40",
                "warning": "#ffc107",
                "error": "#dc3545",
                "success": "#28a745"
            },
            "blue": {
                "name": "Blue",
                "bg": "#e6f2ff",
                "fg": "#00264d",
                "accent": "#0066cc",
                "button_bg": "#cce6ff",
                "entry_bg": "#ffffff",
                "warning": "#ffc107",
                "error": "#dc3545",
                "success": "#28a745"
            },
            "green": {
                "name": "Green",
                "bg": "#e6ffe6",
                "fg": "#003300",
                "accent": "#006600",
                "button_bg": "#ccffcc",
                "entry_bg": "#ffffff",
                "warning": "#ffc107",
                "error": "#dc3545",
                "success": "#28a745"
            },
            "purple": {
                "name": "Purple",
                "bg": "#f2e6ff",
                "fg": "#330066",
                "accent": "#6600cc",
                "button_bg": "#e6ccff",
                "entry_bg": "#ffffff",
                "warning": "#ffc107",
                "error": "#dc3545",
                "success": "#28a745"
            },
            "orange": {
                "name": "Orange",
                "bg": "#fff2e6",
                "fg": "#663300",
                "accent": "#cc6600",
                "button_bg": "#ffdab3",
                "entry_bg": "#ffffff",
                "warning": "#ffc107",
                "error": "#dc3545",
                "success": "#28a745"
            },
            "dark-blue": {
                "name": "Dark Blue",
                "bg": "#1a1a2e",
                "fg": "#e6e6ff",
                "accent": "#4d80e4",
                "button_bg": "#16213e",
                "entry_bg": "#0f3460",
                "warning": "#ffc107",
                "error": "#dc3545",
                "success": "#28a745"
            },
            "cyber": {
                "name": "Cyberpunk",
                "bg": "#0a0a0a",
                "fg": "#00ff00",
                "accent": "#ff00ff",
                "button_bg": "#1a1a1a",
                "entry_bg": "#1a1a1a",
                "warning": "#ffff00",
                "error": "#ff0000",
                "success": "#00ff00"
            },
            "mojang": {
                "name": "Mojang",
                "bg": "#e8e8e8",
                "fg": "#303030",
                "accent": "#ed3b3b",  # Mojang red
                "button_bg": "#dddddd",
                "entry_bg": "#ffffff",
                "warning": "#ffc107",
                "error": "#ed3b3b",
                "success": "#5eba32"  # Minecraft green
            },
            "minecraft": {
                "name": "Minecraft",
                "bg": "#3c682e",  # Grass block green
                "fg": "#ffffff",
                "accent": "#a05a2c",  # Dirt brown
                "button_bg": "#6b8e4e",  # Lighter grass
                "entry_bg": "#e3dfd0",  # Light sand
                "warning": "#ffb300",  # Gold
                "error": "#982121",  # Redstone
                "success": "#e3dfd0"  # Sand
            }
        }

        # Apply the theme
        self.apply_theme(theme_name)

    def apply_theme(self, theme_name):
        """Apply the specified theme to the UI"""
        if theme_name not in self.themes:
            logging.warning(f"Unknown theme: {theme_name}, using system default")
            theme_name = "system"

        self.theme_name = theme_name
        theme = self.themes[theme_name]

        try:
            # Load themed ttk style
            style = ttk.Style()

            if theme_name == "system":
                # Use system theme as base
                style.theme_use("clam" if os.name == "posix" else "vista")
            else:
                style.theme_use("clam")

                # Configure common elements
                style.configure(".",
                               background=theme["bg"],
                               foreground=theme["fg"],
                               fieldbackground=theme["entry_bg"])

                # Configure specific elements
                style.configure("TButton",
                               background=theme["button_bg"])

                style.map("TButton",
                         background=[("active", theme["accent"])],
                         foreground=[("active", "#ffffff")])

                style.configure("TNotebook",
                               background=theme["bg"])

                style.configure("TNotebook.Tab",
                               background=theme["button_bg"],
                               padding=[10, 2])

                style.map("TNotebook.Tab",
                         background=[("selected", theme["accent"])],
                         foreground=[("selected", "#ffffff")])

                style.configure("TProgressbar",
                               background=theme["accent"],
                               troughcolor=theme["button_bg"])

                # Configure root window
                self.root.configure(background=theme["bg"])

                # Additional theme tweaks
                style.configure("TLabelframe",
                               background=theme["bg"],
                               foreground=theme["fg"])

                style.configure("TLabelframe.Label",
                               background=theme["bg"],
                               foreground=theme["fg"])

                style.configure("TCheckbutton",
                               background=theme["bg"],
                               foreground=theme["fg"])

                style.configure("TRadiobutton",
                               background=theme["bg"],
                               foreground=theme["fg"])

                # Treeview configuration
                style.configure("Treeview",
                               background=theme["entry_bg"],
                               foreground=theme["fg"],
                               fieldbackground=theme["entry_bg"])

                style.map("Treeview",
                         background=[("selected", theme["accent"])],
                         foreground=[("selected", "#ffffff")])

            logging.info(f"Applied theme: {theme['name']}")

        except Exception as e:
            logging.error(f"Error applying theme: {e}")

    def get_current_theme(self):
        """Return the current theme dictionary"""
        return self.themes[self.theme_name]

    def get_theme_names(self):
        """Return a list of available theme names"""
        return list(self.themes.keys())