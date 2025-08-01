from django.urls import path
from . import views

app_name = 'mods'

urlpatterns = [
    path('', views.index, name='index'),
    path('browse/', views.browse_all, name='browse_all'),
    path('categories/', views.category_list, name='category_list'),
    path('api/search/', views.api_search, name='api_search'),
    path('logout/', views.logout_view, name='logout'),
    path('<str:mod_slug>/', views.mod_detail, name='mod_detail'),
    path('<str:mod_slug>/edit/', views.edit_mod, name='edit_mod'),
    path('<str:mod_slug>/version/<int:version_id>/edit/', views.edit_version, name='edit_version'),
    path('<str:mod_slug>/version/<int:version_id>/download/', views.download_version, name='download_version'),
] 