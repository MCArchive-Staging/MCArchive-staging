#!/usr/bin/env python3
"""
Script to run the mod import with optimal settings.
This script will import all mods from the MC Mod Archive.
"""

import os
import sys
import django
from django.core.management import execute_from_command_line

# Add the project directory to the Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Set up Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mcarchive.settings')
django.setup()

def main():
    """Run the mod import with optimal settings"""
    print("🚀 Starting mod import...")
    print("📊 This will import all mods from the MC Mod Archive")
    print("✨ Mods will be properly capitalized (e.g., 'abyssal craft' → 'Abyssal Craft')")
    print("📝 Descriptions will be left blank for manual setting")
    print("🏷️  Platform detection (Client/Server/Forge/Fabric/etc.)")
    print("-" * 50)
    
    # Run the import command
    execute_from_command_line([
        'manage.py',
        'import_mods'
    ])

if __name__ == '__main__':
    main() 