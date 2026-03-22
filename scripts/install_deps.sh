#!/bin/bash
set -euo pipefail

echo "Installing verbal-code dependencies..."

sudo apt update
sudo apt install -y \
    build-essential \
    cmake \
    git \
    pkg-config \
    curl \
    unzip \
    libpipewire-0.3-dev \
    libxcb1-dev \
    libxcb-xinput-dev \
    libxkbcommon-dev \
    libxkbcommon-x11-dev \
    libgtk-3-dev \
    libxdo-dev

echo ""
echo "Core build dependencies installed."
echo ""

# Wayland runtime dependencies (needed for text injection on Wayland sessions)
echo "Installing Wayland runtime tools..."
sudo apt install -y \
    wtype \
    wl-clipboard \
    ydotool

echo ""
echo "All dependencies installed successfully."
echo ""
echo "Note: On Wayland, your user must be in the 'input' group for global hotkeys:"
echo "        sudo usermod -aG input \$USER"
echo "      (Log out and back in for group changes to take effect.)"
