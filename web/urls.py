from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('', views.load_manual, name='load_manual'),
    path('chat/', views.chat, name='chat'),
    path('chat/stream/', views.chat_stream, name='chat_stream'),
    path('view_pdf/<str:filename>/', views.view_pdf, name='view_pdf'),
    path('login/', auth_views.LoginView.as_view(template_name='login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
]
