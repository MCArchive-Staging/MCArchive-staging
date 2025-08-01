#!/usr/bin/env python3
"""
Continuous Mod Scanner Script

This script runs the continuous scanner to monitor the femtopedia site for new mods.
"""

import os
import sys
import django

# Add the project directory to the Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Set up Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mcarchive.settings')
django.setup()

from django.core.management import execute_from_command_line

if __name__ == '__main__':
    print("Starting MCArchive Next Continuous Scanner...")
    print("This will scan the femtopedia site every hour for new mods.")
    print("Press Ctrl+C to stop the scanner.")
    print()
    
    # Run the scan_mods command
    execute_from_command_line(['manage.py', 'scan_mods']) 