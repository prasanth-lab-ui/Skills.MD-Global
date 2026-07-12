#!/usr/bin/env python3
"""
Validate AndroidManifest.xml for Reels Guard feature.
Checks for required permissions and service declarations.
Usage: python3 validate_manifest.py /path/to/AndroidManifest.xml
"""

import sys
import xml.etree.ElementTree as ET

REQUIRED_PERMISSIONS = [
    "android.permission.SYSTEM_ALERT_WINDOW",
    "android.permission.PACKAGE_USAGE_STATS",
]

REQUIRED_SERVICE = {
    "name_suffix": "ReelsGuardAccessibilityService",
    "permission": "android.permission.BIND_ACCESSIBILITY_SERVICE",
    "action": "android.accessibilityservice.AccessibilityService",
}

def validate(manifest_path):
    tree = ET.parse(manifest_path)
    root = tree.getroot()
    ns = "http://schemas.android.com/apk/res/android"
    errors = []
    warnings = []

    declared_perms = set()
    for perm in root.findall(".//uses-permission"):
        name = perm.get("{" + ns + "}name", "")
        declared_perms.add(name)

    for req in REQUIRED_PERMISSIONS:
        if req not in declared_perms:
            errors.append("MISSING permission: " + req)

    services = root.findall(".//service")
    found_service = False
    for svc in services:
        svc_name = svc.get("{" + ns + "}name", "")
        svc_perm = svc.get("{" + ns + "}permission", "")
        if REQUIRED_SERVICE["name_suffix"] in svc_name:
            found_service = True
            if svc_perm != REQUIRED_SERVICE["permission"]:
                errors.append("Service '" + svc_name + "' missing permission '" + REQUIRED_SERVICE["permission"] + "'")
            actions = svc.findall(".//intent-filter/action")
            action_names = [a.get("{" + ns + "}name", "") for a in actions]
            if REQUIRED_SERVICE["action"] not in action_names:
                errors.append("Service '" + svc_name + "' missing intent-filter action '" + REQUIRED_SERVICE["action"] + "'")
            metas = svc.findall(".//meta-data")
            has_meta = any(m.get("{" + ns + "}name") == "android.accessibilityservice" for m in metas)
            if not has_meta:
                warnings.append("Service '" + svc_name + "' missing meta-data for android.accessibilityservice config")

    if not found_service:
        errors.append("MISSING service: no service with name containing '" + REQUIRED_SERVICE["name_suffix"] + "' found")

    print("=" * 60)
    print("Reels Guard - Manifest Validation")
    print("=" * 60)
    if errors:
        print("\nERRORS (" + str(len(errors)) + "):")
        for e in errors:
            print("   ERROR: " + e)
    if warnings:
        print("\nWARNINGS (" + str(len(warnings)) + "):")
        for w in warnings:
            print("   WARN: " + w)
    if not errors and not warnings:
        print("\nAll checks passed!")
    print("=" * 60)
    return len(errors) == 0

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 validate_manifest.py <path/to/AndroidManifest.xml>")
        sys.exit(1)
    ok = validate(sys.argv[1])
    sys.exit(0 if ok else 1)
