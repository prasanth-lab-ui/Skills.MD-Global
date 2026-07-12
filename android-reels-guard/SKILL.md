---
name: android-reels-guard
description: >-
  Designs and implements an Android AccessibilityService-based feature inside
  a custom launcher to block and count short-form content (Reels / Shorts /
  Spotlight) on Instagram, YouTube, and Snapchat.  Use when the user says
  "block Instagram reels", "block YouTube shorts", "count reels in my Android
  launcher", "partial block after N reels", "block reels after 10 PM",
  "add digital wellbeing feature to launcher", or similar.  Do NOT use for
  iOS, for blocking non-short-form content, or for general app-blocking
  without reel detection.
---

# Android Reels Guard — Skill

## 1. Overview

Build a launcher-integrated module that:

1. **Counts** reels / shorts consumed in Instagram, YouTube, Snapchat.  
2. **Blocks** short-form content:
   - **Fully** — entire app is blocked (launcher-level + accessibility-level).
   - **Partially** — app opens but Reels/Shorts section is blocked:
     - after a daily reel count limit, or
     - after a time-of-day threshold (e.g. 10 PM).

### What you need

| Component | Role |
|---|---|
| `ReelsGuardAccessibilityService` | Detects Reels/Shorts screens, increments counters, enforces blocks |
| `ScreenDetector` | View-hierarchy heuristics per app |
| `ShortCounterManager` | Counts unique shorts viewed |
| `RuleEngine` | Decides block / allow based on rules |
| `UsageTracker` | `UsageStatsManager` wrapper for total app time |
| `ReelsGuardRepository` + Room | Persists daily counts and per-app rules |
| `BlockOverlayController` | Optional full-screen overlay explaining the block |
| `ReelsGuardSettingsViewModel` + Compose UI | User-facing configuration |
| Launcher icon hook | Pre-launch check before opening target apps |

---

## 2. Step-by-Step Build Workflow

> **Rule:** Always implement in this order. Each step builds on the previous.

### Step 1 — Project setup

1. Add permissions to `AndroidManifest.xml`:
   - `android.permission.SYSTEM_ALERT_WINDOW`
   - `android.permission.PACKAGE_USAGE_STATS` (normal + user grants in Settings)

2. Declare the accessibility service in the manifest (see `reference.md` §1).

3. Create `res/xml/accessibility_service_reels_guard.xml` with:
   - `canRetrieveWindowContent="true"`
   - `canPerformGestures="true"`
   - `accessibilityEventTypes="typeAllMask"`

4. Add Room dependency in `build.gradle` (app): `androidx.room:room-runtime`, `room-ktx`, `kapt room-compiler`.

5. Run `scripts/validate_manifest.py` to confirm all permissions and service declarations are present.

### Step 2 — Room persistence layer

1. Create entities: `ShortUsage` (daily count) and `AppRulesEntity` (per-app config).
2. Create DAOs: `ShortUsageDao`, `AppRulesDao`.
3. Create `ReelsGuardDatabase` singleton.
4. Create `ReelsGuardRepository` with methods:
   - `incrementShortCount(pkg)`, `getShortCountToday(pkg)`
   - `getAppRules(pkg)`, `saveAppRules(rules)`
5. Run `scripts/generate_room_schema.py` to output the schema JSON for migrations.

### Step 3 — AccessibilityService skeleton

1. Implement `ReelsGuardAccessibilityService` extending `AccessibilityService`.
2. In `onAccessibilityEvent`:
   - Filter for target packages.
   - Get `rootInActiveWindow`.
   - Call `ScreenDetector.detect(pkg, root)`.
   - If `screenType.isShortForm`, call `ShortCounterManager.onShortScreenVisible(pkg, root)`.
   - Call `RuleEngine.evaluate(pkg, screenType)`.
   - If `decision.shouldBlock`, call `performBlock(decision)`.
3. `performBlock`: `performGlobalAction(GLOBAL_ACTION_HOME)` + optional overlay.

### Step 4 — Discover view-tree markers (CRITICAL)

1. Add a debug logger `logNodeTree(root, 0)` (see `reference.md` §3).
2. Enable logging in debug builds only.
3. Open each target app, navigate to Reels/Shorts/Spotlight, scroll a few items.
4. Capture Logcat filtered by `ReelsGuardTree`.
5. Identify stable markers per app:
   - **Resource IDs** that only appear on short-form screens.
   - **Text labels** ("Shorts", "Reels", "Spotlight").
   - **Layout patterns** (full-screen video + vertical side controls).
6. Update `ScreenDetector` heuristics with real IDs.
7. Repeat for counting: find a field that changes per short (title, contentDescription).

> **Example output** (YouTube Shorts detection after tree inspection):
> ```kotlin
> private fun detectYouTube(root: AccessibilityNodeInfo): ScreenType {
>     val panel = findById(root, "com.google.android.youtube:id/shorts_control_panel")
>     val player = findById(root, "com.google.android.youtube:id/shorts_video_player")
>     val isShorts = panel != null && player != null
>     return ScreenType(isShorts, if (isShorts) "YouTubeShorts" else "YouTubeOther")
> }
> ```

### Step 5 — ScreenDetector implementation

Implement per-app detection using the IDs discovered in Step 4:
- `detectYouTube(root)` → Shorts vs normal
- `detectInstagram(root)` → Reels vs normal
- `detectSnapchat(root)` → Spotlight vs normal

Provide fallback heuristics: text-based + layout-pattern-based (not just IDs alone).

### Step 6 — ShortCounterManager

1. Maintain `lastShortIdPerApp: MutableMap<String, String?>`.
2. On each short-form screen event:
   - Derive `newId` from a stable field (title / contentDescription / index).
   - If `newId != lastId`, increment count in DB.
3. Reset counters at midnight (use `WorkManager` or check `dateEpochDay` on each access).

### Step 7 — RuleEngine

Implement rules in priority order:
1. `fullBlock` → block everything.
2. Time window: if `screenType.isShortForm && hour >= blockedAfterHour` → block.
3. Count limit: if `screenType.isShortForm && countToday >= maxShortsPerDay` → block.
4. Usage time: if `minutesToday >= maxMinutesPerDay` → block entire app.

Return `RuleDecision(shouldBlock, reason)`.

### Step 8 — UsageTracker

1. Wrap `UsageStatsManager`.
2. `getUsageMinutesToday(pkg)`: query `INTERVAL_DAILY`, sum `totalTimeInForeground`.
3. Before first use, redirect user to `Settings.ACTION_USAGE_ACCESS_SETTINGS`.

### Step 9 — BlockOverlayController (optional)

1. Check `Settings.canDrawOverlays(context)`.
2. If not granted, deep-link to `ACTION_MANAGE_OVERLAY_PERMISSION`.
3. Show a `TYPE_APPLICATION_OVERLAY` view with a message (e.g. "Reels blocked — limit reached").

### Step 10 — Launcher integration

1. In app-icon click handler:
   - Check `repo.getAppRules(pkg)` and `usageTracker.getUsageMinutesToday(pkg)`.
   - If `fullBlock || minutesToday >= maxMinutesPerDay`, show `AppBlockedActivity`.
   - Otherwise launch normally; accessibility service handles Reels-level blocks.

### Step 11 — Compose settings UI

1. Create `ReelsGuardSettingsViewModel` with `StateFlow<AppRules>`.
2. Create `ReelsGuardSettingsScreen` with:
   - Switch: "Fully block app"
   - Slider: "Max reels per day"
   - Slider: "Block reels after hour"
   - Slider: "Max minutes per day"
3. Wire to `ReelsGuardSettingsActivity` that receives `pkg` extra.

### Step 12 — Permissions flow

On first launch of the feature:
1. Check if accessibility service is enabled; if not, prompt with `Settings.ACTION_ACCESSIBILITY_SETTINGS`.
2. Check usage access; if not, prompt with `Settings.ACTION_USAGE_ACCESS_SETTINGS`.
3. Check overlay permission (if using overlays); if not, prompt with `ACTION_MANAGE_OVERLAY_PERMISSION`.

---

## 3. Target App Packages

| App | Package | Short-form section |
|---|---|---|
| YouTube | `com.google.android.youtube` | Shorts |
| Instagram | `com.instagram.android` | Reels |
| Snapchat | `com.snapchat.android` | Spotlight |

---

## 4. Key Rules & Edge Cases

- **App updates break IDs.** App updates can change resource IDs. Always have fallback heuristics (text labels + layout patterns). Re-test after target app updates.
- **AccessibilityNodeInfo lifecycle.** Treat nodes as snapshots — do not cache them across events.
- **Battery.** Keep `onAccessibilityEvent` lightweight. Only process target packages. Skip heavy tree walks for non-target apps.
- **Thread safety.** Room DAOs should use suspend functions or run on a background dispatcher. The accessibility service runs on the main thread — offload DB writes.
- **Counter accuracy.** Counting reels is heuristic, not exact. Accept ±10% error. The goal is behavioral intervention, not analytics.
- **No true firewall.** Android does not provide a true "block app from opening" API for normal apps. Blocking is achieved via:
  - Launcher-level: intercept icon click.
  - Accessibility-level: detect foreground app and perform `GLOBAL_ACTION_HOME`.
- **TalkBack conflict.** If the user also uses TalkBack, your service coexists but events are shared. Test with TalkBack enabled.
- **Service restart.** Accessibility services are restarted by the system if killed. Reinitialize state in `onServiceConnected()`.
- **Dark mode / different locales.** Text-based detection should use `contains(text, ignoreCase = true)` and match locale-specific labels when possible.

---

## 5. Testing Checklist

- [ ] Accessibility service enabled and receiving events for target packages.
- [ ] `logNodeTree` outputs the full hierarchy for each target app's short-form screen.
- [ ] `ScreenDetector` correctly distinguishes Shorts/Reels vs normal feed.
- [ ] Counter increments on each new short, not on every event.
- [ ] RuleEngine blocks after N reels.
- [ ] RuleEngine blocks after time threshold.
- [ ] `GLOBAL_ACTION_HOME` fires and exits the app.
- [ ] Overlay appears (if enabled) with correct reason.
- [ ] Usage access permission requested and granted.
- [ ] Settings screen saves rules to Room and they take effect immediately.
- [ ] Launcher icon click is intercepted when full-block or time-limit is active.
- [ ] Counters reset at midnight.
- [ ] Battery usage is acceptable over a full day.

---

## 6. File structure

```
reels-guard/
├── SKILL.md                      # this file
├── reference.md                  # deep technical reference
└── scripts/
    ├── validate_manifest.py      # check manifest permissions & service declaration
    ├── generate_room_schema.py   # emit schema JSON for Room migrations
    └── log_node_tree_template.py # template for accessibility tree logging
```

Read `reference.md` for:
- Full manifest XML
- Accessibility service config XML
- Complete Kotlin source for all components
- Compose settings screen code
- Permission flow code
- Debug tree-logging utility

---

## 7. Quick reference — decision flow

```
User opens Instagram
    ├─ Launcher check: fullBlock? → show blocked screen
    ├─ Launcher check: minutesToday >= max? → show blocked screen
    └─ Launch app
         ├─ Accessibility detects screen
         │    ├─ Not Reels → allow
         │    └─ Is Reels
         │         ├─ hour >= blockedAfterHour? → HOME action
         │         ├─ countToday >= maxShorts? → HOME action
         │         ├─ new short detected → increment counter
         │         └─ allow
         └─ Normal usage continues
```
