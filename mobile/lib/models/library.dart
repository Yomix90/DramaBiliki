import 'series.dart';

class HistoryItem {
  final int seriesId;
  final String seriesSlug;
  final String title;
  final String coverUrl;
  final int episodeNum;
  final int positionSeconds;
  final int totalSeconds;
  final bool completed;
  final DateTime? updatedAt;

  HistoryItem({
    required this.seriesId,
    required this.seriesSlug,
    required this.title,
    required this.coverUrl,
    required this.episodeNum,
    required this.positionSeconds,
    required this.totalSeconds,
    required this.completed,
    this.updatedAt,
  });

  double get progress => totalSeconds > 0 ? (positionSeconds / totalSeconds).clamp(0.0, 1.0) : 0.0;

  factory HistoryItem.fromJson(Map<String, dynamic> json) {
    return HistoryItem(
      seriesId: json['series_id'] as int? ?? 0,
      seriesSlug: json['series_slug'] as String? ?? '',
      title: json['title'] as String? ?? '',
      coverUrl: json['cover_url'] as String? ?? '',
      episodeNum: json['episode_num'] as int? ?? 1,
      positionSeconds: (json['position_seconds'] as num?)?.toInt() ?? 0,
      totalSeconds: (json['total_seconds'] as num?)?.toInt() ?? 0,
      completed: json['completed'] as bool? ?? false,
      updatedAt: DateTime.tryParse(json['updated_at'] as String? ?? ''),
    );
  }
}

class LibraryModel {
  final List<SeriesModel> favorites;

  /// One entry per series (the most recently watched episode), newest first.
  final List<HistoryItem> history;

  LibraryModel({required this.favorites, required this.history});

  factory LibraryModel.fromJson(Map<String, dynamic> json) {
    final rawFav = json['favorites'] as List<dynamic>? ?? [];
    final rawHistory = json['history'] as List<dynamic>? ?? [];

    // The API returns one row per watched episode: keep only the latest per series.
    final latest = <int, HistoryItem>{};
    for (final raw in rawHistory) {
      final item = HistoryItem.fromJson(raw as Map<String, dynamic>);
      final existing = latest[item.seriesId];
      if (existing == null || _isNewer(item, existing)) {
        latest[item.seriesId] = item;
      }
    }
    final history = latest.values.toList()
      ..sort((a, b) => (b.updatedAt ?? DateTime(0)).compareTo(a.updatedAt ?? DateTime(0)));

    return LibraryModel(
      favorites: rawFav.map((e) => SeriesModel.fromJson(e as Map<String, dynamic>)).toList(),
      history: history,
    );
  }

  static bool _isNewer(HistoryItem a, HistoryItem b) {
    final at = a.updatedAt, bt = b.updatedAt;
    if (at != null && bt != null && at != bt) return at.isAfter(bt);
    return a.episodeNum > b.episodeNum;
  }
}
