from django.db import models
from django.utils import timezone
from django.utils.text import slugify
from datetime import timedelta


class ModCategory(models.Model):
    """Represents a category of mods (e.g., Addons, Mods)"""
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        verbose_name_plural = "Mod categories"
        ordering = ['name']
    
    def __str__(self):
        return self.name


class Mod(models.Model):
    """Represents a mod with its metadata"""
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True, blank=True)
    category = models.ForeignKey(ModCategory, on_delete=models.CASCADE, related_name='mods', null=True, blank=True)
    description = models.TextField(blank=True)
    author = models.CharField(max_length=100, blank=True)
    logo = models.TextField(blank=True)  # Base64 encoded logo
    archive_url = models.URLField(blank=True, help_text="Link to the mod's page on archive.org")
    relevance_count = models.PositiveIntegerField(default=0)  # Number of times mod page was accessed
    download_count = models.PositiveIntegerField(default=0)  # Number of times download was clicked
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['name']
        unique_together = ['name']
    
    def __str__(self):
        return self.name
    
    def save(self, *args, **kwargs):
        """Auto-generate slug if not provided"""
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)
    
    @property
    def latest_version(self):
        """Get the latest version of this mod"""
        return self.versions.order_by('-version_number').first()
    
    @property
    def version_count(self):
        """Get the total number of versions"""
        return self.versions.count()
    
    def fetch_readme_content(self):
        """Fetch README content from the bucket and use as description"""
        import requests
        import re
        
        # Common README file names to look for
        readme_files = ['README.md', 'readme.md', 'README.txt', 'readme.txt', 'README', 'readme']
        
        # Get the mod's folder path from the first version
        first_version = self.versions.first()
        if not first_version:
            return None
            
        # Extract mod folder path: Mods/[letter]/[mod_name]/
        file_path = first_version.file_path
        parts = file_path.split('/')
        if len(parts) < 3:
            return None
            
        mod_folder = '/'.join(parts[:3])  # Mods/[letter]/[mod_name]
        
        # Try to fetch README files
        base_url = "https://mcmodarchive.femtopedia.de/"
        
        for readme_file in readme_files:
            try:
                readme_path = f"{mod_folder}/{readme_file}"
                url = f"{base_url}{readme_path}"
                
                response = requests.get(url, timeout=10)
                if response.status_code == 200:
                    content = response.text
                    
                    # Clean up the content (remove HTML if present, limit length)
                    if len(content) > 2000:
                        content = content[:2000] + "..."
                    
                    return content
                    
            except Exception:
                continue
        
        return None


class ModVersion(models.Model):
    """Represents a specific version of a mod"""
    mod = models.ForeignKey(Mod, on_delete=models.CASCADE, related_name='versions')
    version_number = models.CharField(max_length=50)
    file_path = models.CharField(max_length=500)
    file_name = models.CharField(max_length=200)
    file_size = models.BigIntegerField(null=True, blank=True)
    minecraft_version = models.CharField(max_length=20, blank=True, null=True)
    platform = models.CharField(max_length=50, blank=True, null=True)  # Client, Server, Bukkit, etc.
    download_url = models.URLField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        ordering = ['-created_at']
        unique_together = ['mod', 'version_number', 'file_path']
    
    def __str__(self):
        return f"{self.mod.name} v{self.version_number}"
    
    def get_download_url(self):
        """Generate the full download URL"""
        if self.download_url:
            return self.download_url
        base_url = "https://eu2.contabostorage.com/f9f5ea7cee6e4089be6fd576f7af4a70:mcmodarchive/"
        return f"{base_url}{self.file_path}"


class ModView(models.Model):
    """Tracks all views for mods (accumulates over time)"""
    mod = models.ForeignKey(Mod, on_delete=models.CASCADE, related_name='ip_views')
    ip_address = models.GenericIPAddressField()
    viewed_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        ordering = ['-viewed_at']
    
    def __str__(self):
        return f"{self.mod.name} - {self.ip_address} - {self.viewed_at}"
    
    @classmethod
    def should_increment_relevance(cls, mod, ip_address):
        """Check if this IP should increment the relevance count (not in last 24 hours)"""
        cutoff_time = timezone.now() - timedelta(hours=24)
        
        # Check if this IP has viewed this mod in the last 24 hours
        recent_view = cls.objects.filter(
            mod=mod,
            ip_address=ip_address,
            viewed_at__gte=cutoff_time
        ).first()
        
        return recent_view is None
    
    @classmethod
    def record_view(cls, mod, ip_address):
        """Record a view for a mod from an IP address (always creates new record)"""
        # Always create a new view record
        view = cls.objects.create(
            mod=mod,
            ip_address=ip_address,
            viewed_at=timezone.now()
        )
        
        return True  # Always returns True since we always create a new record
