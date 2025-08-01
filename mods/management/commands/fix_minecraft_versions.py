from django.core.management.base import BaseCommand
from django.db import transaction
from mods.models import ModVersion


class Command(BaseCommand):
    help = 'Fix specific Minecraft versions by adding alpha/beta prefixes'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be updated without making changes',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        # Define the version fixes: old_version -> new_version
        version_fixes = {
            '1.6.6': 'b1.6.6',
            '1.7.3': 'b1.7.3', 
            '1.2.6': 'a1.2.6',
        }
        
        updated_count = 0
        
        if dry_run:
            self.stdout.write("DRY RUN - No changes will be made")
            self.stdout.write("Versions that would be updated:")
        
        with transaction.atomic():
            for old_version, new_version in version_fixes.items():
                # Find all mod versions with the old Minecraft version
                mod_versions = ModVersion.objects.filter(minecraft_version=old_version)
                
                if dry_run:
                    if mod_versions.exists():
                        self.stdout.write(f"  {old_version} -> {new_version}: {mod_versions.count()} versions")
                        for version in mod_versions[:5]:  # Show first 5 examples
                            self.stdout.write(f"    - {version.mod.name} v{version.version_number}")
                        if mod_versions.count() > 5:
                            self.stdout.write(f"    ... and {mod_versions.count() - 5} more")
                    else:
                        self.stdout.write(f"  {old_version} -> {new_version}: No versions found")
                else:
                    # Update the versions
                    count = mod_versions.update(minecraft_version=new_version)
                    if count > 0:
                        self.stdout.write(f"Updated {count} versions: {old_version} -> {new_version}")
                        updated_count += count
                    else:
                        self.stdout.write(f"No versions found for {old_version}")
        
        if not dry_run:
            self.stdout.write(
                self.style.SUCCESS(f"Successfully updated {updated_count} Minecraft versions")
            )
        else:
            self.stdout.write("Dry run completed. Use --dry-run=False to apply changes.") 