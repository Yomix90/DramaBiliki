# Release builds are shrunk by R8. Google Mobile Ads pulls in WorkManager, whose
# Room database classes are created by reflection: without these rules R8 strips
# them and the app crashes at launch ("Failed to create an instance of
# androidx.work.impl.WorkDatabase").
-keep class * extends androidx.room.RoomDatabase { <init>(); }
-keep class androidx.work.impl.** { *; }
-keep class androidx.room.** { *; }
-dontwarn androidx.room.paging.**
