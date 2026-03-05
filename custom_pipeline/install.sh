#!/bin/bash

# Exit on error
set -e

# Default values
PI_HOST=""
PI_USER=""
PI_PORT="22"
PROJECT_DIR="~/voice-assistant"
ENV_FILE=".env.pi"

# Print usage
usage() {
    echo "Usage: $0 -h <pi_hostname/ip> -u <username> [-p <port>]"
    echo "Example: $0 -h 192.168.86.76 -u pi"
    exit 1
}

# Parse command line arguments
while getopts "h:u:p:" opt; do
    case $opt in
        h) PI_HOST="$OPTARG" ;;
        u) PI_USER="$OPTARG" ;;
        p) PI_PORT="$OPTARG" ;;
        *) usage ;;
    esac
done

# Check required parameters
if [ -z "$PI_HOST" ] || [ -z "$PI_USER" ]; then
    usage
fi

echo "🚀 Copying Voice Assistant Files to Raspberry Pi..."
echo "Host: $PI_HOST"
echo "User: $PI_USER"
echo "Port: $PI_PORT"

# Function to run command on Pi
run_on_pi() {
    ssh -o StrictHostKeyChecking=no -p "$PI_PORT" "$PI_USER@$PI_HOST" "$1"
}

# Function to copy file to Pi
copy_to_pi() {
    local src="$1"
    local dest="$2"
    if [ -d "$src" ]; then
        # If source is a directory, use -r flag
        scp -o StrictHostKeyChecking=no -P "$PI_PORT" -r "$src" "$PI_USER@$PI_HOST:$dest"
    else
        # If source is a file, copy normally
        scp -o StrictHostKeyChecking=no -P "$PI_PORT" "$src" "$PI_USER@$PI_HOST:$dest"
    fi
}

echo "📂 Creating project directory on Pi..."
run_on_pi "mkdir -p $PROJECT_DIR"

echo "📦 Copying project files..."

# Copy Python files
echo "  📄 Copying Python files..."
copy_to_pi "simple_local_assistant.py" "$PROJECT_DIR/"
copy_to_pi "cobra_vad.py" "$PROJECT_DIR/"
copy_to_pi "prompts.py" "$PROJECT_DIR/"
copy_to_pi "requirements.txt" "$PROJECT_DIR/"

# Copy sounds directory
echo "  🔊 Copying sounds directory..."
copy_to_pi "sounds" "$PROJECT_DIR/"

# Copy wake word files if they exist
echo "  🎯 Copying wake word files..."
for ppn_file in *raspberry-pi_*.ppn; do
    if [ -f "$ppn_file" ]; then
        echo "    📝 Found wake word file: $ppn_file"
        copy_to_pi "$ppn_file" "$PROJECT_DIR/"
    fi
done

# Copy environment file if it exists
if [ -f "$ENV_FILE" ]; then
    echo "  🔑 Copying environment file..."
    copy_to_pi "$ENV_FILE" "$PROJECT_DIR/.env"
    echo "✅ Environment file copied"
else
    echo "⚠️  No .env.pi file found - you'll need to create .env manually"
fi

# Copy debug scripts for troubleshooting
echo "  🛠️  Copying debug scripts..."
if [ -f "test_volume.py" ]; then
    copy_to_pi "test_volume.py" "$PROJECT_DIR/"
fi
if [ -f "debug_audio.py" ]; then
    copy_to_pi "debug_audio.py" "$PROJECT_DIR/"
fi

echo ""
echo "🐍 Setting up Python environment on Pi..."

# Create virtual environment
run_on_pi "cd $PROJECT_DIR && python3 -m venv venv"

# Install Python packages
echo "📦 Installing Python packages..."
run_on_pi "cd $PROJECT_DIR && source venv/bin/activate && pip install --upgrade pip"
run_on_pi "cd $PROJECT_DIR && source venv/bin/activate && pip install wheel"
run_on_pi "cd $PROJECT_DIR && source venv/bin/activate && pip install -r requirements.txt"
