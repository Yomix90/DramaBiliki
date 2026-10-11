class AppConstants {
  // Bridge API URL (Change to your VPS URL e.g. https://api.dramabiliki.com or LAN IP for testing)
  // When testing on Android Emulator, 10.0.2.2 points to host machine. For real device/VPS, use domain or server IP.
  static const String defaultBaseUrl = "http://2.29.96.137:8090";

  static const String appName = "DramaBiliki";
  static const String appVersion = "1.2.0";

  // Paging
  static const int pageSize = 18;
  static const int episodesPerRange = 30;

  // Shared preferences keys
  static const String keyDeviceId = "device_id";
  static const String keyAuthToken = "auth_token";
  static const String keyLanguage = "selected_language";
  static const String keyBaseUrl = "server_base_url";
  static const String keyDataSaver = "data_saver_mode";
  static const String keyAutoplayNext = "autoplay_next_episode";
  static const String keySubtitles = "subtitles_enabled";
  static const String keyRecentSearches = "recent_searches";
}
