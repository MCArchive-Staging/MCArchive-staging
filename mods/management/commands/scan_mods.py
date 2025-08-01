import re
import requests
import time
from django.core.management.base import BaseCommand
from django.db import transaction
from mods.models import Mod, ModVersion


class Command(BaseCommand):
    help = 'Continuously scan the MC Mod Archive for new mods and updates'

    def add_arguments(self, parser):
        parser.add_argument(
            '--url',
            type=str,
            default='https://mcmodarchive.femtopedia.de/FilesIndex.txt',
            help='URL to the mod archive index file'
        )
        parser.add_argument(
            '--interval',
            type=int,
            default=3600,  # 1 hour default
            help='Scan interval in seconds (default: 3600 = 1 hour)'
        )
        parser.add_argument(
            '--once',
            action='store_true',
            help='Run scan once and exit (for testing)'
        )

    def handle(self, *args, **options):
        url = options['url']
        interval = options['interval']
        once = options['once']

        self.stdout.write(f"Starting continuous scan of {url}")
        self.stdout.write(f"Scan interval: {interval} seconds ({interval/3600:.1f} hours)")
        
        if once:
            self.stdout.write("Running single scan...")
            self._scan_once(url)
            return

        self.stdout.write("Starting continuous scanning (Ctrl+C to stop)...")
        
        try:
            while True:
                self._scan_once(url)
                self.stdout.write(f"Scan completed. Waiting {interval} seconds until next scan...")
                time.sleep(interval)
        except KeyboardInterrupt:
            self.stdout.write("\nScanning stopped by user.")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Scanning error: {e}"))

    def _scan_once(self, url):
        """Perform a single scan for new mods and updates"""
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            lines = response.text.split('\n')
        except requests.RequestException as e:
            self.stdout.write(self.style.ERROR(f"Failed to fetch data: {e}"))
            return

        # Skip comment lines and empty lines
        mod_lines = [line.strip() for line in lines if line.strip() and not line.startswith('#')]
        
        self.stdout.write(f"Found {len(mod_lines)} total entries")

        # Filter to only include mods
        filtered_lines = []
        for line in mod_lines:
            parts = line.split('/')
            if len(parts) >= 5:
                category_name = parts[0].lower()
                if category_name == 'mods':
                    filtered_lines.append(line)
        
        self.stdout.write(f"Filtered to {len(filtered_lines)} mod entries")

        # Track statistics
        new_mods = 0
        new_versions = 0
        updated_mods = 0
        
        with transaction.atomic():
            for i, line in enumerate(filtered_lines):
                if i % 1000 == 0:
                    self.stdout.write(f"Processing entry {i + 1}/{len(filtered_lines)}...")
                
                parts = line.split('/')
                if len(parts) < 3:
                    continue
                
                # Parse the structure: Mods/[letter]/[mod_name]/[version]/[platform]/[file]
                mod_name = parts[2]  # Actual mod name
                
                # Properly capitalize mod name
                mod_name_capitalized = ' '.join(word.capitalize() for word in mod_name.split())
                
                # Check if this URL already exists
                if ModVersion.objects.filter(file_path=line).exists():
                    continue  # Skip if already imported
                
                # Create or get mod
                mod, created = Mod.objects.get_or_create(
                    name=mod_name_capitalized,
                    defaults={}
                )
                if created:
                    new_mods += 1
                
                # Create new version
                version_info = self._parse_version_info(parts, line)
                version, created = ModVersion.objects.get_or_create(
                    mod=mod,
                    file_path=line,
                    defaults=version_info
                )
                if created:
                    new_versions += 1
                    # Update mod's updated_at timestamp
                    mod.save(update_fields=['updated_at'])
                    updated_mods += 1

        # Report results
        if new_mods > 0 or new_versions > 0:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Scan completed!\n"
                    f"New mods found: {new_mods}\n"
                    f"New versions found: {new_versions}\n"
                    f"Mods updated: {updated_mods}"
                )
            )
        else:
            self.stdout.write("No new mods or versions found.")

    def _parse_version_info(self, parts, full_path):
        """Parse version information from file path"""
        file_name = parts[-1] if parts else ''
        
        # Try to extract version number from file name
        version_number = self._extract_version(file_name)
        
        # Try to extract Minecraft version
        minecraft_version = self._extract_minecraft_version(full_path)
        
        # Try to extract platform
        platform = self._extract_platform(full_path)
        
        return {
            'version_number': version_number or 'Unknown',
            'file_name': file_name,
            'minecraft_version': minecraft_version,
            'platform': platform,
        }

    def _extract_version(self, filename):
        """Extract version number from filename"""
        # Common version patterns
        patterns = [
            r'(\d+\.\d+\.\d+)',  # 1.2.3
            r'(\d+\.\d+)',       # 1.2
            r'v(\d+\.\d+\.\d+)', # v1.2.3
            r'v(\d+\.\d+)',      # v1.2
            r'(\d+\.\d+\.\d+[a-zA-Z]+)',  # 1.2.3a
        ]
        
        for pattern in patterns:
            match = re.search(pattern, filename)
            if match:
                return match.group(1)
        return None

    def _extract_minecraft_version(self, path):
        """Extract Minecraft version from the file path structure"""
        parts = path.split('/')
        
        # Structure: Mods/[letter]/[mod_name]/[minecraft_version]/[platform]/[file]
        # OR: Mods/[letter]/[mod_name]/[minecraft_version]/[file]
        if len(parts) >= 4:
            minecraft_version_folder = parts[3]  # This should be the Minecraft version
            
            # Check if it looks like a Minecraft version
            patterns = [
                r'^(\d+\.\d+\.\d+)$',  # 1.2.3
                r'^(\d+\.\d+)$',       # 1.2
                r'^mc(\d+\.\d+\.\d+)$', # mc1.2.3
                r'^mc(\d+\.\d+)$',     # mc1.2
            ]
            
            for pattern in patterns:
                match = re.search(pattern, minecraft_version_folder)
                if match:
                    return match.group(1)
        
        # If not found in the expected position, try to find it anywhere in the path
        patterns = [
            r'(\d+\.\d+\.\d+)',  # 1.2.3
            r'(\d+\.\d+)',       # 1.2
            r'mc(\d+\.\d+\.\d+)', # mc1.2.3
            r'mc(\d+\.\d+)',     # mc1.2
        ]
        
        for pattern in patterns:
            match = re.search(pattern, path)
            if match:
                return match.group(1)
        return None

    def _extract_platform(self, path):
        """Extract platform information from path"""
        path_lower = path.lower()
        
        if 'client' in path_lower:
            return 'Client'
        elif 'server' in path_lower:
            return 'Server'
        elif 'bukkit' in path_lower:
            return 'Bukkit'
        elif 'spigot' in path_lower:
            return 'Spigot'
        elif 'forge' in path_lower:
            return 'Forge'
        elif 'fabric' in path_lower:
            return 'Fabric'
        elif 'mcaddon' in path_lower:
            return 'Bedrock'
        
        return None 