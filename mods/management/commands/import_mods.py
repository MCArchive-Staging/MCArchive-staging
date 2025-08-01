import re
import requests
from django.core.management.base import BaseCommand
from django.db import transaction
from mods.models import ModCategory, Mod, ModVersion


class Command(BaseCommand):
    help = 'Import mods from the MC Mod Archive'

    def add_arguments(self, parser):
        parser.add_argument(
            '--url',
            type=str,
            default='https://mcmodarchive.femtopedia.de/FilesIndex.txt',
            help='URL to the mod archive index file'
        )
        parser.add_argument(
            '--limit',
            type=int,
            help='Limit the number of mods to import (for testing)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be imported without actually importing'
        )

    def handle(self, *args, **options):
        url = options['url']
        limit = options['limit']
        dry_run = options['dry_run']

        self.stdout.write(f"Fetching mod data from {url}...")
        
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            lines = response.text.split('\n')
        except requests.RequestException as e:
            self.stdout.write(self.style.ERROR(f"Failed to fetch data: {e}"))
            return

        # Skip comment lines and empty lines
        mod_lines = [line.strip() for line in lines if line.strip() and not line.startswith('#')]
        
        if limit:
            mod_lines = mod_lines[:limit]
            self.stdout.write(f"Limited to {limit} entries for testing")

        self.stdout.write(f"Found {len(mod_lines)} mod entries to process")

        if dry_run:
            self.stdout.write("DRY RUN - No data will be imported")
            self._analyze_data(mod_lines)
            return

        # Process the data
        self._import_mods(mod_lines)

    def _analyze_data(self, lines):
        """Analyze the data structure without importing"""
        categories = set()
        mods = set()
        
        # Filter to only include mods (same logic as import)
        filtered_lines = []
        for line in lines:
            parts = line.split('/')
            if len(parts) >= 5:  # Need at least 5 parts: Mods/[letter]/[mod_name]/[version]/[file] or Mods/[letter]/[mod_name]/[version]/[platform]/[file]
                category_name = parts[0].lower()
                if category_name == 'mods':
                    # All letters and numbers contain actual mods - they're just for sorting
                    # No need to skip any of them
                    filtered_lines.append(line)
        
        for line in filtered_lines:
            parts = line.split('/')
            if len(parts) >= 3:
                category = parts[0]
                categories.add(category)
                
                if len(parts) >= 3:
                    mod_name = parts[2]  # Actual mod name is the third part
                    # Properly capitalize mod name
                    mod_name_capitalized = ' '.join(word.capitalize() for word in mod_name.split())
                    mods.add(mod_name_capitalized)

        self.stdout.write(f"Would create {len(categories)} categories (Mods only):")
        for category in sorted(categories):
            self.stdout.write(f"  - {category}")
        
        self.stdout.write(f"Would create {len(mods)} mods")
        
        # Show some examples
        self.stdout.write("\nExample mods:")
        for i, mod_name in enumerate(sorted(mods)[:10]):
            self.stdout.write(f"  - {mod_name}")
            if i >= 9:
                break

    def _import_mods(self, lines):
        """Import the mod data into the database"""
        categories_created = 0
        mods_created = 0
        versions_created = 0
        
        # Track what we've seen to avoid duplicates
        seen_categories = set()
        seen_mods = set()
        
        # Filter to only include mods (exclude addons, server software, etc.)
        filtered_lines = []
        for line in lines:
            parts = line.split('/')
            if len(parts) >= 5:  # Need at least 5 parts: Mods/[letter]/[mod_name]/[version]/[file] or Mods/[letter]/[mod_name]/[version]/[platform]/[file]
                category_name = parts[0].lower()
                if category_name == 'mods':
                    # All letters and numbers contain actual mods - they're just for sorting
                    # No need to skip any of them
                    filtered_lines.append(line)
        
        self.stdout.write(f"Filtered to {len(filtered_lines)} mod entries (excluding addons and server software)")
        
        with transaction.atomic():
            for i, line in enumerate(filtered_lines):
                if i % 1000 == 0:
                    self.stdout.write(f"Processing entry {i + 1}/{len(filtered_lines)}...")
                
                parts = line.split('/')
                if len(parts) < 3:
                    continue
                
                # Parse the structure: Mods/[letter]/[mod_name]/[version]/[platform]/[file]
                category_name = parts[0]  # "Mods"
                letter_folder = parts[1]  # "0", "A", "B", etc. (just for sorting)
                mod_name = parts[2]       # Actual mod name
                
                # Determine platform based on the platform folder (if it exists)
                platform = None
                
                # Check if there's a platform folder (Client, Server, Bukkit, etc.)
                # Structure could be: Mods/0/mod_name/version/file OR Mods/0/mod_name/version/platform/file
                if len(parts) > 4:  # Mods/0/mod_name/version/platform/file
                    platform_folder = parts[4].lower()
                    if platform_folder in ['server', 'client', 'bukkit', 'spigot', 'forge', 'fabric']:
                        platform = parts[4].title()
                # If no platform folder, use the default platform detection from file path
                
                # Properly capitalize mod name (e.g., "abyssal craft" → "Abyssal Craft")
                mod_name_capitalized = ' '.join(word.capitalize() for word in mod_name.split())
                
                # Create or get mod (with README content as description)
                mod_key = mod_name_capitalized
                if mod_key not in seen_mods:
                    # Try to fetch README content for description
                    readme_content = None
                    try:
                        # Create a temporary mod object to use the fetch_readme_content method
                        temp_mod = Mod(name=mod_name_capitalized)
                        # We'll need to get the mod folder path from the current line
                        mod_folder = f"{category_name}/{letter_folder}/{mod_name}"
                        readme_content = self._fetch_readme_content(mod_folder)
                    except Exception:
                        pass
                    
                    mod, created = Mod.objects.get_or_create(
                        name=mod_name_capitalized,
                        defaults={'description': readme_content or ''}
                    )
                    if created:
                        mods_created += 1
                    seen_mods.add(mod_key)
                else:
                    mod = Mod.objects.get(name=mod_name_capitalized)
                
                # Check if this URL already exists to prevent reimporting
                if ModVersion.objects.filter(file_path=line).exists():
                    continue  # Skip if already imported
                
                # Create version
                version_info = self._parse_version_info(parts, line)
                version, created = ModVersion.objects.get_or_create(
                    mod=mod,
                    file_path=line,
                    defaults=version_info
                )
                if created:
                    versions_created += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Import completed!\n"
                f"Categories created: {categories_created}\n"
                f"Mods created: {mods_created}\n"
                f"Versions created: {versions_created}"
            )
        )

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
                r'^(\d+\.\d+\.\d+[ab]?\d*)$',  # 1.2.3, 1.2.3a, 1.2.3b, 1.2.3a1, 1.2.3b2
                r'^(\d+\.\d+[ab]?\d*)$',       # 1.2, 1.2a, 1.2b, 1.2a1, 1.2b2
                r'^mc(\d+\.\d+\.\d+[ab]?\d*)$', # mc1.2.3, mc1.2.3a, mc1.2.3b
                r'^mc(\d+\.\d+[ab]?\d*)$',     # mc1.2, mc1.2a, mc1.2b
            ]
            
            for pattern in patterns:
                match = re.search(pattern, minecraft_version_folder)
                if match:
                    return match.group(1)
        
        # If not found in the expected position, try to find it anywhere in the path
        patterns = [
            r'(\d+\.\d+\.\d+[ab]?\d*)',  # 1.2.3, 1.2.3a, 1.2.3b, 1.2.3a1, 1.2.3b2
            r'(\d+\.\d+[ab]?\d*)',       # 1.2, 1.2a, 1.2b, 1.2a1, 1.2b2
            r'mc(\d+\.\d+\.\d+[ab]?\d*)', # mc1.2.3, mc1.2.3a, mc1.2.3b
            r'mc(\d+\.\d+[ab]?\d*)',     # mc1.2, mc1.2a, mc1.2b
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
    
    def _fetch_readme_content(self, mod_folder):
        """Fetch README content from the bucket for a given mod folder using FilesIndexWithMeta.txt"""
        import requests
        
        # Extract mod name from folder path
        parts = mod_folder.split('/')
        if len(parts) < 3:
            return None
            
        mod_name = parts[2]  # The actual mod name
        
        # Get README.md location from FilesIndexWithMeta.txt
        readme_path = self._find_readme_in_meta_file(mod_name)
        
        if readme_path:
            try:
                url = f"https://mcmodarchive.femtopedia.de/{readme_path}"
                response = requests.get(url, timeout=10)
                if response.status_code == 200:
                    content = response.text
                    
                    # Clean up the content (remove HTML if present, limit length)
                    if len(content) > 2000:
                        content = content[:2000] + "..."
                    
                    return content
                    
            except Exception:
                pass
        
        return None
    
    def _find_readme_in_meta_file(self, mod_name):
        """Find README.md file path for a mod in FilesIndexWithMeta.txt"""
        import requests
        
        try:
            meta_url = "https://mcmodarchive.femtopedia.de/FilesIndexWithMeta.txt"
            response = requests.get(meta_url, timeout=30)
            
            if response.status_code == 200:
                lines = response.text.split('\n')
                
                # Look for README.md files in the mod's folder
                for line in lines:
                    if 'README.md' in line and mod_name.lower() in line.lower():
                        # Extract the file path
                        parts = line.split('/')
                        if len(parts) >= 3:
                            # Check if this is the right mod folder
                            if parts[2].lower() == mod_name.lower():
                                return line.strip()
            
        except Exception:
            pass
        
        return None