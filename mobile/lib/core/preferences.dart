import 'package:shared_preferences/shared_preferences.dart';
import 'package:uuid/uuid.dart';
import 'constants.dart';

class PreferencesService {
  final SharedPreferences _prefs;

  PreferencesService(this._prefs);

  static Future<PreferencesService> init() async {
    final prefs = await SharedPreferences.getInstance();
    return PreferencesService(prefs);
  }

  String getDeviceId() {
    String? id = _prefs.getString(AppConstants.keyDeviceId);
    if (id == null || id.isEmpty) {
      id = const Uuid().v4();
      _prefs.setString(AppConstants.keyDeviceId, id);
    }
    return id;
  }

  String? getAuthToken() {
    return _prefs.getString(AppConstants.keyAuthToken);
  }

  Future<void> setAuthToken(String token) async {
    await _prefs.setString(AppConstants.keyAuthToken, token);
  }

  Future<void> clearAuthToken() async {
    await _prefs.remove(AppConstants.keyAuthToken);
  }

  String getLanguage() {
    return _prefs.getString(AppConstants.keyLanguage) ?? 'en';
  }

  Future<void> setLanguage(String code) async {
    await _prefs.setString(AppConstants.keyLanguage, code);
  }

  /// The server address is built into the app (an old value saved by previous
  /// versions is ignored).
  String getBaseUrl() => AppConstants.defaultBaseUrl;

  bool getDataSaver() {
    return _prefs.getBool(AppConstants.keyDataSaver) ?? false;
  }

  Future<void> setDataSaver(bool enabled) async {
    await _prefs.setBool(AppConstants.keyDataSaver, enabled);
  }

  bool getAutoplayNext() {
    return _prefs.getBool(AppConstants.keyAutoplayNext) ?? true;
  }

  Future<void> setAutoplayNext(bool enabled) async {
    await _prefs.setBool(AppConstants.keyAutoplayNext, enabled);
  }

  bool getSubtitlesEnabled() {
    return _prefs.getBool(AppConstants.keySubtitles) ?? true;
  }

  Future<void> setSubtitlesEnabled(bool enabled) async {
    await _prefs.setBool(AppConstants.keySubtitles, enabled);
  }

  int getAdsCounter() {
    return _prefs.getInt(AppConstants.keyAdsCounter) ?? 0;
  }

  Future<void> setAdsCounter(int value) async {
    await _prefs.setInt(AppConstants.keyAdsCounter, value);
  }

  List<String> getRecentSearches() {
    return _prefs.getStringList(AppConstants.keyRecentSearches) ?? const [];
  }

  Future<void> setRecentSearches(List<String> items) async {
    await _prefs.setStringList(AppConstants.keyRecentSearches, items);
  }
}
