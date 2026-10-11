import 'package:dio/dio.dart';
import 'package:video_player/video_player.dart';
import 'api_client.dart';
import '../models/genre.dart';
import '../models/home_feed.dart';
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
