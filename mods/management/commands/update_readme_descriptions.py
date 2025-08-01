from django.core.management.base import BaseCommand
from django.db import transaction
from mods.models import Mod
import requests
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import time


class Command(BaseCommand):
    help = 'Update mod descriptions with README content from the bucket'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be updated without making changes',
        )
        parser.add_argument(
            '--mod-name',
            type=str,
            help='Update only a specific mod by name',
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Show detailed logging',
        )
        parser.add_argument(
            '--workers',
            type=int,
            default=10,
            help='Number of worker threads (default: 10)',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        mod_name = options.get('mod_name')
        verbose = options.get('verbose')
        workers = options.get('workers')
        
        if mod_name:
            mods = Mod.objects.filter(name__icontains=mod_name)
        else:
            mods = Mod.objects.all()
        
        total_mods = mods.count()
        updated_count = 0
        error_count = 0
        no_readme_count = 0
        
        self.stdout.write(f"Starting README description update for {total_mods} mods using {workers} workers...")
        
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - No changes will be made"))
        
        # Convert to list for threading
        mod_list = list(mods)
        
        # Thread-safe counters
        counters = {
            'updated': 0,
            'errors': 0,
            'no_readme': 0,
            'processed': 0
        }
        lock = threading.Lock()
        
        def process_mod(mod):
            nonlocal counters
            result = {'mod': mod, 'success': False, 'content': None, 'error': None}
            
            try:
                readme_content = self._fetch_readme_content_for_mod(mod)
                
                if readme_content:
                    result['success'] = True
                    result['content'] = readme_content
                else:
                    result['success'] = False
                    
            except Exception as e:
                result['error'] = str(e)
            
            # Update counters thread-safely
            with lock:
                counters['processed'] += 1
                if result['error']:
                    counters['errors'] += 1
                elif result['success']:
                    counters['updated'] += 1
                else:
                    counters['no_readme'] += 1
                
                # Progress logging
                if verbose and counters['processed'] % 50 == 0:
                    self.stdout.write(f"Progress: {counters['processed']}/{total_mods} mods processed")
            
            return result
        
        start_time = time.time()
        
        # Process mods with ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=workers) as executor:
            # Submit all tasks
            future_to_mod = {executor.submit(process_mod, mod): mod for mod in mod_list}
            
            # Process completed tasks
            for future in as_completed(future_to_mod):
                result = future.result()
                mod = result['mod']
                
                if result['error']:
                    if verbose:
                        self.stdout.write(self.style.ERROR(f"  ✗ Error processing '{mod.name}': {result['error']}"))
                elif result['success']:
                    if not dry_run:
                        # Update the mod in the database
                        mod.description = result['content']
                        mod.save(update_fields=['description'])
                    
                    if verbose:
                        status = "Would update" if dry_run else "Updated"
                        self.stdout.write(f"  ✓ {status} '{mod.name}' with README content ({len(result['content'])} chars)")
                else:
                    if verbose:
                        self.stdout.write(f"  - No README found for '{mod.name}'")
        
        end_time = time.time()
        duration = end_time - start_time
        
        # Summary
        self.stdout.write("")
        self.stdout.write("=" * 50)
        self.stdout.write("SUMMARY:")
        self.stdout.write(f"  Total mods processed: {counters['processed']}")
        self.stdout.write(f"  Successfully updated: {counters['updated']}")
        self.stdout.write(f"  No README found: {counters['no_readme']}")
        self.stdout.write(f"  Errors: {counters['errors']}")
        self.stdout.write(f"  Processing time: {duration:.2f} seconds")
        self.stdout.write(f"  Average time per mod: {duration/counters['processed']:.3f} seconds")
        
        if not dry_run:
            self.stdout.write(
                self.style.SUCCESS(f"Successfully updated {counters['updated']} mods with README content")
            )
        else:
            self.stdout.write(self.style.WARNING("Dry run completed. Use --dry-run=False to apply changes."))
    
    def _fetch_readme_content_for_mod(self, mod):
        """Fetch README content for a specific mod using FilesIndexWithMeta.txt"""
        # Get the mod's folder path from the first version
        first_version = mod.versions.first()
        if not first_version:
            return None
            
        # Extract mod folder path: Mods/[letter]/[mod_name]/
        file_path = first_version.file_path
        parts = file_path.split('/')
        if len(parts) < 3:
            return None
            
        mod_folder = '/'.join(parts[:3])  # Mods/[letter]/[mod_name]
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
                else:
                    # Don't log HTTP errors in threaded version to avoid spam
                    pass
                    
            except Exception as e:
                # Don't log individual errors in threaded version to avoid spam
                pass
        
        return None
    
    def _find_readme_in_meta_file(self, mod_name):
        """Find README.md file path for a mod in FilesIndexWithMeta.txt"""
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
            else:
                # Don't log HTTP errors in threaded version to avoid spam
                pass
            
        except Exception as e:
            # Don't log individual errors in threaded version to avoid spam
            pass
        
        return None 