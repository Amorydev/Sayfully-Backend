"""Xuất OpenAPI schema ra file JSON để sinh client Dart (Flutter) + TypeScript (Next.js)."""

import json

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Xuất OpenAPI schema (JSON) cho sinh client."

    def add_arguments(self, parser):
        parser.add_argument("--output", default="openapi.json")

    def handle(self, *args, **opts):
        from config.api import api

        schema = api.get_openapi_schema()
        with open(opts["output"], "w", encoding="utf-8") as f:
            json.dump(schema, f, ensure_ascii=False, indent=2)
        self.stdout.write(
            self.style.SUCCESS(
                f"Đã xuất {len(schema['paths'])} path → {opts['output']}. "
                "Sinh client: openapi-generator-cli (dart-dio / typescript-fetch)."
            )
        )
