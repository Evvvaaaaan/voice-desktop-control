#!/bin/bash

# build_dmg.sh - Create a DMG distribution file for VoiceDesk
# Usage: ./build_dmg.sh [version]

set -e

VERSION="${1:-0.1.0}"
DMG_NAME="VoiceDesk-${VERSION}.dmg"
APP_PATH="dist/VoiceDesk.app"

# Verify the app bundle exists
if [ ! -d "$APP_PATH" ]; then
    echo "Error: $APP_PATH not found. Run 'python setup.py py2app' first."
    exit 1
fi

# Remove existing DMG if present
if [ -f "dist/$DMG_NAME" ]; then
    echo "Removing existing $DMG_NAME..."
    rm "dist/$DMG_NAME"
fi

# Create the DMG
echo "Creating $DMG_NAME..."
hdiutil create -volname "VoiceDesk" -srcfolder "$APP_PATH" \
  -ov -format UDZO "dist/$DMG_NAME"

echo "DMG created successfully: dist/$DMG_NAME"
echo "File size: $(du -h "dist/$DMG_NAME" | cut -f1)"
