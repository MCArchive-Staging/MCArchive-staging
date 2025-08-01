from django.contrib import admin
from django.utils.html import format_html
from .models import ModCategory, Mod, ModVersion


@admin.register(ModCategory)
class ModCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'mod_count', 'created_at']
    search_fields = ['name', 'description']
    ordering = ['name']
    
    def mod_count(self, obj):
        return obj.mods.count()
    mod_count.short_description = 'Mod Count'


@admin.register(Mod)
class ModAdmin(admin.ModelAdmin):
    list_display = ['name', 'category', 'author', 'version_count', 'created_at']
    list_filter = ['category', 'created_at']
    search_fields = ['name', 'description', 'author']
    ordering = ['name']
    readonly_fields = ['version_count_display']
    
    def version_count_display(self, obj):
        return obj.version_count
    version_count_display.short_description = 'Version Count'


@admin.register(ModVersion)
class ModVersionAdmin(admin.ModelAdmin):
    list_display = ['mod', 'version_number', 'platform', 'minecraft_version', 'file_name', 'download_link']
    list_filter = ['platform', 'minecraft_version', 'created_at', 'mod__category']
    search_fields = ['mod__name', 'file_name', 'version_number']
    ordering = ['-created_at']
    readonly_fields = ['download_link']
    
    def download_link(self, obj):
        if obj.get_download_url():
            return format_html(
                '<a href="{}" target="_blank" class="button">Download</a>',
                obj.get_download_url()
            )
        return '-'
    download_link.short_description = 'Download'
