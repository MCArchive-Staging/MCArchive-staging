import re
import requests
import time
from django.core.management.base import BaseCommand
from django.db import transaction, IntegrityError
from django.utils.text import slugify
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
            default=3600,
            help='Scan interval in seconds (default: 3600)'
        )
        parser.add_argument(
            '--once',
            action='store_true',
            help='Run scan once and exit'
        )

    def handle(self, *args, **options):
        url = options['url']
        interval = options['interval']
        once = options['once']

        self.stdout.write(f"Starting scan of {url}")
        
        if once:
            self._scan_once(url)
            return

        try:
            while True:
                self._scan_once(url)
                self.stdout.write(f"Waiting {interval}s...")
                time.sleep(interval)
        except KeyboardInterrupt:
            self.stdout.write("\nScanning stopped.")

    def _scan_once(self, url):
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            lines = response.text.split('\n')
        except requests.RequestException as e:
            self.stdout.write(self.style.ERROR(f"Fetch failed: {e}"))
            return

        # 1. Pre-process lines
        mod_lines = [line.strip() for line in lines if line.strip() and line.startswith('Mods/')]
        self.stdout.write(f"Processing {len(mod_lines)} mod entries...")

        # 2. Optimization: Cache existing data to avoid N+1 queries and IntegrityErrors
        existing_paths = set(ModVersion.objects.values_list('file_path', flat=True))
        
        # Build maps for existing mods by name and slug
        all_mods = Mod.objects.all()
        mod_map = {m.name: m for m in all_mods}
        slug_map = {m.slug: m for m in all_mods}

        new_mods = 0
        new_versions = 0
        
        # 3. Transactional Processing
        try:
            with transaction.atomic():
                for i, line in enumerate(mod_lines):
                    if line in existing_paths:
                        continue
                    
                    parts = line.split('/')
                    if len(parts) < 4:
                        continue
                    
                    # Clean up the name
                    raw_name = parts[2]
                    mod_name = ' '.join(word.capitalize() for word in raw_name.split())
                    mod_slug = slugify(mod_name)
                    
                    # 4. Robust Mod retrieval (Prevents UNIQUE constraint error on slug)
                    mod = mod_map.get(mod_name)
                    if not mod:
                        mod = slug_map.get(mod_slug)
                    
                    if not mod:
                        # Create new Mod if neither name nor slug exists
                        mod = Mod.objects.create(name=mod_name)
                        mod_map[mod_name] = mod
                        slug_map[mod_slug] = mod
                        new_mods += 1
                    
                    # 5. Create Version
                    version_info = self._parse_version_info(parts, line)
                    ModVersion.objects.create(
                        mod=mod,
                        file_path=line,
                        **version_info
                    )
                    
                    new_versions += 1
                    existing_paths.add(line)

                    if (new_versions + new_mods) % 500 == 0:
                        self.stdout.write(f"Imported {new_versions} versions so far...")

            self.stdout.write(self.style.SUCCESS(
                f"Scan Complete: {new_mods} new mods, {new_versions} new versions."
            ))

        except IntegrityError as e:
            self.stdout.write(self.style.ERROR(f"Database Integrity Error: {e}"))

    def _parse_version_info(self, parts, full_path):
        file_name = parts[-1]
        return {
            'version_number': self._extract_version(file_name) or 'Unknown',
            'file_name': file_name,
            'minecraft_version': self._extract_minecraft_version(full_path),
            'platform': self._extract_platform(full_path),
        }

    def _extract_version(self, filename):
        patterns = [r'(\d+\.\d+\.\d+)', r'(\d+\.\d+)', r'v(\d+\.\d+\.\d+)']
        for p in patterns:
            match = re.search(p, filename)
            if match: return match.group(1)
        return None

    def _extract_minecraft_version(self, path):
        # Specific folder check (usually index 3 in Mods/A/Name/1.12.2/...)
        parts = path.split('/')
        if len(parts) >= 4:
            folder = parts[3]
            if re.match(r'^\d+\.\d+(\.\d+)?', folder):
                return folder
        return "Unknown"

    def _extract_platform(self, path):
        path_lower = path.lower()
        platforms = {
            'forge': 'Forge', 'fabric': 'Fabric', 'quilt': 'Quilt',
            'bukkit': 'Bukkit', 'spigot': 'Spigot', 'paper': 'Paper',
            'client': 'Client', 'server': 'Server'
        }
        for key, val in platforms.items():
            if key in path_lower: return val
        return 'Universal'