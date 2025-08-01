from django.shortcuts import render, get_object_or_404, redirect
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout
from django.contrib import messages
import json
import re
from .models import ModCategory, Mod, ModVersion, ModView


def index(request):
    """Main page showing site features"""
    context = {
        'total_mods': Mod.objects.count(),
        'total_versions': ModVersion.objects.count(),
    }
    return render(request, 'mods/index.html', context)


def browse_all(request):
    """Browse all mods with pagination and search"""
    # Get search and sort parameters
    search = request.GET.get('search', '')
    sort_by = request.GET.get('sort', 'relevance')  # Default to relevance
    
    mods = Mod.objects.all()
    
    if search:
        mods = mods.filter(
            Q(name__icontains=search) |
            Q(description__icontains=search) |
            Q(author__icontains=search)
        )
    
    # Always annotate version_count for template compatibility
    mods = mods.annotate(version_count_annotated=Count('versions'))
    
    # Sorting
    if sort_by == 'name':
        mods = mods.order_by('name')
    elif sort_by == 'newest':
        mods = mods.order_by('-created_at')
    elif sort_by == 'versions':
        mods = mods.order_by('-version_count_annotated')
    elif sort_by == 'relevance':
        mods = mods.order_by('-relevance_count')
    elif sort_by == 'downloads':
        mods = mods.order_by('-download_count')
    
    # Pagination
    paginator = Paginator(mods, 24)  # 24 mods per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'search': search,
        'sort_by': sort_by,
        'total_mods': paginator.count,
    }
    return render(request, 'mods/browse_all.html', context)


def category_list(request):
    """List all categories"""
    categories = ModCategory.objects.annotate(
        mod_count=Count('mods'),
        version_count=Count('mods__versions')
    ).order_by('-mod_count')
    
    context = {
        'categories': categories,
    }
    return render(request, 'mods/category_list.html', context)


def category_detail(request, category_slug):
    """Show mods in a specific category"""
    category = get_object_or_404(ModCategory, name__iexact=category_slug)
    
    # Get search parameters
    search = request.GET.get('search', '')
    sort_by = request.GET.get('sort', 'name')
    
    mods = Mod.objects.filter(category=category)
    
    if search:
        mods = mods.filter(
            Q(name__icontains=search) |
            Q(description__icontains=search)
        )
    
    # Always annotate version_count for template compatibility
    mods = mods.annotate(version_count_annotated=Count('versions'))
    
    # Sorting
    if sort_by == 'name':
        mods = mods.order_by('name')
    elif sort_by == 'newest':
        mods = mods.order_by('-created_at')
    elif sort_by == 'versions':
        mods = mods.order_by('-version_count_annotated')
    
    # Pagination
    paginator = Paginator(mods, 24)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'category': category,
        'page_obj': page_obj,
        'search': search,
        'sort_by': sort_by,
    }
    return render(request, 'mods/category_detail.html', context)


def mod_detail(request, mod_slug):
    """Show details of a specific mod"""
    mod = get_object_or_404(Mod, slug=mod_slug)
    
    # Get client IP address
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip_address = x_forwarded_for.split(',')[0].strip()
    else:
        ip_address = request.META.get('REMOTE_ADDR', '0.0.0.0')
    
    # Always record the view
    ModView.record_view(mod, ip_address)
    
    # Only increment relevance count if this IP hasn't viewed in the last 24 hours
    if ModView.should_increment_relevance(mod, ip_address):
        mod.relevance_count += 1
        mod.save(update_fields=['relevance_count'])
    
    # Get versions with pagination
    versions = mod.versions.all()
    paginator = Paginator(versions, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'mod': mod,
        'page_obj': page_obj,
    }
    return render(request, 'mods/mod_detail.html', context)


def search(request):
    """Search mods across all categories"""
    query = request.GET.get('q', '')
    category_filter = request.GET.get('category', '')
    sort_by = request.GET.get('sort', 'relevance')
    
    if not query:
        return render(request, 'mods/search.html', {'query': query})
    
    mods = Mod.objects.all()
    
    if category_filter:
        mods = mods.filter(category__name__iexact=category_filter)
    
    # Search in name, description, and author
    mods = mods.filter(
        Q(name__icontains=query) |
        Q(description__icontains=query) |
        Q(author__icontains=query)
    )
    
    # Always annotate version_count for template compatibility
    mods = mods.annotate(version_count_annotated=Count('versions'))
    
    # Sorting
    if sort_by == 'name':
        mods = mods.order_by('name')
    elif sort_by == 'newest':
        mods = mods.order_by('-created_at')
    elif sort_by == 'versions':
        mods = mods.order_by('-version_count_annotated')
    else:  # relevance - order by name similarity
        mods = mods.order_by('name')
    
    # Pagination
    paginator = Paginator(mods, 24)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Get categories for filter
    categories = ModCategory.objects.all()
    
    context = {
        'query': query,
        'page_obj': page_obj,
        'categories': categories,
        'selected_category': category_filter,
        'sort_by': sort_by,
        'result_count': paginator.count,
    }
    return render(request, 'mods/search.html', context)


@csrf_exempt
@require_http_methods(["POST"])
def api_search(request):
    """API endpoint for AJAX search"""
    try:
        data = json.loads(request.body)
        query = data.get('query', '')
        category = data.get('category', '')
        
        if not query:
            return JsonResponse({'results': [], 'count': 0})
        
        mods = Mod.objects.all()
        
        if category:
            mods = mods.filter(category__name__iexact=category)
        
        mods = mods.filter(
            Q(name__icontains=query) |
            Q(description__icontains=query)
        )
        
        # Always annotate version_count for template compatibility
        mods = mods.annotate(version_count=Count('versions'))[:10]  # Limit to 10 results for API
        
        results = []
        for mod in mods:
            results.append({
                'id': mod.id,
                'name': mod.name,
                'description': mod.description[:200] + '...' if len(mod.description) > 200 else mod.description,
                'version_count': mod.version_count,
                'url': f'/mods/{mod.slug}/',
            })
        
        return JsonResponse({
            'results': results,
            'count': len(results)
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
def edit_mod(request, mod_slug):
    """Edit mod details (name, logo and description)"""
    mod = get_object_or_404(Mod, slug=mod_slug)
    
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        author = request.POST.get('author', '').strip()
        description = request.POST.get('description', '')
        
        # Validate name
        if not name:
            messages.error(request, 'Mod name cannot be empty.')
            return redirect('mods:edit_mod', mod_slug=mod_slug)
        
        # Check if name already exists (excluding current mod)
        if name.lower() != mod.name.lower() and Mod.objects.filter(name__iexact=name).exists():
            messages.error(request, f'A mod with the name "{name}" already exists.')
            return redirect('mods:edit_mod', mod_slug=mod_slug)
        
        # Handle file upload if provided
        if 'logo_file' in request.FILES:
            uploaded_file = request.FILES['logo_file']
            if uploaded_file.content_type.startswith('image/'):
                import base64
                logo_data = base64.b64encode(uploaded_file.read()).decode('utf-8')
                mod.logo = f"data:{uploaded_file.content_type};base64,{logo_data}"
            else:
                messages.error(request, 'Please upload a valid image file.')
                return redirect('mods:edit_mod', mod_slug=mod_slug)
        
        # Update mod
        mod.name = name
        mod.author = author
        mod.description = description
        mod.save()
        
        messages.success(request, f'Mod "{mod.name}" updated successfully!')
        return redirect('mods:mod_detail', mod_slug=mod.slug)
    
    context = {
        'mod': mod,
    }
    return render(request, 'mods/edit_mod.html', context)

@login_required
def edit_version(request, mod_slug, version_id):
    """Edit version metadata for logged-in users"""
    mod = get_object_or_404(Mod, slug=mod_slug)
    version = get_object_or_404(ModVersion, id=version_id, mod=mod)
    
    if request.method == 'POST':
        # Update version metadata
        version.platform = request.POST.get('platform', '').strip()
        version.minecraft_version = request.POST.get('minecraft_version', '').strip()
        version.version_number = request.POST.get('version_number', '').strip()
        version.save()
        
        messages.success(request, f'Version {version.version_number} updated successfully!')
        return redirect('mods:mod_detail', mod_slug=mod_slug)
    
    return render(request, 'mods/edit_version.html', {
        'mod': mod,
        'version': version
    })

def download_version(request, mod_slug, version_id):
    """Handle download clicks and increment download count"""
    mod = get_object_or_404(Mod, slug=mod_slug)
    version = get_object_or_404(ModVersion, id=version_id, mod=mod)
    
    # Increment download count
    mod.download_count += 1
    mod.save(update_fields=['download_count'])
    
    # Redirect to the actual download URL
    return redirect(version.get_download_url())


def logout_view(request):
    """Custom logout view that handles GET requests"""
    logout(request)
    messages.success(request, 'You have been successfully logged out.')
    return redirect('mods:index')
