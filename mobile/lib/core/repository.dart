import 'package:dio/dio.dart';
import 'package:video_player/video_player.dart';
import 'api_client.dart';
import '../models/genre.dart';
import '../models/home_feed.dart';
import '../models/account.dart';
import '../models/library.dart';
import '../models/series.dart';

/// Single entry point for every Bridge API call made by the app.
class DramaRepository {
  final ApiClient api;

  DramaRepository(this.api);

  String get baseUrl => api.preferences.getBaseUrl();

  Future<HomeFeedModel> getHomeFeed() async {
    final response = await api.dio.get('/api/v1/home');
    return HomeFeedModel.fromJson(response.data as Map<String, dynamic>);
  }

  Future<List<GenreModel>> getGenres() async {
    final response = await api.dio.get('/api/v1/genres');
    final list = response.data as List<dynamic>? ?? [];
    return list.map((e) => GenreModel.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<List<SeriesModel>> listSeries({String? genre, String? query, int page = 1, int limit = 20}) async {
    final params = <String, dynamic>{'page': page, 'limit': limit};
    if (genre != null && genre.isNotEmpty) params['genre'] = genre;
    if (query != null && query.isNotEmpty) params['q'] = query;
    final response = await api.dio.get('/api/v1/series', queryParameters: params);
    final raw = response.data as List<dynamic>? ?? [];
    return raw.map((e) => SeriesModel.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<List<String>> suggest(String query) async {
    final response = await api.dio.get('/api/v1/search/suggest', queryParameters: {'q': query});
    final raw = response.data as List<dynamic>? ?? [];
    return raw.map((e) => (e as Map<String, dynamic>)['title'] as String? ?? '').where((t) => t.isNotEmpty).toList();
  }

  Future<SeriesDetailModel> getSeriesDetail(String idOrSlug) async {
    final response = await api.dio.get('/api/v1/series/$idOrSlug');
    return SeriesDetailModel.fromJson(response.data as Map<String, dynamic>);
  }

  Future<LibraryModel> getLibrary() async {
    final response = await api.dio.get('/api/v1/me/library');
    return LibraryModel.fromJson(response.data as Map<String, dynamic>);
  }

  Future<void> setFavorite(int seriesId, bool favorite) async {
    if (favorite) {
      final response = await api.dio.post('/api/v1/favorites', data: {'series_id': seriesId});
      // POST toggles server-side: undo if the series was in fact already a favorite.
      final isFav = (response.data as Map<String, dynamic>?)?['is_favorite'] as bool?;
      if (isFav == false) {
        await api.dio.post('/api/v1/favorites', data: {'series_id': seriesId});
      }
    } else {
      await api.dio.delete('/api/v1/favorites/$seriesId');
    }
  }

  Future<void> saveProgress({
    required int seriesId,
    required int episodeNum,
    required int positionSeconds,
    required int totalSeconds,
    required bool completed,
  }) async {
    await api.dio.post('/api/v1/history/progress', data: {
      'series_id': seriesId,
      'episode_num': episodeNum,
      'position_seconds': positionSeconds,
      'total_seconds': totalSeconds,
      'completed': completed,
    });
  }

  /// Progressive MP4 served by the bridge from the Telegram channel (supports HTTP Range).
  // ---------------------------------------------------------------------------
  // Accounts
  // ---------------------------------------------------------------------------

  Future<UserProfile> me() async {
    final response = await api.dio.get('/api/v1/me');
    return UserProfile.fromJson(response.data as Map<String, dynamic>);
  }

  /// Logs in (or registers) and stores the returned token. Throws [AuthException] with the server message.
  Future<void> login(String email, String password) => _authenticate('/api/v1/auth/login', {
        'email': email,
        'password': password,
      });

  Future<void> register(String email, String password, String username) => _authenticate('/api/v1/auth/register', {
        'email': email,
        'password': password,
        'username': username,
      });

  Future<void> _authenticate(String path, Map<String, dynamic> body) async {
    try {
      final response = await api.dio.post(path, data: body);
      final token = (response.data as Map<String, dynamic>)['access_token'] as String?;
      if (token == null || token.isEmpty) throw AuthException('');
      await api.preferences.setAuthToken(token);
    } on DioException catch (e) {
      final data = e.response?.data;
      final detail = data is Map ? data['detail']?.toString() : null;
      throw AuthException(detail ?? '');
    }
  }

  /// Drops the account session and continues as a fresh guest of this device.
  Future<void> logout() async {
    await api.preferences.clearAuthToken();
    await api.authenticateDevice();
  }

  // ---------------------------------------------------------------------------
  // App update & ads
  // ---------------------------------------------------------------------------

  Future<AppUpdateInfo> checkVersion(String currentVersion) async {
    final response = await api.dio.get('/api/v1/app/version', queryParameters: {'current': currentVersion});
    return AppUpdateInfo.fromJson(response.data as Map<String, dynamic>);
  }

  Future<AdsConfig> adsConfig() async {
    final response = await api.dio.get('/api/v1/config/ads');
    return AdsConfig.fromJson(response.data as Map<String, dynamic>);
  }

  Uri streamUri(int seriesId, int episodeNum) => Uri.parse('$baseUrl/stream/$seriesId/$episodeNum.mp4');

  /// Loads the WebVTT subtitles of an episode; an empty file simply shows nothing.
  Future<ClosedCaptionFile> subtitles(int seriesId, int episodeNum) async {
    try {
      final response = await api.dio.get<String>(
        '/subtitles/$seriesId/$episodeNum',
        options: Options(responseType: ResponseType.plain),
      );
      return WebVTTCaptionFile(response.data ?? '');
    } catch (_) {
      return WebVTTCaptionFile('');
    }
  }
}
