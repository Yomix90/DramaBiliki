class AppConstants {
  // Bridge server, built into the app (not editable by users).
  // Override at build time: flutter build apk --dart-define=API_BASE_URL=https://api.example.com
  static const String defaultBaseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'https://dramabiliki.digitlab.dev',
  );

  static const String appName = "DramaBiliki";
  static const String appVersion = "1.5.0";

  // Paging
  static const int pageSize = 18;
  static const int episodesPerRange = 30;

  // Shared preferences keys
  static const String keyDeviceId = "device_id";
  static const String keyAuthToken = "auth_token";
  static const String keyLanguage = "selected_language";
  static const String keyDataSaver = "data_saver_mode";
  static const String keyAutoplayNext = "autoplay_next_episode";
  static const String keySubtitles = "subtitles_enabled";
  static const String keyRecentSearches = "recent_searches";
  static const String keyAdsCounter = "ads_episode_counter";

  // Google's public test ad unit, used until a real one is set in the admin panel.
  static const String testRewardedUnitId = "ca-app-pub-3940256099942544/5224354917";
}
