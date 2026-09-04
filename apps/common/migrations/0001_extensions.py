"""Bật extension Postgres cần cho tìm kiếm trigram (từ điển) — phải chạy TRƯỚC content."""
from django.contrib.postgres.operations import BtreeGinExtension, TrigramExtension
from django.db import migrations


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [TrigramExtension(), BtreeGinExtension()]
