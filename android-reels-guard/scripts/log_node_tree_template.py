#!/usr/bin/env python3
"""
Generate a Kotlin snippet for logging the AccessibilityNodeInfo tree.
Outputs a .kt file with NodeTreeLogger object.
Usage: python3 log_node_tree_template.py [--output NodeTreeLogger.kt]
"""

import argparse

KOTLIN_CODE = []
KOTLIN_CODE.append("package com.your.launcher.reelsguard")
KOTLIN_CODE.append("")
KOTLIN_CODE.append("import android.view.accessibility.AccessibilityNodeInfo")
KOTLIN_CODE.append("")
KOTLIN_CODE.append("/**")
KOTLIN_CODE.append(" * Debug utility: logs the entire AccessibilityNodeInfo tree.")
KOTLIN_CODE.append(" * Enable only in debug builds.")
KOTLIN_CODE.append(" * Filter Logcat: adb logcat -s ReelsGuardTree")
KOTLIN_CODE.append(" */")
KOTLIN_CODE.append("object NodeTreeLogger {")
KOTLIN_CODE.append("")
KOTLIN_CODE.append("    private const val TAG = \"ReelsGuardTree\"")
KOTLIN_CODE.append("")
KOTLIN_CODE.append("    fun log(node: AccessibilityNodeInfo?, depth: Int = 0) {")
KOTLIN_CODE.append("        if (node == null) {")
KOTLIN_CODE.append("            android.util.Log.d(TAG, \"  \".repeat(depth) + \"[null node]\")
KOTLIN_CODE.append("            return")
KOTLIN_CODE.append("        }")
KOTLIN_CODE.append("        val indent = \"  \".repeat(depth)")
KOTLIN_CODE.append("        val text = node.text?.toString()?.take(80) ?: \"\"")
KOTLIN_CODE.append("        val desc = node.contentDescription?.toString()?.take(80) ?: \"\"")
KOTLIN_CODE.append("        val viewId = node.viewIdResourceName ?: \"\"")
KOTLIN_CODE.append("        val clazz = node.className?.toString() ?: \"\"")
KOTLIN_CODE.append("        android.util.Log.d(TAG, indent + \"[\" + depth + \"] \" + clazz + \" | id=\" + viewId + \" | text=\\\" \" + text + \" \\\"\" + \" | desc=\\\" \" + desc + \" \\\"\" + \" | children=\" + node.childCount)")
KOTLIN_CODE.append("        for (i in 0 until node.childCount) {")
KOTLIN_CODE.append("            log(node.getChild(i), depth + 1)")
KOTLIN_CODE.append("        }")
KOTLIN_CODE.append("    }")
KOTLIN_CODE.append("")
KOTLIN_CODE.append("    fun logCompact(node: AccessibilityNodeInfo?, depth: Int = 0) {")
KOTLIN_CODE.append("        if (node == null) return")
KOTLIN_CODE.append("        val indent = \"  \".repeat(depth)")
KOTLIN_CODE.append("        val text = node.text?.toString() ?: \"\"")
KOTLIN_CODE.append("        val desc = node.contentDescription?.toString() ?: \"\"")
KOTLIN_CODE.append("        val viewId = node.viewIdResourceName ?: \"\"")
KOTLIN_CODE.append("        if (viewId.isNotEmpty() || text.isNotEmpty() || desc.isNotEmpty()) {")
KOTLIN_CODE.append("            android.util.Log.d(\"ReelsGuardCompact\", indent + \" id=\" + viewId + \" text=\\\" \" + text + \" \\\"\")
KOTLIN_CODE.append("        }")
KOTLIN_CODE.append("        for (i in 0 until node.childCount) {")
KOTLIN_CODE.append("            logCompact(node.getChild(i), depth + 1)")
KOTLIN_CODE.append("        }")
KOTLIN_CODE.append("    }")
KOTLIN_CODE.append("}")

def main():
    parser = argparse.ArgumentParser(description="Generate Kotlin AccessibilityNodeInfo tree logger")
    parser.add_argument("--output", "-o", default="NodeTreeLogger.kt", help="Output file path")
    args = parser.parse_args()
    with open(args.output, "w") as f:
        f.write("\n".join(KOTLIN_CODE))
    print("Kotlin logger written to " + args.output)
    print("  Paste into your reelsguard package.")
    print("  Usage: NodeTreeLogger.log(rootInActiveWindow, 0)")

if __name__ == "__main__":
    main()