# Installation Guide

## Installing the Pre-built Executable

1. Download the latest release from the [releases page](https://github.com/Bazouz660/minecraft-server-manager/releases)
2. Extract the zip file into your Minecraft server directory
3. Run `Minecraft Server Manager.exe`

## Running from Source

### Prerequisites

- Python 3.8 or higher
- pip (Python package manager)

### Steps

1. Clone the repository:
   git clone https://github.com/yourusername/minecraft-server-manager.git
2. Navigate to the project directory:
   cd minecraft-server-manager
3. Install required packages:
   pip install -r requirements.txt
4. Run the application:
   python src/minecraft_manager.py

## Building from Source

1. Install PyInstaller:
   pip install pyinstaller
2. Run the build script:
   python build/build.py
3. The executable will be created in the `dist` folder
