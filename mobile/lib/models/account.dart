class UserProfile {
  final int id;
  final String? email;
  final String? username;
  final bool isGuest;
  final bool adsFree;

  UserProfile({required this.id, this.email, this.username, required this.isGuest, required this.adsFree});

  String get displayName => (username?.isNotEmpty ?? false) ? username! : (email ?? '');

  factory UserProfile.fromJson(Map<String, dynamic> json) {
    return UserProfile(
      id: json['id'] as int? ?? 0,
      email: json['email'] as String?,
      username: json['username'] as String?,
      isGuest: json['is_guest'] as bool? ?? true,
      adsFree: json['ads_free'] as bool? ?? false,
    );
  }
}

class AuthException implements Exception {
  /// Message returned by the server (may be empty).
  final String message;
  AuthException(this.message);

  @override
  String toString() => message;
}

class AppUpdateInfo {
  final String latestVersion;
  final bool hasUpdate;
  final bool forceUpdate;
  final String downloadUrl;
  final String releaseNotes;

  AppUpdateInfo({
    required this.latestVersion,
    required this.hasUpdate,
    required this.forceUpdate,
    required this.downloadUrl,
    required this.releaseNotes,
  });

  factory AppUpdateInfo.fromJson(Map<String, dynamic> json) {
    return AppUpdateInfo(
      latestVersion: json['latest_version'] as String? ?? '',
      hasUpdate: json['has_update'] as bool? ?? false,
      forceUpdate: json['force_update'] as bool? ?? false,
      downloadUrl: json['download_url'] as String? ?? '',
      releaseNotes: json['release_notes'] as String? ?? '',
    );
  }
}

class AdsConfig {
  final bool enabled;
  final int everyNEpisodes;
  final String rewardedUnitId;

  const AdsConfig({required this.enabled, required this.everyNEpisodes, required this.rewardedUnitId});

  static const disabled = AdsConfig(enabled: false, everyNEpisodes: 5, rewardedUnitId: '');

  factory AdsConfig.fromJson(Map<String, dynamic> json) {
    return AdsConfig(
      enabled: json['enabled'] as bool? ?? false,
      everyNEpisodes: (json['every_n_episodes'] as num?)?.toInt() ?? 5,
      rewardedUnitId: json['rewarded_unit_id'] as String? ?? '',
    );
  }
}
