from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from core.models import UserProfile
from ..models import Purchase, PurchaseItem, Mill, Product, Payment, SaleItem, Sale, Broker
from django.db.models import Q, Sum, F, FloatField, ExpressionWrapper
from django.shortcuts import get_object_or_404
from django.db import transaction