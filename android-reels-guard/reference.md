# Android Reels Guard — Technical Reference

Deep technical document for implementing the reels-blocking feature in a custom Android launcher.

---

## §1. Manifest declarations

```xml
<!-- AndroidManifest.xml -->

<!-- Permissions -->
<uses-permission android:name="android.permission.SYSTEM_ALERT_WINDOW" />
<uses-permission
    android:name="android.permission.PACKAGE_USAGE_STATS"
    tools:ignore="ProtectedPermissions" />

<!-- Accessibility Service -->
<service
    android:name=".reelsguard.ReelsGuardAccessibilityService"
    android:permission="android.permission.BIND_ACCESSIBILITY_SERVICE"
    android:exported="true"
    android:label="@string/reels_guard_label">
    <intent-filter>
        <action android:name="android.accessibilityservice.AccessibilityService" />
    </intent-filter>
    <meta-data
        android:name="android.accessibilityservice"
        android:resource="@xml/accessibility_service_reels_guard" />
</service>
```

---

## §2. Accessibility service config XML

`res/xml/accessibility_service_reels_guard.xml`:

```xml
<accessibility-service xmlns:android="http://schemas.android.com/apk/res/android"
    android:description="@string/reels_guard_description"
    android:accessibilityEventTypes="typeAllMask"
    android:accessibilityFeedbackType="feedbackGeneric"
    android:accessibilityFlags="flagDefault"
    android:notificationTimeout="100"
    android:canRetrieveWindowContent="true"
    android:canPerformGestures="true"
    android:settingsActivity="com.your.launcher.ReelsGuardSettingsActivity" />
```

Key flags:
- `canRetrieveWindowContent="true"` — required to read the view hierarchy via `rootInActiveWindow`.
- `canPerformGestures="true"` — enables `performGlobalAction()` and `dispatchGesture()`.
- `typeAllMask` — receives all accessibility events (you filter by package in code).

---

## §3. Debug tree-logging utility

Temporary debug logger to discover view-hierarchy markers. Enable only in debug builds.

```kotlin
private fun logNodeTree(node: AccessibilityNodeInfo?, depth: Int) {
    if (node == null) return

    val indent = "  ".repeat(depth)
    val text = node.text?.toString() ?: ""
    val desc = node.contentDescription?.toString() ?: ""
    val viewId = node.viewIdResourceName ?: ""
    val clazz = node.className?.toString() ?: ""

    android.util.Log.d("ReelsGuardTree",
        "$indent$clazz=$clazz id=$viewId text=\"$text\" desc=\"$desc\"")

    for (i in 0 until node.childCount) {
        logNodeTree(node.getChild(i), depth + 1)
    }
}
```

Usage:
1. Call `logNodeTree(rootInActiveWindow, 0)` inside `onAccessibilityEvent` for target packages.
2. Open YouTube → Shorts, Instagram → Reels, Snapchat → Spotlight.
3. Filter Logcat: `adb logcat -s ReelsGuardTree`.
4. Identify stable resource IDs and text labels unique to short-form screens.

---

## §4. Complete source: ReelsGuardAccessibilityService

```kotlin
package com.your.launcher.reelsguard

import android.accessibilityservice.AccessibilityService
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo

class ReelsGuardAccessibilityService : AccessibilityService() {

    private lateinit var ruleEngine: RuleEngine
    private lateinit var shortCounter: ShortCounterManager

    override fun onServiceConnected() {
        super.onServiceConnected()
        val db = ReelsGuardDatabase.getInstance(applicationContext)
        val repo = ReelsGuardRepository(db.shortUsageDao(), db.appRulesDao())
        val usageTracker = UsageTracker(applicationContext)
        ruleEngine = RuleEngine(repo, usageTracker)
        shortCounter = ShortCounterManager(repo)
        BlockOverlayController.init(applicationContext)
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (event == null) return
        val pkg = event.packageName?.toString() ?: return
        if (!isTargetApp(pkg)) return

        val root = rootInActiveWindow ?: return

        val screenType = ScreenDetector.detect(pkg, root)

        if (screenType.isShortForm) {
            shortCounter.onShortScreenVisible(pkg, root)
        }

        val decision = ruleEngine.evaluate(pkg, screenType)
        if (decision.shouldBlock) {
            performBlock(decision)
        }
    }

    override fun onInterrupt() {}

    private fun isTargetApp(pkg: String): Boolean {
        return pkg == "com.google.android.youtube" ||
               pkg == "com.instagram.android" ||
               pkg == "com.snapchat.android"
    }

    private fun performBlock(decision: RuleDecision) {
        performGlobalAction(GLOBAL_ACTION_HOME)
        BlockOverlayController.show(reason = decision.reason)
    }
}
```

---

## §5. Complete source: ScreenDetector

```kotlin
package com.your.launcher.reelsguard

import android.view.accessibility.AccessibilityNodeInfo

data class ScreenType(
    val isShortForm: Boolean,
    val sectionName: String
)

object ScreenDetector {

    fun detect(pkg: String, root: AccessibilityNodeInfo): ScreenType {
        return when (pkg) {
            "com.google.android.youtube" -> detectYouTube(root)
            "com.instagram.android"      -> detectInstagram(root)
            "com.snapchat.android"       -> detectSnapchat(root)
            else -> ScreenType(false, "Unknown")
        }
    }

    // ── YouTube Shorts ──────────────────────────────────────────────
    private fun detectYouTube(root: AccessibilityNodeInfo): ScreenType {
        // Primary: resource IDs
        val panel  = findById(root, "com.google.android.youtube:id/shorts_control_panel")
        val player = findById(root, "com.google.android.youtube:id/shorts_video_player")

        // Fallback: text label + layout pattern
        val hasShortsLabel = findByText(root, "Shorts") != null

        val isShorts = (panel != null && player != null) ||
                       (hasShortsLabel && isVerticalVideoLayout(root))

        return ScreenType(isShortForm = isShorts,
            sectionName = if (isShorts) "YouTubeShorts" else "YouTubeOther")
    }

    // ── Instagram Reels ─────────────────────────────────────────────
    private fun detectInstagram(root: AccessibilityNodeInfo): ScreenType {
        val sideControls = findById(root, "com.instagram.android:id/reels_side_controls")
        val reelsLabel   = findByText(root, "Reels")

        val isReels = sideControls != null ||
                      (reelsLabel != null && isVerticalVideoLayout(root))

        return ScreenType(isShortForm = isReels,
            sectionName = if (isReels) "InstagramReels" else "InstagramOther")
    }

    // ── Snapchat Spotlight ──────────────────────────────────────────
    private fun detectSnapchat(root: AccessibilityNodeInfo): ScreenType {
        val spotlightLabel = findByText(root, "Spotlight")
        val isSpotlight = spotlightLabel != null

        return ScreenType(isShortForm = isSpotlight,
            sectionName = if (isSpotlight) "SnapchatSpotlight" else "SnapchatOther")
    }

    // ── Layout-pattern fallback ────────────────────────────────────
    private fun isVerticalVideoLayout(root: AccessibilityNodeInfo): Boolean {
        // Heuristic: look for a full-screen video node with vertical
        // icon stack on the right side (like/comment/share)
        // This is a simplified check; refine after tree inspection.
        val hasVideoView = root.className?.contains("VideoView") == true ||
                           findByText(root, "like") != null
        return hasVideoView
    }

    // ── Node-tree search helpers ───────────────────────────────────
    fun findByText(node: AccessibilityNodeInfo?, text: String): AccessibilityNodeInfo? {
        if (node == null) return null
        if (!node.text.isNullOrEmpty() &&
            node.text.toString().contains(text, ignoreCase = true)) {
            return node
        }
        for (i in 0 until node.childCount) {
            val child = node.getChild(i)
            val result = findByText(child, text)
            if (result != null) return result
        }
        return null
    }

    fun findById(node: AccessibilityNodeInfo?, viewId: String): AccessibilityNodeInfo? {
        if (node == null) return null
        if (node.viewIdResourceName == viewId) return node
        for (i in 0 until node.childCount) {
            val child = node.getChild(i)
            val result = findById(child, viewId)
            if (result != null) return result
        }
        return null
    }
}
```

---

## §6. Complete source: ShortCounterManager

```kotlin
package com.your.launcher.reelsguard

import android.view.accessibility.AccessibilityNodeInfo

class ShortCounterManager(private val repo: ReelsGuardRepository) {

    private val lastShortIdPerApp = mutableMapOf<String, String?>()

    fun onShortScreenVisible(pkg: String, root: AccessibilityNodeInfo) {
        val newId = deriveShortId(pkg, root)
        val lastId = lastShortIdPerApp[pkg]

        if (newId != null && newId != lastId) {
            lastShortIdPerApp[pkg] = newId
            repo.incrementShortCount(pkg)
        }
    }

    private fun deriveShortId(pkg: String, root: AccessibilityNodeInfo): String? {
        return when (pkg) {
            "com.google.android.youtube" -> {
                val titleNode = ScreenDetector.findById(root,
                    "com.google.android.youtube:id/title")
                titleNode?.text?.toString()
            }
            "com.instagram.android" -> {
                val descNode = ScreenDetector.findById(root,
                    "com.instagram.android:id/reel_caption")
                descNode?.contentDescription?.toString()
            }
            "com.snapchat.android" -> {
                val titleNode = ScreenDetector.findByText(root, "spotlight")
                titleNode?.text?.toString()
            }
            else -> null
        }
    }
}
```

---

## §7. Complete source: RuleEngine + data models

```kotlin
package com.your.launcher.reelsguard

import java.time.LocalTime

data class AppRules(
    val packageName: String,
    val maxShortsPerDay: Int?,
    val blockedAfterHour: Int?,
    val fullBlock: Boolean,
    val maxMinutesPerDay: Int?
)

data class RuleDecision(
    val shouldBlock: Boolean,
    val reason: String
)

class RuleEngine(
    private val repo: ReelsGuardRepository,
    private val usageTracker: UsageTracker
) {
    fun evaluate(pkg: String, screenType: ScreenType): RuleDecision {
        val rules = repo.getAppRules(pkg)
        val now = LocalTime.now()

        // 1) Full app block
        if (rules.fullBlock) {
            return RuleDecision(true, "full_block")
        }

        // 2) Reels/Shorts time window
        if (screenType.isShortForm && rules.blockedAfterHour != null &&
            now.hour >= rules.blockedAfterHour) {
            return RuleDecision(true, "time_reels_block")
        }

        // 3) Reels/Shorts count limit
        if (screenType.isShortForm && rules.maxShortsPerDay != null) {
            val count = repo.getShortCountToday(pkg)
            if (count >= rules.maxShortsPerDay) {
                return RuleDecision(true, "shorts_limit_exceeded")
            }
        }

        // 4) Total app usage time limit
        if (rules.maxMinutesPerDay != null) {
            val usedMinutes = usageTracker.getUsageMinutesToday(pkg)
            if (usedMinutes >= rules.maxMinutesPerDay) {
                return RuleDecision(true, "time_limit_exceeded")
            }
        }

        return RuleDecision(false, "allowed")
    }
}
```

---

## §8. Complete source: UsageTracker

```kotlin
package com.your.launcher.reelsguard

import android.app.usage.UsageStatsManager
import android.content.Context
import java.time.LocalDate
import java.time.ZoneId

class UsageTracker(context: Context) {

    private val usm =
        context.getSystemService(Context.USAGE_STATS_SERVICE) as UsageStatsManager

    fun getUsageMinutesToday(pkg: String): Long {
        val now = System.currentTimeMillis()
        val start = LocalDate.now()
            .atStartOfDay(ZoneId.systemDefault())
            .toInstant().toEpochMilli()

        val stats = usm.queryUsageStats(
            UsageStatsManager.INTERVAL_DAILY, start, now)

        val totalMs = stats
            ?.filter { it.packageName == pkg }
            ?.sumOf { it.totalTimeInForeground } ?: 0L

        return totalMs / 60000L
    }
}
```

---

## §9. Complete source: Room persistence

### Entities

```kotlin
@Entity(tableName = "short_usage")
data class ShortUsage(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val packageName: String,
    val dateEpochDay: Long,
    val count: Int
)

@Entity(tableName = "app_rules")
data class AppRulesEntity(
    @PrimaryKey val packageName: String,
    val maxShortsPerDay: Int?,
    val blockedAfterHour: Int?,
    val fullBlock: Boolean,
    val maxMinutesPerDay: Int?
)
```

### DAOs

```kotlin
@Dao
interface ShortUsageDao {
    @Query("SELECT * FROM short_usage WHERE packageName = :pkg AND dateEpochDay = :epochDay LIMIT 1")
    fun getForDate(pkg: String, epochDay: Long): ShortUsage?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    fun insert(usage: ShortUsage)
}

@Dao
interface AppRulesDao {
    @Query("SELECT * FROM app_rules WHERE packageName = :pkg LIMIT 1")
    fun get(pkg: String): AppRulesEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    fun upsert(entity: AppRulesEntity)
}
```

### Database

```kotlin
@Database(entities = [ShortUsage::class, AppRulesEntity::class], version = 1)
abstract class ReelsGuardDatabase : RoomDatabase() {
    abstract fun shortUsageDao(): ShortUsageDao
    abstract fun appRulesDao(): AppRulesDao

    companion object {
        @Volatile private var INSTANCE: ReelsGuardDatabase? = null

        fun getInstance(context: Context): ReelsGuardDatabase {
            return INSTANCE ?: synchronized(this) {
                INSTANCE ?: Room.databaseBuilder(
                    context.applicationContext,
                    ReelsGuardDatabase::class.java,
                    "reels_guard_db"
                ).build().also { INSTANCE = it }
            }
        }
    }
}
```

### Repository

```kotlin
class ReelsGuardRepository(
    private val shortUsageDao: ShortUsageDao,
    private val appRulesDao: AppRulesDao
) {
    fun incrementShortCount(pkg: String) {
        val today = LocalDate.now().toEpochDay()
        val existing = shortUsageDao.getForDate(pkg, today)
        val updated = (existing ?: ShortUsage(
            packageName = pkg, dateEpochDay = today, count = 0
        )).copy(count = (existing?.count ?: 0) + 1)
        shortUsageDao.insert(updated)
    }

    fun getShortCountToday(pkg: String): Int {
        val today = LocalDate.now().toEpochDay()
        return shortUsageDao.getForDate(pkg, today)?.count ?: 0
    }

    fun getAppRules(pkg: String): AppRules {
        val e = appRulesDao.get(pkg) ?: defaultRules(pkg)
        return AppRules(
            packageName = e.packageName,
            maxShortsPerDay = e.maxShortsPerDay,
            blockedAfterHour = e.blockedAfterHour,
            fullBlock = e.fullBlock,
            maxMinutesPerDay = e.maxMinutesPerDay
        )
    }

    fun saveAppRules(rules: AppRules) {
        appRulesDao.upsert(AppRulesEntity(
            packageName = rules.packageName,
            maxShortsPerDay = rules.maxShortsPerDay,
            blockedAfterHour = rules.blockedAfterHour,
            fullBlock = rules.fullBlock,
            maxMinutesPerDay = rules.maxMinutesPerDay
        ))
    }

    private fun defaultRules(pkg: String) = AppRulesEntity(
        packageName = pkg,
        maxShortsPerDay = 50,
        blockedAfterHour = null,
        fullBlock = false,
        maxMinutesPerDay = null
    )
}
```

---

## §10. Complete source: BlockOverlayController

```kotlin
package com.your.launcher.reelsguard

import android.content.Context
import android.content.Intent
import android.graphics.PixelFormat
import android.net.Uri
import android.provider.Settings
import android.view.LayoutInflater
import android.view.View
import android.view.WindowManager
import android.widget.TextView

object BlockOverlayController {

    private var windowManager: WindowManager? = null
    private var overlayView: View? = null

    fun init(context: Context) {
        windowManager = context.getSystemService(Context.WINDOW_SERVICE) as WindowManager
    }

    fun show(reason: String) {
        val wm = windowManager ?: return
        if (overlayView != null) return

        val view = TextView(wm.toString()).apply {
            text = "Reels blocked: $reason"
            textSize = 18f
            setPadding(32, 32, 32, 32)
            setBackgroundColor(0xCC000000.toInt())
            setTextColor(0xFFFFFFFF.toInt())
        }

        val params = WindowManager.LayoutParams(
            WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
            PixelFormat.TRANSLUCENT
        )

        wm.addView(view, params)
        overlayView = view
    }

    fun hide() {
        val wm = windowManager ?: return
        val v = overlayView ?: return
        wm.removeView(v)
        overlayView = null
    }

    fun hasOverlayPermission(context: Context): Boolean {
        return Settings.canDrawOverlays(context)
    }

    fun requestOverlayPermission(context: Context) {
        val intent = Intent(
            Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
            Uri.parse("package:${context.packageName}")
        )
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        context.startActivity(intent)
    }
}
```

---

## §11. Complete source: Compose settings UI

### ViewModel

```kotlin
class ReelsGuardSettingsViewModel(
    private val repo: ReelsGuardRepository,
    private val appPackage: String
) : ViewModel() {

    private val _rules = MutableStateFlow(repo.getAppRules(appPackage))
    val rules: StateFlow<AppRules> = _rules

    fun setFullBlock(enabled: Boolean) =
        update { it.copy(fullBlock = enabled) }

    fun setMaxShortsPerDay(value: Int?) =
        update { it.copy(maxShortsPerDay = value) }

    fun setBlockedAfterHour(hour: Int?) =
        update { it.copy(blockedAfterHour = hour) }

    fun setMaxMinutesPerDay(value: Int?) =
        update { it.copy(maxMinutesPerDay = value) }

    private fun update(transform: (AppRules) -> AppRules) {
        val newRules = transform(_rules.value)
        _rules.value = newRules
        repo.saveAppRules(newRules)
    }
}
```

### Compose screen

```kotlin
@Composable
fun ReelsGuardSettingsScreen(
    viewModel: ReelsGuardSettingsViewModel,
    appLabel: String
) {
    val rules by viewModel.rules.collectAsState()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp)
    ) {
        Text("Reels Guard — $appLabel",
            style = MaterialTheme.typography.titleLarge)

        Spacer(Modifier.height(16.dp))

        // Full block switch
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column(Modifier.weight(1f)) {
                Text("Fully block app")
                Text("Prevent opening once limits are reached.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.7f))
            }
            Switch(checked = rules.fullBlock,
                onCheckedChange = { viewModel.setFullBlock(it) })
        }

        HorizontalDivider(Modifier.padding(vertical = 8.dp))

        // Max shorts per day
        Text("Max reels/shorts per day: ${rules.maxShortsPerDay ?: "Unlimited"}")
        Slider(
            value = (rules.maxShortsPerDay ?: 0).toFloat(),
            onValueChange = { viewModel.setMaxShortsPerDay(it.toInt()) },
            valueRange = 0f..200f,
            steps = 19,
            modifier = Modifier.fillMaxWidth()
        )

        HorizontalDivider(Modifier.padding(vertical = 8.dp))

        // Block reels after hour
        Text("Block reels after: ${rules.blockedAfterHour?.let { "%02d:00".format(it) } ?: "Disabled"}")
        Slider(
            value = (rules.blockedAfterHour ?: 0).toFloat(),
            onValueChange = { viewModel.setBlockedAfterHour(it.toInt()) },
            valueRange = 0f..23f,
            steps = 22,
            modifier = Modifier.fillMaxWidth()
        )

        HorizontalDivider(Modifier.padding(vertical = 8.dp))

        // Max minutes per day
        Text("Max app minutes per day: ${rules.maxMinutesPerDay ?: "Unlimited"}")
        Slider(
            value = (rules.maxMinutesPerDay ?: 0).toFloat(),
            onValueChange = { viewModel.setMaxMinutesPerDay(it.toInt()) },
            valueRange = 0f..300f,
            steps = 29,
            modifier = Modifier.fillMaxWidth()
        )
    }
}
```

### Settings Activity

```kotlin
class ReelsGuardSettingsActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val appPackage = intent.getStringExtra("pkg")
            ?: "com.google.android.youtube"
        val db = ReelsGuardDatabase.getInstance(applicationContext)
        val repo = ReelsGuardRepository(db.shortUsageDao(), db.appRulesDao())

        val viewModel = ViewModelProvider(this, object : ViewModelProvider.Factory {
            @Suppress("UNCHECKED_CAST")
            override fun <T : ViewModel> create(modelClass: Class<T>): T =
                ReelsGuardSettingsViewModel(repo, appPackage) as T
        })[ReelsGuardSettingsViewModel::class.java]

        setContent {
            MaterialTheme {
                ReelsGuardSettingsScreen(
                    viewModel = viewModel,
                    appLabel = labelForPackage(appPackage)
                )
            }
        }
    }

    private fun labelForPackage(pkg: String): String = when (pkg) {
        "com.google.android.youtube" -> "YouTube"
        "com.instagram.android"      -> "Instagram"
        "com.snapchat.android"       -> "Snapchat"
        else -> pkg
    }
}
```

---

## §12. Complete source: Launcher icon hook

```kotlin
fun onAppIconClicked(pkg: String, context: Context) {
    val db = ReelsGuardDatabase.getInstance(context)
    val repo = ReelsGuardRepository(db.shortUsageDao(), db.appRulesDao())
    val usageTracker = UsageTracker(context)

    val rules = repo.getAppRules(pkg)
    val minutesUsed = usageTracker.getUsageMinutesToday(pkg)

    val fullyBlocked = rules.fullBlock ||
        (rules.maxMinutesPerDay != null && minutesUsed >= rules.maxMinutesPerDay)

    if (fullyBlocked) {
        // Show blocked screen instead of launching
        val intent = Intent(context, AppBlockedActivity::class.java).apply {
            putExtra("pkg", pkg)
            flags = Intent.FLAG_ACTIVITY_NEW_TASK
        }
        context.startActivity(intent)
    } else {
        // Launch app normally — accessibility service handles Reels-level blocks
        val launchIntent = context.packageManager
            .getLaunchIntentForPackage(pkg)
        context.startActivity(launchIntent)
    }
}
```

---

## §13. Permission flow helper

```kotlin
object PermissionHelper {

    fun isAccessibilityEnabled(context: Context): Boolean {
        val enabled = Settings.Secure.getInt(
            context.contentResolver,
            Settings.Secure.ACCESSIBILITY_ENABLED, 0
        )
        if (enabled == 0) return false

        val services = Settings.Secure.getString(
            context.contentResolver,
            Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES
        ) ?: return false

        return services.contains(context.packageName)
    }

    fun isUsageAccessEnabled(context: Context): Boolean {
        val appOps = context.getSystemService(Context.APP_OPS_SERVICE) as AppOpsManager
        val mode = appOps.unsafeCheckOpNoThrow(
            AppOpsManager.OPSTR_GET_USAGE_STATS,
            android.os.Process.myUid(),
            context.packageName
        )
        return mode == AppOpsManager.MODE_ALLOWED
    }

    fun openAccessibilitySettings(context: Context) {
        val intent = Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        context.startActivity(intent)
    }

    fun openUsageAccessSettings(context: Context) {
        val intent = Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        context.startActivity(intent)
    }
}
```

---

## §14. Migration & versioning notes

- Room schema: bump version for any entity change.
- Export schema JSON: add `room.schemaLocation` annotation processor arg.
- When target apps update their UI, re-run `logNodeTree` and update `ScreenDetector` IDs.
- Maintain a test matrix: one device per target app, test after each app update.

---

## §15. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Service not receiving events | Accessibility not enabled | `PermissionHelper.isAccessibilityEnabled` → prompt user |
| `rootInActiveWindow` is null | Event too early or window not ready | Add small delay or check on next event |
| Count never increments | `deriveShortId` returns same value | Inspect tree logs, find a different field that changes per short |
| Block fires too aggressively | Detection false positive | Tighten heuristics, require 2+ markers to confirm short-form |
| Overlay not showing | No overlay permission | `BlockOverlayController.requestOverlayPermission` |
| Settings changes don't take effect | Repo not writing to DB | Check DAO `OnConflictStrategy`, verify `saveAppRules` is called |
